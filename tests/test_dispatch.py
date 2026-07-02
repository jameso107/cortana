"""Tests for the plugin dispatcher: ordering, concurrency, and fault isolation."""
import asyncio
import time

from cortana.plugins.registry import PluginRegistry


class _FakePlugin:
    def __init__(self, name, delay=0.0, raises=False):
        self.name = name
        self._delay = delay
        self._raises = raises

    async def handle(self, name, args):
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._raises:
            raise RuntimeError("boom")
        return f"result:{self.name}"


def _reg(**plugins) -> PluginRegistry:
    reg = PluginRegistry()
    reg._plugins = dict(plugins)
    return reg


def _calls(*names):
    return [{"id": str(i), "name": n, "arguments": "{}"} for i, n in enumerate(names)]


async def test_dispatch_preserves_order():
    reg = _reg(a=_FakePlugin("a"), b=_FakePlugin("b"))
    res = await reg.dispatch(_calls("a", "b"))
    assert [r["tool_call_id"] for r in res] == ["0", "1"]
    assert res[0]["content"] == "result:a"
    assert res[1]["content"] == "result:b"


async def test_dispatch_runs_calls_concurrently():
    reg = _reg(a=_FakePlugin("a", delay=0.2), b=_FakePlugin("b", delay=0.2))
    t0 = time.perf_counter()
    await reg.dispatch(_calls("a", "b"))
    elapsed = time.perf_counter() - t0
    # Concurrent → ~0.2s, not the ~0.4s a sequential loop would take.
    assert elapsed < 0.35


async def test_dispatch_isolates_a_failing_tool():
    reg = _reg(a=_FakePlugin("a", raises=True), b=_FakePlugin("b"))
    res = await reg.dispatch(_calls("a", "b"))
    assert "Error in a" in res[0]["content"]
    assert res[1]["content"] == "result:b"


async def test_dispatch_unknown_tool():
    reg = _reg(a=_FakePlugin("a"))
    res = await reg.dispatch(_calls("does_not_exist"))
    assert "Unknown tool" in res[0]["content"]
