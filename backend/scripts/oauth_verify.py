"""
验证 Gmail API 通了:列出最近 5 封邮件标题
(注意:gmail.compose scope 实际不允许 list 邮件,这里只是验证 token 加载和 API 客户端构造无误)
"""
from pathlib import Path
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

BACKEND_DIR = Path(__file__).parent.parent
TOKEN = BACKEND_DIR / "token.json"

creds = Credentials.from_authorized_user_file(str(TOKEN))
service = build("gmail", "v1", credentials=creds)

# 创建一个空草稿(最小权限能做的操作)验证 token 真能用
draft = service.users().drafts().create(
    userId="me",
    body={
        "message": {
            "raw": __import__("base64").urlsafe_b64encode(
                b"To: test@example.com\r\nSubject: oauth test\r\n\r\nhello"
            ).decode()
        }
    },
).execute()
print(f"✅ 测试草稿已创建,id={draft['id']}")
print(f"🗑️ 去 Gmail → 草稿箱 删掉这条测试草稿")