"""Shared rules for System Care. The checker and every remover use this same file.

It answers two questions about any folder on a Windows PC:
  * what kind of place is it?   (tag: SAFE / CHECK / REVIEW / LEAVE / PROGRAM / OTHER)
  * which remover owns it?       (temp / cache / installer / none)

One copy of this file ships in every System Care folder (master: _core).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

VERSION = "1.0.0"
IS_WIN = os.name == "nt"

SAFE = "SAFE"        # regenerates by itself, safe to clear
CHECK = "CHECK"      # safe only after checking each item (Windows Installer cache)
REVIEW = "REVIEW"    # your own files: you decide
LEAVE = "LEAVE"      # Windows itself: never touch
PROGRAM = "PROGRAM"  # installed programs and their data: remove through Settings > Apps
OTHER = "OTHER"

TAG_TEXT = {
    SAFE: "Safe to clear", CHECK: "Check first", REVIEW: "Your call",
    LEAVE: "Leave alone", PROGRAM: "Programs", OTHER: "Other",
}

CACHE_NAMES = frozenset({
    "cache", "code cache", "gpucache", "cache_data", "cachestorage", "scriptcache",
    "shadercache", "grshadercache", "dawngraphitecache", "dawnwebgpucache", "cache2",
})
SYSTEM_FILES = frozenset({"pagefile.sys", "hiberfil.sys", "swapfile.sys"})


def fmt(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


@dataclass(frozen=True)
class Rule:
    pattern: re.Pattern
    tag: str
    remover: str
    label: str
    why: str


END = r"(\\|$)"
USER = r"^\\users\\[^\\]+"
_names = "|".join(re.escape(n) for n in sorted(CACHE_NAMES, key=len, reverse=True))


def _r(pattern: str, tag: str, remover: str, label: str, why: str) -> Rule:
    return Rule(re.compile(pattern), tag, remover, label, why)


# Order matters: the first rule that matches wins, so specific rules come first.
RULES: list[Rule] = [
    _r(r"^\\windows\\temp" + END, SAFE, "temp", "Windows temp files", "Leftovers from installs and updates."),
    _r(USER + r"\\appdata\\local\\temp" + END, SAFE, "temp", "User temp files", "Apps' scratch files. They are made again when needed."),
    _r(r"^\\windows\\softwaredistribution\\download" + END, SAFE, "temp", "Windows Update downloads", "Already-installed update files."),
    _r(r"^\\windows\\(minidump|livekernelreports)" + END, SAFE, "temp", "Crash dumps", "Only useful for diagnosing a crash."),
    _r(r"^\\programdata\\microsoft\\windows\\wer" + END, SAFE, "temp", "Error reports", "Windows error-report leftovers."),
    _r(USER + r"\\appdata\\local\\(crashdumps|microsoft\\windows\\wer)" + END, SAFE, "temp", "Crash dumps", "Only useful for diagnosing a crash."),
    _r(r"^\\\$recycle\.bin" + END, SAFE, "temp", "Recycle Bin", "Files you already deleted."),
    _r(r"^\\programdata\\adobe\\arm" + END, SAFE, "cache", "Adobe update downloads", "Acrobat re-downloads what it needs."),
    _r(USER + r"\\appdata\\local\\ringcentral-updater" + END, SAFE, "cache", "RingCentral update downloads", "Downloaded updates waiting to install."),
    _r(USER + r"\\appdata\\local\\microsoft\\windows\\inetcache" + END, SAFE, "cache", "Internet cache", "Web pages Windows saved."),
    _r(USER + r"\\appdata\\(local|roaming)\\(npm-cache)" + END, SAFE, "cache", "npm cache", "Re-downloads when needed."),
    _r(USER + r"\\appdata\\(local|roaming|locallow)\\(.*\\)?(" + _names + r")" + END, SAFE, "cache", "App caches", "Saved copies an app rebuilds itself."),
    _r(r"^\\windows\\installer" + END, CHECK, "installer", "Windows Installer cache", "Safe only for files no program uses. Installer Remover checks each one."),
    _r(r"^\\windows\.old" + END, REVIEW, "", "Windows.old", "Your previous Windows. Remove it with Windows' own Disk Cleanup."),
    _r(r"^\\system volume information" + END, LEAVE, "", "System restore points", "Windows restore points."),
    _r(r"^\\windows\\winsxs" + END, LEAVE, "", "Windows components", "Trim it safely with DISM, never by hand."),
    _r(r"^\\program files\\windowsapps" + END, LEAVE, "", "Store apps", "Managed by Windows."),
    _r(r"^\\(windows|recovery|boot|efi|\$winreagent)" + END, LEAVE, "", "Windows system", "Windows needs this."),
    _r(r"^\\program files( \(x86\))?" + END, PROGRAM, "", "Installed programs", "Remove through Settings > Apps."),
    _r(r"^\\programdata" + END, PROGRAM, "", "Program data", "Settings and data for installed programs."),
    _r(USER + r"\\(documents|desktop|downloads|pictures|videos|music|onedrive[^\\]*|dropbox|google drive)" + END,
       REVIEW, "", "Your files", "Your own files. You decide."),
    _r(USER + r"\\appdata" + END, PROGRAM, "", "App settings and data", "Settings and saved data for your apps."),
    _r(r"^\\users" + END, OTHER, "", "Other user files", ""),
]
DEFAULT = Rule(re.compile(""), OTHER, "", "Other", "")


def norm(path: str, base: str = "") -> str:
    """Windows-style, lower case, without the drive letter (or without `base`)."""
    p = path.replace("/", "\\")
    b = base.replace("/", "\\").rstrip("\\")
    p = p[len(b):] if b and p.lower().startswith(b.lower()) else re.sub(r"^[A-Za-z]:", "", p)
    p = p.lower().rstrip("\\")
    return p if p.startswith("\\") else "\\" + p


def classify_dir(path: str, base: str = "") -> Rule:
    p = norm(path, base)
    for rule in RULES:
        if rule.pattern.search(p):
            return rule
    return DEFAULT


def classify_file(name: str) -> Rule | None:
    if name.lower() in SYSTEM_FILES:
        return Rule(re.compile(""), LEAVE, "", "Windows system file", "Windows uses this file. Never delete it.")
    return None


# ------------------------------------------------------------------------------ drives
def local_drives() -> list[tuple[str, str]]:
    """[(root, kind)] for fixed and removable drives. Network and CD drives are skipped."""
    if not IS_WIN:
        return [("/", "fixed")]
    import ctypes

    out: list[tuple[str, str]] = []
    kernel = ctypes.windll.kernel32  # ty: ignore[unresolved-attribute]
    mask = kernel.GetLogicalDrives()
    for i in range(26):
        if mask & (1 << i):
            root = f"{chr(65 + i)}:\\"
            kind = kernel.GetDriveTypeW(root)
            if kind == 3:
                out.append((root, "fixed"))
            elif kind == 2:
                out.append((root, "removable"))
    return out


def pick_drives(script_path: str, drives: list[tuple[str, str]] | None = None,
                system_drive: str | None = None, include_all: bool = False) -> tuple[list[str], list[str]]:
    """Which drives to scan and which to ignore.

    The drive this program runs from (the Py Apps drive), or any drive with a 'Py Apps' folder
    at its top, is ignored. The Windows drive is never ignored. If that would leave nothing to scan,
    everything is scanned.
    """
    drives = drives if drives is not None else local_drives()
    sysd = (system_drive or os.environ.get("SYSTEMDRIVE", "C:")).upper().rstrip("\\") + "\\"
    m = re.match(r"^[A-Za-z]:", script_path if re.match(r"^[A-Za-z]:", script_path) else os.path.abspath(script_path))
    mine = (m.group(0).upper() + "\\") if m else ""
    scan: list[str] = []
    ignored: list[str] = []
    for root, _kind in drives:
        r = root.upper()
        has_py = os.path.isdir(os.path.join(root, "Py Apps"))
        if not include_all and r != sysd and (r == mine or has_py):
            ignored.append(root)
        else:
            scan.append(root)
    if not scan:
        return [r for r, _ in drives], []
    return scan, ignored


# ---------------------------------------------------------------------------- programs
JUNK_PROGRAMS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"driver (support|updater|booster|easy|talent|genius)|driversupport|drivermax", re.I), "junk",
     "Driver-updater programs are junk. Windows Update handles drivers."),
    (re.compile(r"mcafee", re.I), "junk", "Trial antivirus nagware. Windows Security already protects the PC."),
    (re.compile(r"pc (cleaner|optimi[sz]er|speed|booster)|registry (cleaner|fix)|tuneup|reimage|cleanmypc|systweak|advanced systemcare|iobit|ccleaner", re.I),
     "junk", "'Cleaner' programs rarely help and often cause problems."),
    (re.compile(r"customer (research|experience|improvement) (participation|program)", re.I), "junk",
     "Sends usage data. Not needed."),
    (re.compile(r"ask toolbar|babylon|conduit|mywebsearch|search protect|wildtangent|candy crush", re.I), "junk",
     "Unwanted extra."),
    (re.compile(r"epson.*(user.?s guide|photo\+|software updater|easy photo scan|event manager)", re.I), "review",
     "Optional printer extra. Keep the driver and scanner software."),
    (re.compile(r"gotomeeting|goto opener", re.I), "review", "Old meeting app. Remove it if you don't use it."),
    (re.compile(r"^copilot$|microsoft copilot", re.I), "review", "Optional. About 1 GB."),
]


def flag_program(name: str) -> tuple[str, str] | None:
    for pat, level, why in JUNK_PROGRAMS:
        if pat.search(name):
            return level, why
    return None
