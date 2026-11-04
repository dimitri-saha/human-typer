#!/bin/zsh
# Builds dist/Human Typer.app. Pass --install to also copy it to /Applications.
# Most people want ./install.sh, which also sets up Python and the connector.
# HT_CODE=<folder with app.py> HT_PYTHON=<python> makes the app run that code (Homebrew uses it).
set -euo pipefail
cd "$(dirname "$0")"

APP="dist/Human Typer.app"
VERSION="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' human_typer/update.py)"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cp human_typer/*.py "$APP/Contents/Resources/"
"${PYTHON:-python3}" tools/make_icon.py "$APP/Contents/Resources/AppIcon.icns"

cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Human Typer</string>
  <key>CFBundleDisplayName</key><string>Human Typer</string>
  <key>CFBundleIdentifier</key><string>io.github.dimitri-saha.human-typer</string>
  <key>CFBundleExecutable</key><string>HumanTyper</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
EOF

# Apps opened from Finder don't get your shell's PATH, so look for a Python
# that has everything Human Typer needs.
cat > "$APP/Contents/MacOS/HumanTyper" <<'EOF'
#!/bin/zsh
HERE="$(cd "$(dirname "$0")/../Resources" && pwd)"
for PY in "$HOME/Library/Application Support/Human Typer/venv/bin/python3" \
          /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
          /Library/Frameworks/Python.framework/Versions/3.*/bin/python3(N) \
          /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  [[ -x "$PY" ]] || continue
  if "$PY" -c "import tkinter, Quartz, AppKit, websockets" 2>/dev/null; then
    exec "$PY" "$HERE/app.py"
  fi
done
osascript -e 'display alert "Human Typer needs Python 3 with a few packages" message "Run ./install.sh from the human-typer folder in Terminal." as critical'
exit 1
EOF
chmod +x "$APP/Contents/MacOS/HumanTyper"

# Homebrew: run the code and Python at fixed paths that survive `brew upgrade`.
if [[ -n "${HT_CODE:-}" ]]; then
  printf '#!/bin/zsh\nexec "%s" "%s/app.py"\n' "$HT_PYTHON" "$HT_CODE" > "$APP/Contents/MacOS/HumanTyper"
fi

echo "Built $APP"
if [[ "${1:-}" == "--install" ]]; then
  rm -rf /Applications/"Human Typer.app"
  cp -R "$APP" /Applications/
  echo "Installed to /Applications/Human Typer.app"
fi
