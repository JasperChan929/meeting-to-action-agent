"""
inspect_tools.py
绕过 Claude Desktop，直接跟 task_server 握手并打印它上报的工具清单。
作用 = 让你亲眼看到 FastMCP 自动生成的 schema 长什么样。
"""
import asyncio
import json
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    # 用 stdio 启动 task_server.py 子进程
    server_params = StdioServerParameters(
        command="uv",
        args=["run", "task_server.py"],
    )
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # 握手
            await session.initialize()
            print("✅ 握手成功\n")
            
            # 请求工具清单
            tools_result = await session.list_tools()
            
            print(f"📦 server 上报了 {len(tools_result.tools)} 个工具：\n")
            for tool in tools_result.tools:
                print("=" * 60)
                print(f"工具名: {tool.name}")
                print(f"描述: {tool.description}")
                print("参数 Schema:")
                print(json.dumps(tool.inputSchema, indent=2, ensure_ascii=False))
                print()

if __name__ == "__main__":
    asyncio.run(main())