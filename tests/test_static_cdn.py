"""CDN scripts must be pinned to an exact version and carry an SRI hash (P2-4)."""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"
TAG = re.compile(r"<script\b[^>]*src=\"(https?://[^\"]+)\"[^>]*>")


def test_cdn_scripts_pinned_with_sri():
    found = 0
    for page in STATIC.glob("*.html"):
        for m in TAG.finditer(page.read_text(encoding="utf-8")):
            found += 1
            tag, url = m.group(0), m.group(1)
            assert re.search(r"@\d+\.\d+\.\d+/", url), f"{page.name}: unpinned {url}"
            assert re.search(r'integrity="sha384-[A-Za-z0-9+/=]+"', tag), f"{page.name}: no SRI {url}"
            assert 'crossorigin="anonymous"' in tag
    assert found >= 5
