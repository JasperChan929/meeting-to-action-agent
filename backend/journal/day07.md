# Day 7 — 2026-05-01

## 今天做了
- Phase 3.1：backend 升级为独立 uv 项目（pyproject.toml + .venv + .env），mcp-learning/ 保留作学习痕迹
- Phase 3.1：写了 backend/mcp_servers/task_server.py（async + httpx + Notion API 2026-03-11 + ActionItem 全字段映射）
- Phase 3.1：写了 backend/mcp_clients/task_client.py（最简 stdio client，端到端 hello world 跑通）
- Phase 3.2：写了 mcp_clients/run_meeting.py，单段纪要 → parser → MCP tool 批量建任务，meeting_01_formal 4/4 成功
- Phase 3.3：写了 mcp_clients/batch_meetings.py，5 份纪要全跑，结果落 tests/results/phase3_batch.json
- 项目根 git init + 第一次 commit（e051419），mcp-learning/.git 和 backend/.git 都清掉合主 repo

## 今天卡的点
- backend 没有独立 venv，shell 激活的是根 .venv 但 uv add 装到了 backend/.venv，warning 提示但没注意。教训：之后一律用 `uv run`，不依赖 `source activate`
- backend/.git 和 mcp-learning/.git 都是 `uv init` 自动建的空 repo，git add 到主 repo 时报 "does not have a commit checked out"。先 git log + ls-files 确认是空 repo + 无 secret，再 rm -rf .git 安全
- run_meeting.py 写错变量名：循环里 `result = await session.call_tool(...)` 把外层 `result = extract_action_items(...)`（ExtractionResult）覆盖掉了，最后 `print(result.items)` 报 AttributeError。改成 `tool_result` 修复
- list_notion_tasks 拉出 3 条空白脏数据排在最上面，一开始以为是 Notion API 2025-09 改了 query 响应结构，加 debug 打印原始 JSON 才发现是 Day 2 留下的旧测试数据本身字段就空

## 今天学到的关键概念
- **MCP 协议层的 async 模型**：FastMCP 的 `mcp.run()` 内部就是 `asyncio.run()` + 事件循环，所有 tool 必须 async def 才能被 await。tool 同步会阻塞整个 event loop，多 client 并发时全卡。同理 server 内部调外部 API 必须用 httpx.AsyncClient 不能 requests，否则即使函数声明 async 也照样阻塞 loop
- **Notion API 2025-09 破坏性变更**：Database 和 Data Source 解耦，一个 Database 可挂多个 Data Source（multi-source 场景，比如同一个任务库聚合多个 workspace）。新代码用 data_source_id，旧的 database_id 是 legacy。我的处理：server 启动时调一次 GET /databases/{id} 拿 data_source_id 缓存到全局，后续 create/list 都复用，避免每次多一次 HTTP
- **uv 的 venv 一致性**：`source .venv/bin/activate` 依赖 shell 状态，跨终端容易错配。`uv run` 看项目所在的 .venv（pyproject.toml 同级），不依赖激活态——是更稳的 entry point
- **LLM 提取不稳定性是本质特性，不是 bug**：同样 5 份纪要 3 次跑结果不同（17/17/19 条），平均 confidence ±0.02，无 owner 比例 15-30% 浮动。原因是 LLM 内部采样的随机性。工程应对：confidence 字段下游过滤 + HITL 兜底 + 评测多次平均

## 真实指标基线（Phase 9 评测前的占位数据）
- 5 份纪要 × 3 次跑：提取 17 / 17 / 19 条 ActionItem
- 真实建 Notion 任务：19/19 成功，成功率 100%
- 平均 confidence 范围：0.916–0.937
- 真实数据特征：无 owner 占比 15-30%、无 deadline 占比 17-21%
- 单条建任务耗时：≈ 0.4-0.6s（含限速）

## 今天的工程选择（决策记录）
- backend 独立 venv vs 复用根 venv：选独立。代价是重装 5 个包（1 分钟），收益是依赖隔离 + 简历可见的项目结构
- Notion API 2022-06-28 vs 2026-03-11：选 2026-03-11。多 10 行代码，未来不返工 + 面试加分点（"为什么升级"是真实工程决策）
- task_demo 的 4 个 property vs 全字段映射：选全字段，加了优先级和任务类型 2 个 select。description/recipient/source_text/confidence 拼进 page body 不进 property（避免 Notion 表格视图杂乱）
- requests vs httpx：选 httpx。同步 requests 在 async 里会阻塞 event loop，httpx.AsyncClient 是 async 原生
- 单段限速 0.4s + 段间 1s：Notion 官方限速 3 req/s，留 buffer 避免触发 429

## 发现但没修的问题（待 Phase 4-5）
- 幂等性：重跑 batch_meetings 会重复建任务。需要 ActionItem 内容 hash → Notion property "task_id"，建之前先 query。Phase 5 做
- 测试数据混在生产 DB 里：脏数据排序时排前面。需要专用测试 DB 或 query filter。Phase 9 做
- list_notion_tasks 解析旧 page 字段全空：脏数据本身的问题，代码无 bug，但解析容错可以更友好（"未填写" vs "（无）"）
- run_meeting.py 和 batch_meetings.py 都自己 spawn server 子进程，启动 server 大约 2-3 秒。Phase 6 引入 SSE 时改成长连 server

## 明天要做（Phase 4 第一天）
- 加邮件 server（mcp_servers/email_server.py），先用 Gmail draft（不真发）
- ⭐ 实现 MCP Resources：让 task_server 通过 resources/list 暴露多个 Notion DB（比如"工作"+"个人"），LLM 协议级感知有哪些 DB 可写，不靠静态别名

## 要问教练
- Resources 和 Tools 在 FastMCP 里写法的区别？@mcp.resource 是不是和 @mcp.tool 类似但更轻量？
- Gmail OAuth 在本地 dev 环境怎么搞最简单？还是直接用 SMTP + 应用专用密码？

## 教练原则强化
- 任何"陌生输出"先看清楚是什么再操作（uv warning 那次差点忽略，幸好 client 跑不通才发现）
- secret 永远不入聊天/不入 git——day07 早上贴 .env 给教练时输出里带了 key，虽然是假的，但同一个动作在真实场景就是事故。下次贴前先 grep -iE 'key|token|secret'
- 写代码时变量命名警觉：result 这种太通用的名字在嵌套作用域容易覆盖（run_meeting.py 那个 bug 就是这么来的）
- LLM 不稳定性必须接受，不必硬刚——工程层兜底（confidence + HITL + 多次平均）