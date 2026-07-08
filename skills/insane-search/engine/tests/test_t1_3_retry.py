#!/usr/bin/env python3
"""Tier 1-3 regression tests — transient-status retry with exponential backoff.

Deterministic, network-free. Locks in:
  * 429 → 429 → 200 sequence recovers (3 calls, final 200)
  * 503 → 503 → 200 recovers similarly
  * 404 is NOT retried (terminal status, no backoff wasted)
  * 200 is returned immediately (no retry attempt)
  * size cap truncates oversized bodies and tags _truncated_download

Run:  python3 engine/tests/test_t1_3_retry.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)

import engine.transport as t  # noqa: E402
from engine.transport import (  # noqa: E402
    MAX_DOWNLOAD_BYTES_DEFAULT,
    _get_with_size_cap,
    _retry_transient,
)

# Neutralise real sleeping so the test is fast.
t.time.sleep = lambda s: None


class _FakeResp:
    def __init__(self, content=b"", status=200, headers=None):
        self.content = content
        self.text = content.decode("utf-8", "replace") if isinstance(content, (bytes, bytearray)) else content
        self.status_code = status
        self.headers = headers or {}


def t_429_then_200_recovers() -> None:
    seq = iter([429, 429, 200])
    calls = {"n": 0}

    def fake_get(url):
        calls["n"] += 1
        return _FakeResp(b"ok", status=next(seq))

    r = _retry_transient(fake_get, "https://x.test/", max_attempts=2)
    assert calls["n"] == 3, f"expected 3 calls, got {calls['n']}"
    assert r.status_code == 200
    print(f"  ✓ 429→429→200 recovered in {calls['n']} calls")


def t_503_then_200_recovers() -> None:
    seq = iter([503, 200])
    calls = {"n": 0}

    def fake_get(url):
        calls["n"] += 1
        return _FakeResp(b"ok", status=next(seq))

    r = _retry_transient(fake_get, "https://x.test/", max_attempts=2)
    assert calls["n"] == 2
    assert r.status_code == 200
    print(f"  ✓ 503→200 recovered in {calls['n']} calls")


def t_404_not_retried() -> None:
    calls = {"n": 0}

    def fake_get(url):
        calls["n"] += 1
        return _FakeResp(b"", status=404)

    r = _retry_transient(fake_get, "https://x.test/", max_attempts=2)
    assert calls["n"] == 1, f"404 should not be retried, got {calls['n']} calls"
    assert r.status_code == 404
    print(f"  ✓ 404 not retried ({calls['n']} call)")


def t_200_no_retry() -> None:
    calls = {"n": 0}

    def fake_get(url):
        calls["n"] += 1
        return _FakeResp(b"ok", status=200)

    r = _retry_transient(fake_get, "https://x.test/", max_attempts=2)
    assert calls["n"] == 1
    print(f"  ✓ 200 returned immediately ({calls['n']} call)")


def t_size_cap_truncates_and_tags() -> None:
    big = b"x" * (MAX_DOWNLOAD_BYTES_DEFAULT + 5000)

    def fake_get(url):
        return _FakeResp(big, status=200)

    r = _get_with_size_cap(fake_get, "https://x.test/", MAX_DOWNLOAD_BYTES_DEFAULT)
    assert len(r.content) == MAX_DOWNLOAD_BYTES_DEFAULT, \
        f"truncated to {len(r.content)}, expected {MAX_DOWNLOAD_BYTES_DEFAULT}"
    assert r._truncated_download is True
    print(f"  ✓ oversized body truncated {len(big)}→{len(r.content)} + tagged")


def t_size_cap_leaves_small_body_alone() -> None:
    small = b"hello world"

    def fake_get(url):
        return _FakeResp(small, status=200)

    r = _get_with_size_cap(fake_get, "https://x.test/", MAX_DOWNLOAD_BYTES_DEFAULT)
    assert r.content == small
    assert not getattr(r, "_truncated_download", False)
    print(f"  ✓ small body unchanged ({len(r.content)} bytes)")


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("t_") and callable(v)]
    failed = 0
    for test in tests:
        try:
            test()
        except AssertionError as e:
            print(f"  ✗ {test.__name__}: {e}")
            failed += 1
    print(f"\n{'OK' if failed == 0 else 'FAIL'}: {len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
