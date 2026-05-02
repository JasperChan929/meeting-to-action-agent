# Phase 2 遗留（Phase 9 评测时回来处理）

- [ ] 测试集从 5 份扩到 30 份
- [ ] 疑问句场景 confidence 校准（"小王你看看？" 当前 0.95，应 < 0.7）
- [ ] task_type 增加 IM 群消息类型（钉钉/飞书）
- [ ] 条件分支任务处理（"如果他们没空就抄送 VP" 被当成独立 Item）
- [ ] deadline 时间默认 23:59:59 而非 00:00:00


src/generators/llm.py (RAG_DISABLE_METADATA 开关)
src/loaders/pdf_loader.py (regex 5-6 位代码)
scripts/12_ingest_all.py (跳过保利 filter)

新增:

scripts/44_smoke_v7_prompt.py
scripts/45_smoke_v8_prompt.py
scripts/46_full_v8_prompt.py
scripts/47_audit_schema_coverage.py
scripts/diag_baoli_recursion_v2.py
docs/day16-summary.md (我已生成, 你 apply 后)
docs/day16-t1-v7-targets.md
docs/day16-t1-v8-targets.md
docs/day16-v8-smoke-targets.md
docs/day16-v7-results.jsonl
docs/day16-v8-smoke-results.jsonl
docs/day16-v8-full-results.jsonl
docs/project_map.md (你 apply 完改动 1-7 后)
docs/day09-decisions.md (Step 4 我还没给, 待会儿写)