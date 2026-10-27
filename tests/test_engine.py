import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "human_typer"))
import engine  # noqa: E402

SAMPLES = [
    "The quick brown fox jumps over the lazy dog. Then it rested!\n\nNew paragraph: 123 apples, "
    "\"quoted\" text; and (parens) — émojis 🙂 too.",
    "a", "", "Hi.", "x y z\n\n\nend", "THE END? Yes; it's 2026-10-27 @ 5:00pm & 100% done!",
]


class PlannerTest(unittest.TestCase):
    def test_final_text_is_always_exact(self):
        for seed in range(400):
            for preset in engine.PRESETS.values():
                s = engine.Settings(**preset)
                s.typos_per_100_words = 15
                text = SAMPLES[seed % len(SAMPLES)]
                self.assertEqual(engine.replay(engine.plan_text(text, s, seed)), text, (seed, preset))

    def test_makes_and_fixes_typos(self):
        text = "Every writer develops habits over the years, some good and some questionable. " * 20
        actions = engine.plan_text(text, engine.Settings(typos_per_100_words=6), seed=1)
        self.assertGreater(sum(a.tag == "typo" for a in actions), 5)
        self.assertGreater(sum(a.kind == "back" for a in actions), 5)

    def test_overall_speed_is_below_burst_speed(self):
        text = "Learning to write well takes practice and patience. " * 40
        for wpm in (30, 60, 110):
            actions = engine.plan_text(text, engine.Settings(wpm=wpm), seed=2)
            overall = len(text) / 5 / (engine.plan_duration(actions) / 60)
            self.assertLess(overall, wpm)
            self.assertGreater(overall, wpm * 0.55)

    def test_no_pauses_when_thinking_off(self):
        text = "One. Two, three.\nFour five six seven eight nine ten. " * 10
        actions = engine.plan_text(text, engine.Settings(thinking=0, second_thoughts=False), seed=3)
        self.assertLess(max(a.delay for a in actions if a.kind == "key"), 1.2)


if __name__ == "__main__":
    unittest.main()
