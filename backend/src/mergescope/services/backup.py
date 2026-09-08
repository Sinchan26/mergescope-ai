import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


class BackupError(RuntimeError):
    pass


@dataclass(frozen=True)
class BackupResult:
    database_path: str
    manifest_path: str
    size_bytes: int
    sha256: str
    created_at: str


def create_sqlite_backup(
    database_path: Path,
    destination: Path,
    *,
    retain: int = 7,
) -> BackupResult:
    if retain < 1:
        raise BackupError("Backup retention must be at least one file.")
    if not database_path.is_file():
        raise BackupError(f"SQLite database does not exist: {database_path}")

    destination.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(UTC)
    stem = f"mergescope-{created_at.strftime('%Y%m%dT%H%M%S%fZ')}"
    final_path = destination / f"{stem}.db"
    temporary_path = destination / f".{stem}.tmp"
    manifest_path = destination / f"{stem}.json"

    try:
        with (
            sqlite3.connect(database_path) as source,
            sqlite3.connect(temporary_path) as target,
        ):
            source.backup(target)
        with sqlite3.connect(temporary_path) as check:
            integrity = check.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise BackupError("SQLite integrity check failed for the new backup.")
        temporary_path.replace(final_path)
        digest = hashlib.sha256(final_path.read_bytes()).hexdigest()
        result = BackupResult(
            database_path=str(final_path),
            manifest_path=str(manifest_path),
            size_bytes=final_path.stat().st_size,
            sha256=digest,
            created_at=created_at.isoformat(),
        )
        manifest_path.write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")
        _prune_backups(destination, retain)
        return result
    except (OSError, sqlite3.Error) as exc:
        raise BackupError(f"Could not create SQLite backup: {exc}") from exc
    finally:
        temporary_path.unlink(missing_ok=True)
        Path(f"{temporary_path}-wal").unlink(missing_ok=True)
        Path(f"{temporary_path}-shm").unlink(missing_ok=True)


def _prune_backups(destination: Path, retain: int) -> None:
    backups = sorted(destination.glob("mergescope-*.db"), reverse=True)
    for backup in backups[retain:]:
        backup.unlink(missing_ok=True)
        backup.with_suffix(".json").unlink(missing_ok=True)
