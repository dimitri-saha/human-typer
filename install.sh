#!/bin/zsh
# Installs or updates Human Typer in one step:
#   - Python packages in their own environment (no clash with your other Python setup)
#   - Human Typer.app in /Applications
#   - the Claude Desktop connector, pointed at the installed app
#
#   ./install.sh               install, or update after pulling new code
#   ./install.sh --no-claude   leave Claude Desktop's settings alone
set -euo pipefail
cd "$(dirname "$0")"

SUPPORT="$HOME/Library/Application Support/Human Typer"
VENV="$SUPPORT/venv"
APP="/Applications/Human Typer.app"

# A Python 3.10+ that has Tk (the app's window toolkit).
good_python() { "$1" -c 'import sys, tkinter; assert sys.version_info >= (3, 10)' 2>/dev/null; }
PY=""
for cand in /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
            /opt/homebrew/bin/python3 /usr/local/bin/python3 "$(command -v python3 || true)"; do
  if [[ -n "$cand" && -x "$cand" ]] && good_python "$cand"; then PY="$cand"; break; fi
done
if [[ -z "$PY" ]]; then
  if command -v brew >/dev/null; then
    echo "Installing Python with Homebrew…"
    brew install python python-tk
    PY="$(brew --prefix)/bin/python3"
  else
    echo "Human Typer needs Python 3.10 or newer. Install it from" \
         "https://www.python.org/downloads/macos/ and run this again." >&2
    exit 1
  fi
fi

echo "Setting up Python packages…"
mkdir -p "$SUPPORT"
if ! good_python "$VENV/bin/python3"; then
  rm -rf "$VENV"
  "$PY" -m venv "$VENV"
fi
"$VENV/bin/python3" -m pip install -q --upgrade pip
"$VENV/bin/python3" -m pip install -q -r requirements.txt

echo "Building the app…"
PYTHON="$VENV/bin/python3" ./build_app.sh --install

if [[ "${1:-}" != "--no-claude" ]]; then
  "$VENV/bin/python3" "$APP/Contents/Resources/mcp_server.py" --install-claude
fi

cat <<EOF

Done. Open Human Typer from Applications or Spotlight.
- Claude Desktop: quit it with Cmd+Q and reopen it to load the connector.
- Focused window mode: allow Human Typer under System Settings › Privacy & Security › Accessibility.
To update later, get the new code and run ./install.sh again.
EOF
