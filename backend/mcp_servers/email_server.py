"""
backend/mcp_servers/email_server.py

MCP Server: 通过 Gmail API 创建邮件草稿(只 compose 权限,不真发)

工具 (Tools):
  - draft_email: 创建一封 Gmail 草稿(承接 ActionItem 的 email 类任务)
  - list_drafts: 列出最近的草稿

资源 (Resources):
  - gmail://account: 当前授权的邮箱信息(用 LLM 知道自己以谁的身份写邮件)

设计要点:
  1. scope = gmail.compose,只能创建/编辑/删除草稿,不能 send/read inbox
     这是有意的安全设计: Agent 写好草稿,人工 review 后手动点发送
  2. token.json 启动时加载,refresh_token 自动续期,无需重新授权
  3. SMTP-style 邮件构造用 stdlib email 库,不用第三方
  4. 跟 task_server 一样:多任务并发用 async + httpx 思路
     (但 google-api-python-client 是 sync 的,这里用 asyncio.to_thread 包一层)
"""
import os
import sys
import json
import base64
import asyncio
import logging
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from mcp.server.fastmcp import FastMCP


# ============ 配置加载 ============
load_dotenv()

BACKEND_DIR = Path(__file__).parent.parent
TOKEN_PATH = BACKEND_DIR / "token.json"

# 日志到 stderr,不污染 MCP stdio 通道
logging.basicConfig(
    level=logging.INFO,
    format="[email_server] %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)


# ============ FastMCP 实例 ============
mcp = FastMCP("email_server")


# ============ 全局状态(启动时初始化) ============
# Gmail API 客户端,所有 tool / resource 共用
_gmail_service = None
# 当前授权的邮箱地址(从 token 反查),给 Resource 用
_account_email: Optional[str] = None


def init_gmail_service() -> None:
    """
    启动时加载 token,构造 Gmail API client。
    Credentials 类会自动用 refresh_token 续期 access_token。
    """
    global _gmail_service, _account_email
    
    if not TOKEN_PATH.exists():
        raise FileNotFoundError(
            f"未找到 {TOKEN_PATH}——先跑 scripts/oauth_init.py 完成授权"
        )
    
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH))
    _gmail_service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    
    # 拿当前邮箱地址(GET /users/me/profile)
    profile = _gmail_service.users().getProfile(userId="me").execute()
    _account_email = profile.get("emailAddress")
    
    log.info(f"✅ Gmail API 已就绪 | account={_account_email}")


def _build_raw_message(
    to: str,
    subject: str,
    body: str,
    cc: Optional[str] = None,
) -> str:
    """
    构造 Gmail API 要求的 base64url 编码邮件原文。
    
    Gmail API 不接受结构化字段,要 RFC 2822 完整邮件文本然后 base64url。
    """
    msg = MIMEText(body, _charset="utf-8")
    msg["To"] = to
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = cc
    # base64url(注意是 url-safe 变体,标准 base64 在 Gmail 这里会被拒)
    raw_bytes = base64.urlsafe_b64encode(msg.as_bytes())
    return raw_bytes.decode("ascii")


# ============ Tool 1: 创建草稿 ============
@mcp.tool()
async def draft_email(
    to: str,
    subject: str,
    body: str,
    cc: Optional[str] = None,
) -> str:
    """
    在当前 Gmail 账户创建一封邮件草稿(不会真发出)。
    
    使用场景:
        ActionItem 的 task_type="email" 时调用此工具。
        典型场景: "通知 X""发邮件给 Y""抄送 VP" 等。
        生成的是草稿,需要用户在 Gmail 网页/客户端手动点发送——
        这是有意的安全设计,Agent 不真发邮件,避免误发。
    
    Args:
        to: 收件人邮箱地址,多个用逗号分隔(如 "a@x.com, b@x.com")
        subject: 邮件主题
        body: 邮件正文(纯文本)
        cc: 抄送邮箱,可选,多个用逗号分隔
    
    Returns:
        草稿创建结果,含 draft id 和 Gmail 网页直达链接。
    """
    if _gmail_service is None:
        return "❌ Gmail service 未初始化"
    
    raw = _build_raw_message(to=to, subject=subject, body=body, cc=cc)
    
    try:
        # google-api-python-client 是同步的,塞进线程池避免阻塞 event loop
        # (跟 task_server 用 httpx.AsyncClient 是不同思路:那边是原生 async,
        # 这边因 SDK 限制只能 to_thread 包,但效果对 caller 一致)
        draft = await asyncio.to_thread(
            lambda: _gmail_service.users().drafts().create(
                userId="me",
                body={"message": {"raw": raw}},
            ).execute()
        )
    except HttpError as e:
        return f"❌ 创建草稿失败 (HTTP {e.resp.status}): {e.reason}"
    except Exception as e:
        return f"❌ 创建草稿失败: {type(e).__name__}: {e}"
    
    draft_id = draft["id"]
    msg_id = draft["message"]["id"]
    # Gmail 网页草稿链接(用 message id,不是 draft id——Gmail 网页 URL 用前者)
    web_url = f"https://mail.google.com/mail/u/0/#drafts/{msg_id}"
    
    return (
        f"✅ 草稿已创建 [account={_account_email}]\n"
        f"  收件人: {to}\n"
        f"  抄送:   {cc or '(无)'}\n"
        f"  主题:   {subject}\n"
        f"  draft_id: {draft_id}\n"
        f"  链接: {web_url}"
    )


# ============ Tool 2: 列出草稿 ============
@mcp.tool()
async def list_drafts(limit: int = 10) -> str:
    """
    列出当前账户最近的邮件草稿。
    
    使用场景:
        用户想"看看我有什么草稿""列出待发邮件"时使用。
    
    Args:
        limit: 返回数量上限,默认 10。
    
    Returns:
        草稿列表的格式化文本。
    """
    if _gmail_service is None:
        return "❌ Gmail service 未初始化"
    
    try:
        # 第一步:列 draft id 列表(只返回 id,不含内容)
        drafts_resp = await asyncio.to_thread(
            lambda: _gmail_service.users().drafts().list(
                userId="me", maxResults=limit
            ).execute()
        )
    except HttpError as e:
        return f"❌ 查询失败 (HTTP {e.resp.status}): {e.reason}"
    
    drafts = drafts_resp.get("drafts", [])
    if not drafts:
        return f"📭 [{_account_email}] 当前没有草稿"
    
    # 第二步:逐个 GET 拿草稿元数据(只取 header,不取 body 节省流量)
    lines = [f"📋 [{_account_email}] 共 {len(drafts)} 条草稿:"]
    for i, d in enumerate(drafts, 1):
        try:
            full = await asyncio.to_thread(
    lambda did=d["id"]: _gmail_service.users().drafts().get(
        userId="me",
        id=did,
        format="metadata",
    ).execute()
)
            headers = full["message"]["payload"].get("headers", [])
            to = next((h["value"] for h in headers if h["name"] == "To"), "(无)")
            subj = next((h["value"] for h in headers if h["name"] == "Subject"), "(无主题)")
            lines.append(f"  {i}. → {to} | {subj}")
        except Exception as e:
            lines.append(f"  {i}. (读取失败: {e})")
    
    return "\n".join(lines)


# ============ Resource: 当前账户信息 ============
@mcp.resource(
    uri="gmail://account",
    name="当前授权的 Gmail 账户",
    description="当前 token 对应的邮箱地址。LLM 在写邮件前可读此资源,知道自己将以哪个身份发件。",
    mime_type="application/json",
)
def account_resource() -> str:
    """
    返回当前授权账户信息。
    比 task_server 的 Resources 简单——这是"单实例"资源,
    不需要 template URI(只有一个账号)。
    """
    return json.dumps(
        {
            "email": _account_email,
            "scopes": ["gmail.compose"],
            "capabilities": ["draft_email", "list_drafts"],
            "limitations": "只能创建草稿,不能真发,不能读取邮件",
        },
        ensure_ascii=False,
        indent=2,
    )


# ============ 启动 ============
if __name__ == "__main__":
    log.info("email_server 启动")
    try:
        init_gmail_service()
    except Exception as e:
        log.error(f"启动失败: {e}")
        sys.exit(1)
    
    log.info("进入 stdio loop")
    mcp.run(transport="stdio")