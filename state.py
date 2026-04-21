import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class StatusSnapshot:
    """Immutable snapshot of execution state, captured under lock."""
    __slots__ = ("is_executing", "task_summary", "start_time", "queue")

    def __init__(self, is_executing: bool, task_summary: str | None,
                 start_time: float | None, queue: list[str]):
        self.is_executing = is_executing
        self.task_summary = task_summary
        self.start_time = start_time
        self.queue = queue


class BotState:
    def __init__(self):
        self._lock = threading.Lock()
        self.mode: str = "normal"
        self.pending_message: str | None = None
        # Execution state
        self.exec_status: str = "idle"
        self.exec_task_summary: str | None = None
        self.exec_start_time: float | None = None
        self.queue: list[str] = []
        self._kill_callback: Optional[Callable] = None

    @property
    def is_waiting_select(self) -> bool:
        with self._lock:
            return self.mode == "waiting_select"

    @property
    def is_executing(self) -> bool:
        with self._lock:
            return self.exec_status == "executing"

    def get_status_snapshot(self) -> StatusSnapshot:
        """Atomically capture all execution state under a single lock."""
        with self._lock:
            return StatusSnapshot(
                is_executing=self.exec_status == "executing",
                task_summary=self.exec_task_summary,
                start_time=self.exec_start_time,
                queue=self.queue[:],
            )

    def set_waiting(self, message: str):
        with self._lock:
            self.pending_message = message
            self.mode = "waiting_select"
        logger.info("进入 WAITING_SELECT 模式，暂存消息（长度=%d）", len(message))

    def clear_pending(self):
        with self._lock:
            self.pending_message = None
            self.mode = "normal"
        logger.info("切回 NORMAL 模式")

    def get_pending(self) -> str | None:
        """Thread-safe read of pending_message."""
        with self._lock:
            return self.pending_message

    def try_start_executing(self, summary: str) -> bool:
        """Atomically transition from idle to executing. Returns False if already executing."""
        with self._lock:
            if self.exec_status == "executing":
                return False
            self.exec_status = "executing"
            self.exec_task_summary = summary[:30]
            self.exec_start_time = time.time()
        logger.info("开始执行：%s", summary[:30])
        return True

    def set_idle(self):
        with self._lock:
            self.exec_status = "idle"
            self.exec_task_summary = None
            self.exec_start_time = None
            self._kill_callback = None
        logger.info("执行结束，回到空闲状态")

    def register_kill(self, callback: Callable):
        with self._lock:
            self._kill_callback = callback

    def kill_process(self):
        with self._lock:
            cb = self._kill_callback
            self._kill_callback = None
        if cb:
            logger.info("调用 kill 回调终止进程")
            cb()

    def try_cancel(self) -> bool:
        """Atomically check if executing, kill process, clear queue, and set idle.
        Returns True if a task was cancelled, False if nothing was running."""
        with self._lock:
            if self.exec_status != "executing":
                return False
            cb = self._kill_callback
            self._kill_callback = None
            self.exec_status = "idle"
            self.exec_task_summary = None
            self.exec_start_time = None
            self.queue.clear()
        if cb:
            logger.info("调用 kill 回调终止进程")
            cb()
        return True

    def enqueue(self, text: str) -> int:
        with self._lock:
            self.queue.append(text)
            pos = len(self.queue)
        logger.info("消息入队（第 %d 位）：%.50s", pos, text)
        return pos

    def drain_queue(self) -> list[str]:
        with self._lock:
            messages = self.queue[:]
            self.queue.clear()
        if messages:
            logger.info("取出 %d 条排队消息", len(messages))
        return messages

    def clear_queue(self):
        with self._lock:
            count = len(self.queue)
            self.queue.clear()
        logger.info("清空队列（%d 条消息）", count)
