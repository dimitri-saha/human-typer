"""Where keystrokes go: the focused window, a background Chrome tab, or a preview."""
import json
import os
import random
import shutil
import subprocess
import time
import urllib.parse
import urllib.request

from engine import SHIFTED, base_key, needs_shift

SHIFTED_OF = {base: shifted for shifted, base in SHIFTED.items()}

# base key -> (macOS virtual keycode, DOM code); Windows VK codes for non-alphanumerics below
KEYMAP = {
    "a": (0, "KeyA"), "s": (1, "KeyS"), "d": (2, "KeyD"), "f": (3, "KeyF"),
    "h": (4, "KeyH"), "g": (5, "KeyG"), "z": (6, "KeyZ"), "x": (7, "KeyX"),
    "c": (8, "KeyC"), "v": (9, "KeyV"), "b": (11, "KeyB"), "q": (12, "KeyQ"),
    "w": (13, "KeyW"), "e": (14, "KeyE"), "r": (15, "KeyR"), "y": (16, "KeyY"),
    "t": (17, "KeyT"), "o": (31, "KeyO"), "u": (32, "KeyU"), "i": (34, "KeyI"),
    "p": (35, "KeyP"), "l": (37, "KeyL"), "j": (38, "KeyJ"), "k": (40, "KeyK"),
    "n": (45, "KeyN"), "m": (46, "KeyM"),
    "1": (18, "Digit1"), "2": (19, "Digit2"), "3": (20, "Digit3"), "4": (21, "Digit4"),
    "6": (22, "Digit6"), "5": (23, "Digit5"), "9": (25, "Digit9"), "7": (26, "Digit7"),
    "8": (28, "Digit8"), "0": (29, "Digit0"),
    "=": (24, "Equal"), "-": (27, "Minus"), "]": (30, "BracketRight"), "[": (33, "BracketLeft"),
    "'": (39, "Quote"), ";": (41, "Semicolon"), "\\": (42, "Backslash"), ",": (43, "Comma"),
    "/": (44, "Slash"), ".": (47, "Period"), "`": (50, "Backquote"), " ": (49, "Space"),
}
WIN_VK = {"=": 187, "-": 189, "]": 221, "[": 219, "'": 222, ";": 186, "\\": 220,
          ",": 188, "/": 191, ".": 190, "`": 192, " ": 32}

MAC_RETURN, MAC_TAB, MAC_DELETE, MAC_SHIFT, MAC_ESC = 36, 48, 51, 56, 53
MAC_MODIFIER_KEYS = {"cmd": 55, "shift": 56, "alt": 58, "ctrl": 59}


def split_combo(spec):
    """"cmd+shift+." -> (["cmd", "shift"], ".")"""
    *mods, key = spec.split("+")
    return mods, key


def _dwell():
    """How long a key is held down."""
    return max(0.02, random.gauss(0.075, 0.02))


# ------------------------------------------------------------ focused window --

class QuartzSink:
    """Posts real keyboard events to whatever window has focus (needs Accessibility)."""

    def __init__(self, shift_enter=False):
        import Quartz
        self.Q = Quartz
        self.shift_enter = shift_enter

    def _post(self, keycode, down, flags=0, text=None):
        Q = self.Q
        ev = Q.CGEventCreateKeyboardEvent(None, keycode, down)
        Q.CGEventSetFlags(ev, flags)
        if text is not None:
            Q.CGEventKeyboardSetUnicodeString(ev, len(text.encode("utf-16-le")) // 2, text)
        Q.CGEventPost(Q.kCGHIDEventTap, ev)

    def _tap(self, keycode, flags=0, text=None, shift=False):
        shift_flag = self.Q.kCGEventFlagMaskShift
        if shift:
            self._post(MAC_SHIFT, True, shift_flag)
            time.sleep(random.uniform(0.02, 0.05))
            flags |= shift_flag
        self._post(keycode, True, flags, text)
        time.sleep(_dwell())
        self._post(keycode, False, flags, text)
        if shift:
            time.sleep(random.uniform(0.01, 0.03))
            self._post(MAC_SHIFT, False, 0)

    def key(self, ch):
        if ch == "\n":
            self._tap(MAC_RETURN, shift=self.shift_enter)
        elif ch == "\t":
            self._tap(MAC_TAB)
        else:
            info = KEYMAP.get(base_key(ch))
            if info:
                self._tap(info[0], text=ch, shift=needs_shift(ch))
            else:
                self._tap(0, text=ch)   # any other character: send it as unicode

    def backspace(self):
        self._tap(MAC_DELETE)

    def combo(self, spec):
        """A keyboard shortcut: modifiers go down one by one, then the key."""
        Q = self.Q
        flag_of = {"cmd": Q.kCGEventFlagMaskCommand, "shift": Q.kCGEventFlagMaskShift,
                   "alt": Q.kCGEventFlagMaskAlternate, "ctrl": Q.kCGEventFlagMaskControl}
        mods, key = split_combo(spec)
        flags = 0
        for m in mods:
            flags |= flag_of[m]
            self._post(MAC_MODIFIER_KEYS[m], True, flags)
            time.sleep(random.uniform(0.03, 0.07))
        keycode = KEYMAP[key][0]
        self._post(keycode, True, flags)
        time.sleep(_dwell())
        self._post(keycode, False, flags)
        for m in reversed(mods):
            time.sleep(random.uniform(0.01, 0.04))
            flags &= ~flag_of[m]
            self._post(MAC_MODIFIER_KEYS[m], False, flags)

    def close(self):
        pass


def accessibility_trusted():
    try:
        from ApplicationServices import AXIsProcessTrusted
        return bool(AXIsProcessTrusted())
    except Exception:
        return False


def frontmost_app():
    """(pid, name) of the app in front."""
    from AppKit import NSWorkspace
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    return (app.processIdentifier(), app.localizedName()) if app else (None, "")


def esc_held():
    import Quartz
    return bool(Quartz.CGEventSourceKeyState(Quartz.kCGEventSourceStateHIDSystemState, MAC_ESC))


def mouse_in_corner():
    import Quartz
    p = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
    return p.x < 3 and p.y < 3


# ---------------------------------------------------------- background Chrome --

CDP_PORT = 9333
PROFILE_DIR = os.path.expanduser("~/Library/Application Support/Human Typer/Chrome Profile")
BROWSERS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]


def find_browser():
    for path in BROWSERS:
        if os.path.exists(path):
            return path
    return shutil.which("google-chrome") or shutil.which("chromium")


def launch_typing_browser(url="https://docs.google.com/document/u/0/", port=CDP_PORT,
                          profile=PROFILE_DIR, extra_args=()):
    """Starts a separate Chrome window the app can type into in the background.

    It uses its own profile (Chrome only allows remote control of a non-default
    profile), so you sign in to Google once in that window and it stays signed in.
    """
    if list_tabs(port) is not None:
        _cdp_http(port, "/json/new?" + urllib.parse.quote(url, safe=":/?=&"), method="PUT")
        return
    path = find_browser()
    if not path:
        raise RuntimeError("Google Chrome (or Edge/Brave) wasn't found in /Applications.")
    os.makedirs(profile, exist_ok=True)
    subprocess.Popen(
        [path, f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
         "--no-first-run", "--no-default-browser-check",
         # Keep the page fully alive while it's hidden behind other windows.
         "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
         "--disable-background-timer-throttling", *extra_args, url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def _cdp_http(port, path, method="GET"):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method)
    with urllib.request.urlopen(req, timeout=2) as r:
        return json.loads(r.read().decode() or "null")


def list_tabs(port=CDP_PORT):
    """Open pages in the typing browser, or None if it isn't running."""
    try:
        return [t for t in _cdp_http(port, "/json/list") if t.get("type") == "page"]
    except Exception:
        return None


class ChromeSink:
    """Types into one Chrome tab through the DevTools protocol, no focus needed."""

    def __init__(self, ws_url, shift_enter=False):
        from websockets.sync.client import connect
        self.shift_enter = shift_enter
        self.ws = connect(ws_url, max_size=None, open_timeout=5)
        self._id = 0
        # Make the page behave as if its window were focused, even when it isn't.
        self.call("Emulation.setFocusEmulationEnabled", enabled=True)

    def call(self, method, **params):
        self._id += 1
        my_id = self._id
        self.ws.send(json.dumps({"id": my_id, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv(timeout=10))
            if msg.get("id") == my_id:
                if "error" in msg:
                    raise RuntimeError(msg["error"].get("message", str(msg["error"])))
                return msg.get("result")

    def _key_event(self, type_, key, code, vk, text=None, modifiers=0):
        params = dict(type=type_, key=key, code=code, windowsVirtualKeyCode=vk,
                      nativeVirtualKeyCode=vk, modifiers=modifiers)
        if text is not None:
            params.update(text=text, unmodifiedText=text)
        self.call("Input.dispatchKeyEvent", **params)

    def _tap(self, key, code, vk, text=None, shift=False):
        mods = 8 if shift else 0
        if shift:
            self._key_event("rawKeyDown", "Shift", "ShiftLeft", 16, modifiers=8)
            time.sleep(random.uniform(0.02, 0.05))
        self._key_event("keyDown" if text else "rawKeyDown", key, code, vk, text, mods)
        time.sleep(_dwell())
        self._key_event("keyUp", key, code, vk, modifiers=mods)
        if shift:
            time.sleep(random.uniform(0.01, 0.03))
            self._key_event("keyUp", "Shift", "ShiftLeft", 16)

    def key(self, ch):
        if ch == "\n":
            self._tap("Enter", "Enter", 13, "\r", shift=self.shift_enter)
        elif ch == "\t":
            self._tap("Tab", "Tab", 9)
        else:
            b = base_key(ch)
            info = KEYMAP.get(b)
            if info:
                vk = WIN_VK.get(b, ord(b.upper()))
                self._tap(ch, info[1], vk, ch, shift=needs_shift(ch))
            else:
                self.call("Input.insertText", text=ch)

    def backspace(self):
        self._tap("Backspace", "Backspace", 8)

    # CDP modifier bit, DOM key, DOM code, Windows VK
    CDP_MODS = {"alt": (1, "Alt", "AltLeft", 18), "ctrl": (2, "Control", "ControlLeft", 17),
                "cmd": (4, "Meta", "MetaLeft", 91), "shift": (8, "Shift", "ShiftLeft", 16)}

    def combo(self, spec):
        mods, key = split_combo(spec)
        bits = 0
        for m in mods:
            bit, k, code, vk = self.CDP_MODS[m]
            bits |= bit
            self._key_event("rawKeyDown", k, code, vk, modifiers=bits)
            time.sleep(random.uniform(0.03, 0.07))
        code = KEYMAP[key][1]
        vk = WIN_VK.get(key, ord(key.upper()))
        shown = SHIFTED_OF.get(key, key.upper()) if "shift" in mods else key
        self._key_event("rawKeyDown", shown, code, vk, modifiers=bits)
        time.sleep(_dwell())
        self._key_event("keyUp", shown, code, vk, modifiers=bits)
        for m in reversed(mods):
            time.sleep(random.uniform(0.01, 0.04))
            bit, k, code, vk = self.CDP_MODS[m]
            bits &= ~bit
            self._key_event("keyUp", k, code, vk, modifiers=bits)

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


# --------------------------------------------------------------------- preview --

class PreviewSink:
    """Hands keystrokes to the GUI thread through a queue."""

    def __init__(self, queue):
        self.q = queue

    def key(self, ch):
        self.q.put(("key", ch))

    def backspace(self):
        self.q.put(("back", ""))

    def combo(self, spec):
        self.q.put(("combo", spec))

    def close(self):
        pass
