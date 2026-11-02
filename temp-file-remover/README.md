# Temp File Remover

A small, safe tool that finds junk temp files, shows you the whole list, and only deletes what you pick.

No installs. Pure Python standard library.

## Why it's safe

- Nothing gets deleted until you review the list and confirm.
- Skips files newer than 24 hours (adjustable), since apps may still be using them.
- Locked or in-use files are skipped, never forced.
- Never follows symlinks.
- Can only touch files inside the known temp folders.

## What it scans

- User Temp folder (all systems)
- On Windows also: Internet Cache, Crash Dumps, Error Reports, Windows Temp (Windows Temp needs admin to fully clean)

## How to run

**Windows (easiest):** double-click `Run Temp File Remover.bat`

**Or from a terminal:**

```
python temp_file_remover.py                 # opens the window
python temp_file_remover.py --scan          # list only, deletes nothing
python temp_file_remover.py --delete        # list, then asks before deleting
python temp_file_remover.py --age 48        # only files older than 48 hours
python temp_file_remover.py --target "User Temp"
```

Needs Python 3.8 or newer. The window uses tkinter, which ships with Python on Windows and macOS.

## Tests

```
python -m unittest -v
```

## License

MIT
