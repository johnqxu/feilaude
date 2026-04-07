import logging

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
    session_mgr = SessionManager()
    bot_state = BotState()
    logger.info("正在初始化飞书客户端...")
    sender = FeishuSender(config.app_id, config.app_secret)

    def on_message(event):
        handle_message(event, config, sender, session_mgr, bot_state)

    event_handler = EventDispatcherHandler.builder("", "") \
        .register_p2_im_message_receive_v1(on_message) \
        .build()

    ws_client = WSClient(
        config.app_id,
        config.app_secret,
        event_handler=event_handler,
    )

    logger.info("=" * 50)
    logger.info("飞书 Claude Bot 已启动，等待消息...")
    logger.info("工作目录: %s", config.workdir)
    logger.info("Claude CLI: %s", config.cli_path)
    logger.info("超时设置: %d秒", config.timeout)
    logger.info("会话数量: %d", len(session_mgr.list()))
    logger.info("=" * 50)
    ws_client.start()


if __name__ == "__main__":
    main()
