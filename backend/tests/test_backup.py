import json
import sqlite3
from pathlib import Path

from mergescope.services.backup import create_sqlite_backup


def test_online_backup_is_valid_and_prunes_old_files(tmp_path: Path) -> None:
    database = tmp_path / "source.db"
    destination = tmp_path / "backups"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE reviews (id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO reviews VALUES ('review-1')")

    first = create_sqlite_backup(database, destination, retain=1)
    second = create_sqlite_backup(database, destination, retain=1)

    backups = list(destination.glob("*.db"))
    manifests = list(destination.glob("*.json"))
    assert len(backups) == len(manifests) == 1
    assert Path(second.database_path) == backups[0]
    assert Path(first.database_path).exists() is False
    assert len(list(destination.iterdir())) == 2
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["sha256"] == second.sha256
    with sqlite3.connect(backups[0]) as connection:
        assert connection.execute("SELECT id FROM reviews").fetchone()[0] == "review-1"
