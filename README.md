# FeiLaude

飞书 Claude Bot — 通过飞书消息驱动本地 Claude CLI，实现随时随地的 AI 编程助手。

## 功能特性

- **消息驱动执行** — 在飞书中发送文字消息即可调用本地 Claude CLI 执行指令，结果以 Markdown 卡片形式返回
- **流式状态反馈** — 实时推送 Claude 的工具调用状态（读取文件、编辑文件、运行命令），无需等待最终结果
- **多工作区管理** — 支持创建多个独立工作区，每个工作区绑定不同项目目录，通过 `/workspaces` 查看和切换
- **多对话上下文** — 每个工作区可维护多个 Claude 对话（session_id），通过 `--resume` 保持上下文连续，支持自由切换和恢复
- **任务队列** — 执行期间新消息自动排队，完成后合并提交给 Claude，避免丢失用户意图
- **任务取消** — 随时中断正在执行的任务（跨平台进程树杀死）并清空队列
- **长文本分段** — 自动将超长回复拆分为多张卡片，在段落边界分割并保护代码块完整性

## 快速开始

### 前置条件

- Python 3.10+
- [Claude CLI](https://docs.anthropic.com/en/docs/claude-code) 已安装并登录

### 安装

```bash
git clone <repo-url> && cd feilaude
pip install -r requirements.txt
```

### 配置

**1. 创建飞书应用**

在[飞书开放平台](https://open.feishu.cn/)创建应用，获取 App ID 和 App Secret，开启以下权限：

- `im:message` — 接收消息
- `im:message:send_as_bot` — 发送消息

**2. 配置环境变量**

```bash
cp .env.example .env
```

编辑 `.env`，填入飞书应用凭证：

```
FEISHU_APP_ID=cli_xxxxxx
FEISHU_APP_SECRET=xxxxxx
```

**3. 配置 Claude CLI**

编辑 `config.yaml`：

```yaml
claude:
  cli_path: "claude"          # Claude CLI 可执行文件路径
  workdir: "."                # 默认工作目录
  timeout: 600                # 执行超时（秒）
```

### 启动

```bash
python main.py
```

## 使用方式

### 工作区管理

| 命令 | 说明 |
|------|------|
| `/new <名称> <工作目录>` | 创建新工作区并切换 |
| `/use <名称>` | 切换到已有工作区 |
| `/workspaces` | 查看所有工作区（含对话数量） |
| `/delete <名称>` | 删除工作区 |

首次发消息时若无活跃工作区，Bot 会列出已有工作区供你选择。

### 对话管理

| 命令 | 说明 |
|------|------|
| `/sessions` | 查看当前工作区的所有对话 |
| `/attach <uuid>` | 切换到指定对话（通过 session_id） |
| `/continue` | 切换到最近一次使用的对话 |

每个工作区可以有多条独立对话，每次执行会自动在当前活跃对话上续接。如果活跃对话不存在，Claude 会创建新对话并自动记录。

### 任务控制

| 命令 | 说明 |
|------|------|
| `/status` | 查看 Bot 当前状态（空闲/执行中、运行时间、队列） |
| `/cancel` | 取消正在执行的任务并清空排队消息 |

### 普通消息

直接发送文字内容即可，Bot 会将其作为 prompt 传递给 Claude CLI。

**示例对话：**

```
用户: 帮我写一个 Python 函数计算斐波那契数列
Bot:  已收到指令，正在调用 Claude 执行...
Bot:  📖 读取 main.py
Bot:  ✏️ 编辑 main.py
Bot:  [Claude 回复卡片]
```

**多对话切换：**

```
用户: /workspaces
Bot:  📋 工作区列表：
       1. my-app (3个对话) ★
          目录: D:\workspace\my-app
       2. api-server (1个对话)
          目录: D:\workspace\api

用户: /sessions
Bot:  📋 工作区 [my-app] 对话历史：
       1. a1b2c3d4... (活跃)  上次: 2026-04-09 14:30
       2. e5f6g7h8...         上次: 2026-04-08 10:15
       3. i9j0k1l2...         上次: 2026-04-07 09:00

用户: /attach e5f6g7h8-xxxx-xxxx-xxxx-xxxxxxxxxxxx
Bot:  ✓ 切换到对话 e5f6g7h8...

用户: /continue
Bot:  ✓ 切换到最近对话 a1b2c3d4...
```

**排队机制：**

```
用户: 帮我重构一下 router.py        ← 正在执行
用户: 顺便更新一下 tests             ← Bot 回复：已排队（第 1 位）
用户: 再帮我看看 README              ← Bot 回复：已排队（第 2 位）
Bot:  [第一项结果卡片]               ← 排队消息合并后自动执行
Bot:  [合并结果卡片]
```

## 项目结构

```
feilaude/
├── main.py              # 入口：WebSocket 客户端与事件分发
├── config.py            # 配置加载（.env + config.yaml）
├── router.py            # 消息路由：命令分发、工作区选择、任务队列
├── executor.py          # Claude CLI 执行器（流式 JSON 解析、进程树管理）
├── feishu_sender.py     # 飞书消息发送（文本 + 交互式卡片，同步/异步）
├── session_manager.py   # 工作区与对话管理（CRUD、多对话、持久化）
├── state.py             # Bot 状态机（idle / executing / waiting_select）
├── config.yaml          # Claude CLI 配置
├── .env.example         # 环境变量模板
└── requirements.txt     # Python 依赖
```

## 架构概览

```
飞书用户 ──消息──▶ 飞书 WebSocket ──事件──▶ router.py
                                            │
                              ┌─────────────┼─────────────┐
                              ▼             ▼             ▼
                         管理命令      工作区选择       Claude 执行
                      /new /use     waiting模式     executor.py
                    /workspaces                       │
                    /sessions     session_mgr     Claude CLI 子进程
                    /attach           │                │
                    /continue         │         流式 JSON 事件
                              │       │                │
                              ▼       ▼                ▼
                      session_manager  state.py   on_status 回调
                         │    │                        │
                         │    ▼                        ▼
                    工作区   对话列表          feishu_sender.py
                   (name,   (sids,                      │
                    workdir) active_sid)       飞书卡片/文本消息
                         │
                         ▼
                    sessions.yaml
```

## 依赖

| 包 | 用途 |
|----|------|
| [lark-oapi](https://github.com/larksuite/oapi-sdk-python) | 飞书开放平台 SDK（WebSocket 长连接 + 消息 API） |
| [pyyaml](https://pypi.org/project/PyYAML/) | 配置与会话数据序列化 |
| [python-dotenv](https://pypi.org/project/python-dotenv/) | 环境变量加载 |

## License

MIT
