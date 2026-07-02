"""Unit tests for the orchestrator's pure helpers (no model/backend needed)."""
from cortana.core.orchestrator import Orchestrator, _est_tokens


def _bare() -> Orchestrator:
    """An Orchestrator without the heavy __init__ (no inference/memory/plugins)."""
    o = Orchestrator.__new__(Orchestrator)
    o._reasoning = "auto"
    o._memory_token_budget = 2048
    return o


def test_est_tokens():
    assert _est_tokens("") == 0
    assert _est_tokens("abcd") == 1
    assert _est_tokens("a" * 400) == 100


def test_strip_think_removes_closed_block():
    visible, in_think = Orchestrator._strip_think("<think>secret reasoning</think>Hello there")
    assert visible == "Hello there"
    assert in_think is False


def test_strip_think_detects_open_block():
    visible, in_think = Orchestrator._strip_think("Answer so far<think>still thinking")
    assert visible == "Answer so far"
    assert in_think is True


def test_emittable_holds_back_partial_tag():
    # A trailing partial "<think>" must not flash in the UI.
    assert Orchestrator._emittable("hello <thi") == "hello "
    assert Orchestrator._emittable("hello <") == "hello "
    assert Orchestrator._emittable("hello world") == "hello world"


def test_reasoning_prefix_auto_simple_vs_complex():
    o = _bare()
    assert o._reasoning_prefix("hi there") == "/no_think"
    assert o._reasoning_prefix("please debug this stack trace") == "/think"  # 'debug' hint


def test_reasoning_prefix_forced_modes():
    o = _bare()
    o._reasoning = "always"
    assert o._reasoning_prefix("hi") == "/think"
    o._reasoning = "never"
    assert o._reasoning_prefix("please analyze everything in detail") == "/no_think"


def test_reasoning_prefix_long_input_triggers_think():
    o = _bare()
    long_text = " ".join(["word"] * 30)  # >24 words
    assert o._reasoning_prefix(long_text) == "/think"


def test_drop_oldest_turn_removes_whole_turn():
    history = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "A"},
        {"role": "user", "content": "b"},
        {"role": "assistant", "content": "B"},
    ]
    assert Orchestrator._drop_oldest_turn(history) is True
    assert history[0]["content"] == "b"
    assert len(history) == 2


def test_drop_oldest_turn_keeps_tool_messages_with_their_assistant():
    # A tool message must never be orphaned from its assistant tool_calls.
    history = [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "t1"}]},
        {"role": "tool", "tool_call_id": "t1", "content": "result"},
        {"role": "assistant", "content": "answer1"},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "answer2"},
    ]
    Orchestrator._drop_oldest_turn(history)
    # The entire first turn (incl. its tool exchange) is gone; second turn remains intact.
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[0]["content"] == "q2"


def test_drop_oldest_turn_single_turn_clears():
    history = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "A"}]
    assert Orchestrator._drop_oldest_turn(history) is True
    assert history == []


def test_cap_tokens_truncates_over_budget():
    o = _bare()
    text = "x" * 1000  # ~250 tokens
    capped = o._cap_tokens(text, budget=10)
    assert len(capped) < len(text)
    assert "truncated" in capped


def test_cap_tokens_leaves_small_text_untouched():
    o = _bare()
    assert o._cap_tokens("short", budget=100) == "short"
