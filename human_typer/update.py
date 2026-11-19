"""Version number, and a once-a-day check for a newer release on GitHub."""
import json
import os
import shutil
import subprocess
import threading
import time
import urllib.request

VERSION = "1.2.1"
REPO = "dimitri-saha/human-typer"
STAMP = os.path.expanduser("~/Library/Application Support/Human Typer/last-update-check")


def notify(message, title="Human Typer"):
    """A macOS notification."""
    script = (f"display notification {json.dumps(message, ensure_ascii=False)} "
              f"with title {json.dumps(title, ensure_ascii=False)}")
    subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)


def newer(latest, current=VERSION):
    """True if version `latest` ("1.2.0" or "v1.2.0") is above `current`."""
    def parts(v):
        return tuple(int(p) for p in v.lstrip("v").split("."))
    try:
        return parts(latest) > parts(current)
    except ValueError:
        return False


def latest_release():
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/releases/latest",
                                 headers={"Accept": "application/vnd.github+json",
                                          "User-Agent": "human-typer-update-check"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)["tag_name"]


def is_brew():
    return "/Cellar/" in os.path.realpath(__file__)


def how_to_update():
    return "brew upgrade human-typer" if is_brew() else "git pull, then ./install.sh"


def brew_upgrade():
    """Runs `brew upgrade human-typer`. Returns (ok, output)."""
    # Apps opened from Finder don't get the shell's PATH, so look in brew's usual places too.
    brew = shutil.which("brew") or next(
        (p for p in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew") if os.path.exists(p)), None)
    if not brew:
        return False, "Homebrew wasn't found."
    r = subprocess.run([brew, "upgrade", "human-typer"], capture_output=True, text=True, timeout=900)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def check(force=False, on_newer=None):
    """Notifies if a newer release is out, and calls on_newer(tag). Checks GitHub at most once a day."""
    try:
        if not force and time.time() - os.path.getmtime(STAMP) < 86400:
            return
    except OSError:
        pass
    try:
        os.makedirs(os.path.dirname(STAMP), exist_ok=True)
        with open(STAMP, "w"):
            pass
        tag = latest_release()
        if newer(tag):
            notify(f"Version {tag.lstrip('v')} is out (you have {VERSION}). "
                   f"Update with: {how_to_update()}", "Human Typer update")
            if on_newer:
                on_newer(tag)
    except Exception:
        pass   # offline, rate-limited, no releases yet: try again tomorrow


def check_in_background(on_newer=None):
    threading.Thread(target=check, kwargs={"on_newer": on_newer}, daemon=True).start()
