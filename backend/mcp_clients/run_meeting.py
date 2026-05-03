"""
backend/mcp_clients/run_meeting.py

端到端 pipeline：会议纪要 → parser 提取 ActionItem → MCP tool 批量建 Notion 任务

执行：
    uv run python mcp_clients/run_meeting.py tests/meeting_corpus/meeting_01_formal.txt

设计要点：
  - 限速：每条 task 之间 sleep 0.4s（Notion API 限速 3 req/s）
  - 上限：单段纪要最多建 10 条（防爆库 + 防 LLM 幻觉拆出过多 Item）
  - 错误隔离：单条 ActionItem 建失败不影响其他（一个 try/except 包一条）
  - 干跑模式：--dry-run 只打印不真建（开发调试用）
"""
import asyncio
import sys
from datetime import datetime
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# 把 backend/ 加进 sys.path，这样能 import extractors.parser
BACKEND_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from extractors.parser import extract_action_items  # noqa: E402
from extractors.schema import ActionItem  # noqa: E402


# ============ 常量 ============
MAX_TASKS_PER_MEETING = 10  # 单段纪要建任务上限
RATE_LIMIT_DELAY = 0.4      # 每两次 tool 调用之间的 sleep（秒）

server_params = StdioServerParameters(
    command="uv",
    args=["run", "python", "mcp_servers/task_server.py"],
    cwd=str(BACKEND_DIR),
)


# ============ ActionItem → tool arguments ============
def item_to_tool_args(item: ActionItem) -> dict:
    """
    把 Pydantic ActionItem 转成 create_notion_task 的参数字典。
    
    关键点：
      - datetime 字段必须序列化成字符串（JSON 不支持 datetime）
      - Enum 字段（task_type, priority）取 .value（字符串）
      - None 值原样传，server 会处理（owner=None 时不传该 property）
    """
    return {
        "name": item.name,
        "description": item.description,
        "owner": item.owner,
        "recipient": item.recipient,
        "task_type": item.task_type.value,
        "priority": item.priority.value,
        # datetime → "YYYY-MM-DD"。Notion date.start 接受这个格式
        "deadline": item.deadline.strftime("%Y-%m-%d") if item.deadline else None,
        "confidence": item.confidence,
        "source_text": item.source_text,
    }


# ============ 主流程 ============
async def run_pipeline(meeting_file: Path, dry_run: bool = False):
    print("=" * 60)
    print(f"📄 会议纪要：{meeting_file.name}")
    print(f"🏃 模式：{'DRY RUN（不真建）' if dry_run else '真实执行'}")
    print("=" * 60)
    
    # ─────────────────────────────────────
    # 步骤 1：读纪要 + LLM 提取（同步，Phase 2 已有）
    # ─────────────────────────────────────
    text = meeting_file.read_text(encoding="utf-8")
    print(f"\n原文（{len(text)} 字符）：")
    print(text)
    print()
    
    print("🧠 调 LLM 提取 ActionItem ...")
    result = extract_action_items(text)
    items = result.items
    print(f"✅ 提取出 {len(items)} 条 ActionItem")
    
    # ─────────────────────────────────────
    # 步骤 2：上限保护
    # ─────────────────────────────────────
    if len(items) > MAX_TASKS_PER_MEETING:
        print(f"⚠️ 超过上限 {MAX_TASKS_PER_MEETING}，截断")
        items = items[:MAX_TASKS_PER_MEETING]
    
    # 干跑模式：只打印不调 server
    if dry_run:
        print("\n--- DRY RUN ---")
        for i, item in enumerate(items, 1):
            print(f"\n[{i}] {item.name} | owner={item.owner} | {item.task_type.value}/{item.priority.value}")
            print(f"    → tool args: {item_to_tool_args(item)}")
        return
    
    # ─────────────────────────────────────
    # 步骤 3：连 MCP server，逐条建任务
    # ─────────────────────────────────────
    print(f"\n🔌 连接 task_server ...")
    
    success_count = 0
    failure_count = 0
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("✅ 已连接\n")
            
            for i, item in enumerate(items, 1):
                args = item_to_tool_args(item)
                print(f"[{i}/{len(items)}] 创建：{item.name}")
                
                try:
                    tool_result = await session.call_tool("create_notion_task", arguments=args)
                    # 拿第一个 text block 作为反馈
                    for block in tool_result.content:
                        if hasattr(block, "text"):
                            # 只打印第一行（"✅ 任务已创建"），不打印全部细节
                            first_line = block.text.split("\n")[0]
                            print(f"    {first_line}")
                            break
                    success_count += 1
                
                except Exception as e:
                    # 错误隔离：单条失败不影响后续
                    print(f"    ❌ 失败: {type(e).__name__}: {e}")
                    failure_count += 1
                
                # 限速：除了最后一条，每条之间 sleep
                if i < len(items):
                    await asyncio.sleep(RATE_LIMIT_DELAY)
    
    # ─────────────────────────────────────
    # 步骤 4：统计
    # ─────────────────────────────────────
    print()
    print("=" * 60)
    print(f"📊 结果统计")
    print(f"  提取: {len(result.items)} 条（处理 {len(items)} 条）")
    print(f"  成功: {success_count}")
    print(f"  失败: {failure_count}")
    print("=" * 60)


# ============ 入口 ============
def main():
    # 命令行参数：第一个是文件路径，--dry-run 可选
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]
    
    if not args:
        print("用法: uv run python mcp_clients/run_meeting.py <纪要文件> [--dry-run]")
        print("\n可用纪要：")
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