"""Human Typer connector: lets Claude, ChatGPT and other AI apps type through Human Typer.

It is an MCP server. With no arguments it talks over stdio, which is what Claude
Desktop and Claude Code use. With --http it serves Streamable HTTP for remote
connectors (ChatGPT, claude.ai); the URL contains a secret token, so only
someone who has the URL can make it type.

    python3 mcp_server.py                     # stdio (Claude Desktop / Claude Code)
    python3 mcp_server.py --http              # http://127.0.0.1:8765/<token>/mcp
    python3 mcp_server.py --install-claude    # add it to Claude Desktop's config
"""
import argparse
import asyncio
import json
import os
import queue
import random
import secrets
import sys
import threading
import time
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import engine  # noqa: E402
import markup  # noqa: E402
import sinks  # noqa: E402
import update  # noqa: E402
from app import Runner  # noqa: E402

from mcp.server.mcpserver import Image, MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402
from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402

SUPPORT_DIR = os.path.expanduser("~/Library/Application Support/Human Typer")
TOKEN_FILE = os.path.join(SUPPORT_DIR, "connector-token")
CLAUDE_CONFIG = os.path.expanduser("~/Library/Application Support/Claude/claude_desktop_config.json")
DEFAULT_PRESET = "Average (60 wpm)"

mcp = MCPServer(
    "Human Typer",
    instructions=(
        "Human Typer types text out like a person: uneven rhythm, typos that get fixed, pauses. "
        "To type into a web page, call open_typing_browser (the user signs in and opens the page "
        "in that window), then list_browser_tabs, then type_text with target='chrome_tab' and the "
        "tab_id. Text may use formatting marks (**bold**, *italic*, __underline__, ~~strike~~, "
        "{size:18}…{/size}, # headings, - bullets, 1. numbered lists), which become keyboard "
        "shortcuts; bold, italic, underline, strike and lists also work in Google Slides, headings "
        "and sizes only in Google Docs. Pass formatting=false to type marks literally. It types where "
        "the page's cursor is: use look_at_tab to see the page and click_in_tab to put the cursor in "
        "place (in Slides, double-click a text box). Typing runs in the background and can take "
        "minutes: wait_for_typing waits until it's done, typing_status reports progress "
        "(include_text=true shows exactly what was typed). change_speed changes speed mid-job; "
        "pause_typing / resume_typing / stop_typing control it, and continue_typing finishes a "
        "stopped text with new settings. After typing, look_at_tab to check the result. "
        "Only one text types at a time."
    ),
)


# ----------------------------------------------------------------- the job --

class Job:
    """The text currently (or last) being typed, and what's needed to finish it later."""

    def __init__(self, runner, actions, plain, doc, target, wpm, start=None):
        self.runner = runner
        self.events = runner.events
        self.actions = actions
        self.total = len(actions)
        self.plain = plain         # the whole text, without marks
        self.doc = doc             # parsed marks, or None when formatting is off
        self.target = target       # (label, make_runner(actions, events))
        self.wpm = wpm             # speed the actions were planned at
        # Where an earlier stopped job left off: screen text, clean prefix length,
        # source position, editor formatting state.
        self.start_screen, self.start_clean, self.start_pos, self.start_state = (
            start or ("", 0, 0, markup.DocsState()))
        self.started = time.monotonic()
        self.done_actions = 0
        self.pos = self.start_pos
        self.typos = 0
        self.status = "Starting…"
        self.finished = None   # reason once done
        self.cursor_moved = False  # click_in_tab ran after this job

    def drain(self):
        while True:
            try:
                ev = self.events.get_nowait()
            except queue.Empty:
                return
            if ev[0] == "status":
                self.status = ev[1]
            elif ev[0] == "progress":
                _, self.done_actions, self.pos, tag = ev
                self.typos += tag == "typo"
            elif ev[0] == "done":
                self.finished = ev[1]
                self.status = ev[1]

    def screen(self):
        """What these keystrokes have left on screen, typos still waiting for a fix included."""
        self.drain()
        return engine.replay(self.actions[:self.done_actions], self.start_screen)

    def resume_point(self):
        """(backspaces, source position, formatting state) to finish the text from here.

        Backs up to the last character that landed where it belongs, so a typo
        that wasn't fixed yet when typing stopped gets deleted.
        """
        done = self.actions[:self.done_actions]
        typed = self.screen()
        screen, good = [], []   # good[i]: screen[:i + 1] matches what's typed
        clean, pos = self.start_clean, self.start_pos
        state = replace(self.start_state)

        def push(c):
            i = len(screen)
            good.append((not good or good[-1]) and i < len(typed) and typed[i] == c)
            screen.append(c)

        for c in self.start_screen:
            push(c)
        for a in done:
            if a.kind == "combo":
                state.apply(a.ch)
            elif a.kind == "back":
                if screen:
                    screen.pop()
                    good.pop()
            else:
                push(a.ch)
                if a.ch == "\n":
                    state.newline()
                if good[-1] and a.pos > 0 and self.plain[a.pos - 1] == a.ch:
                    clean, pos = len(screen), a.pos
        return len(typed) - clean, pos, state

    def continuation(self, settings, seed=None):
        """(actions, start) that finish the text from where it stopped, or None if it's done."""
        back, pos, state = self.resume_point()
        if back == 0 and pos >= len(self.plain):
            return None
        rest = self.plain[pos:]
        if self.doc:
            acts = engine.Planner(settings, seed).plan(rest, markup.format_points(self.doc, pos, state))
        else:
            acts = engine.plan_text(rest, settings, seed)
        backs = [engine.Action("back", "", 0.6 if k == 0 else 0.11, pos, "fix") for k in range(back)]
        typed = self.screen()
        return (backs + [replace(a, pos=a.pos + pos) for a in acts],
                (typed, len(typed) - back, pos, state))

    def report(self, include_text=False):
        self.drain()
        elapsed = time.monotonic() - self.started
        state = ("finished" if self.finished else
                 "paused" if self.runner.paused.is_set() else "typing")
        left = 0 if self.finished else (
            sum(a.delay for a in self.actions[self.done_actions:]) * self.runner.scale)
        out = {
            "state": state,
            "status": self.status,
            "target": self.target[0],
            "wpm": round(self.wpm / self.runner.scale),
            "characters_done": self.pos,
            "characters_total": len(self.plain),
            "percent": round(100 * self.pos / max(1, len(self.plain))),
            "typos_made": self.typos,
            "elapsed_seconds": round(elapsed),
            "seconds_left": round(left),
        }
        if include_text:
            out["typed_text"] = self.screen()
        return out


_job = None
_lock = threading.Lock()


def _busy():
    if _job is None:
        return False
    _job.drain()
    return _job.finished is None


_notify = update.notify   # tests swap this out


def _watch(job):
    job.runner.join()
    job.drain()
    try:
        _notify(f"{job.status} ({job.pos} of {len(job.plain)} characters)")
    except Exception:
        pass


def _start(actions, start, plain, doc, target, wpm):
    global _job
    runner = target[1](actions, queue.Queue())
    _job = Job(runner, actions, plain, doc, target, wpm, start)
    runner.start()
    threading.Thread(target=_watch, args=(_job,), daemon=True).start()
    return _job.report()


def _find_tab(tab_id):
    tabs = sinks.list_tabs()
    if not tabs:
        raise ToolError("The typing browser has no tabs open. Call open_typing_browser first.")
    if tab_id:
        tab = next((t for t in tabs if t["id"] == tab_id), None)
        if not tab:
            raise ToolError(f"No tab with id {tab_id!r}. Call list_browser_tabs.")
        return tab
    google = ("docs.google.com/document/d/", "docs.google.com/presentation/d/")
    return next((t for t in tabs if any(g in t.get("url", "") for g in google)), tabs[0])


def _label(tab):
    return f"Chrome tab: {tab.get('title') or tab.get('url')}"


def _settings(preset, wpm, typos_per_100_words, thinking, leave_typos_share):
    if preset and preset not in engine.PRESETS:
        raise ToolError(f"Unknown preset {preset!r}. Choose one of: {', '.join(engine.PRESETS)}")
    s = engine.Settings(**engine.PRESETS[preset or DEFAULT_PRESET])
    if wpm is not None:
        s.wpm = max(10.0, min(200.0, wpm))
    if typos_per_100_words is not None:
        s.typos_per_100_words = max(0.0, min(20.0, typos_per_100_words))
    if thinking is not None:
        s.thinking = max(0.0, min(3.0, thinking))
    if leave_typos_share is not None:
        s.unfixed_typo_share = max(0.0, min(1.0, leave_typos_share))
    return s


def _focused_guard(pid, name):
    def guard():
        if sinks.esc_held():
            return ("stop", "Stopped (Esc)")
        if sinks.mouse_in_corner():
            return ("stop", "Stopped (mouse in corner)")
        if sinks.frontmost_app()[0] != pid:
            return ("hold", f"Paused: switch back to {name} to continue")
        return None
    return guard


# ------------------------------------------------------------------- tools --

@mcp.tool()
def list_presets() -> dict:
    """The typing speed presets, from 'Hunt & peck (25 wpm)' to 'Pro (115 wpm)', with their settings."""
    return {"default": DEFAULT_PRESET, "presets": engine.PRESETS}


@mcp.tool()
def estimate_typing(text: str, preset: str | None = None, wpm: float | None = None,
                    typos_per_100_words: float | None = None, thinking: float | None = None,
                    formatting: bool = True) -> dict:
    """How long typing `text` would take with these settings, without typing anything."""
    s = _settings(preset, wpm, typos_per_100_words, thinking, None)
    actions, plain = markup.plan(text, s, seed=random.randrange(1 << 30), formatting=formatting)
    secs = engine.plan_duration(actions)
    words = len(plain.split())
    return {
        "seconds": round(secs),
        "overall_wpm": round(words / (secs / 60)) if secs else 0,
        "keystrokes": len(actions),
        "typos_planned": sum(a.tag == "typo" for a in actions),
    }


@mcp.tool()
def open_typing_browser(url: str = "https://docs.google.com/document/u/0/") -> str:
    """Opens Human Typer's own Chrome window (or a new tab in it) at `url`.

    Text can be typed into its tabs in the background. It uses a separate Chrome
    profile, so the user signs in there once.
    """
    try:
        sinks.launch_typing_browser(url)
    except RuntimeError as e:
        raise ToolError(str(e)) from e
    return ("Opened. Ask the user to sign in if needed and open the page to type into, "
            "then call list_browser_tabs.")


@mcp.tool()
def list_browser_tabs() -> list[dict]:
    """Tabs open in the typing browser. Pass a tab's `id` to type_text."""
    tabs = sinks.list_tabs()
    if tabs is None:
        raise ToolError("The typing browser isn't open. Call open_typing_browser first.")
    return [{"id": t["id"], "title": t.get("title", ""), "url": t.get("url", "")} for t in tabs]


@mcp.tool()
def type_text(text: str, target: str = "chrome_tab", tab_id: str | None = None,
              preset: str | None = None, wpm: float | None = None,
              typos_per_100_words: float | None = None, thinking: float | None = None,
              leave_typos_share: float | None = None, shift_enter: bool = False,
              formatting: bool = True, countdown_seconds: int = 5) -> dict:
    """Starts typing `text` like a person and returns at once; typing continues in the background.

    target: 'chrome_tab' types into a tab of the typing browser (tab_id from
    list_browser_tabs; defaults to the open Google Doc or Slides, else the first tab).
    It types where that page's cursor is: in Google Slides, put the cursor in a text
    box first with click_in_tab.
    'focused_window' types into whichever app is in front once `countdown_seconds`
    is up; the user must click into it in time, and Esc stops it.
    preset: one of list_presets (default 'Average (60 wpm)'); wpm, typos_per_100_words,
    thinking (0-3) and leave_typos_share (0-1, typos left unfixed) override it.
    shift_enter: press Shift+Enter for new lines (chat boxes that send on Enter).
    formatting: turn marks into shortcuts (default). **bold**, *italic*, __underline__,
    ~~strike~~ and - / 1. lists work in Google Docs and Slides; # headings and {size:N}
    are Google Docs only. Set false to type the marks as plain characters.
    """
    with _lock:
        if _busy():
            raise ToolError("Already typing. Call stop_typing first, or typing_status to follow it.")
        if not text:
            raise ToolError("Nothing to type.")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        s = _settings(preset, wpm, typos_per_100_words, thinking, leave_typos_share)
        seed = random.randrange(1 << 30)
        doc = markup.parse(text) if formatting else None
        if doc:
            actions, plain = engine.Planner(s, seed).plan(doc.text, markup.format_points(doc)), doc.text
        else:
            actions, plain = engine.plan_text(text, s, seed), text

        if target == "chrome_tab":
            tab = _find_tab(tab_id)
            ws = tab["webSocketDebuggerUrl"]
            make = lambda acts, ev: Runner(acts, lambda: sinks.ChromeSink(ws, shift_enter), ev)  # noqa: E731
            dest = (_label(tab), make)
        elif target == "focused_window":
            if not sinks.accessibility_trusted():
                raise ToolError(
                    "This app isn't allowed to control the keyboard. Allow it under System Settings › "
                    "Privacy & Security › Accessibility, restart it, and try again.")
            countdown = max(0, countdown_seconds)
            dest = ("Focused window",
                    lambda acts, ev: _FocusedRunner(acts, ev, shift_enter, countdown))
        else:
            raise ToolError("target must be 'chrome_tab' or 'focused_window'.")
        return _start(actions, None, plain, doc, dest, s.wpm)


@mcp.tool()
def continue_typing(preset: str | None = None, wpm: float | None = None,
                    typos_per_100_words: float | None = None, thinking: float | None = None,
                    leave_typos_share: float | None = None) -> dict:
    """Types the rest of the last stopped text into the same place, with new settings.

    It first deletes anything left half-typed (a typo not fixed yet), then carries on
    from the last character that landed right, keeping the formatting it was in.
    Settings work as in type_text. To only change speed while typing, use change_speed.
    It types at the page's cursor. After click_in_tab it carries on there, but refuses
    if it would first have to delete a half-typed typo (that would hit the wrong text).
    """
    with _lock:
        if _job is None:
            raise ToolError("Nothing has been typed yet.")
        if _busy():
            raise ToolError("Still typing. Use change_speed, or stop_typing first.")
        s = _settings(preset, wpm, typos_per_100_words, thinking, leave_typos_share)
        if _job.cursor_moved and _job.resume_point()[0]:
            raise ToolError(
                "Typing stopped halfway through a typo, and the cursor has moved since, so the "
                "fix would delete the wrong text. Put the cursor right after the typed text "
                "(click_in_tab), then call type_text with the rest instead.")
        rest = _job.continuation(s, random.randrange(1 << 30))
        if rest is None:
            raise ToolError("The last text was typed in full; there's nothing left.")
        return _start(*rest, _job.plain, _job.doc, _job.target, s.wpm)


@mcp.tool()
def change_speed(wpm: float) -> dict:
    """Changes the speed of the text being typed right now, without stopping it (10-200 wpm)."""
    if not _busy():
        raise ToolError("Nothing is typing. Pass the speed to type_text or continue_typing instead.")
    _job.runner.scale = _job.wpm / max(10.0, min(200.0, wpm))
    return _job.report()


class _FocusedRunner(Runner):
    """Waits out a countdown, then types into whatever app is in front at that moment."""

    def __init__(self, actions, events, shift_enter, countdown):
        super().__init__(actions, lambda: sinks.QuartzSink(shift_enter), events)
        self.countdown = countdown

    def run(self):
        for n in range(self.countdown, 0, -1):
            self.events.put(("status", f"Click into the window to type in… {n}"))
            if not self._wait(1.0):
                self.events.put(("done", "Stopped"))
                return
        pid, name = sinks.frontmost_app()
        self.events.put(("status", f"Typing into {name}…"))
        self.guard = _focused_guard(pid, name)
        super().run()


@mcp.tool()
def typing_status(include_text: bool = False) -> dict:
    """Progress of the current (or last) typing job.

    include_text: also return `typed_text`, exactly what the keystrokes have left on
    screen so far (typos not yet fixed included). It covers only what Human Typer
    typed, not what was in the page before; use look_at_tab to see the page itself.
    """
    if _job is None:
        return {"state": "idle", "status": "Nothing has been typed yet."}
    return _job.report(include_text)


@mcp.tool()
async def wait_for_typing(max_seconds: float = 55) -> dict:
    """Waits until the typing job finishes (or `max_seconds` pass, up to 600), then reports.

    Use it instead of polling typing_status. If it's still typing, call it again.
    """
    end = time.monotonic() + max(0.0, min(600.0, max_seconds))
    while _busy() and time.monotonic() < end:
        await asyncio.sleep(0.25)
    return typing_status()


@mcp.tool()
def look_at_tab(tab_id: str | None = None) -> list:
    """A screenshot of a typing-browser tab, to check the page: leftover typos, where text landed.

    Image pixels are the page coordinates click_in_tab takes. tab_id defaults like type_text.
    """
    tab = _find_tab(tab_id)
    try:
        sink = sinks.ChromeSink(tab["webSocketDebuggerUrl"])
        try:
            data, w, h = sink.screenshot()
        finally:
            sink.close()
    except Exception as e:
        raise ToolError(f"Couldn't take a screenshot of the tab ({e}). "
                        "It has to be the selected tab in its window.") from e
    return [Image(data=data, format="jpeg"), f"{_label(tab)}, {w}x{h} page pixels."]


@mcp.tool()
def click_in_tab(x: float, y: float, tab_id: str | None = None, clicks: int = 1) -> str:
    """Clicks at (x, y) in a typing-browser tab, in look_at_tab's image pixels.

    Use it to put the cursor where type_text should type. In Google Slides,
    double-click (clicks=2) inside a text box to start editing it; clicks=3 selects
    a paragraph. Then call look_at_tab to check the cursor is where you want it.
    """
    if _busy():
        raise ToolError("Typing is running. Wait for it (or stop it) before clicking.")
    tab = _find_tab(tab_id)
    if _job:
        _job.cursor_moved = True
    try:
        sink = sinks.ChromeSink(tab["webSocketDebuggerUrl"])
        try:
            sink.click(x, y, max(1, min(3, clicks)))
        finally:
            sink.close()
    except Exception as e:
        raise ToolError(f"Couldn't click in the tab ({e}).") from e
    return f"Clicked {clicks}x at ({x:g}, {y:g}) in {_label(tab)}."


@mcp.tool()
def pause_typing() -> dict:
    """Pauses the current typing job."""
    if not _busy():
        raise ToolError("Nothing is typing.")
    _job.runner.paused.set()
    return _job.report()


@mcp.tool()
def resume_typing() -> dict:
    """Resumes a paused typing job."""
    if not _busy():
        raise ToolError("Nothing is typing.")
    _job.runner.paused.clear()
    return _job.report()


@mcp.tool()
def stop_typing() -> dict:
    """Stops the current typing job. What was typed so far stays."""
    if not _busy():
        raise ToolError("Nothing is typing.")
    _job.runner.stop_flag.set()
    _job.runner.join(timeout=3)
    return _job.report()


# ------------------------------------------------------------------- setup --

def connector_token():
    """A random secret kept between runs, so the connector URL stays the same."""
    try:
        with open(TOKEN_FILE) as f:
            token = f.read().strip()
        if token:
            return token
    except FileNotFoundError:
        pass
    os.makedirs(SUPPORT_DIR, exist_ok=True)
    token = secrets.token_urlsafe(24)
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token)
    return token


def install_claude_desktop():
    config = {}
    if os.path.exists(CLAUDE_CONFIG):
        with open(CLAUDE_CONFIG) as f:
            config = json.load(f)
    config.setdefault("mcpServers", {})["human-typer"] = {
        "command": sys.executable,
        "args": [os.path.abspath(__file__)],
    }
    os.makedirs(os.path.dirname(CLAUDE_CONFIG), exist_ok=True)
    with open(CLAUDE_CONFIG, "w") as f:
        json.dump(config, f, indent=2)
    print(f"Added Human Typer to {CLAUDE_CONFIG}. Quit and reopen Claude Desktop to use it.")


def main():
    p = argparse.ArgumentParser(description="Human Typer connector (MCP server) for Claude and ChatGPT.")
    p.add_argument("--http", action="store_true", help="serve Streamable HTTP for remote connectors")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--install-claude", action="store_true", help="add this server to Claude Desktop")
    args = p.parse_args()

    if args.install_claude:
        install_claude_desktop()
        return
    update.check_in_background()
    if args.http:
        path = f"/{connector_token()}/mcp"
        print(f"Human Typer connector at http://127.0.0.1:{args.port}{path}\n"
              f"Expose it with:  cloudflared tunnel --url http://127.0.0.1:{args.port}\n"
              f"then give ChatGPT  https://<tunnel-host>{path}", file=sys.stderr)
        # The secret path is the protection; tunnels send their own Host header.
        mcp.run("streamable-http", host="127.0.0.1", port=args.port, streamable_http_path=path,
                transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
    else:
        mcp.run("stdio")


if __name__ == "__main__":
    main()
