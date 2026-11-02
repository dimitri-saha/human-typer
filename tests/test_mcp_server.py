import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "human_typer"))
try:
    import mcp_server  # noqa: E402
    from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402
except ImportError:
    mcp_server = None

import sinks  # noqa: E402


class FakeTab:
    """Stands in for ChromeSink: records what would appear on the page."""
    out = []
    combos = []

    def __init__(self, ws_url, shift_enter=False):
        FakeTab.out = []
        FakeTab.combos = []

    def combo(self, spec):
        FakeTab.combos.append(spec)

    def key(self, ch):
        FakeTab.out.append(ch)

    def backspace(self):
        if FakeTab.out:
            FakeTab.out.pop()

    def close(self):
        pass


@unittest.skipIf(mcp_server is None, "the mcp package isn't installed")
class ConnectorTest(unittest.TestCase):
    def setUp(self):
        self._patched = (sinks.list_tabs, sinks.ChromeSink)
        sinks.list_tabs = lambda port=None: [
            {"id": "A", "title": "Other", "url": "https://example.com", "webSocketDebuggerUrl": "ws://a"},
            {"id": "B", "title": "Doc", "url": "https://docs.google.com/document/d/x/edit",
             "webSocketDebuggerUrl": "ws://b"}]
        sinks.ChromeSink = FakeTab
        mcp_server._job = None

    def tearDown(self):
        if mcp_server._busy():
            mcp_server.stop_typing()
        sinks.list_tabs, sinks.ChromeSink = self._patched

    def _wait_finished(self, timeout=30):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            st = mcp_server.typing_status()
            if st["state"] == "finished":
                return st
            time.sleep(0.05)
        self.fail("typing didn't finish")

    def test_types_exact_text_into_doc_tab(self):
        text = "Hi there, friend. Typing fast."
        st = mcp_server.type_text(text, wpm=200, thinking=0, typos_per_100_words=10)
        self.assertEqual(st["target"], "Chrome tab: Doc")
        st = self._wait_finished()
        self.assertEqual(st["status"], "Done")
        self.assertEqual(st["characters_done"], len(text))
        self.assertEqual("".join(FakeTab.out), text)

    def test_formatting_marks_become_shortcuts(self):
        mcp_server.type_text("Hello **world**", wpm=200, thinking=0, typos_per_100_words=0)
        st = self._wait_finished()
        self.assertEqual("".join(FakeTab.out), "Hello world")
        self.assertEqual(st["characters_total"], len("Hello world"))
        self.assertIn("cmd+b", FakeTab.combos)

    def test_formatting_off_types_marks(self):
        mcp_server.type_text("Hello **world**", wpm=200, thinking=0, typos_per_100_words=0,
                             formatting=False)
        self._wait_finished()
        self.assertEqual("".join(FakeTab.out), "Hello **world**")
        self.assertEqual(FakeTab.combos, [])

    def test_one_job_at_a_time_and_stop(self):
        mcp_server.type_text("slow " * 50, preset="Hunt & peck (25 wpm)")
        with self.assertRaises(ToolError):
            mcp_server.type_text("again")
        self.assertEqual(mcp_server.pause_typing()["state"], "paused")
        self.assertEqual(mcp_server.resume_typing()["state"], "typing")
        st = mcp_server.stop_typing()
        self.assertEqual(st["state"], "finished")
        self.assertEqual(st["status"], "Stopped")

    def test_bad_input(self):
        with self.assertRaises(ToolError):
            mcp_server.type_text("x", tab_id="nope")
        with self.assertRaises(ToolError):
            mcp_server.estimate_typing("x", preset="nope")
        with self.assertRaises(ToolError):
            mcp_server.stop_typing()


if __name__ == "__main__":
    unittest.main()
