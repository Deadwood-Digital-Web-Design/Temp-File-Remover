"""Window for the System Care removers. Master copy lives in _core."""
from __future__ import annotations

import contextlib
import os
import queue
import sys
import threading
import traceback
from pathlib import Path

import removercore as rc
import syscore

NAVY = "#14274e"
ON, OFF = "☑", "☐"


def open_folder(path: Path) -> None:
    with contextlib.suppress(OSError, AttributeError):
        path.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(path))  # ty: ignore[unresolved-attribute]


class App:
    def __init__(self, root, spec: rc.Spec, log_dir: Path, wait: bool = False) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk, self.ttk = tk, ttk
        self.root, self.spec, self.log_dir = root, spec, log_dir
        self.q: queue.Queue = queue.Queue()
        self.plan: rc.Plan | None = None
        self.checked: dict[str, bool] = {}
        self.busy = False
        root.title(f"{spec.title} - Deadwood Digital")
        root.geometry("900x640")
        root.minsize(760, 520)
        style = ttk.Style(root)
        with contextlib.suppress(tk.TclError):
            style.theme_use("vista" if sys.platform == "win32" else "clam")
        style.configure("Treeview", rowheight=26)
        head = tk.Frame(root, bg=NAVY)
        head.pack(fill="x")
        tk.Label(head, text=spec.title, bg=NAVY, fg="white", font=("Segoe UI", 18, "bold"),
                 anchor="w").pack(fill="x", padx=18, pady=(14, 0))
        tk.Label(head, text=spec.intro, bg=NAVY, fg="#c9d4ee", font=("Segoe UI", 10), anchor="w",
                 wraplength=840, justify="left").pack(fill="x", padx=18, pady=(2, 14))
        self.tiles = ttk.Label(root, text="", font=("Segoe UI", 12, "bold"))
        self.tiles.pack(fill="x", padx=18, pady=(12, 2))
        self.tip = ttk.Label(root, text=spec.tip, foreground="#555", wraplength=840, justify="left")
        self.tip.pack(fill="x", padx=18)
        body = ttk.Frame(root)
        body.pack(fill="both", expand=True, padx=18, pady=8)
        cols = ("clear", "group", "files", "size", "what")
        self.tree = ttk.Treeview(body, columns=cols, show="headings", selectmode="browse")
        for c, t, w, a in (("clear", "Clear", 60, "center"), ("group", "What", 260, "w"),
                           ("files", "Files", 80, "e"), ("size", "Size", 90, "e"), ("what", "Why it's safe", 380, "w")):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor=a, stretch=(c == "what"))
        sb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self.on_click)
        self.tree.bind("<space>", self.on_space)
        bar = ttk.Frame(root)
        bar.pack(fill="x", padx=18, pady=(0, 6))
        self.status = ttk.Label(bar, text="", foreground="#333")
        self.status.pack(side="left")
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=160)
        self.btns = ttk.Frame(root)
        self.btns.pack(fill="x", padx=18, pady=(0, 14))
        self.b_clear = ttk.Button(self.btns, text="Clear checked", command=self.clear)
        self.b_clear.pack(side="right")
        self.b_look = ttk.Button(self.btns, text="Look again", command=self.look)
        self.b_look.pack(side="right", padx=8)
        ttk.Button(self.btns, text="Open log folder", command=lambda: open_folder(self.log_dir)).pack(side="left")
        root.report_callback_exception = self.crash
        self.look(wait=wait)

    # ------------------------------------------------------------------ plumbing
    def crash(self, exc, val, tb) -> None:
        text = "".join(traceback.format_exception(exc, val, tb))
        with contextlib.suppress(OSError):
            (Path(__file__).resolve().parent / "crash.log").write_text(text, encoding="utf-8")
        with contextlib.suppress(Exception):
            from tkinter import messagebox
            messagebox.showerror("Something went wrong", "Details were saved in crash.log next to the program.")

    def set_busy(self, busy: bool, text: str = "") -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.b_clear.configure(state=state)
        self.b_look.configure(state=state)
        self.status.configure(text=text)
        if busy:
            self.progress.pack(side="right")
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.pack_forget()

    def run_bg(self, fn, wait: bool) -> None:
        def work() -> None:
            try:
                self.q.put(("done", fn()))
            except Exception:  # noqa: BLE001
                self.q.put(("error", traceback.format_exc()))
        t = threading.Thread(target=work, daemon=True)
        t.start()
        if wait:
            t.join()
            self._poll(again=False)
        else:
            self.root.after(120, self._poll)

    def _poll(self, again: bool = True) -> None:
        pending = True
        while True:
            try:
                kind, payload = self.q.get_nowait()
            except queue.Empty:
                break
            pending = False
            if kind == "progress":
                self.status.configure(text=payload)
                pending = True
            elif kind == "error":
                self.set_busy(False, "Something went wrong.")
                with contextlib.suppress(OSError):
                    (Path(__file__).resolve().parent / "crash.log").write_text(payload, encoding="utf-8")
            elif kind == "done":
                payload()
        if pending and again:
            self.root.after(120, self._poll)

    # --------------------------------------------------------------------- actions
    def look(self, wait: bool = False) -> None:
        if self.busy:
            return
        self.set_busy(True, "Looking ...")

        def job():
            p = rc.plan(self.spec, progress=lambda n: self.q.put(("progress", f"Looking ... {n:,} files")))
            return lambda: self.show(p)
        self.run_bg(job, wait)

    def show(self, p: rc.Plan) -> None:
        self.plan = p
        self.tree.delete(*self.tree.get_children())
        old = self.checked
        self.checked = {}
        for g in sorted(p.groups.values(), key=lambda g: g.size, reverse=True):
            on = old.get(g.label, True)
            self.checked[g.label] = on
            self.tree.insert("", "end", iid=g.label,
                             values=(ON if on else OFF, g.label, f"{len(g.files):,}", syscore.fmt(g.size), g.why))
        self.set_busy(False, "")
        self.refresh_total()
        if not p.groups:
            self.tiles.configure(text="Nothing to clear. All clean.")

    def refresh_total(self) -> None:
        if not self.plan:
            return
        total = sum(g.size for k, g in self.plan.groups.items() if self.checked.get(k))
        n = sum(len(g.files) for k, g in self.plan.groups.items() if self.checked.get(k))
        if self.plan.groups:
            self.tiles.configure(text=f"Ready to clear {syscore.fmt(total)} in {n:,} files")
        self.b_clear.configure(state="normal" if total and not self.busy else "disabled")

    def toggle(self, iid: str) -> None:
        if iid in self.checked:
            self.checked[iid] = not self.checked[iid]
            self.tree.set(iid, "clear", ON if self.checked[iid] else OFF)
            self.refresh_total()

    def on_click(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if row and self.tree.identify_column(event.x) == "#1":
            self.toggle(row)

    def on_space(self, _event) -> None:
        for iid in self.tree.selection():
            self.toggle(iid)

    def clear(self, wait: bool = False, confirm: bool = True) -> None:
        if self.busy or not self.plan:
            return
        chosen = {k for k, v in self.checked.items() if v}
        if not chosen:
            return
        size = sum(self.plan.groups[k].size for k in chosen)
        if confirm:
            from tkinter import messagebox
            if not messagebox.askyesno("Clear these files?", f"Delete {syscore.fmt(size)} of files listed as safe?\n\n"
                                       "Files that are in use are skipped.", default="no", icon="warning"):
                return
        self.set_busy(True, "Clearing ...")
        plan = self.plan

        def job():
            res = rc.execute(plan, chosen, self.log_dir, self.spec.key,
                             progress=lambda d, t: self.q.put(("progress", f"Clearing ... {d:,} of {t:,}")))
            return lambda: self.cleared(res)
        self.run_bg(job, wait)

    def cleared(self, res: rc.Result) -> None:
        self.set_busy(False, f"Freed {syscore.fmt(res.deleted_bytes)} ({res.deleted_files:,} files). "
                             f"{res.in_use:,} in use and skipped.")
        self.look()


def run(spec: rc.Spec, base: Path) -> int:
    import tkinter as tk
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # ty: ignore[unresolved-attribute]
    except (AttributeError, OSError, ImportError):
        pass
    root = tk.Tk()
    App(root, spec, base / "logs")
    root.mainloop()
    return 0
