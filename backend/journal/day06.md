# Day 6 — 2026-04-30

## 今天做了
- 完成 Phase 2 全部内容
- backend/extractors/ 下写了 schema.py（ActionItem 9 字段 Pydantic 模型）和 parser.py（gpt-5.4-mini + Structured Outputs）
- 自建 5 段不同风格测试纪要（正式 / 混乱 / 技术 / 闲聊 / 嵌套），写了 batch_eval.py 批量跑
- 跑通端到端：纪要文本 → LLM 提取 → 结构化 ActionItem
- 指标：召回率 100%，准确率 95%，平均 confidence 0.93

## 今天卡的点
- 一开始没搞懂 LLM 的角色——以为是 Python 用规则提取，反复确认才理解 LLM = 推理引擎，Python = 工程胶水
- confidence 字段的含义反复来回了 3-4 次才真正理解：是 LLM 自评的把握分，不是字段空不空的标志
- "下周三"被算成 5/13，最后用 few-shot 修对成 5/6
- few-shot 选静态虚拟日期 vs 动态生成，最后选静态（保 Prompt Caching 命中率）

## 今天学到的关键概念
- **MCP vs Function Calling**：协议 vs 机制，不是替代关系
- **三层防线**：格式（Pydantic）→ 语义（Prompt）→ 业务（Python 校验）
- **temporal context**：LLM 没实时信息，时间必须注入；分析历史会议要传会议日期不是 now()
- **Prompt Caching**：前缀匹配，固定放头、动态放尾，cached input 收 10% 价
- **confidence 反直觉**：没写不一定低（"明说待定"是 0.95），写了不一定高（语义模糊会自降）

## 发现但没修的问题（写进 TODO.md）
- 疑问句 confidence 偏高（"小王你看看？" 当前 0.95，应 < 0.7）
- IM 群消息 task_type 没覆盖（"扔群里" 被标 email）
- 条件分支任务（"如果他们没空就抄送 VP"）被拆成独立 Item
- deadline 默认 00:00:00 应改成 23:59:59
- 测试集只有 5 段，Phase 9 要扩到 30

## 明天要做（Phase 3.1）
- 把 mcp-learning/task_demo 升级到 backend/mcp_servers/task_server.py
- 用正式项目结构 + .env + python-dotenv 替代 ~/.notion_token
- 开始写 MCP Client（async/await，project 里第一次用异步）

## 要问教练
- Phase 3 的 MCP Client 是 async 的，我对 async/await 不熟，要不要先花 30 分钟补一下基础再开干
- task_server 要不要顺便加 Resources（暴露多个 Notion DB），还是 Phase 4 再加

## 教练原则强化
- 我赶时间时直接说"教练全代写"，但要清楚 trade-off（简历可信度会打折）
- 简历数字必须是真实跑出来的
- 不会就说不会，硬编错答案没用
- LLM 不擅长的事让 Python 兜底（月底用 calendar.monthrange、deadline 范围校验）

---

## 明天新 session 第一条消息（直接粘）

```
Phase 3 第一天。项目档案在 instructions 里（已更新到 v2.1，Phase 2 已完成）。
我每天 3-4 小时，目标大厂 Agent 实习。

昨天的笔记：backend/journal/day06.md
今天打算做 Phase 3.1：把 mcp-learning/task_demo 升级到 backend/mcp_servers/task_server.py，
然后开始写 MCP Client（async）。

我对 async/await 不太熟，要先补基础还是直接开干？

教练模式：不重复我懂的、关键决策让我先答、不讲废话、代码你直接给。
```