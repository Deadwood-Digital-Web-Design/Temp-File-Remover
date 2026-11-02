"""Shared engine for the System Care removers (Temp, Cache). Master copy lives in _core.

A remover describes WHERE to look (roots). This engine does the rest:
  plan()     list what would go, grouped, without touching anything
  execute()  delete the chosen groups, skip anything in use, write a log

Safety rules built in:
  * Only folders that syscore calls SAFE for that remover can ever be cleared.
  * Preview first. Nothing is deleted without an explicit choice.
  * Symlinks and junctions are never followed.
  * Files in use are skipped, never forced.
"""
from __future__ import annotations

import contextlib
import datetime
import math
import os
import stat
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import syscore

DAY = 86400


@dataclass
class Root:
    path: str
    group: str
    why: str = ""
    min_age_days: float = 1.0
    prune: bool = True


@dataclass
class Spec:
    key: str            # "temp" or "cache"
    title: str
    intro: str
    find_roots: Callable[[], list[Root]]
    tip: str = ""
    guard: Callable[[str], bool] | None = None   # tests only; real removers use the safe list


@dataclass
class Group:
    label: str
    why: str = ""
    files: list[tuple[str, int]] = field(default_factory=list)
    roots: list[Root] = field(default_factory=list)

    @property
    def size(self) -> int:
        return sum(s for _, s in self.files)


@dataclass
class Plan:
    groups: dict[str, Group] = field(default_factory=dict)
    refused: list[str] = field(default_factory=list)
    unreadable: int = 0


@dataclass
class Result:
    deleted_files: int = 0
    deleted_bytes: int = 0
    in_use: int = 0
    errors: list[str] = field(default_factory=list)
    log_path: str = ""


def _is_link(path: str) -> bool:
    try:
        if os.path.islink(path):
            return True
        junction = getattr(os.path, "isjunction", None)
        return bool(junction and junction(path))
    except OSError:
        return True


def default_guard(key: str) -> Callable[[str], bool]:
    def guard(path: str) -> bool:
        drive = os.path.splitdrive(path)[0]
        base = drive + "\\" if drive else ""
        rule = syscore.classify_dir(path, base)
        return rule.tag == syscore.SAFE and rule.remover == key
    return guard


def plan(spec: Spec, guard: Callable[[str], bool] | None = None, now: float | None = None,
         progress: Callable[[int], None] | None = None) -> Plan:
    guard = guard or spec.guard or default_guard(spec.key)
    now = time.time() if now is None else now
    out = Plan()
    seen = 0
    for root in spec.find_roots():
        if not os.path.isdir(root.path) or _is_link(root.path):
            continue
        if not guard(root.path):
            out.refused.append(root.path)
            continue
        cutoff = now - root.min_age_days * DAY
        group = out.groups.setdefault(root.group, Group(root.group, root.why))
        group.roots.append(root)

        def onerr(_exc: OSError) -> None:
            out.unreadable += 1

        for dirpath, dirnames, filenames in os.walk(root.path, topdown=True, onerror=onerr, followlinks=False):
            dirnames[:] = [d for d in dirnames if not _is_link(os.path.join(dirpath, d))]
            for name in filenames:
                full = os.path.join(dirpath, name)
                try:
                    st = os.lstat(full)
                except OSError:
                    out.unreadable += 1
                    continue
                if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
                    continue
                if st.st_mtime > cutoff:
                    continue
                group.files.append((full, st.st_size))
                seen += 1
                if progress and seen % 2000 == 0:
                    progress(seen)
    out.groups = {k: g for k, g in out.groups.items() if g.files}
    return out


def delete_file(path: str) -> bool:
    try:
        os.unlink(path)
        return True
    except PermissionError:
        with contextlib.suppress(OSError):
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        try:
            os.unlink(path)
            return True
        except OSError:
            return False
    except FileNotFoundError:
        return True
    except OSError:
        return False


def execute(p: Plan, chosen: set[str] | None, log_dir: Path, name: str,
            progress: Callable[[int, int], None] | None = None) -> Result:
    res = Result()
    groups = [g for k, g in p.groups.items() if chosen is None or k in chosen]
    total = sum(len(g.files) for g in groups)
    done = 0
    deleted_paths: list[tuple[str, int]] = []
    for g in groups:
        for path, size in g.files:
            if delete_file(path):
                res.deleted_files += 1
                res.deleted_bytes += size
                deleted_paths.append((path, size))
            else:
                res.in_use += 1
            done += 1
            if progress and done % 200 == 0:
                progress(done, total)
        for root in g.roots:
            if root.prune:
                prune_empty(root.path)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        lp = log_dir / f"{name}_{stamp}.txt"
        lines = [f"{name} {datetime.datetime.now():%Y-%m-%d %H:%M}",
                 f"Deleted {res.deleted_files} files, {syscore.fmt(res.deleted_bytes)}. Skipped (in use): {res.in_use}", ""]
        lines += [f"{syscore.fmt(s):>10}  {pth}" for pth, s in deleted_paths[:20000]]
        lp.write_text("\n".join(lines), encoding="utf-8")
        res.log_path = str(lp)
    except OSError as exc:
        res.errors.append(f"could not write log: {exc}")
    return res


def prune_empty(root: str) -> None:
    """Remove empty sub-folders (never the root itself)."""
    for dirpath, _dirs, _files in os.walk(root, topdown=False):
        if dirpath == root or _is_link(dirpath):
            continue
        with contextlib.suppress(OSError):
            os.rmdir(dirpath)


def summary_lines(p: Plan) -> list[str]:
    rows = sorted(p.groups.values(), key=lambda g: g.size, reverse=True)
    lines = [f"{syscore.fmt(g.size):>10}  {len(g.files):>7,} files  {g.label}" for g in rows]
    total = sum(g.size for g in rows)
    lines.append(f"{syscore.fmt(total):>10}  {sum(len(g.files) for g in rows):>7,} files  TOTAL")
    return lines


def console(spec: Spec, argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=spec.title)
    ap.add_argument("--delete", action="store_true", help="delete after showing the preview (asks first)")
    ap.add_argument("--age", type=float, help="only files older than this many days (default: per folder)")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
    if args.age is not None and (not math.isfinite(args.age) or args.age < 0):
        ap.error("--age must be 0 or more")
    find = spec.find_roots
    if args.age is not None:
        def find() -> list[Root]:
            rs = spec.find_roots()
            for r in rs:
                r.min_age_days = args.age
            return rs
    work = Spec(spec.key, spec.title, spec.intro, find, spec.tip, spec.guard)
    print(f"\n{spec.title}\n{spec.intro}\n")
    print("Looking ...", flush=True)
    p = plan(work, progress=lambda n: print(f"  ... {n:,} files", flush=True))
    if not p.groups:
        print("Nothing to clear. All clean.")
        return 0
    print("\n".join(summary_lines(p)))
    if p.refused:
        print(f"\n{len(p.refused)} folders were skipped because they are not on the safe list.")
    if p.unreadable:
        print(f"{p.unreadable} places could not be read (run as administrator for more).")
    if spec.tip:
        print(f"\nTip: {spec.tip}")
    if not args.delete:
        print("\nPreview only. Nothing was deleted. Run again with --delete to clear it.")
        return 0
    if input("\nType YES to delete everything listed above: ").strip() != "YES":
        print("Cancelled. Nothing was deleted.")
        return 0
    res = execute(p, None, Path(__file__).resolve().parent / "logs", spec.key)
    print(f"\nDeleted {res.deleted_files:,} files and freed {syscore.fmt(res.deleted_bytes)}."
          f" {res.in_use:,} were in use and skipped.")
    if res.log_path:
        print(f"Log: {res.log_path}")
    return 0
