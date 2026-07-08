#!/usr/bin/env python3
"""Tier 2-6/7/8/9 regression tests — content extraction chain.

Deterministic, network-free. Locks in:
  * trafilatura path wins for real article HTML (source=trafilatura, q>0.3)
  * JSON-LD articleBody extracted when trafilatura fails
  * __NEXT_DATA__ harvested for SPA shells
  * og:description / meta description as last-ditch fallback
  * crude HTML strip when nothing else matches
  * PDF body routed through pypdf (magic-byte sniff + content-type)
  * innerText render-merge: SPA shell + visible innerText keeps the longer one
  * FetchResult carries extraction_quality / extraction_source / extraction_meta

Run:  python3 engine/tests/test_t2_6_extraction.py
"""
from __future__ import annotations

import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)

from engine.fetch_chain import (  # noqa: E402
    FetchResult,
    _extract_html_chain,
    _extract_pdf,
    _extract_response,
    _looks_like_pdf,
    _quality_score,
)


def t_real_article_uses_trafilatura() -> None:
    body = ('<html><head><title>Real Article</title></head>'
            '<body><article><p>This is a real article. It has multiple sentences. '
            'The quick brown fox jumps over the lazy dog. Lorem ipsum dolor sit '
            'amet, consectetur adipiscing elit. ' +
            ('Sed do eiusmod tempor incididunt. ' * 30) +
            '</p></article></body></html>')
    title, md, q, src = _extract_html_chain(body, "https://x.test/article")
    assert src == "trafilatura", f"got {src}"
    assert q > 0.3, f"quality too low: {q}"
    assert title == "Real Article"
    print(f"  ✓ real article → trafilatura (q={q}, len={len(md)})")


def t_spa_shell_falls_through_to_next_data() -> None:
    body = ('<html><head><title>Next Page</title></head>'
            '<body><div id="__next"></div>'
            '<script id="__NEXT_DATA__" type="application/json">'
            '{"props":{"pageProps":{"article":{"body":"This is the article body text. ' +
            'x ' * 100 + '"}}}}'
            '</script></body></html>')
    title, md, q, src = _extract_html_chain(body, "https://x.test/next")
    assert src == "next_data", f"got {src}"
    assert len(md) > 100
    print(f"  ✓ SPA shell → next_data (len={len(md)})")


def t_json_ld_article_body_extracted() -> None:
    # An SPA shell with JSON-LD as the only content source. trafilatura finds
    # nothing useful in the empty DOM, so the chain falls through to JSON-LD.
    body = ('<html><head><title>JSON-LD Article</title></head><body>'
            '<div id="root"></div>'
            '<script type="application/ld+json">'
            '{"@type":"NewsArticle","articleBody":"This is the news article body. ' +
            'Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod. ' * 10 + '"}'
            '</script></body></html>')
    # Force trafilatura to fail by stubbing it out for this test.
    import engine.fetch_chain as fc
    orig = fc._trafilatura
    fc._trafilatura = None
    try:
        title, md, q, src = _extract_html_chain(body, "https://x.test/news")
    finally:
        fc._trafilatura = orig
    assert src == "json_ld", f"got {src}"
    assert "news article body" in md
    print(f"  ✓ JSON-LD articleBody → json_ld (len={len(md)})")


def t_og_description_fallback() -> None:
    body = ('<html><head><title>Page</title>'
            '<meta property="og:description" content="This is a single page app.">'
            '</head><body><div id="root"></div></body></html>')
    title, md, q, src = _extract_html_chain(body, "https://x.test/spa")
    assert src == "meta", f"got {src}"
    assert "single page app" in md
    print(f"  ✓ og:description → meta fallback")


def t_crude_strip_when_nothing_else_matches() -> None:
    body = ('<html><body>'
            '<nav>Home About</nav>'
            '<p>This is some text content without proper article structure.</p>'
            '<footer>Copyright 2024</footer>'
            '</body></html>')
    title, md, q, src = _extract_html_chain(body, "https://x.test/plain")
    assert src == "crude", f"got {src}"
    assert "text content" in md
    print(f"  ✓ no metadata → crude strip (len={len(md)})")


def t_pdf_magic_byte_detection() -> None:
    class FakePdfResp:
        content = b"%PDF-1.4\n%binary garbage"
        text = ""
        headers = {"content-type": "text/html"}  # wrong content-type on purpose

    assert _looks_like_pdf(FakePdfResp(), "https://x.test/doc.pdf") is True
    print("  ✓ %PDF- magic byte detected despite text/html content-type")


def t_pdf_extraction_through_pypdf() -> None:
    try:
        from pypdf import PdfWriter
        from pypdf.generic import RectangleObject
    except ImportError:
        print("  ⚠ skipped: pypdf not installed")
        return
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    # pypdf doesn't trivially inject text without reportlab; just test the
    # error path — empty PDF → pdf_no_text_layer.
    buf = io.BytesIO()
    writer.write(buf)
    body = buf.getvalue()
    title, text, q, err = _extract_pdf(body, "https://x.test/blank.pdf")
    assert err == "pdf_no_text_layer", f"got {err}"
    assert text == ""
    print(f"  ✓ blank PDF → pdf_no_text_layer (err={err})")


def t_inner_text_render_merge() -> None:
    class FakeResp:
        def __init__(self, text, headers=None):
            self.text = text
            self.content = text.encode("utf-8", "ignore")
            self.headers = headers or {"content-type": "text/html"}
            self.status_code = 200

    shell = "<html><body><div id='root'></div></body></html>"
    inner = ("Real visible text harvested from innerText. " * 20)
    title, content, q, meta = _extract_response(
        FakeResp(shell), "https://x.test/x", inner_text=inner)
    assert meta["inner_text_used"] is True, \
        f"innerText should win for SPA shell; meta={meta}"
    assert len(content) > 200
    print(f"  ✓ render-merge: innerText wins for SPA (len={len(content)})")


def t_quality_score_bounds() -> None:
    assert _quality_score("") == 0.0
    assert 0.0 <= _quality_score("Short.") <= 1.0
    long_md = "This is a sentence. " * 100
    q = _quality_score(long_md)
    assert 0.0 <= q <= 1.0
    print(f"  ✓ quality score in [0, 1] (long md → {q})")


def t_fetch_result_carries_extraction_meta() -> None:
    r = FetchResult(
        ok=True, content="hello",
        extraction_quality=0.7,
        extraction_source="trafilatura",
        extraction_meta={"source": "trafilatura", "truncated": False},
    )
    d = r.to_dict()
    assert d["extraction_quality"] == 0.7
    assert d["extraction_source"] == "trafilatura"
    assert d["extraction_meta"]["source"] == "trafilatura"
    print("  ✓ FetchResult.to_dict exposes extraction_*")


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
