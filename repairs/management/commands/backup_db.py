"""Take a consistent copy of the SQLite database while the app is running.

    python manage.py backup_db            # writes /data/backups/crm-YYYYmmdd-HHMMSS.sqlite3, keeps 14
"""
import sqlite3
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Back up the SQLite database using SQLite's online backup API."

    def add_arguments(self, parser):
        parser.add_argument("--dir", type=Path, default=Path(settings.DATA_DIR) / "backups")
        parser.add_argument("--keep", type=int, default=14)

    def handle(self, dir, keep, **opts):
        dir.mkdir(parents=True, exist_ok=True)
        target = dir / f"crm-{datetime.now():%Y%m%d-%H%M%S}.sqlite3"
        src = sqlite3.connect(settings.DATABASES["default"]["NAME"])
        dst = sqlite3.connect(target)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        target.chmod(0o600)
        old = sorted(dir.glob("crm-*.sqlite3"))[:-keep] if keep > 0 else []
        for f in old:
            f.unlink()
        self.stdout.write(self.style.SUCCESS(f"Backed up to {target} ({len(old)} old backups removed)"))
