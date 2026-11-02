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
import json
import os
import queue
import random
import secrets
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import engine  # noqa: E402
import markup  # noqa: E402
import sinks  # noqa: E402
from app import Runner  # noqa: E402

from mcp.server.mcpserver import MCPServer  # noqa: E402
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
        "{size:18}…{/size}, # headings, - bullets, 1. numbered lists), which become Google Docs "
        "shortcuts; pass formatting=false to type them literally. Typing runs in the background "
        "and can take minutes: call typing_status to follow "
        "it, and pause_typing / resume_typing / stop_typing to control it. Only one text types at a time."
    ),
)


# ----------------------------------------------------------------- the job --

class Job:
    """The one text currently (or last) being typed."""

    def __init__(self, runner, actions, text, target):
        self.runner = runner
        self.events = runner.events
        self.total = len(actions)
        self.text_len = len(text)
        self.target = target
        self.planned_secs = engine.plan_duration(actions)
        self.started = time.monotonic()
        self.done_actions = 0
        self.pos = 0
        self.typos = 0
        self.status = "Starting…"
        self.finished = None   # reason once done

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

    def report(self):
        self.drain()
        elapsed = time.monotonic() - self.started
        state = ("finished" if self.finished else
                 "paused" if self.runner.paused.is_set() else "typing")
        return {
            "state": state,
            "status": self.status,
            "target": self.target,
            "characters_done": self.pos,
            "characters_total": self.text_len,
            "percent": round(100 * self.done_actions / max(1, self.total)),
            "typos_made": self.typos,
            "elapsed_seconds": round(elapsed),
            "estimated_total_seconds": round(self.planned_secs),
        }


_job = None
_lock = threading.Lock()


def _busy():
    if _job is None:
        return False
    _job.drain()
    return _job.finished is None


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
    list_browser_tabs; defaults to the open Google Doc, else the first tab).
    'focused_window' types into whichever app is in front once `countdown_seconds`
    is up; the user must click into it in time, and Esc stops it.
    preset: one of list_presets (default 'Average (60 wpm)'); wpm, typos_per_100_words,
    thinking (0-3) and leave_typos_share (0-1, typos left unfixed) override it.
    shift_enter: press Shift+Enter for new lines (chat boxes that send on Enter).
    formatting: turn marks like **bold**, *italic*, # Heading and - bullets into Google Docs
    shortcuts (default). Set false to type the marks as plain characters.
    """
    global _job
    with _lock:
        if _busy():
            raise ToolError("Already typing. Call stop_typing first, or typing_status to follow it.")
        if not text:
            raise ToolError("Nothing to type.")
        s = _settings(preset, wpm, typos_per_100_words, thinking, leave_typos_share)
        actions, plain = markup.plan(text, s, seed=random.randrange(1 << 30), formatting=formatting)
        events = queue.Queue()

        if target == "chrome_tab":
            tabs = sinks.list_tabs()
            if not tabs:
                raise ToolError("The typing browser has no tabs open. Call open_typing_browser first.")
            if tab_id:
                tab = next((t for t in tabs if t["id"] == tab_id), None)
                if not tab:
                    raise ToolError(f"No tab with id {tab_id!r}. Call list_browser_tabs.")
            else:
                tab = next((t for t in tabs if "docs.google.com/document/d/" in t.get("url", "")), tabs[0])
            ws = tab["webSocketDebuggerUrl"]
            runner = Runner(actions, lambda: sinks.ChromeSink(ws, shift_enter), events)
            label = f"Chrome tab: {tab.get('title') or tab.get('url')}"
        elif target == "focused_window":
            if not sinks.accessibility_trusted():
                raise ToolError(
                    "This app isn't allowed to control the keyboard. Allow it under System Settings › "
                    "Privacy & Security › Accessibility, restart it, and try again.")
            runner = _FocusedRunner(actions, events, shift_enter, max(0, countdown_seconds))
            label = "Focused window"
        else:
            raise ToolError("target must be 'chrome_tab' or 'focused_window'.")

        _job = Job(runner, actions, plain, label)
        runner.start()
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
def typing_status() -> dict:
    """Progress of the current (or last) typing job."""
    if _job is None:
        return {"state": "idle", "status": "Nothing has been typed yet."}
    return _job.report()


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
    elif args.http:
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
