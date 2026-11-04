import asyncio
import os
import queue
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "human_typer"))
try:
    import mcp_server  # noqa: E402
    from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402
except ImportError:
    mcp_server = None

import engine  # noqa: E402
import markup  # noqa: E402
import sinks  # noqa: E402


class FakeTab:
    """Stands in for ChromeSink: records what would appear on the page."""
    out = []
    combos = []

    def __init__(self, ws_url, shift_enter=False):
        pass

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
        FakeTab.out, FakeTab.combos = [], []
        self._notify = mcp_server._notify
        mcp_server._notify = lambda message: None
        mcp_server._job = None

    def tearDown(self):
        if mcp_server._busy():
            mcp_server.stop_typing()
        sinks.list_tabs, sinks.ChromeSink = self._patched
        mcp_server._notify = self._notify

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

    def test_change_speed_mid_job(self):
        mcp_server.type_text("slow " * 40, preset="Hunt & peck (25 wpm)", thinking=0)
        st = mcp_server.change_speed(200)
        self.assertEqual(st["wpm"], 200)
        self.assertLess(mcp_server._job.runner.scale, 0.2)

    def test_stop_then_continue_finishes_text(self):
        text = "Hello **bold words** and __underlined__ bits.\n- one item\n- two"
        mcp_server.type_text(text, wpm=120, thinking=0, typos_per_100_words=15)
        time.sleep(0.6)
        mcp_server.stop_typing()
        st = mcp_server.continue_typing(wpm=200, thinking=0, typos_per_100_words=15)
        self.assertEqual(st["wpm"], 200)
        st = asyncio.run(mcp_server.wait_for_typing(30))
        self.assertEqual(st["status"], "Done")
        self.assertEqual("".join(FakeTab.out), markup.parse(text).text)
        self.assertEqual(mcp_server.typing_status(include_text=True)["typed_text"], "".join(FakeTab.out))
        with self.assertRaises(ToolError):
            mcp_server.continue_typing()

    def test_continuation_from_every_stop_point(self):
        """Whatever keystroke typing stops after, continuing ends with the right text and styles."""
        text = "# Title\nSome **bold** text, *quite italic* here.\n1. first\n2. second __under__"
        doc = markup.parse(text)
        s = engine.Settings(wpm=100, typos_per_100_words=20, thinking=1)
        for seed in range(4):
            actions, plain = markup.plan(text, s, seed=seed)

            class Stub:
                events, paused, scale = queue.Queue(), threading.Event(), 1.0

            first = mcp_server.Job(Stub(), actions, plain, doc, ("t", None), 100)
            for cut in range(len(actions) + 1):
                first.done_actions = cut
                rest = first.continuation(s, seed)
                if rest is None:
                    self.assertEqual(cut, len(actions))
                    continue
                acts, start = rest
                done = actions[:cut] + acts
                self.assertEqual(engine.replay(done), plain, (seed, cut))
                self.assertEqual(markup.simulate(done), markup.expected(doc), (seed, cut))
                # ...and continuing the continuation part-way through works too.
                second = mcp_server.Job(Stub(), acts, plain, doc, ("t", None), 100, start)
                second.done_actions = len(acts) // 2
                again, _ = second.continuation(s, seed + 1) or ([], None)
                done = actions[:cut] + acts[:len(acts) // 2] + again
                self.assertEqual(engine.replay(done), plain, (seed, cut, "again"))
                self.assertEqual(markup.simulate(done), markup.expected(doc), (seed, cut, "again"))

    def test_continue_refuses_to_backspace_after_a_click(self):
        mcp_server.type_text("ab", wpm=200, thinking=0, typos_per_100_words=0)
        self._wait_finished()
        job = mcp_server._job
        # Pretend it stopped right after a wrong key: "a", then "x" where "b" belongs.
        job.actions = [engine.Action("key", "a", 0, 1), engine.Action("key", "x", 0, 1)]
        job.done_actions, job.finished = 2, "Stopped"
        job.cursor_moved = True
        with self.assertRaises(ToolError):
            mcp_server.continue_typing()
        job.cursor_moved = False
        self.assertEqual(job.resume_point()[:2], (1, 1))

    def test_bad_input(self):
        with self.assertRaises(ToolError):
            mcp_server.type_text("x", tab_id="nope")
        with self.assertRaises(ToolError):
            mcp_server.estimate_typing("x", preset="nope")
        with self.assertRaises(ToolError):
            mcp_server.stop_typing()
        with self.assertRaises(ToolError):
            mcp_server.change_speed(100)


class UpdateTest(unittest.TestCase):
    def test_newer(self):
        import update
        self.assertTrue(update.newer("v1.10.0", "1.9.3"))
        self.assertFalse(update.newer("1.1.0", "1.1.0"))
        self.assertFalse(update.newer("v1.0.9", "1.1.0"))
        self.assertFalse(update.newer("nightly", "1.1.0"))


if __name__ == "__main__":
    unittest.main()
