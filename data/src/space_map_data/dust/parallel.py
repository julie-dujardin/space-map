"""Forked workers for the build steps."""

import multiprocessing
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ProcessPoolExecutor


def forked_stream[J, R](
    task: Callable[[J], R], jobs: Iterable[J], workers: int
) -> Iterator[R]:
    """`task` over `jobs` in forked workers, results as they come, in job order.

    A worker inherits the module globals of its parent, so a volume is not pickled
    with each job. A killed worker raises `BrokenProcessPool` and does not hang.
    """
    context = multiprocessing.get_context("fork")
    pool = ProcessPoolExecutor(workers, mp_context=context)
    try:
        yield from pool.map(task, jobs)
    finally:
        pool.shutdown(cancel_futures=True)


def forked_map[J, R](
    task: Callable[[J], R], jobs: Iterable[J], workers: int
) -> list[R]:
    """`forked_stream`, collected."""
    return list(forked_stream(task, jobs, workers))
