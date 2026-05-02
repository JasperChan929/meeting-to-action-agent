# backend/extractors/parser.py
import os
import json
from openai import OpenAI
from dotenv import load_dotenv
from .schema import ExtractionResult

load_dotenv()
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])


SYSTEM_PROMPT = """你是会议纪要分析助手。从用户提供的中文会议纪要中提取所有 ActionItem。

规则：
1. 一条纪要可能有多个 ActionItem，也可能没有
2. owner 字段：原文明说的负责人填名字；明说"待定/没人接"填 null；要靠推断的也填 null
3. deadline 字段：转成 ISO 格式（YYYY-MM-DD）；模糊时间（"尽快""这周内"）按当前会议日期合理推断；完全没说填 null
4. task_type 分类：
   - todo: 一般任务（写文档、修 bug、跟进）
   - email: 明确说要发邮件/通知/抄送
   - meeting: 明确说要约会、开会
   - unknown: 无法判断
5. priority：含"紧急/赶紧/立刻"→high，含"尽快/重要"→medium，其他→low
6. confidence（0-1）打分标准：
   - 0.9-1.0：原文明确，无需推理
   - 0.6-0.9：部分字段靠推断
   - 0.3-0.6：任务边界或意图模糊
   - <0.3：高度不确定

返回 JSON，严格符合 schema。
"""


def extract_action_items(meeting_text: str) -> ExtractionResult:
    response = client.responses.parse(
        model="gpt-5.4-mini",
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
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