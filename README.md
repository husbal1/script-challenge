# 🔄 Incremental Directory Backup

A zero-dependency Python script that performs automated incremental backups of a directory on a configurable interval. Runs on any vanilla Linux/Unix system with Python 3.6+.

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
curl -O https://github.com/husbal1/script-challenge/blob/main/backup.py
chmod +x backup.py

# Run (backs up every 60 seconds by default)
python3 backup.py /path/to/source /path/to/backup
```

Stop anytime with Ctrl+C.

## Usage

```bash
usage: backup.py [-h] [-i SEC] [-l FILE] [-v] source backup
```

| Argument     | Short | Default    | Description                    |
|--------------|-------|------------|--------------------------------|
| `source`     | —     | required   | Directory to back up           |
| `backup`     | —     | required   | Destination backup directory   |
| `--interval` | `-i`  | `60`       | Seconds between backup cycles  |
| `--log-file` | `-l`  | `None`     | Path to persistent log file    |
| `--verbose`  | `-v`  | Off        | Enable DEBUG-level output      |

Examples:

# Custom interval (every 2 minutes) with log file
```bash
python3 backup.py /var/www/html /backup/www --interval 120 --log-file /var/log/backup.log
```
# Verbose mode
```bash
python3 backup.py ./src ./src_backup -v
```
# Run in background
```bash
nohup python3 backup.py /data /backup/data --log-file /var/log/backup.log &
```

## How It Works
Each cycle runs six phases:

- Mirror directories — create any new subdirectories from source
- Copy new files — files not yet in backup
- Update changed files — detected via size/mtime, confirmed via SHA-256 when ambiguous
- Remove deleted files — files no longer in source
- Remove deleted directories — deepest first to avoid conflicts
- Save manifest — atomic write of .backup_manifest.json tracking all file metadata
- Unchanged files are skipped entirely after a single O(1) stat() call.

## Sample Output

```bash
2025-04-27 13:17:51 [INFO] Incremental backup started
2025-04-27 13:17:51 [INFO]   Source   : /home/user/project
2025-04-27 13:17:51 [INFO]   Backup   : /mnt/backup/project
2025-04-27 13:17:51 [INFO]   Interval : 60 seconds
2025-04-27 13:17:51 [INFO] Press Ctrl+C to stop.

2025-04-27 13:17:51 [INFO] --- Backup cycle #1 starting ---
2025-04-27 13:17:51 [INFO] CREATED (dir):  src/
2025-04-27 13:17:51 [INFO] COPIED  (new):  README.md
2025-04-27 13:17:51 [INFO] COPIED  (new):  src/main.py
2025-04-27 13:17:51 [INFO] UPDATED:        src/utils.py
2025-04-27 13:17:51 [INFO] DELETED (file): old_config.yaml
2025-04-27 13:17:51 [INFO] Cycle completed in 0.03 seconds.

============================================================
  Backup Cycle Completed - 2025-04-27 13:17:51 UTC
============================================================
  New files copied   : 2
  Files updated      : 1
  Files deleted      : 1
  Dirs created       : 1
  Dirs removed       : 0
  Errors             : 0
============================================================
  [NEW DIRS]
    + src/
  [NEW FILES]
    + README.md
    + src/main.py
  [UPDATED FILES]
    ~ src/utils.py
  [DELETED FILES]
    - old_config.yaml
```


## Restoring from Backup

The backup directory is an exact mirror of the source:
```bash
cp -a /backup/project/* /home/user/project/
```


