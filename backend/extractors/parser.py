# backend/extractors/parser.py
import os
from datetime import datetime
from openai import OpenAI
from dotenv import load_dotenv
from .schema import ExtractionResult

load_dotenv()
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def build_system_prompt(meeting_date: datetime | None = None) -> str:
    today = (meeting_date or datetime.now()).strftime("%Y-%m-%d (%A)")
    
    return f"""你是会议纪要分析助手。从用户提供的中文会议纪要中提取所有 ActionItem。

【关键】当前日期：{today}

时间推算示例（严格遵守）：
- 假设今天是 2026-04-30 (周四)
- "明天" → 2026-05-01
- "下周三" → 2026-05-06（距今最近的下一个周三，5-7 天后）
- "下下周三" → 2026-05-13
- "这周内" → 本周日 2026-05-03
- "本周三" → 2026-04-29（已过则警告）
- "月底" → 2026-04-30
- "尽快""赶紧" → null（不写 deadline）
- "下个月初" → 2026-05-上旬，取 2026-05-05

规则：
1. owner：原文明说的填名字；明说"待定/没人接"或要靠推断的填 null
2. task_type 分类：
   - todo: 写文档、修 bug、跟进、调研
   - email: 含"发""通知""抄送""转发"等动词
   - meeting: 含"约""开会""碰一下""复盘"等
   - unknown: 无法判断
3. priority：
   - high: "紧急/赶紧/立刻/今天必须/阻塞"
   - medium: "尽快/重要/优先级高/这周必须"
   - low: 其他
4. description：用动宾短语归纳，不要直接抄原文
5. confidence（0-1）：
   - 0.9-1.0：原文明确，无需推理
   - 0.6-0.9：部分字段靠推断
   - 0.3-0.6：意图模糊
   - <0.3：高度不确定

返回严格符合 schema 的 JSON。"""


def extract_action_items(meeting_text: str, meeting_date: datetime | None = None) -> ExtractionResult:
    response = client.responses.parse(
        model="gpt-5.4-mini",
        input=[
            {"role": "system", "content": build_system_prompt(meeting_date)},
            {"role": "user", "content": meeting_text},
        ],
        text_format=ExtractionResult,
    )
    return response.output_parsed


if __name__ == "__main__":
    sample = """周二的产品评审会，张伟说下周三之前要把首页改版的 PRD 出一版给设计组看看，
李娜跟进一下用户调研的数据，最好这周内。另外那个支付 bug 上次说要修但一直没人接，
赶紧定个责任人吧。会后大家把会议纪要发一下相关方。"""
    
    result = extract_action_items(sample)
    print(f"提取出 {len(result.items)} 个 ActionItem：\n")
    for i, item in enumerate(result.items, 1):
        print(f"--- {i} ---")
        print(item.model_dump_json(indent=2))