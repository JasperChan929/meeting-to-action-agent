# backend/tests/batch_eval.py
import os
import json
from pathlib import Path
from datetime import datetime
from extractors.parser import extract_action_items


CORPUS_DIR = Path(__file__).parent / "meeting_corpus"
OUTPUT_DIR = Path(__file__).parent / "results"


def run_batch():
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    files = sorted(CORPUS_DIR.glob("meeting_*.txt"))
    print(f"找到 {len(files)} 份纪要\n")
    
    summary = []
    
    for f in files:
        text = f.read_text(encoding="utf-8")
        print(f"\n{'='*60}")
        print(f"📄 {f.name}")
        print(f"{'='*60}")
        print(f"原文：\n{text}\n")
        
        try:
            result = extract_action_items(text)
            print(f"✅ 提取出 {len(result.items)} 个 ActionItem：\n")
            
            for i, item in enumerate(result.items, 1):
                print(f"--- {i} ---")
                print(f"  name:       {item.name}")
                print(f"  owner:      {item.owner}")
                print(f"  recipient:  {item.recipient}")
                print(f"  type:       {item.task_type.value}")
                print(f"  priority:   {item.priority.value}")
                print(f"  deadline:   {item.deadline}")
                print(f"  confidence: {item.confidence}")
                print(f"  desc:       {item.description}")
                print()
            
            # 保存 JSON 结果
            out_file = OUTPUT_DIR / f"{f.stem}_result.json"
            out_file.write_text(
                result.model_dump_json(indent=2),
                encoding="utf-8"
            )
            
            summary.append({
                "file": f.name,
                "n_items": len(result.items),
                "avg_confidence": sum(i.confidence for i in result.items) / len(result.items) if result.items else 0,
                "n_no_owner": sum(1 for i in result.items if i.owner is None),
                "n_low_conf": sum(1 for i in result.items if i.confidence < 0.7),
            })
        
        except Exception as e:
            print(f"❌ 提取失败: {e}")
            summary.append({"file": f.name, "error": str(e)})
    
    # 汇总
    print(f"\n{'='*60}")
    print(f"📊 汇总")
    print(f"{'='*60}")
    print(f"{'文件':<25} {'条数':<6} {'均置信':<10} {'无owner':<10} {'低置信':<8}")
    for s in summary:
        if "error" in s:
            print(f"{s['file']:<25} ❌ {s['error']}")
        else:
            print(f"{s['file']:<25} {s['n_items']:<6} {s['avg_confidence']:<10.2f} {s['n_no_owner']:<10} {s['n_low_conf']:<8}")


if __name__ == "__main__":
    run_batch()