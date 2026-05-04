"""
backend/mcp_clients/test_resources.py

Phase 4 Day 8: 测试 task_server 的 Resources 能力
执行:
    uv run python mcp_clients/test_resources.py

测试场景:
  1. list_resources    —— 拿 server 暴露的所有 resource URI(应看到 notion://databases)
  2. read notion://databases —— 读 DB 目录
  3. read notion://database/work     —— 读单个 DB 的完整 schema
  4. read notion://database/personal —— 读个人 DB
  5. read notion://database/nonexistent —— 错误 db_key 行为验证

设计要点:
  - 不依赖 parser / extractor,纯 MCP 协议层验证
  - 输出格式化清晰,方便对照看每一步效果
"""
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

BACKEND_DIR = Path(__file__).parent.parent

server_params = StdioServerParameters(
    command="uv",
    args=["run", "python", "mcp_servers/task_server.py"],
    cwd=str(BACKEND_DIR),
)


def _print_section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def _pretty_json(text: str) -> str:
    """尝试格式化 JSON 字符串,失败就原样返回"""
    try:
        return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    except Exception:
        return text


async def main():
    print("📡 启动 task_server 并连接...")
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("✅ 连接成功\n")
            
            # ─────────────────────────────────────
            # 测试 1: list_resources(协议握手时拿到的清单)
            # ─────────────────────────────────────
            _print_section("Test 1: list_resources()")
            res = await session.list_resources()
            print(f"暴露 {len(res.resources)} 个静态 resource:")
            for r in res.resources:
                print(f"  • URI:  {r.uri}")
                print(f"    Name: {r.name}")
                print(f"    Desc: {r.description[:80]}...")
                print()
            
            # ⭐ list_resource_templates 拿到 template URI(带 {} 占位符的)
            # 注意:template URI 不会出现在 list_resources 里,要单独问
            _print_section("Test 2: list_resource_templates()")
            templates = await session.list_resource_templates()
            print(f"暴露 {len(templates.resourceTemplates)} 个 template:")
            for t in templates.resourceTemplates:
                print(f"  • URI Template: {t.uriTemplate}")
                print(f"    Name:         {t.name}")
                print()
            
            # ─────────────────────────────────────
            # 测试 3: 读 DB 目录(轻量列表)
            # ─────────────────────────────────────
            _print_section("Test 3: read notion://databases (轻量目录)")
            result = await session.read_resource("notion://databases")
            for content in result.contents:
                if hasattr(content, "text"):
                    print(_pretty_json(content.text))
            
            # ─────────────────────────────────────
            # 测试 4: 读单个 DB 的完整 schema(work)
            # ─────────────────────────────────────
            _print_section("Test 4: read notion://database/work (完整 schema)")
            result = await session.read_resource("notion://database/work")
            for content in result.contents:
                if hasattr(content, "text"):
                    print(_pretty_json(content.text))
            
            # ─────────────────────────────────────
            # 测试 5: 读 personal DB
            # ─────────────────────────────────────
            _print_section("Test 5: read notion://database/personal")
            result = await session.read_resource("notion://database/personal")
            for content in result.contents:
                if hasattr(content, "text"):
                    print(_pretty_json(content.text))
            
            # ─────────────────────────────────────
            # 测试 6: 错误 db_key,验证防御性
            # ─────────────────────────────────────
            _print_section("Test 6: read notion://database/nonexistent (错误处理)")
            try:
                result = await session.read_resource("notion://database/nonexistent")
                for content in result.contents:
                    if hasattr(content, "text"):
                        print(_pretty_json(content.text))
            except Exception as e:
                print(f"⚠️ 抛异常(也可接受): {type(e).__name__}: {e}")
            
            print(f"\n{'='*60}")
            print("✅ Resources 全部测试完成")
            print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())