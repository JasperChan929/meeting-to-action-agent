"""
test_notion.py
用 Python 调一次 Notion API，验证创建任务能跑通。
不是项目代码，只是验证脚本——后面会被 MCP 工具替代。
"""
import os
import requests

# 从环境变量读 token，永远不要硬编码到代码里
TOKEN = os.environ.get("NOTION_TOKEN")
DBID = "3506669aa58880efbe63e3a7b9c570b2"

if not TOKEN:
    raise RuntimeError("请先 export NOTION_TOKEN=你的token")

URL = "https://api.notion.com/v1/pages"

# Notion API 必需的 3 个 header
headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

# 请求体——结构跟 curl 里 -d 后面那段完全对应
payload = {
    "parent": {"database_id": DBID},
    "properties": {
        "名称": {
            "title": [{"text": {"content": "测试任务-from python"}}]
        },
        "负责人": {
            "rich_text": [{"text": {"content": "李四"}}]
        },
        "截止日期": {
            "date": {"start": "2026-05-02"}
        },
        "状态": {
            "status": {"name": "未开始"}
        },
    },
}

# 发请求。注意是 json= 不是 data=
response = requests.post(URL, headers=headers, json=payload)

print("Status code:", response.status_code)
print("Response:", response.json())