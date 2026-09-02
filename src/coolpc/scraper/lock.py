from __future__ import annotations
import os


class ScraperLock:
    def __init__(self, lock_path: str = "data/scraper.lock"):
        self.lock_path = lock_path
        self._acquired = False

    def acquire(self) -> bool:
        parent = os.path.dirname(self.lock_path) or "."
        os.makedirs(parent, exist_ok=True)
        try:
            fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if self._is_stale():
                try:
                    os.remove(self.lock_path)
                except FileNotFoundError:
                    pass
                return self.acquire()
            return False
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
        self._acquired = True
        return True

    def _is_stale(self) -> bool:
        try:
            with open(self.lock_path) as f:
                pid = int(f.read().strip())
        except (ValueError, FileNotFoundError):
            return True
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        return False

    def release(self) -> None:
        if self._acquired and os.path.exists(self.lock_path):
            os.remove(self.lock_path)
        self._acquired = False

    def __enter__(self) -> "ScraperLock":
        if not self.acquire():
            raise RuntimeError("已有抓取程序正在執行中")
        return self

    def __exit__(self, *exc) -> None:
        self.release()
