import asyncio
import json
import logging
import os
import subprocess
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


async def execute_claude(
    prompt: str,
    cli_path: str,
    workdir: str,
    timeout: int,
    session_id: Optional[str] = None,
    on_status: Optional[Callable[[str], Awaitable[None]]] = None,
    cancel_event: Optional[asyncio.Event] = None,
) -> tuple[str, Optional[str]]:
    """Execute Claude CLI with stream-json output and return (result_text, session_id)."""
    if not os.path.isfile(cli_path):
        logger.error("Claude CLI 路径不存在：%s", cli_path)
        return (f"Claude CLI 路径不存在：{cli_path}", None)

    cmd = [cli_path, "-p", "--output-format", "stream-json", "--verbose", "--dangerously-skip-permissions"]
    if session_id:
        cmd += ["--resume", session_id]
    cmd.append(prompt)

    logger.info("执行命令：%s [prompt]", " ".join(cmd[:7]))
    logger.info("工作目录：%s", workdir)

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=workdir,
        )
        logger.info("子进程已启动，PID=%d", process.pid)
    except OSError as e:
        logger.error("启动子进程失败：%s", e)
        return (f"启动 Claude CLI 失败：{e}", None)

    result_text = ""
    extracted_sid: Optional[str] = None
    last_read_file: Optional[str] = None

    async def _read_stream():
        nonlocal result_text, extracted_sid, last_read_file

        while True:
            if cancel_event and cancel_event.is_set():
                logger.info("检测到取消信号，终止子进程 PID=%d", process.pid)
                process.kill()
                result_text = "任务已取消"
                return

            line_bytes = await process.stdout.readline()
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("JSON 解析失败，跳过该行：%.200s", line)
                continue

            event_type = event.get("type")

            if event_type == "system":
                subtype = event.get("subtype")
                if subtype == "init":
                    extracted_sid = event.get("session_id")
                    logger.info("获取 session_id=%s", extracted_sid)

            elif event_type == "assistant":
                message = event.get("message", {})
                for content_block in message.get("content", []):
                    if content_block.get("type") == "tool_use":
                        await _handle_tool_use(content_block, on_status, last_read_file)
                        # Update last_read_file tracking
                        tool_name = content_block.get("name", "")
                        tool_input = content_block.get("input", {})
                        if tool_name == "Read":
                            last_read_file = _basename(tool_input.get("file_path", ""))

            elif event_type == "result":
                result_text = event.get("result", "")
                if not extracted_sid:
                    extracted_sid = event.get("session_id")
                logger.info("获取最终结果，长度=%d", len(result_text))

            # Unknown event types are silently ignored

    try:
        await asyncio.wait_for(_read_stream(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("子进程超时（%d秒），正在终止 PID=%d", timeout, process.pid)
        process.kill()
        return ("指令执行超时，请简化指令后重试", None)

    await process.wait()
    logger.info("子进程结束，returncode=%d", process.returncode)

    if process.returncode != 0:
        stderr_bytes = await process.stderr.read()
        stderr_str = stderr_bytes.decode("utf-8", errors="replace").strip()
        logger.error("Claude CLI 执行失败：returncode=%d, stderr=%s", process.returncode, stderr_str[:500])
        return (f"执行出错：{stderr_str or result_text}", None)

    logger.info("执行成功，结果长度=%d, session_id=%s", len(result_text), extracted_sid or "N/A")
    return (result_text, extracted_sid)


def _basename(file_path: str) -> str:
    """Extract filename from a file path."""
    return os.path.basename(file_path) if file_path else ""


async def _handle_tool_use(
    content_block: dict,
    on_status: Optional[Callable[[str], Awaitable[None]]],
    last_read_file: Optional[str],
):
    """Parse tool_use event and invoke on_status callback with deduplication."""
    if not on_status:
        return

    tool_name = content_block.get("name", "")
    tool_input = content_block.get("input", {})

    status_text = None

    if tool_name == "Read":
        file_path = tool_input.get("file_path", "")
        filename = _basename(file_path)
        # Dedup: skip if same file as previous Read
        if filename and filename != last_read_file:
            status_text = f"📖 读取 {filename}"

    elif tool_name in ("Edit", "Write"):
        file_path = tool_input.get("file_path", "")
        filename = _basename(file_path)
        if filename:
            status_text = f"✏️ 编辑 {filename}"

    elif tool_name == "Bash":
        command = tool_input.get("command", "")
        if command:
            display_cmd = command[:30]
            status_text = f"▶️ 运行 {display_cmd}"

    if status_text:
        try:
            await on_status(status_text)
        except Exception:
            logger.warning("on_status 回调执行失败", exc_info=True)
