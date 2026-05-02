"""
task_server.py
MCP Server：通过 Notion API 管理任务。
工具：
  - create_notion_task: 在 Notion Database 创建一条任务
  - list_notion_tasks:  查询 Database 的最近任务
"""
import os
from datetime import datetime, timedelta
from typing import Optional

import requests
from mcp.server.fastmcp import FastMCP

# ============ 配置 ============
mcp = FastMCP("task_demo")

# 优先读环境变量，没有就读 token 文件
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
if not NOTION_TOKEN:
    token_file = os.path.expanduser("~/.notion_token")
    if os.path.exists(token_file):
        with open(token_file) as f:
            NOTION_TOKEN = f.read().strip()

NOTION_DBID = "3506669aa58880efbe63e3a7b9c570b2"
NOTION_API = "https://api.notion.com/v1"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


# ============ 工具 1：创建任务 ============
@mcp.tool()
def create_notion_task(
    title: str,
    owner: str,
    due_date: Optional[str] = None,
    status: str = "未开始",
) -> str:
    """
    在 Notion Database 中创建一条任务。

    使用场景：
        当用户提到"建一个任务"、"加到 todo"、"分配给某人做某事"时使用。

    Args:
        title: 任务标题，简短清晰，例如 "写周报"
        owner: 负责人姓名
        due_date: 截止日期，格式 YYYY-MM-DD。不填默认 7 天后。
        status: 任务状态，可选值："未开始"、"进行中"、"完成"。默认"未开始"。

    Returns:
        创建结果的中文描述，包含 Notion 页面链接。
    """
    # 处理可选的 due_date
    if due_date is None:
        due_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")

    payload = {
        "parent": {"database_id": NOTION_DBID},
        "properties": {
            "名称": {"title": [{"text": {"content": title}}]},
            "负责人": {"rich_text": [{"text": {"content": owner}}]},
            "截止日期": {"date": {"start": due_date}},
            "状态": {"status": {"name": status}},
        },
    }

    response = requests.post(
        f"{NOTION_API}/pages", headers=HEADERS, json=payload, timeout=10
    )

    if response.status_code != 200:
        return f"❌ 创建失败 (HTTP {response.status_code}): {response.text}"

    data = response.json()
    page_url = data.get("url", "")
    return (
        f"✅ 任务已创建\n"
        f"  标题: {title}\n"
        f"  负责人: {owner}\n"
        f"  截止: {due_date}\n"
        f"  状态: {status}\n"
        f"  链接: {page_url}"
    )


# ============ 工具 2：列出任务 ============
@mcp.tool()
def list_notion_tasks(limit: int = 10) -> str:
    """
    列出 Notion Database 中最近的任务。

    使用场景：
        当用户想"看看有什么待办"、"列出所有任务"时使用。

    Args:
        limit: 返回数量上限，默认 10。

    Returns:
        任务列表的格式化文本。
    """
    payload = {
        "page_size": limit,
        "sorts": [{"timestamp": "created_time", "direction": "descending"}],
    }

    response = requests.post(
        f"{NOTION_API}/databases/{NOTION_DBID}/query",
        headers=HEADERS,
        json=payload,
        timeout=10,
    )

    if response.status_code != 200:
        return f"❌ 查询失败 (HTTP {response.status_code}): {response.text}"

    results = response.json().get("results", [])
    if not results:
        return "📭 当前没有任务"

    lines = [f"📋 共 {len(results)} 条任务："]
    for i, page in enumerate(results, 1):
        props = page["properties"]

        # 解析每个字段（Notion 返回的结构有点深）
        title_arr = props.get("名称", {}).get("title", [])
        title = title_arr[0]["plain_text"] if title_arr else "(无标题)"

        owner_arr = props.get("负责人", {}).get("rich_text", [])
        owner = owner_arr[0]["plain_text"] if owner_arr else "(未指定)"

        date_obj = props.get("截止日期", {}).get("date") or {}
        due = date_obj.get("start", "(无)")

        status_obj = props.get("状态", {}).get("status") or {}
        status = status_obj.get("name", "(无)")

        lines.append(
            f"  {i}. [{status}] {title} | {owner} | 截止: {due}"
        )

    return "\n".join(lines)


# ============ 启动 ============
if __name__ == "__main__":
    if not NOTION_TOKEN:
        # 这条提示在 stderr 里，Claude Desktop 启动时会写进 log
        import sys
        print("❌ 未设置 NOTION_TOKEN 环境变量", file=sys.stderr)
        sys.exit(1)
    mcp.run(transport="stdio")