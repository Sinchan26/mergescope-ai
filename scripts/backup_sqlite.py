#!/usr/bin/env python3
import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend/src"))

from mergescope.services.backup import BackupError, create_sqlite_backup  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create an online, integrity-checked backup of MergeScope's SQLite database."
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=PROJECT_ROOT / "data/mergescope.db",
        help="Source SQLite database path.",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=PROJECT_ROOT / "backups",
        help="Directory for backup databases and manifests.",
    )
    parser.add_argument("--retain", type=int, default=7, help="Number of newest backups to keep.")
    args = parser.parse_args()
    try:
        result = create_sqlite_backup(args.database, args.destination, retain=args.retain)
    except BackupError as exc:
        parser.exit(1, f"Backup failed: {exc}\n")
    print(json.dumps(asdict(result), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
