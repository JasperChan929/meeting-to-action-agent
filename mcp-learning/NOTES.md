# Day 1 笔记：MCP 基础心智模型

**Date：2026-04-28**

> 今日主题：理解 MCP 的运行链路，尤其是 **Host / Client / Server 分工、工具发现、参数传递、stdio 与 HTTP/SSE 的区别**。
> 今天最重要的收获不是“会写一个 MCP Server”，而是建立正确心智模型：
> **LLM 不直接执行工具，Host 才是真正的执行协调者；Server 只是工具提供方；FastMCP 在 Server 端负责协议解析、参数校验和工具路由。**

---

# 1. MCP 的 Host / Client / Server 三个角色各自负责什么？

## 1.1 一句话理解

```text
Host  = 用户直接交互的应用
Client = Host 内部负责 MCP 通信的模块
Server = 工具提供方，真正暴露 tools / resources / prompts
```

对应到 Claude Desktop：

```text
Claude Desktop = MCP Host
Claude Desktop 内部通信模块 = MCP Client
task_server.py / weather.py = MCP Server
FastMCP = Server 端框架
@mcp.tool() = 你暴露出去的工具函数
```

---

## 1.2 三个角色的分工

| 角色         | 是什么               | 负责什么                                                          | 例子                             |
| ---------- | ----------------- | ------------------------------------------------------------- | ------------------------------ |
| **Host**   | 用户直接使用的 AI 应用     | 读配置、启动 Server、管理对话、把工具列表给 LLM、执行权限控制                          | Claude Desktop、Cursor、你的 Agent |
| **Client** | Host 内嵌的 MCP 通信模块 | 按 MCP 协议和 Server 通信，发送 `initialize`、`tools/list`、`tools/call` | Claude Desktop 内部 MCP Client   |
| **Server** | 工具提供方             | 暴露 tools / resources / prompts，执行工具函数，返回结果                    | `task_server.py`、`weather.py`  |

---

## 1.3 谁启动谁？

在 **stdio 模式**下，通常是：

```text
Host 启动 Server 子进程
```

例如 Claude Desktop 启动时读取配置：

```json
{
  "mcpServers": {
    "task_demo": {
      "command": "uv",
      "args": ["run", "task_server.py"]
    }
  }
}
```

这表示：

```text
Claude Desktop 看到配置
   ↓
按 command + args 启动 task_server.py
   ↓
task_server.py 作为本地子进程运行
   ↓
Claude Desktop 通过 stdin/stdout 和它通信
```

所以严格说：

```text
不是 LLM 启动 Server
也不是 Client 单独启动 Server
而是 Host 根据配置启动 Server
Client 负责和 Server 通信
```

---

## 1.4 一图记住

```text
┌─────────────────────────────────────┐
│              MCP Host               │
│     Claude Desktop / Cursor / Agent │
│                                     │
│  ┌───────────────────────────────┐  │
│  │          MCP Client            │  │
│  │  负责 initialize / tools/list  │  │
│  │  tools/call 等协议通信         │  │
│  └───────────────┬───────────────┘  │
└──────────────────┼──────────────────┘
                   │ stdio / HTTP
                   ▼
┌─────────────────────────────────────┐
│              MCP Server             │
│          你的 task_server.py         │
│                                     │
│  ┌───────────────────────────────┐  │
│  │           FastMCP              │  │
│  │  解析协议 / 校验参数 / 路由工具 │  │
│  └───────────────┬───────────────┘  │
│                  ▼                  │
│         @mcp.tool() Python 函数      │
└─────────────────────────────────────┘
```

---

# 2. Claude Desktop 怎么“知道”我有几个工具？

## 2.1 先纠正一个错误理解

Claude Desktop **不是**从 `claude_desktop_config.json` 里知道工具详情的。

配置文件只告诉 Claude：

```text
怎么启动 Server
```

比如：

```json
{
  "mcpServers": {
    "task_demo": {
      "command": "uv",
      "args": ["run", "task_server.py"]
    }
  }
}
```

这里面没有：

```text
create_task
list_tasks
参数类型
工具用途
docstring
```

所以配置文件只是启动说明，不是工具说明书。

---

## 2.2 工具信息来自哪里？

工具信息来自 Server 启动后的：

```text
握手 + tools/list 工具发现流程
```

完整流程：

```text
1. Claude Desktop 启动
   ↓
2. 读取 claude_desktop_config.json
   ↓
3. 按配置启动 task_server.py 子进程
   ↓
4. Server 里的 FastMCP 启动
   ↓
5. Claude Desktop 发送 initialize 请求
   ↓
6. Server 回复自己支持的能力
   ↓
7. Claude Desktop 发送 tools/list 请求
   ↓
8. FastMCP 扫描所有 @mcp.tool() 函数
   ↓
9. FastMCP 生成工具清单
   ↓
10. Claude Desktop 保存工具清单
   ↓
11. 用户提问时，Claude Desktop 把工具清单一起发给 LLM
```

---

## 2.3 `tools/list` 返回什么？

假设你的代码是：

```python
@mcp.tool()
def create_task(
    title: str,
    owner: str,
    due_date: Optional[str] = None
) -> str:
    """创建一个新任务。如果未指定截止日期，默认为 7 天后。"""
    ...
```

FastMCP 会生成类似这样的工具说明：

```json
{
  "name": "create_task",
  "description": "创建一个新任务。如果未指定截止日期，默认为 7 天后。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "title": {
        "type": "string"
      },
      "owner": {
        "type": "string"
      },
      "due_date": {
        "type": "string"
      }
    },
    "required": ["title", "owner"]
  }
}
```

这份东西就是 LLM 看到的“工具说明书”。

---

## 2.4 工具名、参数、用途分别来自哪里？

| 工具信息 | 来源         | 作用                           |
| ---- | ---------- | ---------------------------- |
| 工具名  | Python 函数名 | `create_task` 成为 tool name   |
| 参数名  | 函数签名       | `title`, `owner`, `due_date` |
| 参数类型 | 类型注解       | `str`, `Optional[str]`       |
| 是否必填 | 是否有默认值     | `due_date=None` 说明可选         |
| 工具用途 | docstring  | LLM 判断什么时候调用这个工具             |

最重要的一句话：

```text
函数名 = 工具名
类型注解 + 默认值 = 参数 schema
docstring = 给 LLM 看的工具说明书
```

---

## 2.5 为什么 docstring 很重要？

因为 LLM 不是靠猜工具用途，而是读工具说明。

不好的 docstring：

```python
@mcp.tool()
def create_task(title: str, owner: str, due_date: Optional[str] = None) -> str:
    """创建任务"""
    ...
```

问题是太短，LLM 不知道：

```text
什么时候用？
参数怎么填？
日期格式是什么？
不传 due_date 会怎样？
```

更好的 docstring：

```python
@mcp.tool()
def create_task(
    title: str,
    owner: str,
    due_date: Optional[str] = None
) -> str:
    """
    创建一个新的工作任务并加入待办列表。

    使用场景：
    当用户提到“建一个任务”、“加到 todo”、“分配给某人做某事”时使用。

    Args:
        title: 任务标题，简短清晰，例如“写周报”
        owner: 负责人姓名
        due_date: 截止日期，格式 YYYY-MM-DD。不填则默认 7 天后。

    Returns:
        创建结果的中文描述。
    """
```

所以：

```text
docstring 写得好不好，会直接影响 Agent 工具调用准确率。
```

---

# 3. LLM 调用我的 Python 函数时，参数是怎么一路传到函数的？

## 3.1 总流程

核心链路是：

```text
用户输入
   ↓
LLM 判断要不要调用工具
   ↓
LLM 返回 tool_use 意图
   ↓
Host 把 tool_use 翻译成 MCP JSON-RPC
   ↓
写入 Server stdin
   ↓
FastMCP 读取并校验参数
   ↓
调用 @mcp.tool() 函数
   ↓
函数结果写回 stdout
   ↓
Host 把结果交给 LLM
   ↓
LLM 生成自然语言回复
```

---

## 3.2 五个时刻

## 时刻 1：LLM 建议调用工具

用户输入：

```text
创建一个任务：写日报，负责人张三，截止 2026-04-30
```

Claude Desktop 会把：

```text
用户消息 + 可用工具清单
```

一起发给 LLM。

LLM 判断后，返回类似：

```json
{
  "tool_use": {
    "name": "task_demo:create_task",
    "arguments": {
      "title": "写日报",
      "owner": "张三",
      "due_date": "2026-04-30"
    }
  }
}
```

注意：

```text
LLM 不直接执行 Python 函数
LLM 只是表达“我想调用这个工具，参数是这些”
```

---

## 时刻 2：Claude Desktop 翻译成 JSON-RPC

Host 收到 LLM 的 tool_use 后，会把它翻译成 MCP 协议请求。

底层类似：

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "create_task",
    "arguments": {
      "title": "写日报",
      "owner": "张三",
      "due_date": "2026-04-30"
    }
  }
}
```

这一步是：

```text
LLM tool_use
   ↓
MCP JSON-RPC tools/call
```

---

## 时刻 3：写入 stdin

如果是 stdio 模式，Claude Desktop 会把这段 JSON-RPC 消息写到 Server 子进程的：

```text
stdin
```

也就是：

```text
Claude Desktop → stdin → task_server.py
```

stdio 只是管道，它负责传输消息，不负责理解消息。

---

## 时刻 4：FastMCP 校验参数

Server 里的 `mcp.run(transport="stdio")` 会持续监听 stdin。

收到消息后，FastMCP 做几件事：

```text
1. 读取 stdin
2. 解析 JSON-RPC
3. 看到 method = tools/call
4. 找到 name = create_task
5. 校验 arguments 是否符合 schema
6. 校验通过才调用函数
```

如果少传参数，比如少了 `due_date`，要看 `due_date` 是否必填。

如果函数签名是：

```python
def create_task(title: str, owner: str, due_date: str) -> str:
```

那 `due_date` 必填，少传就会报错，函数不会执行。

如果函数签名是：

```python
def create_task(
    title: str,
    owner: str,
    due_date: Optional[str] = None
) -> str:
```

那 `due_date` 可选，少传也能执行，函数体里再补默认值。

---

## 时刻 5：调用 Python 函数

校验通过后，FastMCP 执行：

```python
create_task(
    title="写日报",
    owner="张三",
    due_date="2026-04-30"
)
```

函数返回后，FastMCP 把返回值包装成 JSON-RPC response，写回 stdout。

然后：

```text
Server stdout
   ↓
Claude Desktop
   ↓
LLM
   ↓
自然语言回复给用户
```

---

## 3.3 关键安全原则

最重要的一句话：

```text
LLM 只建议调用，Host 才真正执行。
```

这也是 Agent 安全设计的基础：

| 角色      | 负责什么                 |
| ------- | -------------------- |
| LLM     | 判断是否需要工具，生成 tool_use |
| Host    | 权限确认，真正发起调用          |
| Server  | 执行工具函数               |
| FastMCP | 协议解析、参数校验、路由函数       |

---

# 4. stdio 和 SSE/HTTP 模式的核心区别？什么场景用哪种？

## 4.1 一句话区分

```text
stdio = 本地插件模式
SSE/HTTP = 远程服务模式
```

更准确地说：

```text
stdio 和 SSE/HTTP 是 transport 层区别
不是 MCP 协议区别
```

也就是：

```text
MCP 协议不变
JSON-RPC 结构不变
tools/list、tools/call 不变
@mcp.tool() 逻辑基本不变
只是消息怎么传变了
```

---

## 4.2 stdio 模式

stdio 的通信方式是：

```text
stdin + stdout
```

结构：

```text
Claude Desktop / Cursor / 你的 Agent
        ↓
启动本地 MCP Server 子进程
        ↓
通过 stdin/stdout 通信
```

特点：

```text
本机使用
Host 启动 Server
通常一对一
调试简单
零部署成本
适合开发阶段
```

---

## 4.3 stdio 的劣势

## 1）一对一耦合

通常是：

```text
一个 Host
  ↔ 一个 MCP Client
      ↔ 一个本地 Server 子进程
```

换一个 Host，通常要重新启动一个新的 Server 子进程。

---

## 2）只能本机使用

stdio 是进程间管道，不能天然跨网络。

```text
你的 server 跑在自己电脑 / WSL 里
同事电脑不能直接连接它
```

---

## 3）不能自然共享状态

如果每个 Host 都启动自己的 Server 子进程：

```text
Claude Desktop 启动一份
Cursor 启动一份
你的 Agent 启动一份
```

如果状态存在内存里，它们之间互相看不见。

---

## 4）冷启动有延迟

每次 Host 启动 Server 时可能要：

```text
fork 子进程
启动 Python
加载依赖
初始化 FastMCP
扫描工具
完成握手
```

如果 Server 初始化很重，启动会慢。

---

## 5）不方便独立运维

stdio Server 不像一个长期运行的服务，不适合：

```text
健康检查
日志聚合
监控告警
限流
统一认证
水平扩容
```

面试金句：

```text
stdio 模式本质上是把 MCP Server 当成 Client 的本地插件用，
不是把它当成一个独立服务用。
```

---

## 4.4 SSE/HTTP 模式

SSE/HTTP 模式更像一个远程服务：

```text
Claude Desktop / Cursor / 自研 Agent
        ↓ HTTP/SSE
Remote MCP Server
```

特点：

```text
Server 独立部署
多个 Client 连接同一个 Server
可以跨机器
可以共享状态
可以接入监控、日志、认证、限流
```

面试金句：

```text
HTTP 模式让 MCP Server 从“插件”升级成“服务”，进入了微服务架构。
```

---

## 4.5 HTTP/SSE 适合什么场景？

适合：

```text
多人共用
多 Agent 共用
公司内部工具服务
企业知识库
统一任务系统
远程数据库查询
需要统一认证和监控
需要共享状态
```

例如：

```text
公司平台团队部署一个 task MCP Server
   ↓
研发组 Agent 连接
运营组 Agent 连接
产品组 Agent 连接
Cursor / Claude Desktop 也能连接
```

---

## 4.6 如果项目给 10 个人共用，选哪种？

选：

```text
SSE/HTTP
```

原因：

## 1）共享状态

10 个人应该连接同一个 Server，同一个数据库。

```text
10 个用户
   ↓
同一个 HTTP MCP Server
   ↓
同一个数据库
```

---

## 2）运维独立

Server 部署一次，所有人使用。

不需要每个人都配置：

```text
本地路径
uv 环境
Python 依赖
command / args
```

---

## 3）可观测性

HTTP Server 可以接入：

```text
日志
监控
健康检查
权限认证
限流
错误追踪
```

---

## 4.7 当前项目用 stdio 是不是设计错了？

不是。

开发阶段用 stdio 是合理的，因为：

```text
零部署成本
本地调试方便
适合学习和 demo
Claude Desktop 可以直接启动子进程
```

但生产阶段如果要多人共用，就应该切到 HTTP/SSE。

高级表达：

```text
我当前项目使用 stdio，是因为它适合开发阶段快速验证和本地调试。
如果项目要进入多人共用或生产部署，我会切到 HTTP/SSE transport。
工具定义和 MCP 协议不需要大改，只是传输层从 stdin/stdout 换成 HTTP。
这体现了 MCP 协议和 transport 解耦的设计。
```

---

# 5. 今天我犯的最大错误是什么？我从中学到了什么？

## 5.1 最大错误：以为“听懂概念”就等于“建立了模型”

今天最大的问题不是某个术语没背下来，而是：

```text
我以为自己懂了 Host / Client / Server / 握手，
但一到具体问题就混淆了。
```

典型表现：

```text
以为 Claude Desktop 从配置文件知道工具
以为 LLM 靠猜工具用途
以为 stdio 负责参数校验
把 Client 和 Host 的职责混在一起
没有真正理解 tools/list 的作用
```

这些错误说明：

```text
我脑子里的 MCP 模型还是扁平的：
client → server

但真实结构是分层的：
Host / Client / Server
LLM / Host / FastMCP
Transport / Protocol / Application
```

---

## 5.2 错误 1：跳过验证，导致概念没有落地

今天有两次想跳过验证。

比如：

```text
没有亲眼看 mcp dev 里的 tools schema
没有通过实验确认 docstring / type hint 如何变成工具说明
```

结果 Q4 暴露出问题：

```text
不知道 Claude Desktop 到底从哪里拿工具清单
误以为配置文件里就有工具信息
```

这说明：

```text
没有验证过的概念，很容易只是“感觉懂了”。
```

---

## 5.3 错误 2：没有把“握手”当成核心动作

今天最关键的概念其实是：

```text
握手 initialize + tools/list
```

它解释了：

```text
Claude Desktop 怎么知道有哪些工具
LLM 怎么知道工具怎么用
FastMCP 为什么要扫描 @mcp.tool()
docstring 为什么重要
类型注解为什么重要
改代码为什么要重启 Host
```

但我一开始没有把它串起来。

所以 Q4 答错，本质不是 Q4 不会，而是 Q1 的握手没有真懂。

---

## 5.4 错误 3：混淆传输层和协议层

我把 stdio 想成了“会处理调用”的东西。

但实际上：

```text
stdio 只是管道
JSON-RPC / MCP 才是协议
FastMCP 才负责解析、校验、路由
```

正确分层应该是：

```text
应用层：@mcp.tool() Python 函数
协议层：MCP / JSON-RPC / FastMCP
传输层：stdio / HTTP / SSE
```

所以：

```text
参数校验不在 stdio
工具发现不在 stdio
函数路由不在 stdio
```

这些都在 FastMCP / MCP 协议层。

---

## 5.5 错误 4：回答停留在第一层，缺少机制和例子

Q5 比 Q4 稳很多，但还是有问题：

```text
知道 stdio 一对一
知道 HTTP 适合多人复用
```

但还不够深。

面试里不能只说抽象概念：

```text
HTTP 适合公司内部复用
```

更好的说法要加场景：

```text
比如公司平台团队部署一个任务 MCP Server 在内网，
研发组、运营组、产品组的 Agent 都连接同一个 Server，
这样任务状态统一，也方便做认证、日志和监控。
```

今天学到：

```text
每个结论后面要跟一个具体机制或具体场景。
```

否则容易被面试官追问到说不清。

---

# 6. 今天真正学到的东西

## 6.1 MCP 不是“LLM 直接调函数”

正确模型：

```text
LLM 只是决定调用意图
Host 才真正执行调用
Server 执行业务函数
FastMCP 负责协议解析和参数校验
```

---

## 6.2 配置文件不是工具说明书

配置文件只负责：

```text
启动 Server
```

工具说明来自：

```text
FastMCP 扫描 @mcp.tool()
tools/list 上报
```

---

## 6.3 docstring 和类型注解是工程关键

在 MCP 里：

```text
docstring 不是普通注释
类型注解不是装饰品
```

它们会变成 LLM 看到的工具 schema。

---

## 6.4 stdio 和 HTTP/SSE 是 transport 差异

不是 MCP 协议差异。

```text
stdio 适合本地插件
HTTP/SSE 适合远程服务
```

---

## 6.5 技术选型要讲边界

不能说：

```text
MCP 一定比 Function Calling 好
HTTP 一定比 stdio 好
```

应该说：

```text
开发调试阶段，stdio 简单；
生产多人共用，HTTP/SSE 更合适。

单 Agent 工具少，Function Calling 更轻；
多 Host 工具复用，MCP 更有价值。
```

---

# 7. Day 1 总结图

```text
用户
 ↓
Claude Desktop = Host
 ↓
Host 内部 MCP Client
 ↓
读取配置并启动 Server 子进程
 ↓
initialize 握手
 ↓
tools/list 获取工具清单
 ↓
工具清单来自 FastMCP 扫描 @mcp.tool()
 ↓
用户输入问题
 ↓
LLM 根据工具清单生成 tool_use
 ↓
Host 把 tool_use 转成 JSON-RPC tools/call
 ↓
stdin 写给 Server
 ↓
FastMCP 校验参数并路由函数
 ↓
@mcp.tool() Python 函数执行
 ↓
stdout 返回结果
 ↓
Host 把结果交给 LLM
 ↓
LLM 生成最终回复
```

---

# 8. Day 1 最短复习版

```text
Host：用户交互应用，负责启动 Server 和管理工具调用。
Client：Host 内部通信模块，负责说 MCP 协议。
Server：工具提供方，执行 @mcp.tool() 函数。
```

```text
配置文件只告诉 Host 怎么启动 Server。
工具清单来自 Server 的 tools/list 上报。
```

```text
FastMCP 扫描 @mcp.tool()：
函数名 → 工具名
类型注解 → 参数 schema
默认值 → 是否必填
docstring → 工具描述
```

```text
LLM 不直接执行函数。
LLM 只提出 tool_use。
Host 才真正执行调用。
Server 执行工具逻辑。
```

```text
stdio 是本地插件模式。
HTTP/SSE 是远程服务模式。
```

```text
stdio 适合开发调试。
HTTP/SSE 适合多人共用和生产部署。
```

```text
今天最大教训：
没有亲眼验证过的概念，很容易只是“感觉懂了”。
```

---

# 9. 面试可复述版

```text
我现在理解 MCP 的运行流程是：

Claude Desktop 作为 Host，启动时读取配置文件。
配置文件里并不包含工具详情，只包含如何启动 MCP Server 的 command 和 args。

Server 启动后，Host 内部的 MCP Client 会通过 initialize 和 tools/list 与 Server 握手并获取工具清单。
在 FastMCP 里，Server 会扫描所有 @mcp.tool() 函数，把函数名作为工具名，把类型注解和默认值转成 JSON Schema，把 docstring 作为工具描述。

当用户输入问题时，Claude Desktop 会把用户问题和工具清单一起发给 LLM。
LLM 不直接执行代码，它只返回 tool_use 意图。
Host 在授权后把 tool_use 转成 MCP 的 JSON-RPC tools/call 请求，通过 stdio 或 HTTP 发给 Server。
Server 端 FastMCP 校验参数，通过后才调用对应的 Python 函数。
函数结果返回给 Host，再交给 LLM 生成自然语言回复。

stdio 和 HTTP/SSE 的区别主要是传输层区别。
stdio 更像本地插件，适合开发调试；
HTTP/SSE 更像远程服务，适合多人共用、跨机器访问、共享状态和生产运维。
```
