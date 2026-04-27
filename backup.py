#!/usr/bin/env python3
"""
Incremental Directory Backup Script
====================================

Performs incremental backups of a source directory to a backup directory
every 60 seconds. Only new, modified, or deleted files AND directories
are processed on each cycle, preserving the original directory structure.

Usage:
    python3 backup.py /path/to/source /path/to/backup
    python3 backup.py /path/to/source /path/to/backup --interval 120 --log-file backup.log
    python3 backup.py --help

The script runs continuously until interrupted with Ctrl+C.

Requirements:
    Python 3.6+ on any vanilla Linux/Unix system. No third-party packages.
"""

import argparse
import hashlib
import json
import logging
import logging.handlers  # FIX: added for RotatingFileHandler
import os
import shutil
import signal
import sys
import time
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_INTERVAL_SEC = 60
MANIFEST_FILENAME = ".backup_manifest.json"
HASH_CHUNK_SIZE = 65536
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_MAX_BYTES = 10 * 1024 * 1024  # FIX: 10 MB per log file
LOG_BACKUP_COUNT = 5               # FIX: keep 5 rotated log files

# ---------------------------------------------------------------------------
# Graceful shutdown helper
# ---------------------------------------------------------------------------

_shutdown_requested = False


def _signal_handler(signum, _frame):
    """Handle SIGINT / SIGTERM so the current cycle can finish cleanly."""
    global _shutdown_requested
    _shutdown_requested = True
    logging.info(
        "Shutdown signal received (signal %s). Will exit after current cycle.",
        signum,
    )


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def file_checksum(filepath: str) -> str:
    """Return the SHA-256 hex digest of *filepath*.

    Reading in chunks keeps memory usage constant regardless of file size.
    """
    sha = hashlib.sha256()
    try:
        with open(filepath, "rb") as fh:
            while True:
                chunk = fh.read(HASH_CHUNK_SIZE)
                if not chunk:
                    break
                sha.update(chunk)
    except OSError as exc:
        # FIX: log the failure instead of silent empty return
        logging.warning("Could not hash file '%s': %s", filepath, exc)
        return ""
    return sha.hexdigest()


def file_metadata(filepath: str) -> dict:
    """Return a small metadata dict used for fast change detection."""
    try:
        stat = os.stat(filepath)
        return {
            "mtime": stat.st_mtime,
            "size": stat.st_size,
        }
    except OSError as exc:
        # FIX: log instead of silently returning empty dict
        logging.debug("Could not stat file '%s': %s", filepath, exc)
        return {}


def files_are_equal(src: str, dst: str) -> bool:
    """Quick check: size + mtime, falling back to SHA-256 if mtime differs."""
    src_meta = file_metadata(src)
    dst_meta = file_metadata(dst)
    if not src_meta or not dst_meta:
        # FIX: explicit log — caller will treat as "needs copy"
        logging.debug(
            "Metadata unavailable for comparison: src='%s' dst='%s'", src, dst
        )
        return False
    # Fast path – identical size *and* mtime.
    if (
        src_meta["size"] == dst_meta["size"]
        and src_meta["mtime"] == dst_meta["mtime"]
    ):
        return True
    # Size differs → definitely changed.
    if src_meta["size"] != dst_meta["size"]:
        return False
    # Same size but different mtime → compare content hashes.
    return file_checksum(src) == file_checksum(dst)


def _cleanup_failed_copy(dst_path: str) -> None:
    """FIX: Remove a partially written file left behind by a failed copy."""
    try:
        if os.path.exists(dst_path):
            os.remove(dst_path)
            logging.debug("Cleaned up partial file: %s", dst_path)
    except OSError as exc:
        logging.warning("Could not clean up partial file '%s': %s", dst_path, exc)


# ---------------------------------------------------------------------------
# Manifest (state) management
# ---------------------------------------------------------------------------


def load_manifest(backup_dir: str) -> dict:
    """Load the previous-run manifest from the backup directory.

    The manifest stores two keys:
        "files" – dict mapping relative file paths  -> metadata
        "dirs"  – list of relative directory paths

    An empty structure is returned when no manifest exists (first run).
    """
    manifest_path = os.path.join(backup_dir, MANIFEST_FILENAME)
    if not os.path.isfile(manifest_path):
        logging.debug("No existing manifest found — treating as first run.")
        return {"files": {}, "dirs": []}
    try:
        with open(manifest_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        # Handle legacy flat manifests from a previous version
        if "files" not in data:
            logging.info("Migrating legacy flat manifest to new format.")
            return {"files": data, "dirs": []}
        return data
    except (json.JSONDecodeError, OSError) as exc:
        # FIX: more explicit about the consequence
        logging.warning(
            "Corrupt or unreadable manifest (%s) — "
            "starting fresh (next cycle will be a full sync): %s",
            manifest_path,
            exc,
        )
        return {"files": {}, "dirs": []}


def save_manifest(backup_dir: str, manifest: dict) -> bool:
    """Atomically persist the manifest to disk.

    FIX: Returns True on success, False on failure so caller can track it.
    """
    manifest_path = os.path.join(backup_dir, MANIFEST_FILENAME)
    tmp_path = manifest_path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2)
        os.replace(tmp_path, manifest_path)
        logging.debug("Manifest saved successfully (%d files tracked).", len(manifest.get("files", {})))
        return True
    except OSError as exc:
        logging.error(
            "Failed to write manifest to '%s': %s. "
            "Next cycle will perform a full re-sync.",
            manifest_path,
            exc,
        )
        # FIX: clean up tmp file if it was written
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        return False


# ---------------------------------------------------------------------------
# Source scanning — FIX: fully wrapped in error handling
# ---------------------------------------------------------------------------


def scan_source(source_dir: str) -> tuple:
    """Walk *source_dir* and return (set_of_rel_dirs, dict_of_rel_files, list_of_errors).

    FIX: Every OS error is caught and accumulated — one unreadable subdirectory
    does NOT abort the entire scan.
    """
    rel_dirs = set()
    rel_files = {}
    scan_errors = []

    def _on_walk_error(err):
        """Callback invoked by os.walk when it cannot list a directory."""
        rel = os.path.relpath(err.filename, source_dir)
        logging.error("Cannot access directory '%s': %s", rel, err.strerror)
        scan_errors.append(rel)

    for dirpath, dirnames, filenames in os.walk(source_dir, onerror=_on_walk_error):
        # Record every sub-directory (even empty ones)
        for dname in dirnames:
            try:
                abs_dir = os.path.join(dirpath, dname)
                rel_dir = os.path.relpath(abs_dir, source_dir)
                rel_dirs.add(rel_dir)
            except (ValueError, OSError) as exc:
                logging.error("Error processing directory '%s': %s", dname, exc)
                scan_errors.append(dname)

        for fname in filenames:
            try:
                abs_path = os.path.join(dirpath, fname)
                rel_path = os.path.relpath(abs_path, source_dir)
                rel_files[rel_path] = abs_path
            except (ValueError, OSError) as exc:
                logging.error("Error processing file '%s': %s", fname, exc)
                scan_errors.append(fname)

    if scan_errors:
        logging.warning(
            "Source scan completed with %d error(s). Affected paths were skipped.",
            len(scan_errors),
        )

    return rel_dirs, rel_files, scan_errors


# ---------------------------------------------------------------------------
# Core backup logic
# ---------------------------------------------------------------------------


def perform_backup(source_dir: str, backup_dir: str) -> dict:
    """Execute one incremental backup cycle.

    Returns a summary dict with lists of copied, updated, deleted files
    and created / removed directories.
    """
    cycle_start = time.monotonic()  # FIX: track cycle duration

    summary = {
        "timestamp": datetime.now(timezone.utc).strftime(DATE_FORMAT + " UTC"),
        "copied": [],
        "updated": [],
        "deleted": [],
        "dirs_created": [],
        "dirs_removed": [],
        "errors": [],
    }

    # FIX: verify source is still accessible at start of each cycle
    if not os.path.isdir(source_dir):
        logging.error(
            "Source directory '%s' is no longer accessible. Skipping cycle.",
            source_dir,
        )
        summary["errors"].append("SOURCE_UNAVAILABLE")
        return summary

    old_manifest = load_manifest(backup_dir)
    old_files = old_manifest["files"]
    old_dirs = set(old_manifest["dirs"])

    current_dirs, current_files, scan_errors = scan_source(source_dir)
    summary["errors"].extend(scan_errors)
    new_file_manifest = {}

    # ------------------------------------------------------------------
    # Phase 1: Mirror directories (create new ones)
    # ------------------------------------------------------------------
    for rel_dir in sorted(current_dirs):
        dst_dir = os.path.join(backup_dir, rel_dir)
        if not os.path.isdir(dst_dir):
            try:
                os.makedirs(dst_dir, exist_ok=True)
                summary["dirs_created"].append(rel_dir)
                logging.info("CREATED (dir):  %s/", rel_dir)
            except OSError as exc:
                logging.error(
                    "Failed to create directory '%s': %s", dst_dir, exc
                )
                summary["errors"].append(rel_dir + "/")

    # ------------------------------------------------------------------
    # Phase 2: Copy new files / update changed files
    # ------------------------------------------------------------------
    for rel_path, src_path in current_files.items():
        dst_path = os.path.join(backup_dir, rel_path)
        meta = file_metadata(src_path)
        if not meta:
            logging.warning(
                "Skipping file '%s': unable to read metadata.", rel_path
            )
            summary["errors"].append(rel_path)
            continue

        new_file_manifest[rel_path] = meta

        try:
            if not os.path.exists(dst_path):
                os.makedirs(os.path.dirname(dst_path), exist_ok=True)
                shutil.copy2(src_path, dst_path)
                summary["copied"].append(rel_path)
                logging.info("COPIED  (new):  %s", rel_path)

            elif not files_are_equal(src_path, dst_path):
                shutil.copy2(src_path, dst_path)
                summary["updated"].append(rel_path)
                logging.info("UPDATED:        %s", rel_path)

        except FileNotFoundError:
            # FIX: source file disappeared between scan and copy (race condition)
            logging.warning(
                "File '%s' disappeared before it could be copied (race condition).",
                rel_path,
            )
            summary["errors"].append(rel_path)
        except PermissionError as exc:
            # FIX: explicit permission error handling
            logging.error("Permission denied copying '%s': %s", rel_path, exc)
            _cleanup_failed_copy(dst_path)
            summary["errors"].append(rel_path)
        except OSError as exc:
            # FIX: catch disk-full and other OS errors, clean up partial file
            logging.error(
                "Failed to copy '%s' -> '%s': %s", src_path, dst_path, exc
            )
            _cleanup_failed_copy(dst_path)
            summary["errors"].append(rel_path)

    # ------------------------------------------------------------------
    # Phase 3: Detect and remove deleted files
    # ------------------------------------------------------------------
    deleted_files = set(old_files.keys()) - set(new_file_manifest.keys())
    for rel_path in sorted(deleted_files):
        dst_path = os.path.join(backup_dir, rel_path)
        try:
            if os.path.exists(dst_path):
                os.remove(dst_path)
            summary["deleted"].append(rel_path)
            logging.info("DELETED (file): %s", rel_path)
        except OSError as exc:
            logging.error("Failed to delete '%s': %s", dst_path, exc)
            summary["errors"].append(rel_path)

    # ------------------------------------------------------------------
    # Phase 4: Detect and remove deleted directories (deepest first)
    # ------------------------------------------------------------------
    deleted_dirs = old_dirs - current_dirs
    for rel_dir in sorted(
        deleted_dirs, key=lambda p: p.count(os.sep), reverse=True
    ):
        dst_dir = os.path.join(backup_dir, rel_dir)
        try:
            if os.path.isdir(dst_dir):
                shutil.rmtree(dst_dir)
            summary["dirs_removed"].append(rel_dir)
            logging.info("DELETED (dir):  %s/", rel_dir)
        except OSError as exc:
            logging.error(
                "Failed to remove directory '%s': %s", dst_dir, exc
            )
            summary["errors"].append(rel_dir + "/")

    # ------------------------------------------------------------------
    # Phase 5: Prune empty directories not in source
    # ------------------------------------------------------------------
    _prune_empty_dirs(backup_dir, current_dirs)

    # ------------------------------------------------------------------
    # Phase 6: Persist new manifest
    # ------------------------------------------------------------------
    manifest_saved = save_manifest(
        backup_dir,
        {"files": new_file_manifest, "dirs": sorted(current_dirs)},
    )
    if not manifest_saved:
        summary["errors"].append("MANIFEST_WRITE_FAILED")

    # FIX: log cycle duration
    elapsed = time.monotonic() - cycle_start
    logging.info("Cycle completed in %.2f seconds.", elapsed)

    return summary


def _prune_empty_dirs(backup_dir: str, source_dirs: set) -> None:
    """Remove directories in backup that are not in *source_dirs* and are empty."""
    for dirpath, dirnames, filenames in os.walk(backup_dir, topdown=False):
        if dirpath == backup_dir:
            continue
        rel_dir = os.path.relpath(dirpath, backup_dir)
        if rel_dir in source_dirs:
            continue
        remaining = [
            n for n in (filenames + dirnames) if n != MANIFEST_FILENAME
        ]
        if not remaining:
            try:
                os.rmdir(dirpath)
                # FIX: log instead of silent pass
                logging.debug("Pruned empty directory: %s", rel_dir)
            except OSError as exc:
                logging.debug(
                    "Could not prune directory '%s': %s", rel_dir, exc
                )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_summary(summary: dict) -> None:
    """Pretty-print the cycle summary to stdout."""
    border = "=" * 60
    print(f"\n{border}")
    print(f"  Backup Cycle Completed - {summary['timestamp']}")
    print(border)
    print(f"  New files copied   : {len(summary['copied'])}")
    print(f"  Files updated      : {len(summary['updated'])}")
    print(f"  Files deleted      : {len(summary['deleted'])}")
    print(f"  Dirs created       : {len(summary['dirs_created'])}")
    print(f"  Dirs removed       : {len(summary['dirs_removed'])}")
    print(f"  Errors             : {len(summary['errors'])}")
    print(border)

    if summary["dirs_created"]:
        print("  [NEW DIRS]")
        for d in summary["dirs_created"]:
            print(f"    + {d}/")
    if summary["copied"]:
        print("  [NEW FILES]")
        for f in summary["copied"]:
            print(f"    + {f}")
    if summary["updated"]:
        print("  [UPDATED FILES]")
        for f in summary["updated"]:
            print(f"    ~ {f}")
    if summary["dirs_removed"]:
        print("  [REMOVED DIRS]")
        for d in summary["dirs_removed"]:
            print(f"    - {d}/")
    if summary["deleted"]:
        print("  [DELETED FILES]")
        for f in summary["deleted"]:
            print(f"    - {f}")
    if summary["errors"]:
        print("  [ERRORS]")
        for f in summary["errors"]:
            print(f"    ! {f}")

    has_changes = any(
        summary[k]
        for k in ("copied", "updated", "deleted", "dirs_created", "dirs_removed")
    )
    if not has_changes and not summary["errors"]:
        print("  (no changes detected)")
    print()


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_args(argv=None) -> argparse.Namespace:
    """Parse and validate CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Incremental directory backup running on a fixed interval.",
        epilog="Example: %(prog)s /home/user/docs /mnt/backups/docs --interval 120",
    )
    parser.add_argument(
        "source",
        help="Path to the source directory to back up.",
    )
    parser.add_argument(
        "backup",
        help="Path to the destination backup directory.",
    )
    parser.add_argument(
        "-i",
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL_SEC,
        metavar="SEC",
        help=f"Seconds between backup cycles (default: {DEFAULT_INTERVAL_SEC}).",
    )
    parser.add_argument(
        "-l",
        "--log-file",
        default=None,
        metavar="FILE",
        help="Optional path to a log file (logs always go to stderr too).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging output.",
    )

    args = parser.parse_args(argv)

    if not os.path.isdir(args.source):
        parser.error(f"Source directory does not exist: {args.source}")

    args.source = os.path.realpath(args.source)
    args.backup = os.path.realpath(args.backup)

    if args.source == args.backup:
        parser.error("Source and backup directories must be different.")

    if args.backup.startswith(args.source + os.sep):
        parser.error(
            "Backup directory must not be inside the source directory."
        )

    if args.interval < 1:
        parser.error("Interval must be at least 1 second.")

    return args


# ---------------------------------------------------------------------------
# Logging configuration — FIX: added log rotation
# ---------------------------------------------------------------------------


def configure_logging(log_file: str = None, verbose: bool = False) -> None:
    """Set up the root logger with stderr + optional rotating file handler."""
    level = logging.DEBUG if verbose else logging.INFO

    handlers = [logging.StreamHandler(sys.stderr)]

    if log_file:
        try:
            # FIX: RotatingFileHandler prevents unbounded log growth
            file_handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=LOG_MAX_BYTES,
                backupCount=LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setFormatter(
                logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
            )
            handlers.append(file_handler)
            # Can't use logging yet, print to stderr
            print(
                f"Logging to file: {log_file} "
                f"(max {LOG_MAX_BYTES // (1024*1024)} MB x {LOG_BACKUP_COUNT} rotations)",
                file=sys.stderr,
            )
        except OSError as exc:
            print(
                f"WARNING: Cannot open log file {log_file}: {exc}",
                file=sys.stderr,
            )

    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt=DATE_FORMAT,
        handlers=handlers,
    )


# ---------------------------------------------------------------------------
# Main entry point — FIX: exit code reflects error state
# ---------------------------------------------------------------------------


def main() -> int:
    """Parse arguments, set up logging, and run the backup loop."""
    args = parse_args()
    configure_logging(log_file=args.log_file, verbose=args.verbose)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    try:
        os.makedirs(args.backup, exist_ok=True)
    except OSError as exc:
        logging.critical(
            "Cannot create backup directory %s: %s", args.backup, exc
        )
        return 1

    logging.info("Incremental backup started")
    logging.info("  Source   : %s", args.source)
    logging.info("  Backup   : %s", args.backup)
    logging.info("  Interval : %d seconds", args.interval)
    logging.info("Press Ctrl+C to stop.\n")

    cycle = 0
    total_errors = 0  # FIX: track cumulative errors for exit code

    while not _shutdown_requested:
        cycle += 1
        logging.info("--- Backup cycle #%d starting ---", cycle)

        try:
            summary = perform_backup(args.source, args.backup)
            print_summary(summary)
            total_errors += len(summary["errors"])
        except Exception:
            logging.exception(
                "Unexpected error during backup cycle #%d", cycle
            )
            total_errors += 1

        deadline = time.monotonic() + args.interval
        while time.monotonic() < deadline and not _shutdown_requested:
            time.sleep(min(1, deadline - time.monotonic()))

    logging.info(
        "Backup service stopped gracefully after %d cycle(s) (%d total error(s)).",
        cycle,
        total_errors,
    )

    # FIX: non-zero exit code if any errors occurred during the run
    return 1 if total_errors > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
