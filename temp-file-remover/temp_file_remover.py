#!/usr/bin/env python3
"""
Temp File Remover
-----------------
Finds junk temp files, shows you the full list, and only deletes what YOU pick.

Safe by design:
  * Nothing is deleted until you review the list and confirm.
  * Files newer than a cutoff (default 24 hours) are skipped, since apps may still use them.
  * Files that are locked / in use are skipped, not forced.
  * Symlinks are never followed.
  * Only stuff inside the known temp folders can ever be touched.

Pure standard library. No installs needed.

Usage:
  python temp_file_remover.py                 # opens the window (GUI)
  python temp_file_remover.py --scan          # list only, deletes nothing
  python temp_file_remover.py --delete        # list, then ask before deleting
  python temp_file_remover.py --delete --yes  # delete without asking (be careful)
  python temp_file_remover.py --age 48        # only files older than 48 hours
"""

import argparse
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

__version__ = "1.1.0"


# ---------------------------------------------------------------------------
# Where the temp files live
# ---------------------------------------------------------------------------

def get_targets():
    """Return a dict of {friendly name: folder path} for temp locations that exist."""
    targets = {}

    # The current user's temp folder (works on every OS)
    targets["User Temp"] = Path(tempfile.gettempdir())

    if os.name == "nt":  # Windows only extras
        local = os.environ.get("LOCALAPPDATA")
        windir = os.environ.get("WINDIR", r"C:\Windows")
        if local:
            targets["Internet Cache"] = Path(local) / "Microsoft" / "Windows" / "INetCache"
            targets["Crash Dumps"] = Path(local) / "CrashDumps"
            targets["Error Reports"] = Path(local) / "Microsoft" / "Windows" / "WER"
        # Needs admin rights to delete; non-admin files just get skipped
        targets["Windows Temp"] = Path(windir) / "Temp"

    # Only keep folders that actually exist
    return {name: p for name, p in targets.items() if p.is_dir()}


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

@dataclass
class Item:
    path: Path
    size: int
    mtime: float
    target: str  # which temp location it came from


def scan(targets, min_age_hours=24.0):
    """Walk the temp folders and return a list of Items older than min_age_hours."""
    cutoff = time.time() - (min_age_hours * 3600)
    items = []
    for name, root in targets.items():
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            # Don't descend into symlinked folders
            dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
            for fname in filenames:
                full = os.path.join(dirpath, fname)
                try:
                    st = os.lstat(full)  # lstat = don't follow symlinks
                except OSError:
                    continue  # vanished or no access, skip it
                if os.path.islink(full):
                    continue
                if st.st_mtime > cutoff:
                    continue  # too new, leave it alone
                items.append(Item(Path(full), st.st_size, st.st_mtime, name))
    return items


# ---------------------------------------------------------------------------
# Deleting
# ---------------------------------------------------------------------------

def _inside(path, roots):
    """True only if `path` is really inside one of the allowed roots."""
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def delete_items(items, targets):
    """
    Delete the given items. Returns (freed_bytes, deleted_count, failed_list).
    Locked or protected files are skipped and reported, never forced.
    """
    roots = list(targets.values())
    freed = 0
    deleted = 0
    failed = []
    touched_dirs = set()

    for item in items:
        if not _inside(item.path, roots):
            failed.append((item.path, "outside temp folders, refused"))
            continue
        try:
            item.path.unlink()
            freed += item.size
            deleted += 1
            touched_dirs.add(item.path.parent)
        except PermissionError:
            failed.append((item.path, "in use or no permission"))
        except FileNotFoundError:
            pass  # already gone, fine
        except OSError as e:
            failed.append((item.path, str(e)))

    # Clean up folders that are now empty (never removes the temp roots themselves)
    root_set = {r.resolve() for r in roots}
    for d in sorted(touched_dirs, key=lambda p: len(p.parts), reverse=True):
        cur = d
        while cur.resolve() not in root_set and _inside(cur, roots):
            try:
                cur.rmdir()  # only works if empty
            except OSError:
                break
            cur = cur.parent

    return freed, deleted, failed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def human_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def age_text(mtime):
    days = (time.time() - mtime) / 86400
    return f"{days:.0f}d" if days >= 1 else f"{days * 24:.0f}h"


# ---------------------------------------------------------------------------
# Command line mode
# ---------------------------------------------------------------------------

def run_cli(args):
    targets = get_targets()
    if args.target:
        wanted = {t.lower() for t in args.target}
        targets = {n: p for n, p in targets.items() if n.lower() in wanted}
    if not targets:
        print("No temp folders found.")
        return 1

    print(f"Scanning: {', '.join(targets)} (files older than {args.age:g}h)...")
    items = scan(targets, args.age)
    if not items:
        print("Nothing to clean. All good.")
        return 0

    items.sort(key=lambda i: i.size, reverse=True)
    total = sum(i.size for i in items)
    for i in items[:50]:
        print(f"  {human_size(i.size):>10}  {age_text(i.mtime):>4}  {i.path}")
    if len(items) > 50:
        print(f"  ... and {len(items) - 50} more")
    print(f"\n{len(items)} files, {human_size(total)} can be freed.")

    if not args.delete:
        print("Scan only. Nothing deleted. Use --delete to remove them.")
        return 0

    if not args.yes:
        if input("Delete all of these? Type YES to confirm: ").strip() != "YES":
            print("Cancelled. Nothing deleted.")
            return 0

    freed, deleted, failed = delete_items(items, targets)
    print(f"Deleted {deleted} files, freed {human_size(freed)}.")
    if failed:
        print(f"Skipped {len(failed)} (in use or protected).")
    return 0


# ---------------------------------------------------------------------------
# Window mode
# ---------------------------------------------------------------------------

def run_gui():
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title(f"Temp File Remover v{__version__}")
    root.geometry("860x560")

    targets = get_targets()
    items = []          # current scan results
    checked = {}        # tree row id -> True/False

    # ---- top bar
    top = ttk.Frame(root, padding=8)
    top.pack(fill="x")
    ttk.Label(top, text="Skip files newer than (hours):").pack(side="left")
    age_var = tk.StringVar(value="24")
    ttk.Spinbox(top, from_=0, to=720, width=6, textvariable=age_var).pack(side="left", padx=6)
    scan_btn = ttk.Button(top, text="Scan")
    scan_btn.pack(side="left", padx=6)

    # ---- list
    cols = ("sel", "size", "age", "where", "path")
    tree = ttk.Treeview(root, columns=cols, show="headings", selectmode="browse")
    for col, text, width in (
        ("sel", "", 36), ("size", "Size", 80), ("age", "Age", 50),
        ("where", "Location", 110), ("path", "File", 540),
    ):
        tree.heading(col, text=text)
        tree.column(col, width=width, anchor="w", stretch=(col == "path"))
    tree.pack(fill="both", expand=True, padx=8)

    # ---- bottom bar
    bottom = ttk.Frame(root, padding=8)
    bottom.pack(fill="x")
    status = tk.StringVar(value="Click Scan to look for temp files. Nothing is deleted until you confirm.")
    ttk.Label(bottom, textvariable=status).pack(side="left")
    delete_btn = ttk.Button(bottom, text="Delete selected")
    delete_btn.pack(side="right")
    ttk.Button(bottom, text="Select none", command=lambda: set_all(False)).pack(side="right", padx=6)
    ttk.Button(bottom, text="Select all", command=lambda: set_all(True)).pack(side="right")

    def refresh_status():
        sel = [items[int(r)] for r, v in checked.items() if v]
        status.set(f"{len(items)} found. {len(sel)} selected ({human_size(sum(i.size for i in sel))}).")

    def set_all(value):
        for row in tree.get_children():
            checked[row] = value
            tree.set(row, "sel", "[x]" if value else "[ ]")
        refresh_status()

    def toggle(event):
        row = tree.identify_row(event.y)
        if row:
            checked[row] = not checked[row]
            tree.set(row, "sel", "[x]" if checked[row] else "[ ]")
            refresh_status()

    tree.bind("<Button-1>", toggle)

    def do_scan():
        nonlocal items
        try:
            hours = float(age_var.get())
        except ValueError:
            messagebox.showerror("Oops", "Hours has to be a number.")
            return
        status.set("Scanning...")
        root.update_idletasks()
        items = sorted(scan(targets, hours), key=lambda i: i.size, reverse=True)
        tree.delete(*tree.get_children())
        checked.clear()
        for idx, it in enumerate(items):
            row = tree.insert("", "end", iid=str(idx),
                              values=("[ ]", human_size(it.size), age_text(it.mtime), it.target, str(it.path)))
            checked[row] = False
        refresh_status()
        if not items:
            status.set("Nothing to clean. All good.")

    def do_delete():
        sel = [items[int(r)] for r, v in checked.items() if v]
        if not sel:
            messagebox.showinfo("Nothing selected", "Tick the files you want gone first.")
            return
        size = human_size(sum(i.size for i in sel))
        if not messagebox.askyesno("Are you sure?", f"Delete {len(sel)} files ({size})?\nThis can't be undone."):
            return
        freed, deleted, failed = delete_items(sel, targets)
        msg = f"Deleted {deleted} files, freed {human_size(freed)}."
        if failed:
            msg += f"\nSkipped {len(failed)} that were in use or protected."
        messagebox.showinfo("Done", msg)
        do_scan()

    scan_btn.config(command=do_scan)
    delete_btn.config(command=do_delete)
    root.mainloop()


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Find and remove temp files safely.")
    ap.add_argument("--scan", action="store_true", help="list temp files, delete nothing")
    ap.add_argument("--delete", action="store_true", help="delete what the scan finds (asks first)")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation question")
    ap.add_argument("--age", type=float, default=24.0, help="skip files newer than this many hours (default 24)")
    ap.add_argument("--target", nargs="+", help='only these locations, e.g. "User Temp"')
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args()

    if args.scan or args.delete:
        sys.exit(run_cli(args))
    run_gui()


if __name__ == "__main__":
    main()
