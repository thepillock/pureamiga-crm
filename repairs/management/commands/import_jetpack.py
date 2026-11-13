"""Import customers and repair jobs from a Jetpack CRM (WordPress) phpMyAdmin dump.

    python manage.py import_jetpack /data/import.sql            # dry run, prints a summary
    python manage.py import_jetpack /data/import.sql --commit   # actually write

The same import is available in the browser under Tools.
"""
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from repairs.importer import run_import


class Command(BaseCommand):
    help = "Import customers and repair jobs from a Jetpack CRM SQL dump."

    def add_arguments(self, parser):
        parser.add_argument("dump", type=Path)
        parser.add_argument("--commit", action="store_true", help="Write to the database (default is a dry run).")
        parser.add_argument("--include-leads", action="store_true",
                            help="Also import contacts that never had a repair job (mostly contact-form leads/spam).")
        parser.add_argument("--holder", metavar="USERNAME",
                            help="Person the imported jobs are with, e.g. the one who handled them all.")

    def handle(self, dump, commit, include_leads, holder=None, **opts):
        if not dump.exists():
            raise CommandError(f"{dump} not found")
        holder_user = None
        if holder:
            holder_user = get_user_model().objects.filter(username=holder).first()
            if holder_user is None:
                raise CommandError(f"No user called {holder}")
        result = run_import(dump.read_text(encoding="utf-8", errors="replace"),
                            commit=commit, include_leads=include_leads, holder=holder_user)
        for line in result.lines():
            self.stdout.write(line)
        if result.committed:
            self.stdout.write(self.style.SUCCESS("Import committed."))
        else:
            self.stdout.write(self.style.WARNING("Dry run - nothing saved. Re-run with --commit to import."))
