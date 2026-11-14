"""One-off: load the old repairs spreadsheet (as JSON from scripts/legacy_repairs/convert.py).

    python manage.py load_legacy_repairs /data/legacy.json --as chris            # dry run: shows what would happen
    python manage.py load_legacy_repairs /data/legacy.json --as chris --commit   # do it

Safe to re-run. See repairs/legacy.py for the rules.
"""
import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from repairs.legacy import load


class Command(BaseCommand):
    help = "Load the old repairs spreadsheet (converted to JSON)."

    def add_arguments(self, parser):
        parser.add_argument("path", type=Path)
        parser.add_argument("--as", dest="username", required=True,
                            help="Your username: technician, holder and 'added by' for what's loaded")
        parser.add_argument("--commit", action="store_true", help="Write to the database (default: dry run)")

    def handle(self, path, username, commit, **opts):
        if not path.exists():
            raise CommandError(f"{path} not found")
        user = get_user_model().objects.filter(username=username).first()
        if user is None:
            raise CommandError(f"No user called {username}")
        result = load(json.loads(path.read_text()), user, commit=commit)
        for key, value in result.stats.items():
            self.stdout.write(f"{key.replace('_', ' ').capitalize()}: {value}")
        for line in result.conflicts:
            self.stdout.write(self.style.WARNING(f"CONFLICT {line}"))
        for line in result.notes:
            self.stdout.write(f"note: {line}")
        if result.committed:
            self.stdout.write(self.style.SUCCESS("Loaded."))
        else:
            self.stdout.write(self.style.WARNING("Dry run - nothing saved. Add --commit to load."))
