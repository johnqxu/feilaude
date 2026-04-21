import asyncio
import logging
import signal
import threading

from lark_oapi.ws import Client as WSClient
from lark_oapi.event.dispatcher_handler import EventDispatcherHandler

from config import Config
from feishu_sender import FeishuSender
from router import handle_message
from session_manager import SessionManager
from state import BotState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def main():
    logger = logging.getLogger(__name__)

    logger.info("正在加载配置...")
    config = Config()
    logger.info("正在初始化会话管理器...")
    session_mgr = SessionManager(config.sessions_file)
    bot_state = BotState()
    logger.info("正在初始化飞书客户端...")
    sender = FeishuSender(config.app_id, config.app_secret)

    # Create a dedicated event loop for async tasks (Claude execution, async send)
    loop = asyncio.new_event_loop()

    def _run_loop():
        asyncio.set_event_loop(loop)
        loop.run_forever()

    loop_thread = threading.Thread(target=_run_loop, daemon=True)
    loop_thread.start()
    logger.info("异步事件循环已启动")

    def on_message(event):
        handle_message(event, config, sender, session_mgr, bot_state, loop)

    event_handler = EventDispatcherHandler.builder("", "") \
        .register_p2_im_message_receive_v1(on_message) \
        .build()

    ws_client = WSClient(
        config.app_id,
        config.app_secret,
        event_handler=event_handler,
    )

    # Graceful shutdown: kill subprocess and exit on SIGINT/SIGTERM
    shutdown_event = threading.Event()

    def _signal_handler(signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info("收到信号 %s，正在关闭...", sig_name)
        bot_state.kill_process()
        shutdown_event.set()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    logger.info("=" * 50)
    logger.info("飞书 Claude Bot 已启动，等待消息...")
    logger.info("工作目录: %s", config.workdir)
    logger.info("Claude CLI: %s", config.cli_path)
    logger.info("超时设置: %d秒", config.timeout)
    logger.info("会话数量: %d", len(session_mgr.list()))
    logger.info("=" * 50)

    # Run ws_client.start() in a thread so main thread can handle signals
    ws_thread = threading.Thread(target=ws_client.start, daemon=True)
    ws_thread.start()

    # Block until shutdown signal (periodic wakeup needed on Windows
    # so the main thread can process Ctrl+C / SIGINT)
    while not shutdown_event.is_set():
        shutdown_event.wait(timeout=1)
    loop.call_soon_threadsafe(loop.stop)
    logger.info("飞书 Claude Bot 已关闭")


if __name__ == "__main__":
    main()
