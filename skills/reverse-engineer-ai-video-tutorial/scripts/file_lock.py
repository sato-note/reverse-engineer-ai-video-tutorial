"""Small cross-platform advisory lock held for the lifetime of a process."""

from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path


class HeldFileLock:
    def __init__(self, path: Path, handle) -> None:
        self.path = path
        self._handle = handle
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._released = True


def acquire(path: Path, description: str, *, attempts: int = 5, delay: float = 0.05) -> HeldFileLock:
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(attempts):
        handle = None
        try:
            handle = path.open("a+b")
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            handle.seek(0)
            handle.truncate()
            handle.write(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "host": socket.gethostname(),
                        "created_at": time.time(),
                        "description": description,
                    }
                ).encode("utf-8")
            )
            handle.flush()
            return HeldFileLock(path, handle)
        except OSError as exc:
            if handle is not None:
                try:
                    handle.close()
                except OSError:
                    pass
            if attempt + 1 == attempts:
                raise RuntimeError(f"{description} already in progress: {path}") from exc
            time.sleep(delay)
    raise RuntimeError(f"{description} already in progress: {path}")
