"""Plans a human-like keystroke sequence for a piece of text.

The planner turns text into a list of Actions (key presses and backspaces,
each with the delay to wait before it). Everything that makes the typing look
human lives here: rhythm, typos and their corrections, and pauses.
"""
import math
import random
from dataclasses import dataclass

# ---------------------------------------------------------------- keyboard --

# US QWERTY rows and the horizontal stagger of each row (in key widths).
ROWS = ["`1234567890-=", "qwertyuiop[]\\", "asdfghjkl;'", "zxcvbnm,./"]
ROW_OFFSET = [0.0, 1.5, 1.75, 2.25]
SHIFTED = dict(zip('~!@#$%^&*()_+{}|:"<>?', "`1234567890-=[]\\;',./"))

FINGERS = {
    "Lp": "`1qaz", "Lr": "2wsx", "Lm": "3edc", "Li": "45rtfgvb",
    "Ri": "67yuhjnm", "Rm": "8ik,", "Rr": "9ol.", "Rp": "0-=p[]\\;'/",
}
FINGER_OF = {k: f for f, keys in FINGERS.items() for k in keys}

# Bigrams that trained fingers roll through quickly.
COMMON_BIGRAMS = set(
    "th he in er an re on at en nd ti es or te of ed is it al ar st to nt ng "
    "se ha as ou io le ve co me de hi ri ro ic ne ea ra ce li ch ll be ma si "
    "om ur ca el ta la ns ge ly ei os no pe do su ac ec il wh".split()
)


def base_key(ch):
    """The unshifted key a character lives on ('A' -> 'a', '!' -> '1')."""
    if ch.isalpha() and ch.isascii():
        return ch.lower()
    return SHIFTED.get(ch, ch)


def needs_shift(ch):
    return (ch.isalpha() and ch.isascii() and ch.isupper()) or ch in SHIFTED


def _key_positions():
    pos = {}
    for r, row in enumerate(ROWS):
        for c, k in enumerate(row):
            pos[k] = (r, c + ROW_OFFSET[r])
    return pos


KEY_POS = _key_positions()


def _neighbors():
    out = {}
    for k, (r, x) in KEY_POS.items():
        near = []
        for k2, (r2, x2) in KEY_POS.items():
            if k2 == k or abs(r2 - r) > 1:
                continue
            if (r2 == r and abs(x2 - x) <= 1.01) or (r2 != r and abs(x2 - x) <= 0.8):
                near.append(k2)
        out[k] = near
    return out


NEIGHBORS = _neighbors()


def neighbor_typo(ch, rng):
    """A plausible fat-finger replacement for ch, or None."""
    key = base_key(ch)
    near = NEIGHBORS.get(key)
    if not near:
        return None
    if key.isalpha():
        near = [k for k in near if k.isalpha()] or near
    elif key.isdigit():
        near = [k for k in near if k.isdigit()] or near
    wrong = rng.choice(near)
    if ch.isupper() and wrong.isalpha():
        wrong = wrong.upper()
    return wrong


# ---------------------------------------------------------------- settings --

@dataclass
class Settings:
    wpm: float = 60.0               # burst speed while actually typing
    variability: float = 0.33       # spread of individual keystroke timing
    typos_per_100_words: float = 4.0
    thinking: float = 1.0           # 0 = no thinking pauses, 3 = lots
    fatigue: bool = True            # slow down gradually over long texts
    second_thoughts: bool = True    # occasionally type a word, delete it, retype
    unfixed_typo_share: float = 0.0  # fraction of typos left uncorrected


PRESETS = {
    "Hunt & peck (25 wpm)": dict(wpm=25, variability=0.45, typos_per_100_words=6, thinking=1.5),
    "Casual (45 wpm)": dict(wpm=45, variability=0.38, typos_per_100_words=5, thinking=1.2),
    "Average (60 wpm)": dict(wpm=60, variability=0.33, typos_per_100_words=4, thinking=1.0),
    "Fast (85 wpm)": dict(wpm=85, variability=0.28, typos_per_100_words=3, thinking=0.8),
    "Pro (115 wpm)": dict(wpm=115, variability=0.22, typos_per_100_words=2, thinking=0.5),
}


# ------------------------------------------------------------------ actions --

@dataclass
class Action:
    kind: str      # "key", "back" or "combo" (a shortcut such as "cmd+b")
    ch: str        # character for "key", shortcut for "combo"
    delay: float   # seconds to wait before this keystroke
    pos: int       # how many characters of the source text are done after it
    tag: str = ""  # "", "typo", "fix", "think", "rethink", "fmt" (for status display)


class Planner:
    def __init__(self, settings, seed=None):
        self.s = settings
        self.rng = random.Random(seed)
        self.speed = 1.0          # slowly drifting "flow" multiplier
        self.keys_typed = 0
        self.seen_words = set()

    # -- timing ---------------------------------------------------------
    def _drift(self):
        # Ornstein-Uhlenbeck style random walk: speed wanders but stays near 1.
        self.speed += 0.2 * (1.0 - self.speed) + self.rng.gauss(0, 0.06)
        self.speed = min(1.35, max(0.75, self.speed))

    def key_delay(self, prev, ch, word_start=False, careful=False, familiar=False):
        s = self.s
        m = 1.0
        if prev:
            pair = (base_key(prev) + base_key(ch))
            fp, fc = FINGER_OF.get(base_key(prev)), FINGER_OF.get(base_key(ch))
            if pair in COMMON_BIGRAMS:
                m *= 0.78
            elif base_key(prev) == base_key(ch):
                m *= 0.9
            elif fp and fc and fp == fc:
                m *= 1.3            # same finger, different key: slow
            elif fp and fc and fp[0] != fc[0]:
                m *= 0.86           # alternating hands: fast
        if ch == " ":
            m *= 0.85
        elif needs_shift(ch):
            m *= 1.35
        if ch.isdigit():
            m *= 1.3
        elif not ch.isalnum() and ch not in " \n":
            m *= 1.4
        if word_start:
            m *= 1.12
        if careful:
            m *= 1.15
        if familiar:
            m *= 0.92
        fatigue = 1.0 + (0.15 * min(1.0, self.keys_typed / 4000) if s.fatigue else 0.0)
        sigma = max(0.05, s.variability)
        noise = math.exp(self.rng.gauss(-sigma * sigma / 2, sigma))
        base = 60.0 / (max(5.0, s.wpm) * 5.0)
        return max(0.028, base * m * self.speed * fatigue * noise)

    def backspace_delay(self, first, count):
        if first:
            return self.rng.uniform(0.18, 0.55)
        # Long runs feel like a held key; short ones are individual taps.
        mean = 0.055 if count > 5 else 0.095
        return max(0.03, self.rng.gauss(mean, 0.018))

    def _lognormal(self, median, sigma):
        return median * math.exp(self.rng.gauss(0, sigma))

    def pause_after(self, ch):
        """Extra pause to add before the next word, given the char just typed."""
        t = self.s.thinking
        if ch in ",;:":
            return self.rng.uniform(0.1, 0.45) * t
        if ch in ".!?":
            return min(4.0, self._lognormal(0.65, 0.5)) * t
        if ch == "\n":
            return min(6.0, self._lognormal(1.4, 0.5)) * t
        return 0.0

    # -- planning -------------------------------------------------------
    def plan(self, text, formats=None):
        """formats: {text index: shortcuts to press before typing that character}.

        Formatting changes act as barriers: no typo, correction or second
        thought crosses one, so nothing is ever retyped in the wrong style.
        """
        rng, s = self.rng, self.s
        formats = formats or {}
        if not formats:
            text = text.replace("\r\n", "\n").replace("\r", "\n")
        n = len(text)
        typo_p = s.typos_per_100_words / 100.0 / 5.5
        actions = []
        prev = ""
        pending_pause = 0.0
        cooldown = 0
        sentence_start = True
        i = 0

        def emit_key(ch, pos, word_start=False, careful=False, familiar=False, tag="", extra=0.0):
            nonlocal prev
            d = self.key_delay(prev, ch, word_start, careful, familiar) + extra
            actions.append(Action("key", ch, d, pos, tag))
            prev = ch
            self.keys_typed += 1

        def emit_backspaces(count, pos, notice):
            nonlocal prev
            for k in range(count):
                d = self.backspace_delay(k == 0, count) + (notice if k == 0 else 0.0)
                actions.append(Action("back", "", d, pos, "fix"))
            prev = ""

        while i < n:
            ch = text[i]
            word_start = ch not in " \n\t" and (i == 0 or text[i - 1] in " \n\t")
            familiar = False
            extra = 0.0

            if word_start:
                self._drift()
                j = i
                while j < n and text[j] not in " \n\t":
                    j += 1
                word = text[i:j]
                key = word.lower().strip(".,;:!?\"'()")
                familiar = key in self.seen_words
                self.seen_words.add(key)
                extra += pending_pause
                pending_pause = 0.0
                tag = ""
                # Stopping to think about what to write next.
                p_think = 0.02 * s.thinking + (0.04 * s.thinking if sentence_start else 0.0)
                if rng.random() < p_think:
                    extra += min(9.0, self._lognormal(1.8, 0.6))
                    tag = "think"
                # Hesitating before a long or unusual word.
                elif sum(c.isalpha() for c in word) >= 9 and rng.random() < 0.3 * min(s.thinking, 1.5):
                    extra += rng.uniform(0.25, 0.9)
                # Second thoughts: type the word, decide against it, retype it.
                if (s.second_thoughts and len(word) >= 4 and i > 0
                        and not any(b in formats for b in range(i, j))
                        and rng.random() < 0.007 * max(s.thinking, 0.3)):
                    for k, c in enumerate(word):
                        emit_key(c, i, word_start=(k == 0), tag="rethink" if k == 0 else "",
                                 extra=extra if k == 0 else 0.0)
                    extra = 0.0
                    emit_backspaces(len(word), i, rng.uniform(0.5, 1.6))
                    extra = rng.uniform(0.6, 2.2)
                    tag = "rethink"
                sentence_start = False
            else:
                tag = ""

            # ---- formatting shortcuts, pressed right before the character ----
            if i in formats:
                reach = rng.uniform(0.2, 0.55)
                for k, combo in enumerate(formats[i]):
                    d = extra + reach if k == 0 else rng.uniform(0.12, 0.3)
                    first_tag = (tag or "fmt") if k == 0 else "fmt"
                    actions.append(Action("combo", combo, d, i, first_tag))
                extra = rng.uniform(0.08, 0.25)
                tag = ""
                prev = ""

            # ---- typo? ----
            kind = None
            if cooldown > 0:
                cooldown -= 1
            elif i > 0 and i not in formats and ch.isascii() and ch.isprintable() and ch != " ":
                p = typo_p * (1.3 if (needs_shift(ch) or not ch.isalnum()) else 1.0)
                if rng.random() < p:
                    kind = self._choose_typo(text, i, i + 1 not in formats)

            if kind:
                wrong, consumed = self._make_typo(kind, text, i)
                # How many more correct characters slip out before noticing.
                if rng.random() < 0.45 and kind != "omission":
                    k = 0
                else:
                    k = rng.choice([1, 1, 1, 2, 2, 3, 3, 4, 5, 7])
                start_extra = i + consumed
                limit = start_extra
                while (limit < n and text[limit] != "\n" and limit not in formats
                       and limit - start_extra < k):
                    limit += 1
                extra_chars = text[start_extra:limit]
                if not wrong and not extra_chars:
                    kind = None  # an omission nobody could notice yet; skip it
                else:
                    first = True
                    for c in wrong + list(extra_chars):
                        emit_key(c, i, word_start=word_start and first, familiar=familiar,
                                 tag="typo" if first else "", extra=extra if first else 0.0)
                        first = False
                    leave = (kind in ("substitution", "double", "omission", "caps")
                             and k == 0 and rng.random() < s.unfixed_typo_share)
                    if leave:
                        i += consumed
                        cooldown = 3
                    else:
                        # Sometimes delete one character too many.
                        overshoot = 1 if (i > 0 and text[i - 1] not in "\n" and i - 1 not in formats
                                          and rng.random() < 0.1) else 0
                        notice = rng.uniform(0.15, 0.6) + 0.08 * len(extra_chars)
                        emit_backspaces(len(wrong) + len(extra_chars) + overshoot, i, notice)
                        redo_from = i - overshoot
                        redo_to = start_extra + len(extra_chars)
                        pre_redo = rng.uniform(0.1, 0.35)
                        for k2, c in enumerate(text[redo_from:redo_to]):
                            emit_key(c, redo_from + k2 + 1, careful=True,
                                     extra=pre_redo if k2 == 0 else 0.0)
                        i = redo_to
                        cooldown = 3
                    if i > 0:
                        pending_pause += self.pause_after(text[i - 1])
                        if text[i - 1] in ".!?\n":
                            sentence_start = True
                    continue

            emit_key(ch, i + 1, word_start=word_start, familiar=familiar, tag=tag, extra=extra)
            pending_pause += self.pause_after(ch)
            if ch in ".!?\n":
                sentence_start = True
            i += 1
        return actions

    def _choose_typo(self, text, i, next_ok=True):
        ch = text[i]
        # Typos that involve the next character can't reach across a formatting change.
        nxt = text[i + 1] if i + 1 < len(text) and next_ok else ""
        options = [("substitution", 50), ("double", 8), ("insertion", 8)]
        if nxt and nxt not in " \n\t":
            options.append(("omission", 11))
        if nxt.isalpha() and ch.isalpha() and nxt.lower() != ch.lower():
            options.append(("transposition", 16))
        if ch.isupper() and nxt.isalpha() and nxt.islower():
            options.append(("caps", 12))
        total = sum(w for _, w in options)
        r = self.rng.uniform(0, total)
        for name, w in options:
            r -= w
            if r <= 0:
                return name
        return "substitution"

    def _make_typo(self, kind, text, i):
        """Returns (characters actually typed, source characters they stand for)."""
        ch = text[i]
        if kind == "transposition":
            return [text[i + 1], ch], 2
        if kind == "caps":
            return [ch, text[i + 1].upper()], 2   # "THe": shift held too long
        if kind == "omission":
            return [], 1
        if kind == "double":
            return [ch, ch], 1
        wrong = neighbor_typo(ch, self.rng)
        if wrong is None:
            return [ch, ch], 1
        if kind == "insertion":
            return ([wrong, ch] if self.rng.random() < 0.5 else [ch, wrong]), 1
        return [wrong], 1


def plan_text(text, settings, seed=None):
    return Planner(settings, seed).plan(text)


def plan_duration(actions):
    return sum(a.delay for a in actions)


def replay(actions, start=""):
    """What the screen would show after performing the actions on `start`."""
    out = list(start)
    for a in actions:
        if a.kind == "key":
            out.append(a.ch)
        elif a.kind == "back" and out:
            out.pop()
    return "".join(out)
