#!/usr/bin/env python3
"""Tier 1-1 regression tests — JS shell detection & BOT_WALL_SUSPECTED verdict.

Deterministic, network-free. Locks in:
  * empty SPA mount points (React/Next/Nuxt) → Verdict.JS_SHELL (non-terminal)
  * real pages are never misclassified as JS shells
  * non-2xx + hard challenge marker → Verdict.BOT_WALL_SUSPECTED (terminal)
  * 2xx + challenge marker stays CHALLENGE (browser may still help)
  * JS_SHELL is excluded from TERMINAL_NONSUCCESS so the chain queues Playwright

Run:  python3 engine/tests/test_t1_1_js_shell.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)

from engine.validators import (  # noqa: E402
    Verdict, TERMINAL_NONSUCCESS, validate, _looks_like_js_shell,
)


class _FakeResp:
    def __init__(self, text, status=200, ctype="text/html"):
        self.text = text
        self.status_code = status
        self.content = text.encode("utf-8", "ignore") if isinstance(text, str) else text
        self.headers = {"content-type": ctype}
        self.cookies = type("C", (), {"jar": []})()


def t_empty_react_mount_is_js_shell() -> None:
    html = ('<html><head><title>React App</title></head>'
            '<body><div id="root"></div></body></html>')
    assert _looks_like_js_shell(html), "empty React mount should be detected"
    vr = validate(_FakeResp(html))
    assert vr.verdict == Verdict.JS_SHELL, f"got {vr.verdict}"
    assert "js_shell_detected" in vr.reasons
    print("  ✓ empty React mount → JS_SHELL")


def t_empty_next_mount_is_js_shell() -> None:
    html = ('<html><head><title>Next</title></head>'
            '<body><div id="__next"></div></body></html>')
    assert _looks_like_js_shell(html), "empty Next mount should be detected"
    vr = validate(_FakeResp(html))
    assert vr.verdict == Verdict.JS_SHELL, f"got {vr.verdict}"
    print("  ✓ empty __next mount → JS_SHELL")


def t_real_article_not_misclassified() -> None:
    big = ('<html><body>' + ('<p>Real article content here. ' * 200) +
           '</body></html>')
    assert not _looks_like_js_shell(big), "big page is not a shell"
    vr = validate(_FakeResp(big))
    assert vr.verdict == Verdict.WEAK_OK, f"got {vr.verdict}"
    print("  ✓ real article (10KB+) → WEAK_OK (not JS_SHELL)")


def t_example_dot_com_still_weak_ok() -> None:
    # example.com is ~600 bytes and was the historical WEAK_OK anchor.
    html = ('<html><head><title>Example Domain</title></head>'
            '<body><div><h1>Example Domain</h1>'
            '<p>This domain is for use in documentation examples.</p>'
            '<p><a href="https://iana.org/domains/example">Learn more</a></p>'
            '</div></body></html>')
    vr = validate(_FakeResp(html))
    assert vr.verdict == Verdict.WEAK_OK, f"got {vr.verdict}"
    print("  ✓ example.com (~600B, complete) → WEAK_OK")


def t_403_with_cloudflare_marker_is_bot_wall() -> None:
    html = '<html><title>Just a moment...</title></html>'
    vr = validate(_FakeResp(html, status=403))
    assert vr.verdict == Verdict.BOT_WALL_SUSPECTED, f"got {vr.verdict}"
    assert vr.verdict in TERMINAL_NONSUCCESS, "bot wall must be terminal"
    print("  ✓ 403 + Cloudflare marker → BOT_WALL_SUSPECTED (terminal)")


def t_200_with_challenge_marker_stays_challenge() -> None:
    # A 2xx with a hard marker is still a challenge — but not a terminal bot
    # wall, because the body could be a legitimate page that quotes the marker.
    html = '<html><title>Just a moment...</title></html>'
    vr = validate(_FakeResp(html, status=200))
    assert vr.verdict == Verdict.CHALLENGE, f"got {vr.verdict}"
    assert vr.verdict not in TERMINAL_NONSUCCESS
    print("  ✓ 200 + Cloudflare marker → CHALLENGE (non-terminal, browser may help)")


def t_js_shell_is_non_terminal() -> None:
    assert Verdict.JS_SHELL not in TERMINAL_NONSUCCESS, \
        "JS_SHELL must be non-terminal so Playwright fallback gets a chance"
    print("  ✓ JS_SHELL excluded from TERMINAL_NONSUCCESS")


def t_bot_wall_in_terminal_set() -> None:
    assert Verdict.BOT_WALL_SUSPECTED in TERMINAL_NONSUCCESS, \
        "BOT_WALL_SUSPECTED must be terminal"
    print("  ✓ BOT_WALL_SUSPECTED in TERMINAL_NONSUCCESS")


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("t_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            print(f"  ✗ {t.__name__}: {e}")
            failed += 1
    print(f"\n{'OK' if failed == 0 else 'FAIL'}: {len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
