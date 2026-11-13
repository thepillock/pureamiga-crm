"""Consistent SQLite snapshots, safe while the app is running."""
import sqlite3
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.db import connection


def backup_dir():
    return Path(settings.DATA_DIR) / "backups"


def make_backup(directory=None, keep=14):
    """Copy the live database with SQLite's online backup API. Returns the new file's path."""
    directory = Path(directory or backup_dir())
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"crm-{datetime.now():%Y%m%d-%H%M%S}.sqlite3"
    connection.ensure_connection()  # back up through Django's own sqlite3 connection
    dst = sqlite3.connect(target)
    try:
        with dst:
            connection.connection.backup(dst)
    finally:
        dst.close()
    target.chmod(0o600)
    if keep > 0:
        for old in sorted(directory.glob("crm-*.sqlite3"))[:-keep]:
            old.unlink()
    return target
