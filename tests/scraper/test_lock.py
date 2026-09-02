import os
from coolpc.scraper.lock import ScraperLock

def test_acquire_and_release(tmp_path):
    lock_path = str(tmp_path / "scraper.lock")
    lock = ScraperLock(lock_path)
    assert lock.acquire() is True
    assert os.path.exists(lock_path)
    lock.release()
    assert not os.path.exists(lock_path)

def test_second_acquire_fails_while_held(tmp_path):
    lock_path = str(tmp_path / "scraper.lock")
    lock1 = ScraperLock(lock_path)
    lock2 = ScraperLock(lock_path)
    assert lock1.acquire() is True
    assert lock2.acquire() is False
    lock1.release()
    assert lock2.acquire() is True
    lock2.release()

def test_stale_lock_is_reclaimed(tmp_path):
    lock_path = str(tmp_path / "scraper.lock")
    with open(lock_path, "w") as f:
        f.write("999999999")  # 不存在的 PID
    lock = ScraperLock(lock_path)
    assert lock.acquire() is True
    lock.release()

def test_context_manager_raises_when_locked(tmp_path):
    lock_path = str(tmp_path / "scraper.lock")
    holder = ScraperLock(lock_path)
    holder.acquire()
    try:
        with __import__("pytest").raises(RuntimeError):
            with ScraperLock(lock_path):
                pass
    finally:
        holder.release()
