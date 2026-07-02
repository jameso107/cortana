"""Tests for the memory store's pure recency-weighting helper."""
from datetime import datetime, timedelta, timezone

from cortana.memory.store import MemoryStore


def test_recency_weight_now_is_near_one():
    now = datetime.now(timezone.utc)
    w = MemoryStore._recency_weight(now.isoformat(), now, 30)
    assert 0.99 <= w <= 1.0


def test_recency_weight_one_half_life_is_about_half():
    now = datetime.now(timezone.utc)
    past = (now - timedelta(days=30)).isoformat()
    w = MemoryStore._recency_weight(past, now, 30)
    assert 0.45 <= w <= 0.55


def test_recency_weight_two_half_lives_is_about_quarter():
    now = datetime.now(timezone.utc)
    past = (now - timedelta(days=60)).isoformat()
    w = MemoryStore._recency_weight(past, now, 30)
    assert 0.20 <= w <= 0.30


def test_recency_weight_missing_timestamp_is_neutral():
    now = datetime.now(timezone.utc)
    assert MemoryStore._recency_weight(None, now, 30) == 0.5


def test_recency_weight_handles_naive_timestamp():
    # Naive (no tz) timestamps are treated as UTC rather than raising.
    now = datetime.now(timezone.utc)
    naive = now.replace(tzinfo=None).isoformat()
    w = MemoryStore._recency_weight(naive, now, 30)
    assert 0.99 <= w <= 1.0
