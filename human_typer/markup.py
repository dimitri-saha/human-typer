"""Formatting marks in the text box, and the Google Docs shortcuts that apply them.

Marks (Markdown-like):
    **bold**   *italic*   __underline__   ~~strikethrough~~   {size:18}bigger{/size}
    # Heading 1 ... ###### Heading 6     - bullet item     1. numbered item
    A backslash types the next mark literally: \\*  \\_  \\~  \\{  \\#

Formatting is applied the way a person would: press the shortcut, then type.
The planner keeps typo corrections inside a single formatting run, so text
never gets retyped with the wrong style.
"""
import re
from dataclasses import dataclass, replace
from html.parser import HTMLParser

import engine

# Google Docs' font-size steps (Cmd+Shift+. / Cmd+Shift+, move between these).
SIZE_STEPS = [8, 9, 10, 11, 12, 14, 18, 24, 30, 36, 48, 60, 72, 96]
HEADING_SIZE = {0: 11, 1: 20, 2: 16, 3: 14, 4: 12, 5: 11, 6: 11}

# Google Docs keyboard shortcuts (macOS).
BOLD, ITALIC, UNDERLINE, STRIKE = "cmd+b", "cmd+i", "cmd+u", "cmd+shift+x"
SIZE_UP, SIZE_DOWN = "cmd+shift+.", "cmd+shift+,"
BULLETS, NUMBERS = "cmd+shift+8", "cmd+shift+7"


def heading_combo(level):
    return f"cmd+alt+{level}"   # level 0 is "Normal text"


@dataclass(frozen=True)
class Inline:
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    size: int = None     # None = the paragraph's default size


@dataclass(frozen=True)
class Para:
    heading: int = 0     # 0 = normal text
    list: str = ""       # "", "bullet" or "number"


@dataclass
class Doc:
    text: str            # plain text to type
    inline: list         # an Inline per character of text
    paras: list          # a Para per paragraph (text.count("\n") + 1 of them)


# ------------------------------------------------------------------ parsing --

ESCAPABLE = set("\\*_~{}#-.+`•")
LINE_RE = re.compile(r"^(?:(#{1,6})\s+|\s*([-*•])\s+|\s*(\d+)[.)]\s+)")
SIZE_RE = re.compile(r"\{size:\s*(\d+(?:\.\d+)?)\}|\{/size\}")
TOGGLES = {"**": "bold", "*": "italic", "__": "underline", "~~": "strike"}


def _tokenize(line):
    """Splits one line into literal characters, toggles and size changes."""
    out = []   # ("ch", c) | ("tog", kind, mark) | ("size", n or None)
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if c == "\\" and i + 1 < n and line[i + 1] in ESCAPABLE:
            out.append(("ch", line[i + 1]))
            i += 2
            continue
        m = SIZE_RE.match(line, i)
        if m:
            out.append(("size", round(float(m.group(1))) if m.group(1) else None))
            i = m.end()
            continue
        if c in "*_~":
            j = i
            while j < n and line[j] == c:
                j += 1
            run = j - i
            before = line[i - 1] if i > 0 else " "
            after = line[j] if j < n else " "
            if before.isspace() and after.isspace():
                out.extend(("ch", c) for _ in range(run))   # "5 * 3": a real asterisk
            elif c == "*":
                out.extend(("tog", "bold", "**") for _ in range(run // 2))
                if run % 2:
                    out.append(("tog", "italic", "*"))
            else:
                kind = "underline" if c == "_" else "strike"
                out.extend(("tog", kind, c * 2) for _ in range(run // 2))
                if run % 2:
                    out.append(("ch", c))   # a lone _ or ~ is just a character
            i = j
            continue
        out.append(("ch", c))
        i += 1

    # A mark with no partner on the same line is typed as-is.
    for kind in ("bold", "italic", "underline", "strike"):
        idx = [k for k, t in enumerate(out) if t[0] == "tog" and t[1] == kind]
        if len(idx) % 2:
            mark = out[idx[-1]][2]
            out[idx[-1]:idx[-1] + 1] = [("ch", ch) for ch in mark]
    return out


def parse(markup):
    """Markup text -> Doc with plain text and per-character formatting."""
    markup = markup.replace("\r\n", "\n").replace("\r", "\n")
    text, inline, paras = [], [], []
    for line in markup.split("\n"):
        para = Para()
        m = LINE_RE.match(line)
        if m:
            if m.group(1):
                para = Para(heading=len(m.group(1)))
            elif m.group(2):
                para = Para(list="bullet")
            else:
                para = Para(list="number")
            line = line[m.end():]
        paras.append(para)
        style = Inline()
        for tok in _tokenize(line):
            if tok[0] == "tog":
                style = replace(style, **{tok[1]: not getattr(style, tok[1])})
            elif tok[0] == "size":
                style = replace(style, size=tok[1])
            else:
                text.append(tok[1])
                inline.append(style)
        text.append("\n")
        inline.append(Inline())
    text.pop()
    inline.pop()
    return Doc("".join(text), inline, paras)


def has_marks(markup):
    doc = parse(markup)
    return doc.text != markup.replace("\r\n", "\n").replace("\r", "\n")


# ------------------------------------------------------------ Docs model --

def snap_size(size, heading):
    """The size Docs can reach with its size shortcuts."""
    default = HEADING_SIZE[heading]
    if size is None or size == default:
        return default
    return min(SIZE_STEPS, key=lambda s: (abs(s - size), s))


def size_up(s):
    return next((x for x in SIZE_STEPS if x > s), s)


def size_down(s):
    return next((x for x in reversed(SIZE_STEPS) if x < s), s)


@dataclass
class DocsState:
    """What Google Docs will apply to the next character typed."""
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    size: int = 11
    heading: int = 0
    list: str = ""

    def apply(self, combo):
        if combo == BOLD:
            self.bold = not self.bold
        elif combo == ITALIC:
            self.italic = not self.italic
        elif combo == UNDERLINE:
            self.underline = not self.underline
        elif combo == STRIKE:
            self.strike = not self.strike
        elif combo == SIZE_UP:
            self.size = size_up(self.size)
        elif combo == SIZE_DOWN:
            self.size = size_down(self.size)
        elif combo == BULLETS:
            self.list = "" if self.list == "bullet" else "bullet"
        elif combo == NUMBERS:
            self.list = "" if self.list == "number" else "number"
        elif combo.startswith("cmd+alt+"):
            self.heading = int(combo[-1])
            self.size = HEADING_SIZE[self.heading]

    def newline(self):
        # Pressing Return at the end of a heading starts a Normal text paragraph.
        if self.heading:
            self.heading = 0
            self.size = HEADING_SIZE[0]

    def combos_for(self, para=None, inline=None):
        """Shortcuts that bring this state to the wanted paragraph/inline style."""
        combos = []
        if para is not None:
            if para.heading != self.heading:
                combos.append(heading_combo(para.heading))
            if para.list != self.list:
                if para.list == "":
                    combos.append(BULLETS if self.list == "bullet" else NUMBERS)
                else:
                    combos.append(BULLETS if para.list == "bullet" else NUMBERS)
        heading = para.heading if para is not None else self.heading
        size = HEADING_SIZE[heading] if para is not None and para.heading != self.heading else self.size
        if inline is not None:
            target = snap_size(inline.size, heading)
            while size < target and size_up(size) != size:
                size = size_up(size)
                combos.append(SIZE_UP)
            while size > target and size_down(size) != size:
                size = size_down(size)
                combos.append(SIZE_DOWN)
            for attr, combo in (("bold", BOLD), ("italic", ITALIC),
                                ("underline", UNDERLINE), ("strike", STRIKE)):
                if getattr(inline, attr) != getattr(self, attr):
                    combos.append(combo)
        return combos


def format_points(doc, start=0, state=None):
    """{text index: shortcuts to press just before typing that character}.

    start/state: plan only doc.text[start:] (indexes counted from start), with the
    editor already in `state` (what was applied before stopping).
    """
    state = replace(state) if state else DocsState()
    points = {}
    p = doc.text.count("\n", 0, start)
    para_start = start == 0 or doc.text[start - 1] == "\n"
    for i in range(start, len(doc.text)):
        ch = doc.text[i]
        para = doc.paras[p] if para_start else None
        combos = state.combos_for(para, None if ch == "\n" else doc.inline[i])
        for c in combos:
            state.apply(c)
        if combos:
            points[i - start] = combos
        if ch == "\n":
            state.newline()
            p += 1
            para_start = True
        else:
            para_start = False
    return points


def plan(markup, settings, seed=None, formatting=True):
    """Returns (actions, plain text being typed)."""
    if not formatting:
        return engine.plan_text(markup, settings, seed), markup
    doc = parse(markup)
    return engine.Planner(settings, seed).plan(doc.text, format_points(doc)), doc.text


def simulate(actions):
    """Plays actions against the Docs model: [(char, style tuple)], [Para]."""
    state = DocsState()
    chars = []
    paras = [Para()]
    for a in actions:
        if a.kind == "combo":
            state.apply(a.ch)
            paras[-1] = Para(state.heading, state.list)
        elif a.kind == "key":
            if a.ch == "\n":
                state.newline()
                paras.append(Para(state.heading, state.list))
                chars.append(("\n", None))
            else:
                chars.append((a.ch, (state.bold, state.italic, state.underline, state.strike, state.size)))
        else:
            if chars.pop()[0] == "\n":
                raise AssertionError("a correction deleted a line break")
    return chars, paras


def expected(doc):
    """What simulate() should produce for a parsed Doc."""
    chars = []
    p = 0
    for ch, st in zip(doc.text, doc.inline):
        if ch == "\n":
            chars.append(("\n", None))
            p += 1
        else:
            size = snap_size(st.size, doc.paras[p].heading)
            chars.append((ch, (st.bold, st.italic, st.underline, st.strike, size)))
    return chars, list(doc.paras)


# ------------------------------------------------------ pasting rich text --

class _HtmlReader(HTMLParser):
    BLOCKS = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "blockquote"}
    SKIP = {"style", "script", "head", "title"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paras = [[Para(), []]]       # [Para, [(text, Inline)]]
        self.styles = [Inline()]
        self.lists = []
        self.skip = 0

    def _cur(self):
        return self.paras[-1]

    def _break(self, force=False):
        if force or self._cur()[1]:
            self.paras.append([Para(), []])

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
            return
        attrs = dict(attrs)
        if tag == "br":
            self._break(force=True)
            return
        if tag in ("ul", "ol"):
            self.lists.append("number" if tag == "ol" else "bullet")
        if tag in self.BLOCKS:
            self._break()
            para = self._cur()[0]
            if tag[0] == "h" and tag[1:].isdigit():
                para = replace(para, heading=int(tag[1]))
            if tag == "li" and self.lists:
                para = replace(para, list=self.lists[-1])
            self._cur()[0] = para
        style = self.styles[-1]
        if tag in ("b", "strong"):
            style = replace(style, bold=True)
        elif tag in ("i", "em"):
            style = replace(style, italic=True)
        elif tag == "u":
            style = replace(style, underline=True)
        elif tag in ("s", "strike", "del"):
            style = replace(style, strike=True)
        style = self._css(style, attrs.get("style", ""))
        if tag not in ("img", "meta", "link", "hr", "input"):
            self.styles.append(style)

    def _css(self, style, css):
        for decl in css.split(";"):
            if ":" not in decl:
                continue
            prop, val = (x.strip().lower() for x in decl.split(":", 1))
            if prop == "font-weight":
                style = replace(style, bold=val == "bold" or (val.isdigit() and int(val) >= 600))
            elif prop == "font-style":
                style = replace(style, italic=val == "italic")
            elif prop in ("text-decoration", "text-decoration-line"):
                style = replace(style, underline="underline" in val, strike="line-through" in val)
            elif prop == "font-size":
                m = re.match(r"([\d.]+)(pt|px)", val)
                if m:
                    pt = float(m.group(1)) * (0.75 if m.group(2) == "px" else 1)
                    style = replace(style, size=round(pt))
        return style

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if tag in ("ul", "ol") and self.lists:
            self.lists.pop()
        if tag in self.BLOCKS:
            self._break()
        if tag not in ("br", "img", "meta", "link", "hr", "input") and len(self.styles) > 1:
            self.styles.pop()

    def handle_data(self, data):
        if self.skip:
            return
        data = re.sub(r"\s+", " ", data.replace("\xa0", " "))
        if not self._cur()[1]:
            data = data.lstrip()
        if data:
            self._cur()[1].append((data, self.styles[-1]))


def _escape(text):
    return "".join("\\" + c if c in "\\*_~{" else c for c in text)


def html_to_markup(html):
    """Rich text copied from Google Docs, Word or a web page -> markup."""
    reader = _HtmlReader()
    reader.feed(html)
    reader.close()
    paras = reader.paras
    while paras and not paras[-1][1]:
        paras.pop()
    lines = []
    num = 0
    for para, runs in paras:
        if para.heading:
            prefix = "#" * para.heading + " "
        elif para.list == "bullet":
            prefix = "- "
        elif para.list == "number":
            num += 1
            prefix = f"{num}. "
        else:
            prefix = ""
        if para.list != "number":
            num = 0
        default = HEADING_SIZE[para.heading]
        # Merge runs, and let whitespace-only runs take the previous style.
        merged = []
        for text, st in runs:
            st = replace(st, size=None if st.size in (None, default) else st.size)
            if merged and (text.isspace() or merged[-1][1] == st):
                merged[-1][0] += text
            else:
                merged.append([text, st])
        # Closing marks hug the end of the previous word and opening marks the
        # start of the next one, so a mark never sits between two spaces, where
        # the parser would read it as a literal asterisk.
        out = []
        cur = Inline()
        pending = ""
        for text, st in merged:
            body = text.rstrip()
            trail = text[len(body):]
            stripped = body.lstrip()
            pending += body[:len(body) - len(stripped)]
            if st != cur:
                # Turn off what st doesn't have, then the gap, then turn on the rest.
                kept = Inline(*(getattr(cur, f) and getattr(st, f)
                                for f in ("bold", "italic", "underline", "strike")), size=cur.size)
                out.append(_marks(cur, kept))
                out.append(pending)
                out.append(_marks(kept, st))
                cur = st
            else:
                out.append(pending)
            out.append(_escape(stripped))
            pending = trail
        out.append(_marks(cur, Inline()))
        line = "".join(out).rstrip()
        if not prefix and re.match(r"(#{1,6}\s|[-*•]\s|\d+[.)]\s)", line):
            line = "\\" + line if line[0] != "\\" else line
            line = re.sub(r"^\\(\d+)([.)])", r"\1\\\2", line)
        lines.append(prefix + line)
    return "\n".join(lines)


def _marks(a, b):
    """Marks that switch inline style a to b."""
    out = []
    if a.size != b.size:
        out.append("{/size}" if b.size is None else f"{{size:{b.size}}}")
    if a.bold != b.bold:
        out.append("**")
    if a.italic != b.italic:
        out.append("*")
    if a.underline != b.underline:
        out.append("__")
    if a.strike != b.strike:
        out.append("~~")
    return "".join(out)
