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

## Formatting (Google Docs)

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
- The shortcuts are Google Docs ones on macOS. In other apps, ⌘B/⌘I/⌘U usually still
  work, but headings, lists and sizes may not.

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

## Tests

```bash
python3 -m unittest discover tests
```

## Limitations

- Code editors that auto-close brackets or auto-indent will alter typed code.
- Focused-window mode types with a US QWERTY key layout. Other characters are sent as text.
