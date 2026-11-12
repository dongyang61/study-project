"""会话持久化：`.agents/sessions/<session-id>.jsonl`。

文件格式（每行一个 JSON 对象）：
- 第 1 行：`{"type": "meta", ...}`，含会话 ID、创建时间、工作目录、模型、消息数、
  token 估算与 usage；
- 后续行：`{"type": "message", "message": {...}}`，按原顺序保存消息。

写入使用同目录临时文件 + `os.replace`，避免半截文件。
"""

from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

SESSIONS_DIR = Path(".agents") / "sessions"
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class SessionError(RuntimeError):
    """会话读写错误。"""


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class SessionStore:
    def __init__(self, root=None) -> None:
        self.root = Path(root or Path.cwd()).resolve()
        self.directory = self.root / SESSIONS_DIR

    def new_id(self) -> str:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return f"{stamp}-{secrets.token_hex(3)}"

    def path(self, session_id: str) -> Path:
        if not isinstance(session_id, str) or not SESSION_ID_RE.fullmatch(session_id):
            raise SessionError(f"非法会话 ID：{session_id!r}")
        return self.directory / f"{session_id}.jsonl"

    def save(
        self,
        session_id: str,
        *,
        messages: list[dict],
        created_at: str,
        cwd: str,
        model: str,
        last_tokens: int = 0,
        last_usage: dict | None = None,
        state: str = "normal",
    ) -> Path:
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SessionError(f"创建会话目录失败：{exc}") from exc

        target = self.path(session_id)
        meta = {
            "type": "meta",
            "sessionId": session_id,
            "createdAt": created_at,
            "updatedAt": _now(),
            "cwd": cwd,
            "model": model,
            "messageCount": len(messages),
            "lastTokens": int(last_tokens or 0),
            "lastUsage": last_usage,
            "state": state,
        }
        lines = [json.dumps(meta, ensure_ascii=False)]
        for message in messages:
            lines.append(
                json.dumps(
                    {"type": "message", "message": message}, ensure_ascii=False
                )
            )

        temp = self.directory / f".{session_id}.{os.getpid()}.tmp"
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as fh:
                fh.write("\n".join(lines) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temp, target)
        except (OSError, TypeError, ValueError) as exc:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            raise SessionError(f"写入会话失败：{exc}") from exc
        return target

    def list(self) -> list[dict]:
        if not self.directory.is_dir():
            return []
        entries = []
        for path in self.directory.glob("*.jsonl"):
            meta = self._read_meta(path)
            if meta is not None:
                entries.append(meta)
        entries.sort(key=lambda item: item.get("updatedAt", ""), reverse=True)
        return entries

    def load(self, session_id: str) -> dict:
        target = self.path(session_id)
        if not target.is_file():
            raise SessionError(f"会话不存在：{session_id}")
        meta: dict | None = None
        messages: list[dict] = []
        try:
            with target.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(record, dict):
                        continue
                    if record.get("type") == "meta" and meta is None:
                        meta = record
                    elif record.get("type") == "message":
                        message = record.get("message")
                        if isinstance(message, dict):
                            messages.append(message)
        except OSError as exc:
            raise SessionError(f"读取会话失败：{exc}") from exc

        if meta is None:
            raise SessionError(f"会话文件缺少元信息：{target}")
        return {"meta": meta, "messages": messages, "path": target}

    @staticmethod
    def _read_meta(path: Path) -> dict | None:
        try:
            with path.open("r", encoding="utf-8") as fh:
                first = fh.readline().strip()
        except OSError:
            return None
        if not first:
            return None
        try:
            record = json.loads(first)
        except json.JSONDecodeError:
            return None
        if not isinstance(record, dict) or record.get("type") != "meta":
            return None
        record.setdefault("sessionId", path.stem)
        return record
