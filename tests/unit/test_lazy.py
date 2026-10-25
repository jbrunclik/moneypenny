"""Lazy (src/utils/lazy.py): the shared helper for process-wide singletons."""

import threading
import time

from src.utils.lazy import Lazy


def test_builds_once_and_returns_the_same_value() -> None:
    lazy = Lazy(object)
    assert lazy.peek() is None
    first = lazy.get()
    assert lazy.get() is first
    assert lazy.peek() is first


def test_racing_threads_build_a_single_value() -> None:
    builds = 0

    def slow_factory() -> object:
        nonlocal builds
        builds += 1
        time.sleep(0.02)  # widen the race window
        return object()

    lazy = Lazy(slow_factory)
    barrier = threading.Barrier(20)
    results: list[object] = []

    def worker() -> None:
        barrier.wait()
        results.append(lazy.get())

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert builds == 1
    assert all(r is results[0] for r in results)


def test_reset_builds_a_new_value() -> None:
    lazy = Lazy(object)
    first = lazy.get()
    lazy.reset()
    assert lazy.get() is not first


def test_override_serves_a_value_and_restores_the_previous_one() -> None:
    lazy = Lazy(object)
    original = lazy.get()
    stand_in = object()
    with lazy.override(stand_in):
        assert lazy.get() is stand_in
    assert lazy.get() is original


def test_override_of_an_unbuilt_value_leaves_it_unbuilt() -> None:
    lazy = Lazy(object)
    with lazy.override(object()):
        pass
    assert lazy.peek() is None
