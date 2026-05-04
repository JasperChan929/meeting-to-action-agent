"""
backend/mcp_clients/run_meeting.py (v2 - 多 server 编排)

端到端 pipeline:
  会议纪要 → parser 提取 ActionItem → 按 task_type 路由到不同 MCP server

路由规则:
  - task_type ∈ {todo, meeting, unknown}  → task_server.create_notion_task
  - task_type == "email"                  → email_server.draft_email
  
执行:
    uv run python mcp_clients/run_meeting.py tests/meeting_corpus/meeting_01_formal.txt
    uv run python mcp_clients/run_meeting.py <file> --dry-run

Phase 4.2 改动点 vs v1 (Day 7):
  ⭐ 同时连 2 个 server (task + email),用 AsyncExitStack 管理生命周期
  ⭐ 按 task_type 路由 ActionItem
  ⭐ email 用静态模板拼装(Phase 5 再上 LLM 写正文)
  ⭐ 限速从单 server 0.4s 改为按 server 独立计时(2 个 server 不互相阻塞)
  
设计要点:
  - 单条 ActionItem 失败不影响其他(错误隔离)
  - 上限保护 MAX_TASKS_PER_MEETING 不变
  - dry-run 模式不连任何 server,只打印路由结果
"""
import asyncio
import sys
import time
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# 把 backend/ 加进 sys.path,以 import extractors
BACKEND_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from extractors.parser import extract_action_items  # noqa: E402
from extractors.schema import ActionItem  # noqa: E402


# ============ 常量 ============
MAX_TASKS_PER_MEETING = 10
RATE_LIMIT_DELAY = 0.4  # 同一 server 内两次调用间隔(秒)

# ⭐ 2 个 server 的启动参数
TASK_SERVER = StdioServerParameters(
    command="uv",
    args=["run", "python", "mcp_servers/task_server.py"],
    cwd=str(BACKEND_DIR),
)

EMAIL_SERVER = StdioServerParameters(
    command="uv",
    args=["run", "python", "mcp_servers/email_server.py"],
    cwd=str(BACKEND_DIR),
)


# ============ ActionItem → tool args 转换 ============
def item_to_task_args(item: ActionItem, db_key: str = "work") -> dict:
    """ActionItem → task_server.create_notion_task 的参数"""
    return {
        "db_key": db_key,
        "name": item.name,
        "description": item.description,
        "owner": item.owner,
        "recipient": item.recipient,
        "task_type": item.task_type.value,
        "priority": item.priority.value,
        "deadline": item.deadline.strftime("%Y-%m-%d") if item.deadline else None,
        "confidence": item.confidence,
        "source_text": item.source_text,
    }


def item_to_email_args(item: ActionItem) -> dict:
    """
    ActionItem → email_server.draft_email 的参数。
    
    ⚠️ Phase 4 妥协:
      ActionItem 没有"邮件正文"字段,这里用静态模板拼装。
      正文读起来像机器写的——Phase 5 用 LLM 二次调用生成自然正文。
      
    收件人推断逻辑:
      - 如果 recipient 看起来像邮箱(含@),直接用
      - 否则用 placeholder,在主题里标注真实交付对象
        (反正是草稿,真发前用户会改)
    """
    # ⭐ 收件人:从 recipient 字段推断,不像邮箱就用 placeholder
    if item.recipient and "@" in item.recipient:
        to = item.recipient
        subject = item.name
    else:
        to = "TODO@example.com"
        subject = f"[发给 {item.recipient or '待定'}] {item.name}"
    
    # ⭐ 正文模板:description + 原文 + 元信息
    body_lines = [
        item.description,
        "",
        "─" * 30,
        f"原会议纪要片段: {item.source_text}",
    ]
    if item.owner:
        body_lines.insert(0, f"负责人: {item.owner}")
    if item.deadline:
        body_lines.insert(0, f"截止: {item.deadline.strftime('%Y-%m-%d')}")
    
    return {
        "to": to,
        "subject": subject,
        "body": "\n".join(body_lines),
    }


# ============ 路由决策 ============
def route_item(item: ActionItem) -> str:
    """
    根据 task_type 决定走哪个 server。
    返回 "task" 或 "email"。
    """
    if item.task_type.value == "email":
        return "email"
    return "task"  # todo / meeting / unknown 都进 task_server


# ============ 主流程 ============
async def run_pipeline(meeting_file: Path, dry_run: bool = False):
    print("=" * 60)
    print(f"📄 会议纪要: {meeting_file.name}")
    print(f"🏃 模式: {'DRY RUN' if dry_run else '真实执行'}")
    print("=" * 60)
    
    # ─────────────────────────────────────
    # Step 1: 读 + LLM 提取
    # ─────────────────────────────────────
    text = meeting_file.read_text(encoding="utf-8")
    print(f"\n原文 ({len(text)} 字符):")
    print(text)
    
    print("\n🧠 LLM 提取 ActionItem ...")
    result = extract_action_items(text)
    items = result.items
    print(f"✅ 提取出 {len(items)} 条")
    
    # ─────────────────────────────────────
    # Step 2: 上限保护 + 路由分发
    # ─────────────────────────────────────
    if len(items) > MAX_TASKS_PER_MEETING:
        print(f"⚠️ 超过上限 {MAX_TASKS_PER_MEETING},截断")
        items = items[:MAX_TASKS_PER_MEETING]
    
    # ⭐ 按 server 分桶
    task_items = []
    email_items = []
    for item in items:
        if route_item(item) == "email":
            email_items.append(item)
        else:
            task_items.append(item)
    
    print(f"\n📊 路由分发:")
    print(f"   → task_server  {len(task_items)} 条")
    print(f"   → email_server {len(email_items)} 条")
    
    # ─────────────────────────────────────
    # dry-run 模式:打印路由结果不连 server
    # ─────────────────────────────────────
    if dry_run:
        print("\n--- DRY RUN ---")
        print("\n[task server 计划写入]")
        for i, item in enumerate(task_items, 1):
            args = item_to_task_args(item)
            print(f"  [{i}] {item.name} | type={item.task_type.value} | owner={item.owner}")
        print("\n[email server 计划草稿]")
        for i, item in enumerate(email_items, 1):
            args = item_to_email_args(item)
            print(f"  [{i}] to={args['to']} | subject={args['subject']}")
        return
    
    # ─────────────────────────────────────
    # Step 3: 同时连 2 个 server (AsyncExitStack 管理)
    # ─────────────────────────────────────
    print(f"\n🔌 同时连接 task_server + email_server ...")
    
    task_success, task_fail = 0, 0
    email_success, email_fail = 0, 0
    
    # ⭐ AsyncExitStack:嵌套 async context manager,一次 enter 一次 exit
    # 比写 2 层 async with 嵌套清晰,且失败时自动逐个 unwind 已 enter 的资源
    async with AsyncExitStack() as stack:
        # 连 task_server
        task_streams = await stack.enter_async_context(stdio_client(TASK_SERVER))
        task_session = await stack.enter_async_context(
            ClientSession(task_streams[0], task_streams[1])
        )
        await task_session.initialize()
        print("  ✅ task_server connected")
        
        # 连 email_server
        email_streams = await stack.enter_async_context(stdio_client(EMAIL_SERVER))
        email_session = await stack.enter_async_context(
            ClientSession(email_streams[0], email_streams[1])
        )
        await email_session.initialize()
        print("  ✅ email_server connected")
        
        # ─────────────────────────────────────
        # Step 4: 真实执行,task 和 email 分别处理
        # ─────────────────────────────────────
        # 处理 task_server 桶
        if task_items:
            print(f"\n📌 写入 task_server ({len(task_items)} 条):")
            for i, item in enumerate(task_items, 1):
                args = item_to_task_args(item)
                print(f"  [{i}/{len(task_items)}] {item.name}")
                try:
                    tool_result = await task_session.call_tool(
                        "create_notion_task", arguments=args
                    )
                    first_line = ""
                    for block in tool_result.content:
                        if hasattr(block, "text"):
                            first_line = block.text.split("\n")[0]
                            break
                    if first_line.startswith("✅"):
                        print(f"      {first_line}")
                        task_success += 1
                    else:
                        print(f"      ❌ {first_line[:80]}")
                        task_fail += 1
                except Exception as e:
                    print(f"      ❌ {type(e).__name__}: {e}")
                    task_fail += 1
                
                if i < len(task_items):
                    await asyncio.sleep(RATE_LIMIT_DELAY)
        
        # 处理 email_server 桶
        if email_items:
            print(f"\n📧 写入 email_server ({len(email_items)} 条):")
            for i, item in enumerate(email_items, 1):
                args = item_to_email_args(item)
                print(f"  [{i}/{len(email_items)}] {item.name} → {args['to']}")
                try:
                    tool_result = await email_session.call_tool(
                        "draft_email", arguments=args
                    )
                    first_line = ""
                    for block in tool_result.content:
                        if hasattr(block, "text"):
                            first_line = block.text.split("\n")[0]
                            break
                    if first_line.startswith("✅"):
                        print(f"      {first_line}")
                        email_success += 1
                    else:
                        print(f"      ❌ {first_line[:80]}")
                        email_fail += 1
                except Exception as e:
                    print(f"      ❌ {type(e).__name__}: {e}")
                    email_fail += 1
                
                if i < len(email_items):
                    await asyncio.sleep(RATE_LIMIT_DELAY)
    
    # ─────────────────────────────────────
    # Step 5: 统计
    # ─────────────────────────────────────
    print()
    print("=" * 60)
    print("📊 结果统计")
    print(f"  task_server:  {task_success}/{len(task_items)} 成功")
    print(f"  email_server: {email_success}/{len(email_items)} 成功")
    print(f"  总成功:       {task_success + email_success}/{len(items)}")
    print(f"  总失败:       {task_fail + email_fail}")
    print("=" * 60)


# ============ 入口 ============
def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]
    
    if not args:
        print("用法: uv run python mcp_clients/run_meeting.py <纪要文件> [--dry-run]")
        print("\n可用纪要:")
        for f in sorted((BACKEND_DIR / "tests/meeting_corpus").glob("*.txt")):
            print(f"  - tests/meeting_corpus/{f.name}")
        sys.exit(1)
    
    meeting_file = Path(args[0])
    if not meeting_file.is_absolute():
        meeting_file = BACKEND_DIR / meeting_file
    
    if not meeting_file.exists():
        print(f"❌ 文件不存在: {meeting_file}")
        sys.exit(1)
    
    asyncio.run(run_pipeline(meeting_file, dry_run=dry_run))


if __name__ == "__main__":
    main()