import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "human_typer"))
import engine  # noqa: E402
import markup as M  # noqa: E402

SAMPLES = [
    "# A Title Here\nSome **bold words** and *italic* and __under__ and ~~gone~~ text.\n\n"
    "## Section two\n- first **item**\n- second *item*\n\n1. one\n2. two\n"
    "Back to {size:18}big text{/size} and normal. 5 * 3 = 15.",
    "**B**o*l*d at every letter **a***b*__c__~~d~~",
    "plain text only, no marks.",
    "### Small\n{size:30}Huge **bold** stuff{/size}\n- x\n1. y\n- z",
]


class ParseTest(unittest.TestCase):
    def test_inline_marks(self):
        doc = M.parse("a **b** *c* __d__ ~~e~~")
        self.assertEqual(doc.text, "a b c d e")
        styles = {ch: st for ch, st in zip(doc.text, doc.inline)}
        self.assertTrue(styles["b"].bold)
        self.assertTrue(styles["c"].italic)
        self.assertTrue(styles["d"].underline)
        self.assertTrue(styles["e"].strike)
        self.assertEqual(styles["a"], M.Inline())

    def test_paragraphs(self):
        doc = M.parse("# Title\n- item\n3. step\nplain")
        self.assertEqual(doc.text, "Title\nitem\nstep\nplain")
        self.assertEqual(doc.paras, [M.Para(heading=1), M.Para(list="bullet"),
                                     M.Para(list="number"), M.Para()])

    def test_literal_asterisks_and_escapes(self):
        self.assertEqual(M.parse("5 * 3 = 15").text, "5 * 3 = 15")
        self.assertEqual(M.parse(r"a \*not italic\* b").text, "a *not italic* b")
        self.assertEqual(M.parse("an *unclosed mark").text, "an *unclosed mark")
        self.assertEqual(M.parse("snake_case_name").text, "snake_case_name")

    def test_size(self):
        doc = M.parse("a{size:18}b{/size}c")
        self.assertEqual([st.size for st in doc.inline], [None, 18, None])


class PlanTest(unittest.TestCase):
    def test_every_character_gets_the_right_style(self):
        for seed in range(300):
            src = SAMPLES[seed % len(SAMPLES)]
            settings = engine.Settings(typos_per_100_words=15, thinking=1.5)
            actions, plain = M.plan(src, settings, seed)
            got_chars, got_paras = M.simulate(actions)
            exp_chars, exp_paras = M.expected(M.parse(src))
            self.assertEqual(got_chars, exp_chars, seed)
            for got, exp, line in zip(got_paras, exp_paras, plain.split("\n")):
                if line:
                    self.assertEqual(got, exp, (seed, line))

    def test_formatting_off_types_marks_literally(self):
        actions, plain = M.plan("**hi**", engine.Settings(typos_per_100_words=0), 1, formatting=False)
        self.assertEqual(engine.replay(actions), "**hi**")
        self.assertFalse(any(a.kind == "combo" for a in actions))

    def test_shortcuts(self):
        doc = M.parse("# H\nx {size:14}y{/size}z")
        points = M.format_points(doc)
        self.assertEqual(points[0], ["cmd+alt+1"])
        self.assertNotIn(2, points)                                       # Return already ends the heading
        self.assertEqual(points[4], [M.SIZE_UP, M.SIZE_UP])               # 11 -> 12 -> 14
        self.assertEqual(points[5], [M.SIZE_DOWN, M.SIZE_DOWN])


class HtmlTest(unittest.TestCase):
    # Trimmed from what Google Docs puts on the clipboard.
    DOCS_HTML = (
        '<meta charset="utf-8"><b style="font-weight:normal;" id="docs-internal-guid-1">'
        '<h1 dir="ltr"><span style="font-size:20pt;font-weight:400">My Heading</span></h1>'
        '<p dir="ltr"><span style="font-size:11pt;font-weight:400">Plain and </span>'
        '<span style="font-size:11pt;font-weight:700">bold</span>'
        '<span style="font-size:11pt;font-weight:400"> then </span>'
        '<span style="font-size:11pt;font-style:italic">italic</span>'
        '<span style="font-size:18pt"> big</span></p><br>'
        '<ul><li dir="ltr"><p dir="ltr"><span style="font-size:11pt">first</span></p></li>'
        '<li dir="ltr"><p dir="ltr"><span style="font-size:11pt;text-decoration:underline">second</span></p></li></ul>'
        '<p><span style="font-size:11pt">5 * 3 costs $2_000</span></p></b>'
    )

    def test_google_docs_clipboard(self):
        out = M.html_to_markup(self.DOCS_HTML)
        self.assertEqual(out.split("\n"), [
            "# My Heading",
            "Plain and **bold** then *italic* {size:18}big{/size}",
            "",
            "- first",
            "- __second__",
            r"5 \* 3 costs $2\_000",
        ])
        doc = M.parse(out)
        self.assertEqual(doc.text, "My Heading\nPlain and bold then italic big\n\nfirst\nsecond\n5 * 3 costs $2_000")

    def test_round_trip(self):
        for src in SAMPLES[:2]:
            doc = M.parse(src)
            html = []
            for line, para in zip(doc.text.split("\n"), doc.paras):
                html.append("<p>" + "".join(f"<span>{c}</span>" for c in line) + "</p>")
            self.assertEqual(M.parse(M.html_to_markup("".join(html))).text.replace("\n\n", "\n"),
                             doc.text.replace("\n\n", "\n"))


if __name__ == "__main__":
    unittest.main()
