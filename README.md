# FeiLaude

飞书 Claude Bot — 通过飞书消息驱动本地 Claude CLI，实现随时随地的 AI 编程助手。

## 功能特性

- **消息驱动执行** — 在飞书中发送文字消息即可调用本地 Claude CLI 执行指令，结果以 Markdown 卡片形式返回
- **流式状态反馈** — 实时推送 Claude 的工具调用状态（读取文件、编辑文件、运行命令），无需等待最终结果
- **多会话管理** — 支持创建多个独立会话，每个会话绑定不同工作目录，通过 Claude session_id 保持上下文连续
- **任务队列** — 执行期间新消息自动排队，完成后合并提交给 Claude，避免丢失用户意图
- **任务取消** — 随时中断正在执行的任务并清空队列
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

### 会话管理

| 命令 | 说明 |
|------|------|
| `/new <名称> <工作目录>` | 创建新会话并切换 |
| `/use <名称>` | 切换到已有会话 |
| `/sessions` | 查看所有会话 |
| `/delete <名称>` | 删除会话 |

首次发消息时若无活跃会话，Bot 会列出已有会话供你选择。

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
├── router.py            # 消息路由：命令分发、会话选择、任务队列
├── executor.py          # Claude CLI 执行器（流式 JSON 解析）
├── feishu_sender.py     # 飞书消息发送（文本 + 交互式卡片）
├── session_manager.py   # 会话管理（CRUD、持久化到 sessions.yaml）
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
                         管理命令      会话选择       Claude 执行
                        /new /use    waiting模式     executor.py
                              │             │             │
                              ▼             ▼             ▼
                      session_manager   state.py    Claude CLI 子进程
                              │                           │
                              ▼                    流式 JSON 事件
                        sessions.yaml              ▼
                                            on_status 回调
                                                  │
                                                  ▼
                                          feishu_sender.py
                                                  │
                                          飞书卡片/文本消息
```

## 依赖

| 包 | 用途 |
|----|------|
| [lark-oapi](https://github.com/larksuite/oapi-sdk-python) | 飞书开放平台 SDK（WebSocket 长连接 + 消息 API） |
| [pyyaml](https://pypi.org/project/PyYAML/) | 配置与会话数据序列化 |
| [python-dotenv](https://pypi.org/project/python-dotenv/) | 环境变量加载 |

## License

MIT
