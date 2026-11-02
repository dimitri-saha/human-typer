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

## Install

Requires macOS 12+ and Python 3 from [python.org](https://www.python.org/downloads/macos/)
(it includes Tk).

```bash
python3 -m pip install -r requirements.txt
./build_app.sh --install
```

This puts **Human Typer.app** in `/Applications`. To run from source instead:
`python3 human_typer/app.py`.

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
| `typing_status` | Shows progress: how much is typed, typos made, time left. |
| `pause_typing` / `resume_typing` / `stop_typing` | Controls the text being typed. |
| `estimate_typing` | Says how long a text would take, without typing it. |
| `list_presets` | Lists the speed presets (25 to 115 wpm). |

Only one text types at a time.

### Before you start (all apps)

1. Install Human Typer's requirements (see [Install](#install)). The connector
   also needs the `mcp` package, which is in `requirements.txt`, and Python 3.10 or newer:

   ```bash
   python3 -m pip install -r requirements.txt
   ```

2. Check that it starts. This should print nothing and wait; press Ctrl+C to quit:

   ```bash
   python3 human_typer/mcp_server.py
   ```

Run every command below from the `human-typer` folder.

### Claude Desktop

1. Add the connector to Claude Desktop's settings:

   ```bash
   python3 human_typer/mcp_server.py --install-claude
   ```

   This adds a `human-typer` entry to
   `~/Library/Application Support/Claude/claude_desktop_config.json` and keeps
   anything already there. It saves the full path to the connector, so run it
   again if you move the `human-typer` folder.

2. Quit Claude Desktop completely (⌘Q) and open it again.
3. In a chat, open the tools menu and check that **human-typer** is listed and switched on.
4. *Optional:* to type into the app in front (**Focused window**), allow
   **Claude** under System Settings › Privacy & Security › Accessibility, then
   restart Claude.

### Claude Code

```bash
claude mcp add human-typer -- python3 "$PWD/human_typer/mcp_server.py"
```

Run `claude mcp list` to check that it connected.

### ChatGPT, or claude.ai on the web

These apps reach connectors over the internet, not on your Mac. So the
connector runs as a small web server, and a free tunnel gives it a public
HTTPS address.

1. **Start the connector's web server** and leave the Terminal window open:

   ```bash
   python3 human_typer/mcp_server.py --http
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
  URL can make your Mac type, so don't share it. To get a new one, delete
  `~/Library/Application Support/Human Typer/connector-token` and restart the server.
- ChatGPT may ask you to confirm each tool call before it runs. That's expected.

### Troubleshooting

- **The tools don't appear in Claude Desktop:** make sure you quit it with ⌘Q
  (closing the window isn't enough). Then check that the command at the top of
  this section runs without errors.
- **`ModuleNotFoundError: No module named 'mcp'`:** install the requirements
  with the same `python3` you use to run the connector.
- **"The typing browser isn't open":** ask the AI to open it first, or click
  *Open typing window* in the app.
- **Focused window mode refuses to start:** the app running the connector
  (Claude, or Terminal for `--http`) needs Accessibility permission.

## Tests

```bash
python3 -m unittest discover tests
```

## Limitations

- Code editors that auto-close brackets or auto-indent will alter typed code.
- Focused-window mode types with a US QWERTY key layout. Other characters are sent as text.
