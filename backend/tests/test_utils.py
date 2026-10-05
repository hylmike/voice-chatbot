"""Unit tests for pipeline utilities."""

import asyncio

from api.utils.merge_async_iters import merge_async_iters


async def test_merge_async_iters_empty() -> None:
    results = [item async for item in merge_async_iters()]
    assert results == []


async def test_merge_async_iters_single() -> None:
    async def stream_one():
        yield 1
        yield 2
        yield 3

    results = [item async for item in merge_async_iters(stream_one())]
    assert results == [1, 2, 3]


async def test_merge_async_iters_multiple() -> None:
    async def stream_a():
        for i in [1, 2, 3]:
            await asyncio.sleep(0.01)
            yield f"a{i}"

    async def stream_b():
        for i in [1, 2]:
            await asyncio.sleep(0.015)
            yield f"b{i}"

    results = [item async for item in merge_async_iters(stream_a(), stream_b())]
    assert len(results) == 5
    assert set(results) == {"a1", "a2", "a3", "b1", "b2"}
