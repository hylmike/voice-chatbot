"""Utility functions for the voice agent pipeline.

This module provides helper functions for working with async iterators
and other common operations across the voice agent system.
"""

import asyncio
from collections.abc import AsyncIterable, AsyncIterator
from typing import Any


async def merge_async_iters[T](*aiters: AsyncIterable[T]) -> AsyncIterator[T]:
    """Merge multiple async iterators into a single async iterator.

    This function takes any number of async iterators and yields items from all
    of them as they become available, in the order they are produced. This is
    useful for combining multiple event streams (e.g., STT chunks, agent chunks,
    TTS chunks) into a single unified stream for processing.

    The function uses a queue-based approach with producer tasks for each input
    iterator. All iterators are consumed concurrently, and items are yielded as
    soon as any iterator produces them. The merged iterator completes only after
    all input iterators have been exhausted.

    Args:
        *aiters: Variable number of async iterators or iterables to merge.

    Yields:
        Items from any of the input iterators, in the order they become
        available.

    Example:
        >>> async def iter1():
        ...     yield 1
        ...     yield 2
        >>> async def iter2():
        ...     yield "a"
        ...     yield "b"
        >>> async def main():
        ...     async for item in merge_async_iters(iter1(), iter2()):
        ...         print(item)  # Could print: 1, 'a', 2, 'b' (order may vary)
        >>> asyncio.run(main())
    """
    if not aiters:
        return

    queue: asyncio.Queue[Any] = asyncio.Queue()
    sentinel = object()

    async def producer(it: AsyncIterable[T]) -> None:
        async for item in it:
            await queue.put(item)
        await queue.put(sentinel)

    try:
        async with asyncio.TaskGroup() as tg:
            for stream in aiters:
                tg.create_task(producer(stream))

            finished = 0
            while finished < len(aiters):
                queue_item = await queue.get()
                if queue_item is sentinel:
                    finished += 1
                else:
                    yield queue_item
    except* GeneratorExit:
        pass
