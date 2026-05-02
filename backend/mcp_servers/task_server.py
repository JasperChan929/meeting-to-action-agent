"""
backend/mcp_servers/task_server.py

MCP Server (v1)：通过 Notion API 管理任务
工具：
  - create_notion_task: 在 Notion Database 创建一条任务（全字段）
  - list_notion_tasks:  列出最近任务

相对 Day 2 task_demo 的改造点：
  1. requests (sync) → httpx.AsyncClient (async)
  2. Notion API: 2022-06-28 → 2026-03-11，用 data_source_id 替代 database_id
  3. 加 ActionItem 全字段映射（priority, task_type, description, recipient, source_text）
  4. 去掉 ~/.notion_token 兜底，强制走 .env
  5. 启动时缓存 data_source_id（避免每次 create 都 retrieve 一次）
"""
import os
import sys
import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP


# ============ 配置加载 ============
# 从 backend/.env 读 secret，server 自己加载（不依赖父进程环境）
# 这样不管谁 spawn 这个 server（Claude Desktop / 你的 client / mcp dev），
# 它都能拿到 token——避免 Day 2 踩过的 WSL env 不继承坑
load_dotenv()

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2026-03-11"  # ⭐ 升级到当前最新版本（多 data source 模型）

# 日志写到 stderr，不污染 stdio（stdout 是 MCP 协议通信通道，绝对不能写日志）
logging.basicConfig(
    level=logging.INFO,
    format="[task_server] %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)


# ============ FastMCP 实例 ============
mcp = FastMCP("task_server")

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json",
}

# data_source_id 启动时缓存
# 全局变量，在 startup 函数里填充，所有 tool 共用
_data_source_id: Optional[str] = None


# ============ 启动时初始化（拿 data_source_id） ============
async def init_data_source() -> str:
    """
    Notion API 2025-09 之后，Database 是容器，真正能写入的是 Data Source。
    一个 Database 可以有多个 Data Source（multi-source），但简单 DB 只有一个。
    
    这个函数：
      1. 调 GET /databases/{id} 拿到 database 元数据
      2. 从中提取 data_sources[0].id 作为写入目标
      3. 缓存到全局，所有 tool 共用
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{NOTION_API}/databases/{NOTION_DATABASE_ID}",
            headers=HEADERS,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"无法读取 database：HTTP {resp.status_code} {resp.text}"
            )
        data = resp.json()
        sources = data.get("data_sources", [])
        if not sources:
            raise RuntimeError(
                "database 没有 data_sources 字段——可能 NOTION_VERSION 设置错了或 DB 配置异常"
            )
        ds_id = sources[0]["id"]
        log.info(f"已缓存 data_source_id: {ds_id[:8]}...")
        return ds_id


# ============ 工具 1：创建任务（全字段映射） ============
@mcp.tool()
async def create_notion_task(
    name: str,
    description: str,
    owner: Optional[str] = None,
    recipient: Optional[str] = None,
    task_type: str = "todo",
    priority: str = "medium",
    deadline: Optional[str] = None,
    confidence: float = 1.0,
    source_text: Optional[str] = None,
) -> str:
    """
    在 Notion Database 中创建一条任务，承接 ActionItem 全部字段。

    使用场景：
        从会议纪要提取出 ActionItem 后，把每个 item 写入 Notion 任务库。
        当用户提到"建任务"、"加到 todo"、"安排某人做某事"时使用。

    Args:
        name: 任务名称，简短，10 字内（必填）
        description: 任务详细描述（必填）
        owner: 负责人姓名，可为空（待定）
        recipient: 交付对象，例如 "设计组"、"VP"
        task_type: 任务类型，必须是 "todo"/"email"/"meeting"/"unknown" 之一
        priority: 优先级，必须是 "high"/"medium"/"low" 之一
        deadline: 截止日期，格式 YYYY-MM-DD 或 ISO 8601 datetime；None 默认 7 天后
        confidence: 提取置信度 0-1，会写进 description 末尾
        source_text: 原文片段，会写进 description 末尾

    Returns:
        创建结果的中文描述，包含 Notion 页面链接。
    """
    global _data_source_id
    if _data_source_id is None:
        _data_source_id = await init_data_source()
    
    # ---- 1. 处理 deadline ----
    if deadline is None:
        deadline_str = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    elif "T" in deadline:
        # ISO datetime（来自 ActionItem.deadline 的 datetime 序列化）
        # Notion 的 date.start 接受 YYYY-MM-DD 或 ISO 8601，这里直接传
        deadline_str = deadline
    else:
        deadline_str = deadline  # 已经是 YYYY-MM-DD
    
    # ---- 2. 拼装 description (写进 page body) ----
    # 这些字段不放 Notion property（避免视图杂乱），都拼进正文
    body_lines = [description]
    if recipient:
        body_lines.append(f"📮 交付对象: {recipient}")
    if source_text:
        body_lines.append(f"📜 原文: {source_text}")
    body_lines.append(f"🎯 提取置信度: {confidence:.2f}")
    full_body = "\n\n".join(body_lines)
    
    # ---- 3. 拼装 Notion API payload ----
    properties = {
        # title 类型必须包成 [{text:{content:...}}] 这种结构
        "名称": {"title": [{"text": {"content": name}}]},
        "截止日期": {"date": {"start": deadline_str}},
        "状态": {"status": {"name": "未开始"}},
        "优先级": {"select": {"name": priority}},
        "任务类型": {"select": {"name": task_type}},
    }
    # owner 为空时不传该字段，避免 Notion 写入空字符串
    if owner:
        properties["负责人"] = {"rich_text": [{"text": {"content": owner}}]}
    
    payload = {
        # ⭐ 用 data_source_id，不是 database_id（API 2025-09 之后的写法）
        "parent": {"data_source_id": _data_source_id},
        "properties": properties,
        # children 是 page body，把 description 写成段落
        "children": [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": full_body}}]
                },
            }
        ],
    }
    
    # ---- 4. 调 Notion API ----
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{NOTION_API}/pages",
            headers=HEADERS,
            json=payload,
        )
    
    if resp.status_code != 200:
        return f"❌ 创建失败 (HTTP {resp.status_code}): {resp.text[:300]}"
    
    page_url = resp.json().get("url", "")
    return (
        f"✅ 任务已创建\n"
        f"  名称: {name}\n"
        f"  负责人: {owner or '(待定)'}\n"
        f"  类型: {task_type}\n"
        f"  优先级: {priority}\n"
        f"  截止: {deadline_str}\n"
        f"  链接: {page_url}"
    )


# ============ 工具 2：列出任务 ============
@mcp.tool()
async def list_notion_tasks(limit: int = 10) -> str:
    """
    列出 Notion Database 中最近创建的任务。

    使用场景：
        当用户想"看看有什么待办"、"列出所有任务"时使用。

    Args:
        limit: 返回数量上限，默认 10。

    Returns:
        任务列表的格式化文本。
    """
    global _data_source_id
    if _data_source_id is None:
        _data_source_id = await init_data_source()
    
    payload = {
        "page_size": limit,
        "sorts": [{"timestamp": "created_time", "direction": "descending"}],
    }
    
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            # ⭐ 2025-09+ 版本：query 走 data_sources/{id}/query，不是 databases/{id}/query
            f"{NOTION_API}/data_sources/{_data_source_id}/query",
            headers=HEADERS,
            json=payload,
        )
    
    if resp.status_code != 200:
        return f"❌ 查询失败 (HTTP {resp.status_code}): {resp.text[:300]}"
    
    results = resp.json().get("results", [])
    if not results:
        return "📭 当前没有任务"

    
    lines = [f"📋 共 {len(results)} 条任务："]
    for i, page in enumerate(results, 1):
        props = page["properties"]
        
        title_arr = props.get("名称", {}).get("title", [])
        title = title_arr[0]["plain_text"] if title_arr else "(无标题)"
        
        owner_arr = props.get("负责人", {}).get("rich_text", [])
        owner = owner_arr[0]["plain_text"] if owner_arr else "(待定)"
        
        date_obj = props.get("截止日期", {}).get("date") or {}
        due = date_obj.get("start", "(无)")
        
        status_obj = props.get("状态", {}).get("status") or {}
        status = status_obj.get("name", "(无)")
        
        priority_obj = props.get("优先级", {}).get("select") or {}
        priority = priority_obj.get("name", "(无)")
        
        lines.append(
            f"  {i}. [{status}] [{priority}] {title} | {owner} | 截止: {due}"
        )
    
    return "\n".join(lines)


# ============ 启动 ============
if __name__ == "__main__":
    if not NOTION_TOKEN:
        log.error("未设置 NOTION_TOKEN（检查 backend/.env）")
        sys.exit(1)
    if not NOTION_DATABASE_ID:
        log.error("未设置 NOTION_DATABASE_ID（检查 backend/.env）")
        sys.exit(1)
    
    log.info(f"task_server 启动 | API version {NOTION_VERSION}")
    mcp.run(transport="stdio")