# Human Typer

A small macOS app that types text out the way a person does: uneven rhythm,
typos that get noticed and fixed, pauses to think, and the occasional change
of mind.

## Features

**Rhythm**
- Each keystroke's timing varies at random.
- Common letter pairs ("th", "er", "in") roll out faster.
- Two keys on the same finger are slower; switching hands is quicker.
- Capitals, digits and symbols take longer, with Shift pressed as its own key.
- Each key is held for a realistic moment.
- Speed drifts up and down, and long texts slow down a little from fatigue.

**Typos**
- Neighboring-key slips, swapped letters, doubled or skipped letters, "THe"-style capitals.
- Some are caught right away, others a few letters later.
- Fixes use backspace, sometimes one too many, then retype a little more carefully.
- Optionally, a few typos are left in.

**Pauses**
- Short pauses after commas, longer ones after sentences and paragraphs.
- Hesitation before long words and occasional stops to think.
- Now and then a word is typed, deleted, and typed again.

**Controls**
- Five presets from *Hunt & peck* (25 wpm) to *Pro* (115 wpm), plus sliders.
- A live estimate of total time and overall speed.

## Where it can type

| Mode | Works with | Notes |
|---|---|---|
| **Background: Chrome tab** | Any web page in a dedicated Chrome window | Keeps typing while you use other apps. Uses its own Chrome profile, so you sign in once there. Don't minimize the window or click inside the page while it types. |
| **Focused window** | Any app | The target must stay in front. Switching apps pauses; switching back resumes. **Esc** or moving the mouse to the top-left corner stops it. Needs Accessibility permission. |
| **Preview** | A window inside the app | For trying out settings. |

Background mode needs Google Chrome, Microsoft Edge or Brave (not Safari or Arc).

## Formatting (Google Docs and Slides)

Mark up the text and Human Typer applies the formatting with Google Docs'
keyboard shortcuts while it types, pressing a shortcut and then typing like a person would.

| Mark | Result | Shortcut pressed |
|---|---|---|
| `**bold**` | **bold** | ⌘B |
| `*italic*` | *italic* | ⌘I |
| `__underline__` | underline | ⌘U |
| `~~strike~~` | ~~strike~~ | ⌘⇧X |
| `{size:18}text{/size}` | 18 pt text | ⌘⇧. / ⌘⇧, (once per size step) |
| `# Heading` … `###### Heading` | Heading 1–6 | ⌘⌥1 … ⌘⌥6 |
| `- item` | Bulleted list | ⌘⇧8 |
| `1. item` | Numbered list | ⌘⇧7 |

- The toolbar above the text box (B, I, U, S, Size, Paragraph) adds marks around the selection.
- **Paste formatted** turns rich text copied from Google Docs, Word or a web page into marks.
- A lone `*` between spaces (as in `5 * 3`) and a mark with no partner on the line are typed as-is. A backslash types a mark literally: `\*`, `\_`, `\~`, `\{`, `\#`.
- Uncheck **Apply formatting** to type the text exactly as written.
- Typos and their fixes never cross a formatting change, so nothing is retyped in the wrong style.
- Font sizes snap to Docs' size steps (8, 9, 10, 11, 12, 14, 18, 24, 30, 36, 48, 60, 72, 96).
- Start with the cursor in plain Normal text (11 pt, nothing toggled on). The app tracks
  formatting from there.
- The shortcuts are Google Docs ones on macOS. Google Slides uses the same ones for bold,
  italic, underline, strikethrough and lists, but not for headings, and its size steps
  are different. In other apps, ⌘B/⌘I/⌘U usually still work.

## Install

Requires macOS 12+.

### With Homebrew (recommended)

```bash
brew install dimitri-saha/tap/human-typer
human-typer setup
```

`human-typer setup` puts **Human Typer.app** in Applications and adds the
connector to Claude Desktop. You only run it once: `brew upgrade human-typer`
updates the app and the connector together. Other commands:
`human-typer connector` runs the connector, `human-typer check-update` checks
for an update now, and `human-typer version` prints the version.

### From the code

```bash
git clone https://github.com/dimitri-saha/human-typer.git
cd human-typer
./install.sh
```

The installer:

1. Finds Python 3.10+ with Tk (from [python.org](https://www.python.org/downloads/macos/)
   or Homebrew). If there isn't one and Homebrew is installed, it installs
   `python` and `python-tk` with Homebrew.
2. Installs the packages in their own environment in
   `~/Library/Application Support/Human Typer/venv`, apart from your other Python projects.
3. Builds **Human Typer.app** and puts it in `/Applications`.
4. Adds the connector to Claude Desktop, pointed at the installed app. Pass
   `--no-claude` to skip this step.

To update, run `git pull`, then `./install.sh` again.

To run without installing: `python3 -m pip install -r requirements.txt`, then
`python3 human_typer/app.py`.

### Updates

Once a day, the app and the connector check GitHub for a new release. When
there is one, a Mac notification tells you how to update. After updating, quit
Claude Desktop (⌘Q) and open it again.

For **Focused window** mode, allow Human Typer (or Python) under
System Settings › Privacy & Security › Accessibility, then reopen the app.

## Use it from Claude or ChatGPT

Human Typer comes with a **connector**, so you can ask an AI app to do the
typing for you, for example: *"Open my Google Doc in the typing browser and
type this essay at 45 wpm with a few typos."*

The connector is an [MCP](https://modelcontextprotocol.io) server in
`human_typer/mcp_server.py`. It gives the AI these tools:

| Tool | What it does |
|---|---|
| `open_typing_browser` | Opens Human Typer's Chrome window (or a new tab in it) at a web address. |
| `list_browser_tabs` | Lists the tabs in that window, so the AI can pick one. |
| `type_text` | Starts typing. Returns straight away; typing carries on in the background. |
| `typing_status` | Shows progress: how much is typed, typos made, time left. With `include_text`, it also shows exactly what was typed. |
| `wait_for_typing` | Waits until typing finishes, then reports. You also get a Mac notification when it's done. |
| `change_speed` | Changes the speed while typing, without stopping. |
| `pause_typing` / `resume_typing` / `stop_typing` | Controls the text being typed. |
| `continue_typing` | Finishes a stopped text with new settings. It deletes any half-fixed typo first. |
| `look_at_tab` | Takes a screenshot of the page, so the AI can check for typos and see where the text went. |
| `click_in_tab` | Clicks on the page, for example double-clicking a Google Slides text box to type in it. |

Formatting marks work in Google Docs. Bold, italic, underline, strikethrough and lists also work in Google Slides. Headings and `{size:N}` only work in Docs.
| `estimate_typing` | Says how long a text would take, without typing it. |
| `list_presets` | Lists the speed presets (25 to 115 wpm). |

Only one text types at a time.

A good way to ask: *"Look at the slide, double-click the text box under the
title, type this at 60 wpm, and look again when it's done to check for typos."*

### Before you start (all apps)

Installing (see [Install](#install)) sets up everything the connector needs.
The commands below use the installed copy. With Homebrew, use
`human-typer connector` in place of `"$HT_PY" "$HT_SERVER"`. With `./install.sh`, set:

```bash
HT_PY="$HOME/Library/Application Support/Human Typer/venv/bin/python3"
HT_SERVER="/Applications/Human Typer.app/Contents/Resources/mcp_server.py"
```

To check that it starts, run `"$HT_PY" "$HT_SERVER"`. It should print nothing and wait. Press Ctrl+C to quit.

If you run from source instead, use `python3` and `human_typer/mcp_server.py`.

### Claude Desktop

1. `human-typer setup` or `./install.sh` already added the connector. To add it by hand:

   ```bash
   "$HT_PY" "$HT_SERVER" --install-claude
   ```

   This adds a `human-typer` entry to
   `~/Library/Application Support/Claude/claude_desktop_config.json` and keeps
   anything already there.

2. Quit Claude Desktop completely (⌘Q) and open it again.
3. In a chat, open the tools menu and check that **human-typer** is listed and switched on.
4. *Optional:* to type into the app in front (**Focused window**), allow
   **Claude** under System Settings › Privacy & Security › Accessibility, then
   restart Claude.

### Claude Code

```bash
claude mcp add human-typer -- "$HT_PY" "$HT_SERVER"
```

Run `claude mcp list` to check that it connected.

### ChatGPT, or claude.ai on the web

These apps reach connectors over the internet, not on your Mac. So the
connector runs as a small web server, and a free tunnel gives it a public
HTTPS address.

1. **Start the connector's web server** and leave the Terminal window open:

   ```bash
   "$HT_PY" "$HT_SERVER" --http
   ```

   It prints a local address ending in a secret code, such as
   `http://127.0.0.1:8765/Q_qN…azG/mcp`. Copy the part from the `/` after the
   port to the end: `/Q_qN…azG/mcp`.

2. **Open a tunnel** in a second Terminal window and leave it open too:

   ```bash
   brew install cloudflared
   ```

   ```bash
   cloudflared tunnel --url http://127.0.0.1:8765
   ```

   It prints an address like `https://some-words.trycloudflare.com`.

3. **Put the two together.** Your connector URL is the tunnel address followed
   by the secret path:
   `https://some-words.trycloudflare.com/Q_qN…azG/mcp`

4. **Add it to the app.**
   - **ChatGPT** (paid plans; workspace plans may need an admin to allow it):
     open Settings and turn on **Developer mode**, under Apps & Connectors ›
     Advanced settings (on some accounts it's under Security). Then choose
     **Create**, give it a name such as *Human Typer*, paste the URL, choose
     **No authentication**, confirm that you trust it, and click Create. In a
     chat, open the **+** menu, choose Developer mode, and switch Human Typer on.
   - **claude.ai:** Settings › Connectors › **Add custom connector**, give it a
     name, paste the URL, and click Add. In a chat, switch it on in the tools menu.

**Keep in mind**

- The server and the tunnel must both keep running while you use the
  connector. A free `trycloudflare.com` address changes each time you start
  the tunnel, so you'll need to update the URL in the app.
- The secret part of the URL stays the same between runs. Anyone with the full
  URL can make your Mac type and see the pages open in the typing browser, so
  don't share it. To get a new one, delete
  `~/Library/Application Support/Human Typer/connector-token` and restart the server.
- ChatGPT may ask you to confirm each tool call before it runs. That's expected.

### Troubleshooting

- **The tools don't appear in Claude Desktop:** make sure you quit it with ⌘Q
  (closing the window isn't enough). Then check that the command at the top of
  this section runs without errors.
- **`ModuleNotFoundError: No module named 'mcp'`:** run `./install.sh` again. If
  you run from source, install the requirements with the same `python3` that runs the connector.
- **New tools are missing after an update:** run `brew upgrade human-typer` (or
  `./install.sh` again), then quit Claude Desktop with ⌘Q and reopen it.
- **`look_at_tab` fails:** the tab has to be the selected tab in its window, and
  the window can't be minimized.
- **"The typing browser isn't open":** ask the AI to open it first, or click
  *Open typing window* in the app.
- **Focused window mode refuses to start:** the app running the connector
  (Claude, or Terminal for `--http`) needs Accessibility permission.

## Working on the code

See [HANDOFF.md](HANDOFF.md) for how the pieces fit together, and how to
publish a release with `./release.sh`.

## Tests

```bash
python3 -m unittest discover tests
```

## Limitations

- Code editors that auto-close brackets or auto-indent will alter typed code.
- Focused-window mode types with a US QWERTY key layout. Other characters are sent as text.
