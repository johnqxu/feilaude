from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class SidEntry:
    sid: str
    last_used: Optional[str] = None

    def touch(self):
        self.last_used = datetime.now().isoformat(timespec="seconds")


@dataclass
class Session:
    name: str
    workdir: str
    active: bool = False
    active_sid: Optional[str] = None
    sids: list[SidEntry] = field(default_factory=list)
    last_used: Optional[str] = None

    def touch(self):
        self.last_used = datetime.now().isoformat(timespec="seconds")


class SessionManager:
    def __init__(self, path: Path = Path("sessions.yaml")):
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
        self._sessions = []
        for s in raw:
            # Migrate legacy format: single sid → sids list + active_sid
            if "sids" in s and isinstance(s.get("sids"), list):
                sids = [
                    SidEntry(sid=e["sid"], last_used=e.get("last_used"))
                    for e in s["sids"]
                ]
                active_sid = s.get("active_sid")
            else:
                # Legacy format: single sid field
                legacy_sid = s.get("sid")
                if legacy_sid:
                    sids = [SidEntry(sid=legacy_sid, last_used=s.get("last_used"))]
                    active_sid = legacy_sid
                else:
                    sids = []
                    active_sid = None
            self._sessions.append(Session(
                name=s["name"],
                workdir=s["workdir"],
                active=s.get("active", False),
                active_sid=active_sid,
                sids=sids,
                last_used=s.get("last_used"),
            ))
        logger.info("已加载 %d 个会话", len(self._sessions))

    def save(self):
        data = {
            "sessions": [
                {
                    "name": s.name,
                    "workdir": s.workdir,
                    "active": s.active,
                    "active_sid": s.active_sid,
                    "sids": [
                        {"sid": e.sid, "last_used": e.last_used}
                        for e in s.sids
                    ],
                    "last_used": s.last_used,
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
            raise ValueError(f"会话 [{name}] 不存在，/workspaces 查看所有工作区")
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
        # Update existing or append new
        existing = self._find_sid_entry(s, sid)
        if existing:
            existing.touch()
        else:
            entry = SidEntry(sid=sid)
            entry.touch()
            s.sids.append(entry)
        s.active_sid = sid
        self.save()
        logger.info("更新 session_id 到会话 [%s]: %s", name, sid[:8] + "...")

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

    # --- sid management ---

    def attach(self, name: str, uuid: str) -> tuple[bool, str]:
        """Attach to a specific conversation by uuid. Returns (success, message)."""
        s = self._find(name)
        if not s:
            return False, f"会话 [{name}] 不存在"
        entry = self._find_sid_entry(s, uuid)
        if not entry:
            # Fallback: unknown sid — optimistically add and attempt connection
            entry = SidEntry(sid=uuid)
            entry.touch()
            s.sids.append(entry)
            s.active_sid = uuid
            self.save()
            logger.info("attach 未知 sid 到 [%s]: %s (fallback)", name, uuid[:8] + "...")
            return True, f"⚠ 对话 {uuid[:8]}... 不在本地记录中，已尝试连接"
        s.active_sid = uuid
        entry.touch()
        self.save()
        logger.info("切换对话到 [%s]: %s", name, uuid[:8] + "...")
        return True, f"✓ 切换到对话 {uuid[:8]}..."

    def continue_session(self, name: str) -> tuple[bool, str]:
        """Switch to the most recently used conversation. Returns (success, message)."""
        s = self._find(name)
        if not s:
            return False, f"会话 [{name}] 不存在"
        if not s.sids:
            return False, "当前工作区暂无对话历史"
        # Find the sid with the latest last_used
        latest = max(s.sids, key=lambda e: e.last_used or "")
        if s.active_sid == latest.sid:
            return False, "当前已是最近对话"
        s.active_sid = latest.sid
        latest.touch()
        self.save()
        logger.info("继续最近对话 [%s]: %s", name, latest.sid[:8] + "...")
        return True, f"✓ 切换到最近对话 {latest.sid[:8]}..."

    def list_sids(self, name: str) -> list[SidEntry]:
        """Return the sid list for a session."""
        s = self._find(name)
        if not s:
            return []
        return list(s.sids)

    # --- internal ---

    def _find(self, name: str) -> Optional[Session]:
        for s in self._sessions:
            if s.name == name:
                return s
        return None

    def _find_sid_entry(self, session: Session, sid: str) -> Optional[SidEntry]:
        for e in session.sids:
            if e.sid == sid:
                return e
        return None
