"""Tests for ConnectionPool dead-thread reaping."""

import threading
from pathlib import Path

from src.utils.connection_pool import ConnectionPool


class TestConnectionPoolReaping:
    """Verify that connections from dead threads are cleaned up."""

    def test_reap_dead_thread_connection(self, tmp_path: Path) -> None:
        """Connections from exited threads should be reaped when a new thread joins."""
        db_path = tmp_path / "test.db"
        pool = ConnectionPool(db_path)

        # Acquire a connection in a short-lived thread
        thread_done = threading.Event()

        def worker() -> None:
            with pool.get_connection() as conn:
                conn.execute("SELECT 1")
            thread_done.set()

        t = threading.Thread(target=worker)
        t.start()
        t.join()
        thread_done.wait()

        # The dead thread's connection is still in the pool
        assert pool.connection_count() == 1

        # Now acquire a connection from another new thread, which triggers reaping
        thread2_done = threading.Event()

        def worker2() -> None:
            with pool.get_connection() as conn:
                conn.execute("SELECT 1")
            thread2_done.set()

        t2 = threading.Thread(target=worker2)
        t2.start()
        t2.join()
        thread2_done.wait()

        # After reaping, only the new thread's connection remains (also dead now)
        # but the old one was cleaned up during the new connection creation.
        # Both threads are dead, so a manual reap should bring it to 0.
        pool._lock.acquire()
        pool._reap_dead_threads()
        pool._lock.release()
        assert pool.connection_count() == 0

        pool.close_all()

    def test_close_thread_connection_removes_entry(self, tmp_path: Path) -> None:
        """close_thread_connection() should remove the entry for the calling thread."""
        db_path = tmp_path / "test.db"
        pool = ConnectionPool(db_path)

        result = threading.Event()

        def worker() -> None:
            with pool.get_connection() as conn:
                conn.execute("SELECT 1")
            pool.close_thread_connection()
            result.set()

        t = threading.Thread(target=worker)
        t.start()
        t.join()
        result.wait()

        assert pool.connection_count() == 0
        pool.close_all()

    def test_long_lived_thread_not_reaped(self, tmp_path: Path) -> None:
        """Connections from still-alive threads should NOT be reaped."""
        db_path = tmp_path / "test.db"
        pool = ConnectionPool(db_path)

        ready = threading.Event()
        done = threading.Event()

        def long_worker() -> None:
            with pool.get_connection() as conn:
                conn.execute("SELECT 1")
            ready.set()
            done.wait()  # Keep thread alive

        t = threading.Thread(target=long_worker)
        t.start()
        ready.wait()

        assert pool.connection_count() == 1

        # Trigger reaping from another thread
        trigger_done = threading.Event()

        def trigger() -> None:
            with pool.get_connection() as conn:
                conn.execute("SELECT 1")
            trigger_done.set()

        t2 = threading.Thread(target=trigger)
        t2.start()
        t2.join()
        trigger_done.wait()

        # Long worker thread is still alive, so its connection should NOT be reaped.
        # We should have 2 connections (long worker + trigger, though trigger is dead).
        # After manual reap, the dead trigger thread's connection is cleaned but
        # the long worker's remains.
        pool._lock.acquire()
        pool._reap_dead_threads()
        pool._lock.release()
        assert pool.connection_count() == 1

        done.set()
        t.join()
        pool.close_all()
