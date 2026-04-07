import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

SESSIONS_FILE = Path(__file__).parent / "sessions.yaml"


@dataclass
class Session:
    name: str
    workdir: str
    sid: Optional[str] = None
    last_used: Optional[str] = None
    active: bool = False

    def touch(self):
        self.last_used = datetime.now().isoformat(timespec="seconds")


class SessionManager:
    def __init__(self, path: Path = SESSIONS_FILE):
        self._path = path
        self._sessions: list[Session] = []
        self.load()

    # --- persistence ---

    def load(self):
        if not self._path.exists():
            self._sessions = []
            return
        with open(self._path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        raw = data.get("sessions", [])
        self._sessions = [
            Session(
                name=s["name"],
                workdir=s["workdir"],
                sid=s.get("sid"),
                last_used=s.get("last_used"),
                active=s.get("active", False),
            )
            for s in raw
        ]
        logger.info("已加载 %d 个会话", len(self._sessions))

    def save(self):
        data = {
            "sessions": [
                {
                    "name": s.name,
                    "workdir": s.workdir,
                    "sid": s.sid,
                    "last_used": s.last_used,
                    "active": s.active,
                }
                for s in self._sessions
            ]
        }
        with open(self._path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
        logger.debug("sessions.yaml 已写入")

    # --- CRUD ---

    def create(self, name: str, workdir: str) -> Session:
        if self._find(name):
            raise ValueError(f"会话 [{name}] 已存在，请使用其他名称")
        # deactivate all
        for s in self._sessions:
            s.active = False
        session = Session(name=name, workdir=workdir, active=True)
        session.touch()
        self._sessions.append(session)
        self.save()
        logger.info("创建会话 [%s] workdir=%s", name, workdir)
        return session

    def switch(self, name: str) -> Session:
        s = self._find(name)
        if not s:
            raise ValueError(f"会话 [{name}] 不存在，/sessions 查看所有会话")
        for s2 in self._sessions:
            s2.active = False
        s.active = True
        s.touch()
        self.save()
        logger.info("切换到会话 [%s]", name)
        return s

    def list(self) -> list[Session]:
        return list(self._sessions)

    def delete(self, name: str):
        s = self._find(name)
        if not s:
            raise ValueError(f"会话 [{name}] 不存在")
        was_active = s.active
        self._sessions.remove(s)
        self.save()
        logger.info("删除会话 [%s] was_active=%s", name, was_active)
        return was_active

    def get_active(self) -> Optional[Session]:
        for s in self._sessions:
            if s.active:
                return s
        return None

    def update_sid(self, name: str, sid: str):
        s = self._find(name)
        if not s:
            return
        s.sid = sid
        self.save()
        logger.info("绑定 session_id 到会话 [%s]: %s", name, sid[:8] + "...")

    def touch(self, name: str):
        s = self._find(name)
        if s:
            s.touch()
            self.save()

    def get_by_index(self, index: int) -> Optional[Session]:
        """1-based index for user-facing selection."""
        if 1 <= index <= len(self._sessions):
            return self._sessions[index - 1]
        return None

    # --- internal ---

    def _find(self, name: str) -> Optional[Session]:
        for s in self._sessions:
            if s.name == name:
                return s
        return None
