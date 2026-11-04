"""Human Typer: types text out like a person would."""
import os
import queue
import random
import subprocess
import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

import engine
import markup
import update
import sinks

MODE_FOCUSED, MODE_CHROME, MODE_PREVIEW = "focused", "chrome", "preview"


class Runner(threading.Thread):
    """Plays a planned list of actions into a sink, honoring pause/stop."""

    def __init__(self, actions, make_sink, events, guard=None):
        super().__init__(daemon=True)
        self.actions = actions
        self.make_sink = make_sink   # built on this thread (websocket lives here)
        self.events = events
        self.guard = guard
        self.stop_flag = threading.Event()
        self.paused = threading.Event()
        self.scale = 1.0   # multiplies every planned delay; changed live to change speed

    def _wait(self, seconds):
        """Sleeps for `seconds` of un-paused time. False means stop."""
        remaining = seconds
        held = False
        while remaining > 0:
            if self.stop_flag.is_set():
                return False
            verdict = self.guard() if self.guard else None
            if verdict and verdict[0] == "stop":
                self.events.put(("status", verdict[1]))
                return False
            if verdict and verdict[0] == "hold":
                if not held:
                    self.events.put(("status", verdict[1]))
                held = True
                time.sleep(0.05)
                continue
            if held:
                held = False
                self.events.put(("status", "Typing…"))
                remaining = max(remaining, 0.8)   # settle back in before resuming
            step = min(0.02, remaining)
            time.sleep(step)
            if not self.paused.is_set():
                remaining -= step
        return True

    def run(self):
        sink = None
        reason = "Done"
        try:
            sink = self.make_sink()
            self.events.put(("status", "Typing…"))
            debt = 0.0
            for idx, a in enumerate(self.actions):
                wait = a.delay * self.scale - debt
                if a.tag == "think" and a.delay > 1.2:
                    self.events.put(("status", "Thinking…"))
                if not self._wait(max(0.004, wait)):
                    reason = "Stopped"
                    break
                if a.tag == "think":
                    self.events.put(("status", "Typing…"))
                t0 = time.monotonic()
                if a.kind == "key":
                    sink.key(a.ch)
                elif a.kind == "back":
                    sink.backspace()
                else:
                    sink.combo(a.ch)
                debt = time.monotonic() - t0   # key hold time counts toward the next gap
                self.events.put(("progress", idx + 1, a.pos, a.tag))
        except Exception as e:
            reason = f"Error: {e}"
        finally:
            if sink:
                sink.close()
            self.events.put(("done", reason))


class App:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.preview_q = queue.Queue()
        self.runner = None
        self.estimate_job = None
        self.tabs = []
        root.title("Human Typer")
        root.geometry("820x780")
        root.minsize(680, 640)
        self._build()
        self._apply_preset()
        self._on_mode()
        self.root.after(30, self._pump)

    # ------------------------------------------------------------- layout --
    def _build(self):
        pad = dict(padx=12, pady=6)
        outer = ttk.Frame(self.root)
        outer.pack(fill="both", expand=True, padx=8, pady=8)

        ttk.Label(outer, text="Text to type", font=("Helvetica", 13, "bold")).pack(anchor="w", **pad)
        self._build_format_bar(outer)
        self.text = scrolledtext.ScrolledText(outer, height=12, wrap="word", font=("Helvetica", 13),
                                              undo=True, borderwidth=1, relief="solid")
        self.text.pack(fill="both", expand=True, padx=12)
        self.text.bind("<<Modified>>", self._on_text_change)
        ttk.Label(outer, foreground="#666", text=(
            "Marks: **bold**  *italic*  __underline__  ~~strike~~  {size:18}text{/size}  "
            "# Heading  - bullet  1. numbered   (\\* types a real *)")).pack(anchor="w", padx=12, pady=(2, 0))

        # --- how it types
        style = ttk.LabelFrame(outer, text="Typing style")
        style.pack(fill="x", **pad)
        style.columnconfigure(1, weight=1)

        ttk.Label(style, text="Preset").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        self.preset = tk.StringVar(value="Average (60 wpm)")
        cb = ttk.Combobox(style, textvariable=self.preset, values=list(engine.PRESETS), state="readonly", width=24)
        cb.grid(row=0, column=1, sticky="w", padx=8)
        cb.bind("<<ComboboxSelected>>", lambda e: self._apply_preset())

        self.wpm = tk.DoubleVar()
        self.typos = tk.DoubleVar()
        self.thinking = tk.DoubleVar()
        self.variability = tk.DoubleVar()
        self._slider(style, 1, "Speed (WPM)", self.wpm, 15, 150, lambda v: f"{v:.0f}")
        self._slider(style, 2, "Typos per 100 words", self.typos, 0, 15, lambda v: f"{v:.1f}")
        self._slider(style, 3, "Thinking pauses", self.thinking, 0, 3,
                     lambda v: ["Off", "Few", "Normal", "Many", "Lots"][min(4, round(v * 4 / 3))])
        self._slider(style, 4, "Rhythm variation", self.variability, 0.05, 0.6,
                     lambda v: "Steady" if v < 0.2 else "Natural" if v < 0.42 else "Erratic")

        checks = ttk.Frame(style)
        checks.grid(row=5, column=0, columnspan=3, sticky="w", padx=4, pady=(4, 6))
        self.fatigue = tk.BooleanVar(value=True)
        self.second = tk.BooleanVar(value=True)
        self.unfixed = tk.BooleanVar(value=False)
        self.shift_enter = tk.BooleanVar(value=False)
        for var, label in [(self.fatigue, "Gets tired on long texts"),
                           (self.second, "Second thoughts (retypes a word)"),
                           (self.unfixed, "Leave a few typos unfixed"),
                           (self.shift_enter, "Shift+Return for line breaks (chat apps)")]:
            ttk.Checkbutton(checks, text=label, variable=var, command=self._schedule_estimate).pack(side="left", padx=4)

        # --- where it types
        where = ttk.LabelFrame(outer, text="Where to type")
        where.pack(fill="x", **pad)
        self.mode = tk.StringVar(value=MODE_CHROME)
        modes = [(MODE_CHROME, "Background: Chrome tab (keep using your Mac)"),
                 (MODE_FOCUSED, "Focused window (any app, must stay in front)"),
                 (MODE_PREVIEW, "Preview here")]
        for i, (val, label) in enumerate(modes):
            ttk.Radiobutton(where, text=label, value=val, variable=self.mode,
                            command=self._on_mode).grid(row=0, column=i, sticky="w", padx=8, pady=4)

        self.chrome_row = ttk.Frame(where)
        self.chrome_row.grid(row=1, column=0, columnspan=3, sticky="ew", padx=8, pady=(0, 6))
        ttk.Button(self.chrome_row, text="Open typing window", command=self._open_chrome).pack(side="left")
        self.tab_var = tk.StringVar()
        self.tab_box = ttk.Combobox(self.chrome_row, textvariable=self.tab_var, state="readonly", width=44)
        self.tab_box.pack(side="left", padx=8, fill="x", expand=True)
        ttk.Button(self.chrome_row, text="↻ Tabs", command=self._refresh_tabs, width=7).pack(side="left")

        self.focused_row = ttk.Frame(where)
        self.focused_row.grid(row=2, column=0, columnspan=3, sticky="ew", padx=8, pady=(0, 6))
        ttk.Label(self.focused_row, text="Countdown").pack(side="left")
        self.countdown = tk.IntVar(value=5)
        ttk.Spinbox(self.focused_row, from_=1, to=30, textvariable=self.countdown, width=4).pack(side="left", padx=6)
        ttk.Label(self.focused_row, text="sec").pack(side="left")
        self.ax_btn = ttk.Button(self.focused_row, text="Allow keyboard control…", command=self._open_ax_settings)
        self.ax_btn.pack(side="right")

        self.hint = ttk.Label(where, foreground="#666", wraplength=740, justify="left")
        self.hint.grid(row=3, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 8))

        # --- controls
        ctl = ttk.Frame(outer)
        ctl.pack(fill="x", **pad)
        self.start_btn = ttk.Button(ctl, text="▶ Start", command=self._start)
        self.start_btn.pack(side="left")
        self.pause_btn = ttk.Button(ctl, text="Pause", command=self._toggle_pause, state="disabled")
        self.pause_btn.pack(side="left", padx=6)
        self.stop_btn = ttk.Button(ctl, text="Stop", command=self._stop, state="disabled")
        self.stop_btn.pack(side="left")
        self.estimate = ttk.Label(ctl, foreground="#666")
        self.estimate.pack(side="right")

        self.progress = ttk.Progressbar(outer, maximum=1000)
        self.progress.pack(fill="x", padx=12, pady=(0, 4))
        bottom = ttk.Frame(outer)
        bottom.pack(fill="x", padx=12)
        self.status = ttk.Label(bottom, text="Ready")
        self.status.pack(side="left")
        self.stats = ttk.Label(bottom, foreground="#666")
        self.stats.pack(side="right")

    def _build_format_bar(self, parent):
        bar = ttk.Frame(parent)
        bar.pack(fill="x", padx=12, pady=(0, 4))
        for label, mark, font in (("B", "**", ("Helvetica", 13, "bold")), ("I", "*", ("Helvetica", 13, "italic")),
                                  ("U", "__", ("Helvetica", 13, "underline")),
                                  ("S", "~~", ("Helvetica", 13, "overstrike"))):
            tk.Button(bar, text=label, font=font, width=2,
                      command=lambda m=mark: self._wrap_selection(m, m)).pack(side="left", padx=1)
        self.size_pick = ttk.Combobox(bar, values=[str(x) for x in markup.SIZE_STEPS], width=4, state="readonly")
        self.size_pick.set("Size")
        self.size_pick.pack(side="left", padx=(8, 2))
        self.size_pick.bind("<<ComboboxSelected>>", self._apply_size)
        self.para_pick = ttk.Combobox(bar, state="readonly", width=11, values=[
            "Normal text", "Heading 1", "Heading 2", "Heading 3", "Heading 4", "Bulleted list", "Numbered list"])
        self.para_pick.set("Paragraph")
        self.para_pick.pack(side="left", padx=2)
        self.para_pick.bind("<<ComboboxSelected>>", self._apply_para)
        ttk.Button(bar, text="Paste formatted", command=self._paste_formatted).pack(side="left", padx=8)
        self.use_fmt = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="Apply formatting (Google Docs)", variable=self.use_fmt,
                        command=self._schedule_estimate).pack(side="right")

    def _selection(self):
        try:
            return self.text.index("sel.first"), self.text.index("sel.last")
        except tk.TclError:
            return None

    def _wrap_selection(self, before, after):
        sel = self._selection()
        if sel:
            self.text.insert(sel[1], after)
            self.text.insert(sel[0], before)
        else:
            self.text.insert("insert", before + after)
            self.text.mark_set("insert", f"insert-{len(after)}c")
        self.text.focus_set()

    def _apply_size(self, _=None):
        self._wrap_selection(f"{{size:{self.size_pick.get()}}}", "{/size}")
        self.size_pick.set("Size")

    def _apply_para(self, _=None):
        choice = self.para_pick.get()
        prefix = {"Normal text": "", "Bulleted list": "- ", "Numbered list": "1. "}.get(
            choice, "#" * int(choice[-1]) + " " if choice.startswith("Heading") else "")
        sel = self._selection() or (self.text.index("insert"), self.text.index("insert"))
        first, last = int(sel[0].split(".")[0]), int(sel[1].split(".")[0])
        for n, line in enumerate(range(first, last + 1)):
            content = self.text.get(f"{line}.0", f"{line}.end")
            m = markup.LINE_RE.match(content)
            if m:
                self.text.delete(f"{line}.0", f"{line}.{m.end()}")
            p = f"{n + 1}. " if prefix == "1. " else prefix
            if p:
                self.text.insert(f"{line}.0", p)
        self.para_pick.set("Paragraph")
        self.text.focus_set()

    def _paste_formatted(self):
        """Pastes the clipboard, turning rich text (Docs, Word, web) into marks."""
        html = None
        try:
            from AppKit import NSPasteboard
            html = NSPasteboard.generalPasteboard().stringForType_("public.html")
        except Exception:
            pass
        if html:
            content = markup.html_to_markup(str(html))
        else:
            try:
                content = self.root.clipboard_get()
            except tk.TclError:
                return
        sel = self._selection()
        if sel:
            self.text.delete(*sel)
        self.text.insert("insert", content)
        self.text.focus_set()

    def _slider(self, parent, row, label, var, lo, hi, fmt):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=2)
        value = ttk.Label(parent, width=8)
        def changed(_=None):
            value.config(text=fmt(var.get()))
            self.preset.set("Custom") if self._user_drag else None
            self._schedule_estimate()
        s = ttk.Scale(parent, from_=lo, to=hi, variable=var, command=changed)
        s.grid(row=row, column=1, sticky="ew", padx=8)
        value.grid(row=row, column=2, sticky="w", padx=4)
        var.trace_add("write", lambda *a: value.config(text=fmt(var.get())))

    _user_drag = True

    def _apply_preset(self):
        p = engine.PRESETS.get(self.preset.get())
        if not p:
            return
        self._user_drag = False
        self.wpm.set(p["wpm"])
        self.typos.set(p["typos_per_100_words"])
        self.thinking.set(p["thinking"])
        self.variability.set(p["variability"])
        self._user_drag = True
        self._schedule_estimate()

    def _settings(self):
        return engine.Settings(
            wpm=self.wpm.get(), variability=self.variability.get(),
            typos_per_100_words=self.typos.get(), thinking=self.thinking.get(),
            fatigue=self.fatigue.get(), second_thoughts=self.second.get(),
            unfixed_typo_share=0.12 if self.unfixed.get() else 0.0)

    def _source_text(self):
        return self.text.get("1.0", "end-1c")

    # ----------------------------------------------------------- estimate --
    def _on_text_change(self, _=None):
        self.text.edit_modified(False)
        self._schedule_estimate()

    def _schedule_estimate(self):
        if self.estimate_job:
            self.root.after_cancel(self.estimate_job)
        self.estimate_job = self.root.after(350, self._update_estimate)

    def _update_estimate(self):
        self.estimate_job = None
        text = self._source_text()
        if not text.strip():
            self.estimate.config(text="")
            return
        actions, plain = markup.plan(text, self._settings(), seed=1, formatting=self.use_fmt.get())
        secs = engine.plan_duration(actions)
        words = len(plain) / 5
        self.estimate.config(text=f"≈ {fmt_duration(secs)}  ·  ~{words / (secs / 60):.0f} wpm overall")

    # --------------------------------------------------------------- modes --
    def _on_mode(self):
        m = self.mode.get()
        self.chrome_row.grid() if m == MODE_CHROME else self.chrome_row.grid_remove()
        self.focused_row.grid() if m == MODE_FOCUSED else self.focused_row.grid_remove()
        if m == MODE_CHROME:
            self.hint.config(text=(
                "Opens a separate Chrome window. Sign in to Google there once, open your doc, and click "
                "where the text should go. Then press Start and go do other things. The window can sit "
                "behind other apps, but don't minimize it or click inside the doc while it's typing."))
            self._refresh_tabs()
        elif m == MODE_FOCUSED:
            trusted = sinks.accessibility_trusted()
            self.hint.config(text=(
                "Press Start, then click into the window to type in before the countdown ends. Switching "
                "to another app pauses it; switching back resumes. Esc or moving the mouse to the top-left "
                "corner stops it." + ("" if trusted else
                "\n⚠ Keyboard control isn't allowed yet: add the app you launched this from (e.g. Terminal) "
                "under System Settings › Privacy & Security › Accessibility, then restart Human Typer.")))
            self.ax_btn.pack(side="right") if not trusted else self.ax_btn.pack_forget()
        else:
            self.hint.config(text="Types into a preview window here so you can see the behavior.")

    def _open_ax_settings(self):
        subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"])

    def _open_chrome(self):
        try:
            sinks.launch_typing_browser()
        except Exception as e:
            messagebox.showerror("Human Typer", str(e))
            return
        self.status.config(text="Opening Chrome… sign in if needed, open your doc, then press ↻ Tabs")
        self.root.after(2500, self._refresh_tabs)

    def _refresh_tabs(self):
        tabs = sinks.list_tabs()
        if tabs is None:
            self.tabs = []
            self.tab_box.config(values=[])
            self.tab_var.set("Typing window not open")
            return
        self.tabs = tabs
        labels = [f"{t.get('title') or t.get('url')}"[:80] for t in tabs]
        self.tab_box.config(values=labels)
        best = next((i for i, t in enumerate(tabs) if "docs.google.com/document/d/" in t.get("url", "")), 0)
        self.tab_var.set(labels[best] if labels else "No tabs open")

    def _selected_tab(self):
        labels = list(self.tab_box.cget("values"))
        if self.tab_var.get() in labels:
            return self.tabs[labels.index(self.tab_var.get())]
        return None

    # ------------------------------------------------------------- running --
    def _start(self):
        text = self._source_text()
        if not text:
            messagebox.showinfo("Human Typer", "Paste or type some text first.")
            return
        actions, plain = markup.plan(text, self._settings(), seed=random.randrange(1 << 30),
                                     formatting=self.use_fmt.get())
        self.total_actions = len(actions)
        self.text_len = len(plain)
        self.typos_made = 0
        self.started = None
        mode = self.mode.get()
        shift_enter = self.shift_enter.get()

        if mode == MODE_CHROME:
            tab = self._selected_tab()
            if not tab:
                messagebox.showinfo("Human Typer", "Open the typing window and pick the tab with your doc first.")
                return
            ws = tab["webSocketDebuggerUrl"]
            self._launch(actions, lambda: sinks.ChromeSink(ws, shift_enter))
        elif mode == MODE_PREVIEW:
            self._open_preview()
            self._launch(actions, lambda: sinks.PreviewSink(self.preview_q))
        else:
            if not sinks.accessibility_trusted():
                self._on_mode()
                messagebox.showwarning("Human Typer", "Allow keyboard control first (see the note under 'Where to type').")
                return
            self._set_running(True)
            self._countdown(actions, self.countdown.get(), shift_enter)

    def _countdown(self, actions, n, shift_enter):
        if self.runner is None and not self._counting:
            return
        if n > 0:
            self.status.config(text=f"Click into the window to type in… {n}")
            self.root.after(1000, self._countdown, actions, n - 1, shift_enter)
            return
        pid, name = sinks.frontmost_app()
        if pid == os.getpid():
            self.status.config(text="Waiting for you to click into another app…")
            self.root.after(300, self._countdown, actions, 0, shift_enter)
            return
        self._counting = False

        def guard():
            if sinks.esc_held():
                return ("stop", "Stopped (Esc)")
            if sinks.mouse_in_corner():
                return ("stop", "Stopped (mouse in corner)")
            if sinks.frontmost_app()[0] != pid:
                return ("hold", f"Paused: switch back to {name} to continue")
            return None
        self._launch(actions, lambda: sinks.QuartzSink(shift_enter), guard)

    _counting = False

    def _launch(self, actions, make_sink, guard=None):
        self.runner = Runner(actions, make_sink, self.events, guard)
        self._set_running(True)
        self.started = time.monotonic()
        self.runner.start()

    def _set_running(self, running):
        if running and self.runner is None:
            self._counting = True
        self.start_btn.config(state="disabled" if running else "normal")
        self.stop_btn.config(state="normal" if running else "disabled")
        self.pause_btn.config(state="normal" if running and self.runner else "disabled", text="Pause")

    def _toggle_pause(self):
        if not self.runner:
            return
        if self.runner.paused.is_set():
            self.runner.paused.clear()
            self.pause_btn.config(text="Pause")
            self.status.config(text="Typing…")
        else:
            self.runner.paused.set()
            self.pause_btn.config(text="Resume")
            self.status.config(text="Paused")

    def _stop(self):
        self._counting = False
        if self.runner:
            self.runner.stop_flag.set()
        else:
            self._set_running(False)
            self.status.config(text="Cancelled")

    def _pump(self):
        try:
            while True:
                ev = self.events.get_nowait()
                if ev[0] == "status":
                    self.status.config(text=ev[1])
                elif ev[0] == "progress":
                    _, done, pos, tag = ev
                    if tag == "typo":
                        self.typos_made += 1
                    self.progress["value"] = 1000 * done / max(1, self.total_actions)
                    elapsed = time.monotonic() - self.started
                    wpm = (pos / 5) / (elapsed / 60) if elapsed > 3 else 0
                    self.stats.config(text=f"{pos}/{self.text_len} chars  ·  {self.typos_made} typos  ·  "
                                           f"{wpm:.0f} wpm  ·  {fmt_duration(elapsed)}")
                elif ev[0] == "done":
                    self.status.config(text=ev[1] if ev[1] != "Done" else "Done ✓")
                    self.runner = None
                    self._set_running(False)
        except queue.Empty:
            pass
        self._pump_preview()
        self.root.after(15, self._pump)

    # ------------------------------------------------------------- preview --
    def _open_preview(self):
        self.pv = markup.DocsState()   # the formatting the preview applies next
        self.pv_num = 0
        if getattr(self, "preview_win", None) and self.preview_win.winfo_exists():
            self.preview_text.delete("1.0", "end")
            self.preview_win.lift()
            return
        self.preview_win = tk.Toplevel(self.root)
        self.preview_win.title("Preview")
        self.preview_win.geometry("680x460")
        self.preview_text = tk.Text(self.preview_win, wrap="word", font=("Helvetica", 15),
                                    padx=14, pady=14, insertwidth=2)
        self.preview_text.pack(fill="both", expand=True)
        self.preview_text.tag_configure("marker", foreground="#555")
        # Only the simulated typist writes here; real keystrokes are ignored.
        self.preview_text.bind("<Key>", lambda e: "break")

    def _pv_style_tag(self):
        st = self.pv
        name = f"s{int(st.bold)}{int(st.italic)}{int(st.underline)}{int(st.strike)}_{st.size}"
        if name not in self.preview_text.tag_names():
            styles = [w for w, on in (("bold", st.bold), ("italic", st.italic)) if on]
            self.preview_text.tag_configure(name, font=("Helvetica", round(st.size * 1.35), " ".join(styles)),
                                            underline=st.underline, overstrike=st.strike)
        return name

    def _pv_marker(self):
        """Shows the current paragraph's bullet or number, like Docs does."""
        t = self.preview_text
        start = t.index("insert linestart")
        rng = t.tag_nextrange("marker", start, f"{start} lineend")
        if rng and rng[0] == start:
            t.delete(*rng)
        if self.pv.list == "bullet":
            t.insert(start, "  •  ", "marker")
        elif self.pv.list == "number":
            t.insert(start, f"  {self.pv_num}.  ", "marker")

    def _pump_preview(self):
        try:
            while True:
                kind, ch = self.preview_q.get_nowait()
                if not (getattr(self, "preview_win", None) and self.preview_win.winfo_exists()):
                    continue
                t = self.preview_text
                if kind == "key":
                    if ch == "\n":
                        t.insert("insert", "\n")
                        self.pv.newline()
                        if self.pv.list:
                            self.pv_num += 1
                            self._pv_marker()
                    else:
                        t.insert("insert", ch, self._pv_style_tag())
                elif kind == "back":
                    if "marker" not in t.tag_names("insert-1c"):
                        t.delete("insert-1c")
                else:
                    before = (self.pv.heading, self.pv.list)
                    self.pv.apply(ch)
                    if self.pv.list != before[1]:
                        self.pv_num = 1 if self.pv.list == "number" and before[1] != "number" else self.pv_num
                        self._pv_marker()
                t.see("insert")
        except queue.Empty:
            pass


def fmt_duration(secs):
    secs = int(round(secs))
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m {secs % 60:02d}s"
    return f"{secs // 3600}h {secs % 3600 // 60:02d}m"


def set_dock_icon():
    """Inside the .app bundle Python would otherwise show its own Dock icon."""
    icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "AppIcon.icns")
    if not os.path.exists(icon):
        return
    try:
        from AppKit import NSApplication, NSImage
        NSApplication.sharedApplication().setApplicationIconImage_(
            NSImage.alloc().initWithContentsOfFile_(icon))
    except Exception:
        pass


def main():
    root = tk.Tk()
    set_dock_icon()
    App(root)
    update.check_in_background()
    root.mainloop()


if __name__ == "__main__":
    main()
