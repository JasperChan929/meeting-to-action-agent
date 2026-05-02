"""
backend/mcp_clients/task_client.py

MCP Client：连接 task_server 并调用工具。
今天用途：端到端 hello world 验证。

────────────────────────────────────────────────
async/await 入门讲解（边读代码边看注释，1 小时之后你就懂了）
────────────────────────────────────────────────

什么是 async？
  - 同步代码：按顺序执行，遇到 IO 等待时整个程序卡住（比如 requests.post）
  - 异步代码：遇到 IO 时让出控制权，让其他代码先跑，IO 好了再回来

为什么 MCP 必须 async？
  - server 和 client 之间的 stdio 通信是 IO 操作（跨进程）
  - 多个工具调用可能并发（虽然今天还用不到）
  - SDK 设计成 async，client 调用方就必须配合

3 个核心规则：
  1. async def 定义的函数 = 协程（coroutine），调用时不会真的执行，
     需要 await 才会执行
  2. 所有 IO 操作前面要加 await（session.call_tool 是 IO，要 await）
  3. 程序入口用 asyncio.run() 进入异步世界
"""
import asyncio
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


# ============ 启动参数 ============
# 告诉 client 怎么启动 server 子进程
# 这里我们用 uv run 启动 server，确保 server 跑在 backend/.venv 的环境里
# cwd 指向 backend/ 根（让 .env 能被 dotenv 找到）
BACKEND_DIR = Path(__file__).parent.parent  # /home/.../backend

server_params = StdioServerParameters(
    command="uv",
    args=["run", "python", "mcp_servers/task_server.py"],
    cwd=str(BACKEND_DIR),  # ← 关键：让 server 进程的工作目录是 backend/，这样 load_dotenv() 能找到 .env
)


async def main():
    """
    端到端 hello world：
      1. 启动 server 子进程并建立连接
      2. 列出 server 暴露的工具（验证连接成功）
      3. 调 create_notion_task 建一条假任务
      4. 调 list_notion_tasks 查回来
    """
    print("=" * 60)
    print("MCP Hello World")
    print("=" * 60)
    
    # ─────────────────────────────────────
    # async with：异步版的 with，进入时 await __aenter__()，
    # 退出时 await __aexit__()，这里管理 server 子进程的生命周期
    # ─────────────────────────────────────
    async with stdio_client(server_params) as (read, write):
        # read/write 是和 server 子进程通信的两个 stream
        
        async with ClientSession(read, write) as session:
            # session 是 MCP 协议层的封装，帮你做 JSON-RPC 编解码
            
            # ─────────────────────────────────────
            # 1. 初始化握手（必须，server 在这一步告诉 client 它有哪些工具）
            # await：等待 server 回传初始化响应，期间 IO 阻塞但不阻塞整个程序
            # ─────────────────────────────────────
            await session.initialize()
            print("✅ 已连接到 task_server\n")
            
            # ─────────────────────────────────────
            # 2. 列出工具
            # ─────────────────────────────────────
            tools = await session.list_tools()
            print(f"📦 server 暴露 {len(tools.tools)} 个工具：")
            for t in tools.tools:
                print(f"  - {t.name}: {t.description.split(chr(10))[0] if t.description else '(无描述)'}")
            print()
            
            # ─────────────────────────────────────
            # 3. 调 create_notion_task
            # 模拟 Phase 2 提取出来的一个 ActionItem
            # ─────────────────────────────────────
            print("🚀 调用 create_notion_task ...")
            result = await session.call_tool(
                "create_notion_task",
                arguments={
                    "name": "Hello MCP",
                    "description": "Phase 3.1 端到端 hello world 测试任务",
                    "owner": "测试员",
                    "recipient": "Phase 3 自己",
                    "task_type": "todo",
                    "priority": "medium",
                    "deadline": "2026-05-15",
                    "confidence": 0.95,
                    "source_text": "（这是 Phase 3.1 hello world 的源文本）",
                },
            )
            # result.content 是 list，每个元素是一个返回 block
            # 文本工具的返回会在 result.content[0].text
            for block in result.content:
                if hasattr(block, "text"):
                    print(block.text)
            print()
            
            # ─────────────────────────────────────
            # 4. 调 list_notion_tasks 验证
            # ─────────────────────────────────────
            print("🚀 调用 list_notion_tasks ...")
            result = await session.call_tool("list_notion_tasks", arguments={"limit": 3})
            for block in result.content:
                if hasattr(block, "text"):
                    print(block.text)
            print()
    
    print("=" * 60)
    print("✅ Hello World 完成")
    print("=" * 60)


# ─────────────────────────────────────
# asyncio.run() = 进入异步世界的大门
# main() 调用本身只是创建协程对象（不执行），
# asyncio.run() 才真的把协程跑起来
# ─────────────────────────────────────
if __name__ == "__main__":
    asyncio.run(main())