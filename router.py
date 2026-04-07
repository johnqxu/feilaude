import asyncio
import json
import logging
import time

from executor import execute_claude
from feishu_sender import FeishuSender
from session_manager import SessionManager
from state import BotState

logger = logging.getLogger(__name__)

MANAGEMENT_COMMANDS = ("/new", "/use", "/sessions", "/delete", "/status", "/cancel")


def _is_management_command(text: str) -> bool:
    """Check if text starts with a management command."""
    for cmd in MANAGEMENT_COMMANDS:
        if text == cmd or text.startswith(cmd + " "):
            return True
    return False


def handle_message(
    event,
    config,
    sender: FeishuSender,
    session_mgr: SessionManager,
    state: BotState,
):
    event_data = event.event
    message = event_data.message
    sender_open_id = event_data.sender.sender_id.open_id

    logger.info("收到消息：open_id=%s, type=%s", sender_open_id, message.message_type)

    # Filter non-text messages
    if message.message_type != "text":
        sender.send_message(sender_open_id, "暂不支持该消息类型，请发送文字消息")
        return

    # Parse text content
    try:
        content = json.loads(message.content)
        raw_text = content.get("text", "").strip()
    except json.JSONDecodeError:
        sender.send_message(sender_open_id, "消息解析失败，请重试")
        return

    if not raw_text:
        sender.send_message(sender_open_id, "请输入要执行的指令")
        return

    logger.info("消息内容（长度=%d）：%.100s%s", len(raw_text), raw_text, "..." if len(raw_text) > 100 else "")

    # ---- WAITING_SELECT mode ----
    if state.is_waiting_select:
        _handle_waiting_select(raw_text, sender_open_id, sender, config, session_mgr, state)
        return

    # ---- Management commands (always handled locally) ----
    if _is_management_command(raw_text):
        _handle_command(raw_text, sender_open_id, sender, session_mgr, state)
        return

    # ---- Queue if currently executing ----
    if state.is_executing:
        pos = state.enqueue(raw_text)
        sender.send_message(sender_open_id, f"已排队（第 {pos} 位）")
        return

    # ---- Normal message routing ----
    active = session_mgr.get_active()
    if not active:
        # No active session → trigger selection flow
        sessions = session_mgr.list()
        if not sessions:
            sender.send_message(sender_open_id, "请先创建会话：/new <名称> <工作目录>")
            return
        # Stash message and ask user to select
        _list_sessions(sender_open_id, sender, session_mgr)
        sender.send_message(sender_open_id, "请回复编号或会话名称选择会话，你的指令将在选择后自动执行。")
        state.set_waiting(raw_text)
        return

    # Active session exists → execute
    _execute_and_reply(raw_text, active, sender_open_id, sender, config, session_mgr, state)


# ---- Session selection in WAITING_SELECT mode ----

def _handle_waiting_select(raw_text, sender_open_id, sender, config, session_mgr, state):
    pending = state.pending_message

    # Allow /new in waiting mode
    if raw_text.startswith("/new ") or raw_text == "/new":
        _handle_command(raw_text, sender_open_id, sender, session_mgr, state)
        # If session was created, execute pending message
        active = session_mgr.get_active()
        if active and pending:
            state.clear_pending()
            _execute_and_reply(pending, active, sender_open_id, sender, config, session_mgr, state)
        return

    # Try to match by number
    try:
        idx = int(raw_text.strip())
        session = session_mgr.get_by_index(idx)
        if session:
            session_mgr.switch(session.name)
            sender.send_message(sender_open_id, f"✓ 切换到会话 [{session.name}]")
            state.clear_pending()
            if pending:
                _execute_and_reply(pending, session, sender_open_id, sender, config, session_mgr, state)
            return
    except ValueError:
        pass

    # Try to match by name
    for s in session_mgr.list():
        if s.name == raw_text.strip():
            session_mgr.switch(s.name)
            sender.send_message(sender_open_id, f"✓ 切换到会话 [{s.name}]")
            state.clear_pending()
            if pending:
                _execute_and_reply(pending, s, sender_open_id, sender, config, session_mgr, state)
            return

    sender.send_message(sender_open_id, "无效选择，请回复编号或会话名称")


# ---- Management command dispatch ----

def _handle_command(raw_text, sender_open_id, sender, session_mgr, state):
    parts = raw_text.split(maxsplit=2)

    if parts[0] == "/new":
        if len(parts) < 3:
            sender.send_message(sender_open_id, "用法：/new <名称> <工作目录>")
            return
        name, workdir = parts[1], parts[2]
        try:
            session_mgr.create(name, workdir)
            sender.send_message(sender_open_id, f"✓ 会话 [{name}] 已创建\n工作目录: {workdir}")
        except ValueError as e:
            sender.send_message(sender_open_id, str(e))

    elif parts[0] == "/use":
        if len(parts) < 2:
            sender.send_message(sender_open_id, "用法：/use <名称>")
            return
        try:
            session_mgr.switch(parts[1])
            sender.send_message(sender_open_id, f"✓ 切换到会话 [{parts[1]}]")
        except ValueError as e:
            sender.send_message(sender_open_id, str(e))

    elif parts[0] == "/sessions":
        _list_sessions(sender_open_id, sender, session_mgr)

    elif parts[0] == "/delete":
        if len(parts) < 2:
            sender.send_message(sender_open_id, "用法：/delete <名称>")
            return
        name = parts[1]
        try:
            was_active = session_mgr.delete(name)
            msg = f"✓ 会话 [{name}] 已删除"
            if was_active:
                msg += "\n（当前无活跃会话）"
            sender.send_message(sender_open_id, msg)
        except ValueError as e:
            sender.send_message(sender_open_id, str(e))

    elif parts[0] == "/status":
        _handle_status(sender_open_id, sender, state)

    elif parts[0] == "/cancel":
        _handle_cancel(sender_open_id, sender, state)


def _handle_status(sender_open_id, sender, state):
    if not state.is_executing:
        sender.send_message(sender_open_id, "🟢 Bot 状态：空闲")
        return

    lines = ["🔴 Bot 状态：执行中"]
    if state.exec_task_summary:
        lines.append(f"📋 当前任务：{state.exec_task_summary}")
    if state.exec_start_time:
        elapsed = int(time.time() - state.exec_start_time)
        minutes, seconds = divmod(elapsed, 60)
        lines.append(f"⏱️ 已执行：{minutes}分{seconds}秒")
    if state.queue:
        lines.append(f"📥 排队任务（{len(state.queue)}条）：")
        for i, msg in enumerate(state.queue, 1):
            display = msg[:30] + ("..." if len(msg) > 30 else "")
            lines.append(f"  {i}. {display}")

    sender.send_message(sender_open_id, "\n".join(lines))


def _handle_cancel(sender_open_id, sender, state):
    if not state.is_executing:
        sender.send_message(sender_open_id, "当前没有正在执行的任务")
        return

    if state.cancel_event:
        state.cancel_event.set()
    state.clear_queue()
    sender.send_message(sender_open_id, "已取消当前任务并清空队列")


def _list_sessions(sender_open_id, sender, session_mgr):
    sessions = session_mgr.list()
    if not sessions:
        sender.send_message(sender_open_id, "暂无会话，请使用 /new <名称> <工作目录> 创建")
        return
    lines = ["📋 会话列表：\n"]
    for i, s in enumerate(sessions, 1):
        active_mark = " ★" if s.active else ""
        sid_status = "已绑定" if s.sid else "新会话"
        lines.append(f"  {i}. {s.name} ({sid_status}){active_mark}")
        lines.append(f"     目录: {s.workdir}")
    sender.send_message(sender_open_id, "\n".join(lines))


# ---- Claude execution ----

def _execute_and_reply(raw_text, session, sender_open_id, sender, config, session_mgr, state):
    sender.send_message(sender_open_id, "已收到指令，正在调用 Claude 执行...")
    state.set_executing(raw_text)

    async def on_status(status_text: str):
        sender.send_message(sender_open_id, status_text)

    async def run():
        text, sid = await execute_claude(
            prompt=raw_text,
            cli_path=config.cli_path,
            workdir=session.workdir,
            timeout=config.timeout,
            session_id=session.sid,
            on_status=on_status,
            cancel_event=state.cancel_event,
        )

        # Update session: bind sid if first time, touch last_used
        if sid and not session.sid:
            session_mgr.update_sid(session.name, sid)
        session_mgr.touch(session.name)

        state.set_idle()
        logger.info("执行完成，结果长度=%d", len(text))
        sender.send_card(sender_open_id, text)

        # Check for queued messages
        queued = state.drain_queue()
        if queued:
            merged = _merge_queue(queued)
            _execute_and_reply(merged, session, sender_open_id, sender, config, session_mgr, state)

    loop = asyncio.get_event_loop()
    loop.create_task(run())


def _merge_queue(messages: list[str]) -> str:
    """Merge queued messages into a single prompt."""
    if len(messages) == 1:
        return messages[0]
    lines = ["用户在你执行期间发了以下消息："]
    for i, msg in enumerate(messages, 1):
        lines.append(f"[{i}] {msg}")
    lines.append("请根据最新意图执行。")
    return "\n".join(lines)
