"""
backend/scripts/oauth_init.py

一次性 OAuth 授权脚本:第一次跑会弹浏览器授权,
完成后生成 backend/token.json,之后 email_server 就用 token.json 免授权。

执行:
    uv run python scripts/oauth_init.py
"""
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

# 只要 compose 权限(创建草稿),不能发送、不能读取——最小权限原则
SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]

BACKEND_DIR = Path(__file__).parent.parent
CREDENTIALS = BACKEND_DIR / "credentials.json"
TOKEN = BACKEND_DIR / "token.json"

if not CREDENTIALS.exists():
    raise FileNotFoundError(f"未找到 {CREDENTIALS}——先去 GCP Console 下载")

print(f"📡 启动 OAuth 流程,scope: {SCOPES}")
flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS), SCOPES)
# run_local_server 会自动起本地服务器接 callback,弹浏览器
creds = flow.run_local_server(
    port=0,
    open_browser=False,    # ⭐ 关键:不要自动打开浏览器
)

# 保存 token (含 refresh_token,后续不用再授权)
TOKEN.write_text(creds.to_json())
print(f"✅ token 已保存: {TOKEN}")
print(f"🔒 记得把 token.json 加进 .gitignore!")