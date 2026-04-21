import logging
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


class Config:
    def __init__(self):
        base_dir = Path(__file__).parent

        # Load .env
        env_path = base_dir / ".env"
        load_dotenv(env_path)
        self.app_id = os.getenv("FEISHU_APP_ID")
        self.app_secret = os.getenv("FEISHU_APP_SECRET")
        missing = []
        if not self.app_id:
            missing.append("FEISHU_APP_ID")
        if not self.app_secret:
            missing.append("FEISHU_APP_SECRET")
        if missing:
            logger.error(".env 文件缺少以下变量：%s", ", ".join(missing))
            sys.exit(1)
        logger.info("飞书凭证加载成功 (APP_ID=%s...%s)", self.app_id[:6], self.app_id[-4:])

        # Load config.yaml
        config_path = base_dir / "config.yaml"
        if not config_path.exists():
            logger.error("配置文件 config.yaml 不存在")
            sys.exit(1)

        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        claude_cfg = data.get("claude", {})
        self.cli_path = claude_cfg.get("cli_path", "claude")
        self.workdir = claude_cfg.get("workdir", str(base_dir))
        self.timeout = claude_cfg.get("timeout", 600)
        self.sessions_file = base_dir / claude_cfg.get("sessions_file", "sessions.yaml")
        logger.info("配置加载完成：cli_path=%s, workdir=%s, timeout=%ds", self.cli_path, self.workdir, self.timeout)
