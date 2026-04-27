


# 🔄 Incremental Directory Backup

A zero-dependency Python script that performs automated incremental backups of a directory on a configurable interval. Runs on any vanilla Linux/Unix system with Python 3.6+.

![Python](https://img.shields.io/badge/Python-3.6%2B-blue?logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)
![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20macOS%20%7C%20BSD-lightgrey)
![Dependencies](https://img.shields.io/badge/Dependencies-None-brightgreen)

---

## Features

- **Incremental** — only new, modified, or deleted files are processed each cycle
- **Directory structure preservation** — full tree mirrored, including empty directories
- **Two-tier change detection** — fast `size + mtime` check, SHA-256 fallback only when needed
- **Deletion tracking** — files and directories removed from source are cleaned from backup
- **Atomic state file** — crash-safe manifest via `tmp` then `os.replace()`
- **Graceful shutdown** — `Ctrl+C` finishes the current cycle before exiting
- **Log rotation** — capped at 50 MB (10 MB x 5 rotations) to prevent disk fill
- **Detailed logging** — timestamped logs to stderr, optional log file, and summary to stdout

---

## Quick Start

```bash
# Download
curl -O https://raw.githubusercontent.com/yourusername/incremental-backup/main/backup.py
chmod +x backup.py

# Run (backs up every 60 seconds by default)
python3 backup.py /path/to/source /path/to/backup
```

Stop anytime with Ctrl+C.


