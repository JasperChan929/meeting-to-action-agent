"""
backend/mcp_servers/task_server.py

MCP Server (v2)：通过 Notion API 管理多个 Database 中的任务

工具 (Tools):
  - create_notion_task(db_key, ...): 在指定 DB 创建任务
  - list_notion_tasks(db_key, limit): 列出指定 DB 最近任务

资源 (Resources) ⭐ Phase 4 新增:
  - notion://databases          列出所有可写 DB（轻量目录）
  - notion://database/{db_key}  单个 DB 的完整 schema（按需加载）

相对 v1 (Day 7) 的改造点：
  ⭐ 1. 单 DB → 多 DB（dict 结构 _databases，启动时并发拉取所有 schema）
  ⭐ 2. 加 @mcp.resource 装饰器，暴露目录 + schema template
  ⭐ 3. 工具加 db_key 参数（默认 "work" 保持向后兼容）
  ⭐ 4. .env 变量名变了：NOTION_DATABASE_ID → NOTION_DB_WORK + NOTION_DB_PERSONAL
"""
import os
import sys
import json
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP


# ============ 配置加载 ============
load_dotenv()

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2026-03-11"

# ⭐ 多 DB 配置：通过命名约定声明所有 db_key
# 之后再加 DB 只需要在这里加一行 + .env 加一个变量,server 代码不动
DB_CONFIG = {
    "work":     os.environ.get("NOTION_DB_WORK"),
    "personal": os.environ.get("NOTION_DB_PERSONAL"),
}

# 日志写到 stderr,绝不污染 stdout(MCP 协议通道)
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

# ⭐ 多 DB 元信息缓存：启动时填充,所有 tool / resource 共用
# 结构: {db_key: {"db_id": str, "ds_id": str, "title": str, "schema": dict}}
_databases: dict[str, dict] = {}


# ============ 启动时初始化（多 DB 并发拉 schema） ============
async def fetch_database_meta(client: httpx.AsyncClient, db_key: str, db_id: str) -> dict:
    """
    拉取单个 Database 的元数据 + schema。
    
    Notion API 2025-09 之后:
      Database 是容器,真正能写入的是 Data Source。
      一个 Database 可挂多个 Data Source(multi-source 场景),简单 DB 只有一个。
    
    返回结构: {db_id, ds_id, title, schema}
    """
    # ---- 1. GET /databases/{id} 拿 data_source_id 和标题 ----
    resp = await client.get(
        f"{NOTION_API}/databases/{db_id}",
        headers=HEADERS,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"无法读取 database '{db_key}' (id={db_id[:8]}...): "
            f"HTTP {resp.status_code} {resp.text[:200]}"
        )
    db_data = resp.json()
    sources = db_data.get("data_sources", [])
    if not sources:
        raise RuntimeError(
            f"database '{db_key}' 没有 data_sources 字段——"
            f"NOTION_VERSION 设错或 DB 配置异常"
        )
    ds_id = sources[0]["id"]
    
    # 标题：Notion 把它存成 rich_text 数组,取第一段的 plain_text
    title_arr = db_data.get("title", [])
    title = title_arr[0]["plain_text"] if title_arr else db_key
    
    # ---- 2. GET /data_sources/{ds_id} 拿真实 schema ----
    # ⭐ 这是 Resources 路线 B 的核心:实时拉 schema 而不是硬编
    resp = await client.get(
        f"{NOTION_API}/data_sources/{ds_id}",
        headers=HEADERS,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"无法读取 data_source for '{db_key}': "
            f"HTTP {resp.status_code} {resp.text[:200]}"
        )
    ds_data = resp.json()
    properties = ds_data.get("properties", {})
    
    # 把 properties 简化成 LLM 友好的格式(完整版字段太多)
    # 只保留 name + type + select 选项(如有)
    simplified_schema = {}
    for prop_name, prop_def in properties.items():
        prop_type = prop_def.get("type")
        entry = {"type": prop_type}
        # select / status 类型展开选项,LLM 知道有哪些值可选
        if prop_type in ("select", "status"):
            options = prop_def.get(prop_type, {}).get("options", [])
            entry["options"] = [opt["name"] for opt in options]
        simplified_schema[prop_name] = entry
    
    return {
        "db_id": db_id,
        "ds_id": ds_id,
        "title": title,
        "schema": simplified_schema,
    }


async def init_all_databases() -> None:
    """
    启动时初始化所有配置的 DB(并发,避免串行多 1 倍延迟)。
    
    缺失的 NOTION_DB_xxx 环境变量会跳过(只警告不致命),
    这样开发阶段只配 work 也能跑。
    """
    global _databases
    
    # 过滤掉没配的 db_key
    active_dbs = {k: v for k, v in DB_CONFIG.items() if v}
    if not active_dbs:
        raise RuntimeError("没有任何 DB 配置——检查 .env 里 NOTION_DB_* 变量")
    
    # ⭐ 并发拉所有 DB 的 schema
    async with httpx.AsyncClient(timeout=10) as client:
        tasks = [
            fetch_database_meta(client, k, v)
            for k, v in active_dbs.items()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 写入全局缓存,失败的 DB 跳过(只 log warning,不阻塞 server 启动)
    for db_key, result in zip(active_dbs.keys(), results):
        if isinstance(result, Exception):
            log.warning(f"DB '{db_key}' 初始化失败,将跳过: {result}")
            continue
        _databases[db_key] = result
        log.info(
            f"✅ DB '{db_key}' 已加载 | title={result['title']} "
            f"| ds_id={result['ds_id'][:8]}... | {len(result['schema'])} 个 property"
        )
    
    if not _databases:
        raise RuntimeError("所有 DB 初始化都失败了,server 无法启动")


def _ensure_db(db_key: str) -> dict:
    """
    工具内部用:校验 db_key 合法,返回 DB 元信息。
    不合法时抛带可读消息的异常(LLM 看到能纠错)。
    """
    if db_key not in _databases:
        available = list(_databases.keys())
        raise ValueError(
            f"未知的 db_key='{db_key}',可选值: {available}。"
            f"请先调用 list_resources 查看 notion://databases。"
        )
    return _databases[db_key]


# ============ Tool 1：创建任务（加了 db_key 参数） ============
@mcp.tool()
async def create_notion_task(
    name: str,
    description: str,
    db_key: str = "work",  # ⭐ 新增:指定写到哪个 DB,默认 work 保持向后兼容
    owner: Optional[str] = None,
    recipient: Optional[str] = None,
    task_type: str = "todo",
    priority: str = "medium",
    deadline: Optional[str] = None,
    confidence: float = 1.0,
    source_text: Optional[str] = None,
) -> str:
    """
    在指定 Notion Database 中创建一条任务,承接 ActionItem 全部字段。

    使用场景:
        从会议纪要提取出 ActionItem 后,把每个 item 写入 Notion 任务库。
        当用户提到"建任务""加到 todo""安排某人做某事"时使用。
        若 ActionItem 是个人事务(健身/学习/家事),把 db_key 设为 "personal";
        否则默认 "work"。可用 DB 列表请先读 notion://databases 资源。

    Args:
        name: 任务名称,简短,10 字内(必填)
        description: 任务详细描述(必填)
        db_key: 目标 DB 标识,可选 "work" / "personal",默认 "work"
        owner: 负责人姓名,可为空(待定)
        recipient: 交付对象,例如 "设计组""VP"
        task_type: "todo"/"email"/"meeting"/"unknown" 之一
        priority: "high"/"medium"/"low" 之一
        deadline: YYYY-MM-DD 或 ISO 8601 datetime;None 默认 7 天后
        confidence: 提取置信度 0-1,会写进 page body
        source_text: 原文片段,会写进 page body

    Returns:
        创建结果的中文描述,包含 Notion 页面链接。
    """
    # ⭐ 校验 db_key + 取出对应 DB 元信息
    db_info = _ensure_db(db_key)
    
    # ---- 1. 处理 deadline ----
    if deadline is None:
        deadline_str = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    else:
        deadline_str = deadline  # ISO 或 YYYY-MM-DD,Notion 都接受
    
    # ---- 2. 拼装 description (写进 page body) ----
    body_lines = [description]
    if recipient:
        body_lines.append(f"📮 交付对象: {recipient}")
    if source_text:
        body_lines.append(f"📜 原文: {source_text}")
    body_lines.append(f"🎯 提取置信度: {confidence:.2f}")
    full_body = "\n\n".join(body_lines)
    
    # ---- 3. 拼装 Notion API payload ----
    properties = {
        "名称": {"title": [{"text": {"content": name}}]},
        "截止日期": {"date": {"start": deadline_str}},
        "状态": {"status": {"name": "未开始"}},
        "优先级": {"select": {"name": priority}},
        "任务类型": {"select": {"name": task_type}},
    }
    if owner:
        properties["负责人"] = {"rich_text": [{"text": {"content": owner}}]}
    
    payload = {
        # ⭐ parent 用从对应 DB 缓存里取的 ds_id
        "parent": {"data_source_id": db_info["ds_id"]},
        "properties": properties,
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
        f"✅ 任务已创建 [{db_key}/{db_info['title']}]\n"
        f"  名称: {name}\n"
        f"  负责人: {owner or '(待定)'}\n"
        f"  类型: {task_type}\n"
        f"  优先级: {priority}\n"
        f"  截止: {deadline_str}\n"
        f"  链接: {page_url}"
    )


# ============ Tool 2：列出任务（加了 db_key 参数） ============
@mcp.tool()
async def list_notion_tasks(db_key: str = "work", limit: int = 10) -> str:
    """
    列出指定 Notion Database 中最近创建的任务。

    使用场景:
        用户想"看看待办""列出所有任务"时使用。
        若用户说"我个人的任务",传 db_key="personal";否则默认 "work"。

    Args:
        db_key: 目标 DB,默认 "work"
        limit: 返回数量上限,默认 10

    Returns:
        任务列表的格式化文本。
    """
    db_info = _ensure_db(db_key)
    
    payload = {
        "page_size": limit,
        "sorts": [{"timestamp": "created_time", "direction": "descending"}],
    }
    
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{NOTION_API}/data_sources/{db_info['ds_id']}/query",
            headers=HEADERS,
            json=payload,
        )
    
    if resp.status_code != 200:
        return f"❌ 查询失败 (HTTP {resp.status_code}): {resp.text[:300]}"
    
    results = resp.json().get("results", [])
    if not results:
        return f"📭 [{db_key}/{db_info['title']}] 当前没有任务"
    
    lines = [f"📋 [{db_key}/{db_info['title']}] 共 {len(results)} 条任务:"]
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


# ============ Resource 1：DB 目录（轻量列表） ============
@mcp.resource(
    uri="notion://databases",
    name="可写 Notion 数据库列表",
    description="所有可被 create_notion_task 写入的 Notion Database 概览,含 db_key 和用途说明。LLM 应在选 db_key 前先读这个资源。",
    mime_type="application/json",
)
def list_databases_resource() -> str:
    """
    返回所有已加载 DB 的目录(不含详细 schema)。
    
    设计要点:
      - 列表轻量(仅 db_key/title/property 数量),不占 LLM context
      - LLM 看到目录后,如果需要某个 DB 的具体字段,
        再 read_resource("notion://database/work") 加载详情
      - 这就是 Resources 相对 tool 的核心优势:目录-内容二级懒加载
    """
    catalog = []
    for db_key, info in _databases.items():
        catalog.append({
            "db_key": db_key,
            "title": info["title"],
            "property_count": len(info["schema"]),
            "detail_uri": f"notion://database/{db_key}",
        })
    return json.dumps(
        {"databases": catalog, "count": len(catalog)},
        ensure_ascii=False,
        indent=2,
    )


# ============ Resource 2：单个 DB 的完整 schema（template） ============
@mcp.resource(
    uri="notion://database/{db_key}",  # ⭐ template URI,{db_key} 是占位符
    name="Notion 数据库详细 schema",
    description="指定 db_key 的 Database 完整字段定义,含每个 property 的类型和 select 可选值。在调 create_notion_task 前可读此资源,确认要传的 select 值合法。",
    mime_type="application/json",
)
def get_database_schema(db_key: str) -> str:
    """
    返回单个 DB 的完整 schema(实时拉自 Notion API,启动时缓存)。
    
    URI 形如 notion://database/work,{db_key} 由 client 调用时传入。
    """
    if db_key not in _databases:
        available = list(_databases.keys())
        return json.dumps(
            {"error": f"未知 db_key='{db_key}'", "available": available},
            ensure_ascii=False,
        )
    
    info = _databases[db_key]
    return json.dumps(
        {
            "db_key": db_key,
            "title": info["title"],
            "ds_id": info["ds_id"],
            "schema": info["schema"],
        },
        ensure_ascii=False,
        indent=2,
    )


# ============ 启动 ============
if __name__ == "__main__":
    if not NOTION_TOKEN:
        log.error("未设置 NOTION_TOKEN(检查 backend/.env)")
        sys.exit(1)
    
    # ⭐ 启动前先拉所有 DB 元数据
    # 这里用 asyncio.run 启同步前置,然后 mcp.run 才进 stdio loop
    log.info(f"task_server v2 启动 | API version {NOTION_VERSION}")
    log.info(f"配置的 DB: {[k for k, v in DB_CONFIG.items() if v]}")
    
    try:
        asyncio.run(init_all_databases())
    except Exception as e:
        log.error(f"启动失败: {e}")
        sys.exit(1)
    
    log.info(f"已加载 {len(_databases)} 个 DB,进入 stdio loop")
    mcp.run(transport="stdio")