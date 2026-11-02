"""Temp Remover - clears temp files, crash dumps, Windows Update leftovers and the Recycle Bin.

Opens a window. It shows what it found, you tick what to clear, it asks, then it deletes.
Files in use are skipped. Run as administrator to include Windows' own temp folders.
Command line:  python temp_remover.py            window
               python temp_remover.py --delete   text mode: preview, then asks before deleting
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import removercore as rc  # noqa: E402
import syscore  # noqa: E402

SKIP_PROFILES = {"all users", "default", "default user", "public", "defaultuser0"}


def profiles() -> list[Path]:
    users = Path(os.environ.get("SYSTEMDRIVE", "C:") + "\\", "Users")
    out = []
    try:
        for p in users.iterdir():
            if p.is_dir() and not p.is_symlink() and p.name.lower() not in SKIP_PROFILES:
                out.append(p)
    except OSError:
        pass
    return out


def find_roots() -> list[rc.Root]:
    sysdrive = os.environ.get("SYSTEMDRIVE", "C:") + "\\"
    windir = Path(os.environ.get("SYSTEMROOT", sysdrive + "Windows"))
    roots: list[rc.Root] = []
    for p in profiles():
        roots.append(rc.Root(str(p / "AppData/Local/Temp"), f"Temp files ({p.name})",
                             "Apps' scratch files. They are made again when needed.", 2))
        roots.append(rc.Root(str(p / "AppData/Local/CrashDumps"), "Crash dumps",
                             "Only useful for diagnosing a crash.", 0))
        roots.append(rc.Root(str(p / "AppData/Local/Microsoft/Windows/WER"), "Error reports",
                             "Windows error-report leftovers.", 0))
    roots.append(rc.Root(str(windir / "Temp"), "Windows temp files", "Leftovers from installs and updates.", 2))
    roots.append(rc.Root(str(windir / "SoftwareDistribution/Download"), "Windows Update downloads",
                         "Update files Windows already installed.", 0))
    roots.append(rc.Root(str(windir / "Minidump"), "Crash dumps", "Only useful for diagnosing a crash.", 0))
    roots.append(rc.Root(str(windir / "LiveKernelReports"), "Crash dumps", "Only useful for diagnosing a crash.", 0))
    roots.append(rc.Root(str(Path(sysdrive) / "ProgramData/Microsoft/Windows/WER"), "Error reports",
                         "Windows error-report leftovers.", 0))
    scan, _ignored = syscore.pick_drives(__file__)
    for d in scan:
        roots.append(rc.Root(d + "$Recycle.Bin", f"Recycle Bin ({d[:2]})", "Files you already deleted.", 0, prune=False))
    return roots


SPEC = rc.Spec(
    key="temp",
    title="Temp Remover",
    intro="Clears temp files, crash dumps, Windows Update leftovers and the Recycle Bin. "
          "Only places that are safe to clear are ever touched.",
    find_roots=find_roots,
    tip="Close your programs first. Files that are in use are skipped. Run as administrator for the full clean.",
)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        try:
            import tkinter  # noqa: F401
        except ImportError:
            return rc.console(SPEC, [])
        import remover_gui
        return remover_gui.run(SPEC, HERE)
    return rc.console(SPEC, argv)


if __name__ == "__main__":
    sys.exit(main())
