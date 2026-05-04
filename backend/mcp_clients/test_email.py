"""
backend/mcp_clients/test_email.py

Phase 4.2: 测试 email_server 的 tools + resources

执行:
    uv run python mcp_clients/test_email.py

测试场景:
  1. list_resources / list_resource_templates —— 看 server 暴露的资源
  2. read gmail://account                    —— 读账户信息
  3. draft_email                             —— 真创建一封测试草稿
  4. list_drafts                             —— 验证草稿能被列出
  5. (手动)去 Gmail 网页删测试草稿

设计要点:
  - 跟 test_resources.py 同款风格,纯协议层验证
  - 测试草稿主题加 "[MCP TEST]" 前缀,方便人工识别 + 删除
"""
import asyncio
from datetime import datetime
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

BACKEND_DIR = Path(__file__).parent.parent

server_params = StdioServerParameters(
    command="uv",
    args=["run", "python", "mcp_servers/email_server.py"],
    cwd=str(BACKEND_DIR),
)


def _print_section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


async def main():
    print("📡 启动 email_server 并连接...")
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("✅ 连接成功\n")
            
            # ─────────────────────────────────────
            # Test 1: list_resources / templates
            # ─────────────────────────────────────
            _print_section("Test 1: list_resources / list_resource_templates")
            res = await session.list_resources()
            print(f"static resources: {len(res.resources)}")
            for r in res.resources:
                print(f"  • {r.uri}")
            templates = await session.list_resource_templates()
            print(f"resource templates: {len(templates.resourceTemplates)}")
            for t in templates.resourceTemplates:
                print(f"  • {t.uriTemplate}")
            
            # ─────────────────────────────────────
            # Test 2: read gmail://account
            # ─────────────────────────────────────
            _print_section("Test 2: read gmail://account")
            result = await session.read_resource("gmail://account")
            for content in result.contents:
                if hasattr(content, "text"):
                    print(content.text)
            
            # ─────────────────────────────────────
            # Test 3: 创建一封测试草稿
            # ─────────────────────────────────────
            _print_section("Test 3: draft_email")
            ts = datetime.now().strftime("%H:%M:%S")
            tool_result = await session.call_tool(
                "draft_email",
                arguments={
                    "to": "test-recipient@example.com",
                    "subject": f"[MCP TEST] Phase 4.2 自动化测试 {ts}",
                    "body": (
                        "这是一封由 email_server.draft_email 自动创建的测试草稿。\n\n"
                        "若你看到这封草稿,说明 MCP email_server 工作正常。\n"
                        "请手动删除此草稿。"
                    ),
                },
            )
            for block in tool_result.content:
                if hasattr(block, "text"):
                    print(block.text)
            
            # ─────────────────────────────────────
            # Test 4: list_drafts 验证草稿被创建
            # ─────────────────────────────────────
            _print_section("Test 4: list_drafts (limit=5)")
            tool_result = await session.call_tool(
                "list_drafts",
                arguments={"limit": 5},
            )
            for block in tool_result.content:
                if hasattr(block, "text"):
                    print(block.text)
            
            print(f"\n{'='*60}")
            print("✅ Email server 测试完成")
            print("🗑️  请手动去 Gmail → 草稿箱 删掉刚才创建的 [MCP TEST] 草稿")
            print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())