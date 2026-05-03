"""
backend/mcp_clients/batch_meetings.py

批量端到端 pipeline：跑 tests/meeting_corpus/ 下所有纪要，
统计提取 + 建任务的整体表现，结果落到 tests/results/phase3_batch.json

执行：
    uv run python mcp_clients/batch_meetings.py
    uv run python mcp_clients/batch_meetings.py --dry-run

设计要点：
  - 复用 run_meeting.py 的 item_to_tool_args（不重写）
  - 段与段之间 sleep 1s（避免 Notion API 短时间打太多）
  - 段内限速 0.4s（继承 run_meeting 的）
  - 统计 owner=null / 平均 confidence / 各 task_type 分布
  - 输出 JSON 结果，方便后续 Phase 9 评测对比
"""
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

BACKEND_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from extractors.parser import extract_action_items  # noqa: E402

# 复用 run_meeting.py 里的转换函数和常量
from mcp_clients.run_meeting import item_to_tool_args, MAX_TASKS_PER_MEETING, RATE_LIMIT_DELAY  # noqa: E402


# ============ 常量 ============
CORPUS_DIR = BACKEND_DIR / "tests/meeting_corpus"
RESULTS_DIR = BACKEND_DIR / "tests/results"
INTER_MEETING_DELAY = 1.0  # 段与段之间额外 sleep（秒）

server_params = StdioServerParameters(
    command="uv",
    args=["run", "python", "mcp_servers/task_server.py"],
    cwd=str(BACKEND_DIR),
)


# ============ 单段纪要处理 ============
async def process_one_meeting(
    session: ClientSession | None,
    meeting_file: Path,
    dry_run: bool,
) -> dict:
    """
    处理一段纪要，返回该段统计 dict。
    
    Args:
        session: MCP session（dry_run=True 时传 None）
        meeting_file: 纪要文件路径
        dry_run: 是否干跑（不真建）
    """
    text = meeting_file.read_text(encoding="utf-8")
    
    # 步骤 1：LLM 提取
    extraction = extract_action_items(text)
    items = extraction.items
    n_extracted = len(items)
    
    # 上限保护
    truncated = n_extracted > MAX_TASKS_PER_MEETING
    items = items[:MAX_TASKS_PER_MEETING]
    
    # 步骤 2：批量调 tool
    success, failure = 0, 0
    failure_details = []
    
    if dry_run:
        # 干跑模式：只验证序列化无报错
        for item in items:
            try:
                _ = item_to_tool_args(item)  # 触发任何序列化错误
                success += 1
            except Exception as e:
                failure += 1
                failure_details.append(f"{item.name}: {type(e).__name__}: {e}")
    else:
        # 真实跑：调 server
        for i, item in enumerate(items):
            args = item_to_tool_args(item)
            try:
                tool_result = await session.call_tool("create_notion_task", arguments=args)
                # 看 tool 返回是不是 ✅ 开头（业务层 success）
                first_block_text = ""
                for block in tool_result.content:
                    if hasattr(block, "text"):
                        first_block_text = block.text
                        break
                if first_block_text.startswith("✅"):
                    success += 1
                else:
                    failure += 1
                    failure_details.append(f"{item.name}: server 返回 {first_block_text[:80]}")
            except Exception as e:
                failure += 1
                failure_details.append(f"{item.name}: {type(e).__name__}: {e}")
            
            # 段内限速（除最后一条）
            if i < len(items) - 1:
                await asyncio.sleep(RATE_LIMIT_DELAY)
    
    # 步骤 3：本段统计
    return {
        "file": meeting_file.name,
        "n_extracted": n_extracted,
        "n_processed": len(items),
        "truncated": truncated,
        "success": success,
        "failure": failure,
        "failure_details": failure_details,
        "n_no_owner": sum(1 for it in items if it.owner is None),
        "n_no_deadline": sum(1 for it in items if it.deadline is None),
        "avg_confidence": (
            round(sum(it.confidence for it in items) / len(items), 3)
            if items else 0
        ),
        "task_type_distribution": {
            t: sum(1 for it in items if it.task_type.value == t)
            for t in ["todo", "email", "meeting", "unknown"]
        },
    }


# ============ 批量主流程 ============
async def run_batch(dry_run: bool = False):
    files = sorted(CORPUS_DIR.glob("meeting_*.txt"))
    if not files:
        print(f"❌ {CORPUS_DIR} 下没有纪要文件")
        return
    
    print("=" * 60)
    print(f"📦 批量 pipeline：{len(files)} 份纪要")
    print(f"🏃 模式：{'DRY RUN（不真建）' if dry_run else '真实建任务'}")
    print("=" * 60)
    
    per_meeting_stats = []
    
    if dry_run:
        # 干跑：不需要 server
        for f in files:
            print(f"\n📄 {f.name}")
            stats = await process_one_meeting(None, f, dry_run=True)
            print(f"  提取 {stats['n_extracted']} 条，"
                  f"序列化 OK {stats['success']}，"
                  f"序列化 FAIL {stats['failure']}")
            per_meeting_stats.append(stats)
    else:
        # 真实跑：连一次 server，跑完所有纪要
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                print("\n✅ 已连接 task_server\n")
                
                for idx, f in enumerate(files):
                    print(f"📄 [{idx+1}/{len(files)}] {f.name}")
                    stats = await process_one_meeting(session, f, dry_run=False)
                    print(f"  提取 {stats['n_extracted']} 条，"
                          f"建成功 {stats['success']}，失败 {stats['failure']}")
                    per_meeting_stats.append(stats)
                    
                    # 段间 sleep（除最后一段）
                    if idx < len(files) - 1:
                        await asyncio.sleep(INTER_MEETING_DELAY)
    
    # ─────────────────────────────────────
    # 汇总统计
    # ─────────────────────────────────────
    total_extracted = sum(s["n_extracted"] for s in per_meeting_stats)
    total_processed = sum(s["n_processed"] for s in per_meeting_stats)
    total_success = sum(s["success"] for s in per_meeting_stats)
    total_failure = sum(s["failure"] for s in per_meeting_stats)
    total_no_owner = sum(s["n_no_owner"] for s in per_meeting_stats)
    total_no_deadline = sum(s["n_no_deadline"] for s in per_meeting_stats)
    
    summary = {
        "timestamp": datetime.now().isoformat(),
        "mode": "dry_run" if dry_run else "real",
        "n_meetings": len(files),
        "total_extracted": total_extracted,
        "total_processed": total_processed,
        "total_success": total_success,
        "total_failure": total_failure,
        "success_rate": round(total_success / total_processed, 3) if total_processed else 0,
        "no_owner_rate": round(total_no_owner / total_processed, 3) if total_processed else 0,
        "no_deadline_rate": round(total_no_deadline / total_processed, 3) if total_processed else 0,
        "avg_confidence_overall": round(
            sum(s["avg_confidence"] * s["n_processed"] for s in per_meeting_stats)
            / total_processed,
            3,
        ) if total_processed else 0,
        "per_meeting": per_meeting_stats,
    }
    
    print()
    print("=" * 60)
    print("📊 汇总统计")
    print("=" * 60)
    print(f"  纪要数:         {summary['n_meetings']}")
    print(f"  总提取:         {summary['total_extracted']}")
    print(f"  总处理:         {summary['total_processed']}")
    print(f"  建任务成功:     {summary['total_success']}")
    print(f"  建任务失败:     {summary['total_failure']}")
    print(f"  成功率:         {summary['success_rate']*100:.1f}%")
    print(f"  无 owner 占比:   {summary['no_owner_rate']*100:.1f}%")
    print(f"  无 deadline 占比:{summary['no_deadline_rate']*100:.1f}%")
    print(f"  平均 confidence: {summary['avg_confidence_overall']}")
    
    # 落盘
    RESULTS_DIR.mkdir(exist_ok=True)
    suffix = "_dryrun" if dry_run else ""
    out_path = RESULTS_DIR / f"phase3_batch{suffix}.json"
    out_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\n💾 详细结果已写入: {out_path.relative_to(BACKEND_DIR)}")


def main():
    dry_run = "--dry-run" in sys.argv[1:]
    asyncio.run(run_batch(dry_run=dry_run))


if __name__ == "__main__":
    main()