"""Back up the SQLite database while the app is running.

    python manage.py backup_db            # writes /data/backups/crm-YYYYmmdd-HHMMSS.sqlite3, keeps 14
"""
from pathlib import Path

from django.core.management.base import BaseCommand

from repairs.backup import backup_dir, make_backup


class Command(BaseCommand):
    help = "Back up the SQLite database using SQLite's online backup API."

    def add_arguments(self, parser):
        parser.add_argument("--dir", type=Path, default=None)
        parser.add_argument("--keep", type=int, default=14)

    def handle(self, dir, keep, **opts):
        target = make_backup(dir or backup_dir(), keep=keep)
        self.stdout.write(self.style.SUCCESS(f"Backed up to {target}"))
