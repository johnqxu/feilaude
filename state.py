import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class BotState:
    def __init__(self):
        self.mode: str = "normal"
        self.pending_message: str | None = None
        # Execution state
        self.exec_status: str = "idle"
        self.exec_task_summary: str | None = None
        self.exec_start_time: float | None = None
        self.queue: list[str] = []
        self.cancel_event: asyncio.Event | None = None

    @property
    def is_waiting_select(self) -> bool:
        return self.mode == "waiting_select"

    @property
    def is_executing(self) -> bool:
        return self.exec_status == "executing"

    def set_waiting(self, message: str):
        self.pending_message = message
        self.mode = "waiting_select"
        logger.info("进入 WAITING_SELECT 模式，暂存消息（长度=%d）", len(message))

    def clear_pending(self):
        self.pending_message = None
        self.mode = "normal"
        logger.info("切回 NORMAL 模式")

    def set_executing(self, summary: str):
        self.exec_status = "executing"
        self.exec_task_summary = summary[:30]
        self.exec_start_time = time.time()
        self.cancel_event = asyncio.Event()
        logger.info("开始执行：%s", self.exec_task_summary)

    def set_idle(self):
        self.exec_status = "idle"
        self.exec_task_summary = None
        self.exec_start_time = None
        self.cancel_event = None
        logger.info("执行结束，回到空闲状态")

    def enqueue(self, text: str) -> int:
        self.queue.append(text)
        pos = len(self.queue)
        logger.info("消息入队（第 %d 位）：%.50s", pos, text)
        return pos

    def drain_queue(self) -> list[str]:
        messages = self.queue[:]
        self.queue.clear()
        if messages:
            logger.info("取出 %d 条排队消息", len(messages))
        return messages

    def clear_queue(self):
        count = len(self.queue)
        self.queue.clear()
        logger.info("清空队列（%d 条消息）", count)
