# Handoff notes

What you need to know to keep working on Human Typer. The README covers using it.

## Layout

| File | What's in it |
|---|---|
| `human_typer/engine.py` | Plans keystrokes: timing, typos and fixes, pauses. Its output is a list of `Action`s (`key`, `back`, `combo`), each with a delay and `pos` (how many source characters are done). `replay()` shows what the actions leave on screen. |
| `human_typer/markup.py` | Formatting marks → Google Docs shortcuts. `DocsState` models what the editor applies next. `format_points(doc, start, state)` says which shortcuts to press before each character. |
| `human_typer/sinks.py` | Where keys go: `QuartzSink` (the focused window), `ChromeSink` (a background Chrome tab over DevTools, which also does `screenshot()` and `click()`), and `PreviewSink`. |
| `human_typer/app.py` | The Tk app, and `Runner`, the thread that plays actions into a sink. `Runner.scale` multiplies every delay, so speed can change live. |
| `human_typer/mcp_server.py` | The Claude/ChatGPT connector (an MCP server). `Job` follows one typing run. |
| `install.sh` | The one-step install: a venv in `~/Library/Application Support/Human Typer/venv`, the app in `/Applications`, and the Claude Desktop config. |
| `human_typer/update.py` | `VERSION`, and the once-a-day check against GitHub's latest release that sends the "update available" notification. The app and the connector both call it at startup. |
| `build_app.sh` | Builds `dist/Human Typer.app`, which is a zsh launcher plus the `.py` files. It doesn't bundle Python. With `HT_CODE`/`HT_PYTHON` set, the launcher runs code at those paths instead (Homebrew uses this). |
| `release.sh` | Publishes a version (see below). |

## Installs and releases

- There are two ways to install:
  - **Homebrew:** the formula is `Formula/human-typer.rb` in
    [dimitri-saha/homebrew-tap](https://github.com/dimitri-saha/homebrew-tap). It
    builds a venv in `libexec`. The app and the Claude config point at
    `$(brew --prefix)/opt/human-typer/...`, which follows upgrades, so
    `human-typer setup` only ever runs once.
  - **`./install.sh`:** copies the code into `/Applications/Human Typer.app`.
- Claude Desktop runs the installed copy, not this folder. To try a change
  locally, run `./install.sh` and restart Claude Desktop (⌘Q).
- **To release:** commit your changes, then run `./release.sh 1.2.0`. It runs
  the tests, sets `VERSION`, tags and pushes, updates the tap's URL and sha256,
  and publishes the GitHub release last. Publishing the release is what makes
  users' apps show the update notification, so a version that hasn't been
  released isn't announced. Release when a batch of commits is worth updating
  for, not after every commit.
- The formula uses Python 3.14 on purpose. When the newest Python has
  ready-built wheels for pyobjc and pydantic-core, the pin can move up.

## Connector

- The tool descriptions and the `instructions=` text in `mcp_server.py` are all
  the AI knows about the tools. If a feature isn't described there, the AI won't
  use it. That's why underline in Slides looked impossible before.
- `continue_typing` relies on `Job.resume_point()`. It replays the keystrokes
  that were sent and backs up to the last character that landed where it
  belongs, so a half-fixed typo gets deleted first. It also replays the
  shortcuts that were pressed, so formatting carries on. For example, if typing
  stopped inside bold text, it doesn't press ⌘B again.
  `test_continuation_from_every_stop_point` stops at every keystroke and checks this.
- When a job ends, a thread posts a macOS notification. Tests replace `_notify` with a no-op.

## Testing

```bash
python3 -m unittest discover -s tests
```

The connector tests use a fake Chrome tab, so they don't need a browser.
`look_at_tab` and `click_in_tab` need a real typing browser. To check them,
run `open_typing_browser`, open a page, and call them. Don't click in a real
document.

## Known gaps

- Font sizes in Google Slides follow Docs' size steps, so `{size:N}` may land on the wrong size in Slides.
- `look_at_tab` only works on the selected tab in a window that isn't minimized.
- `typing_status(include_text=true)` shows only what Human Typer typed, not what was on the page before.
- With `leave_typos_share` > 0, `continue_typing` can, rarely, retype one character next to a typo that was left in on purpose.
- The update check uses GitHub's API without signing in, which allows 60 requests an hour per IP address. That's plenty for a check once a day.
