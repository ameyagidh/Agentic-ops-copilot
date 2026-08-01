"""Regression test for the original prototype's import-time crash: the old
`agentic_ops_copilot.py` built `ChatOpenAI(...)` at module scope, so simply
importing it raised without OPENAI_API_KEY. This asserts the package (and
graph construction) works with a completely scrubbed environment.
"""

import subprocess
import sys


def test_import_with_zero_env_vars():
    script = (
        "import asyncio\n"
        "from ops_copilot.graph import build_graph, close_graph\n"
        "async def main():\n"
        "    g = await build_graph()\n"
        "    await close_graph(g)\n"
        "asyncio.run(main())\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},  # deliberately no OPENAI_API_KEY / AWS creds / OPS_* vars
        cwd=None,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout
