"""Runs the node-based XSS tests (tests/js) when node is available."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_js_xss_suite():
    res = subprocess.run(["node", "--test", "tests/js/xss.test.mjs"], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stdout + res.stderr
