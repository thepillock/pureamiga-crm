"""Import customers and repair jobs from a Jetpack CRM (WordPress) phpMyAdmin dump.

    python manage.py import_jetpack /import/dump.sql            # dry run, prints a summary
    python manage.py import_jetpack /import/dump.sql --commit   # actually write

Safe to re-run: records are matched on their Jetpack IDs and skipped if already imported.
"""
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from repairs import jetpack_import as ji
from repairs.models import Customer, JobNote, Machine, RepairJob, Stage, StageChange


class DryRun(Exception):
    pass


class Command(BaseCommand):
    help = "Import customers and repair jobs from a Jetpack CRM SQL dump."

    def add_arguments(self, parser):
        parser.add_argument("dump", type=Path)
        parser.add_argument("--commit", action="store_true", help="Write to the database (default is a dry run).")
        parser.add_argument("--include-leads", action="store_true",
                            help="Also import contacts that never had a repair job (mostly contact-form leads/spam).")

    def handle(self, dump, commit, include_leads, **opts):
        if not dump.exists():
            raise CommandError(f"{dump} not found")
        data = ji.build(dump.read_text(encoding="utf-8", errors="replace"), include_leads=include_leads)
        self.stdout.write(
            f"Found {len(data.customers)} customers, {len(data.jobs)} jobs "
            f"({data.skipped_contacts} contacts without jobs skipped, "
            f"{len(data.orphan_quotes)} quotes with no customer skipped: {data.orphan_quotes})"
        )
        try:
            with transaction.atomic():
                stats = self._import(data)
                if not commit:
                    raise DryRun
        except DryRun:
            self.stdout.write(self.style.WARNING("Dry run - nothing saved. Re-run with --commit to import."))
        else:
            self.stdout.write(self.style.SUCCESS("Import committed."))
        for k, v in stats.items():
            self.stdout.write(f"  {k}: {v}")

    def _technician(self, name):
        """Match a legacy technician name to an existing user; never creates accounts."""
        if not name:
            return None
        if name not in self._tech_cache:
            User = get_user_model()
            self._tech_cache[name] = User.objects.filter(
                Q(username__iexact=name) | Q(first_name__iexact=name)).first()
        return self._tech_cache[name]

    def _import(self, data):
        self._tech_cache = {}
        stats = dict(customers_created=0, customers_existing=0, machines_created=0,
                     jobs_created=0, jobs_existing=0, jobs_not_returned=0, technicians_unmatched=set())
        customers = {}
        for c in data.customers:
            obj = Customer.objects.filter(legacy_jetpack_id=c.legacy_id).first()
            if obj:
                stats["customers_existing"] += 1
            else:
                obj = Customer(legacy_jetpack_id=c.legacy_id, first_name=c.first_name or "(no name)",
                               last_name=c.last_name, email=c.email, phone=c.phone,
                               address_line1=c.address_line1, address_line2=c.address_line2, city=c.city,
                               county=c.county, postcode=c.postcode, country=c.country or "")
                if c.created_at:
                    obj.created_at = c.created_at
                obj.save()
                stats["customers_created"] += 1
            customers[c.legacy_id] = obj

        for j in sorted(data.jobs, key=lambda j: j.legacy_id):
            if RepairJob.objects.filter(legacy_jetpack_id=j.legacy_id).exists():
                stats["jobs_existing"] += 1
                continue
            customer = customers[j.customer_legacy_id]
            machine = None
            if j.serial_number:  # Only merge machines we can identify by serial
                machine = customer.machines.filter(model=j.model, serial_number__iexact=j.serial_number).first()
            if machine is None:
                machine = Machine.objects.create(customer=customer, model=j.model, description=j.model_detail,
                                                 serial_number=j.serial_number)
                stats["machines_created"] += 1

            tech = self._technician(j.technician)
            if j.technician and tech is None:
                stats["technicians_unmatched"].add(j.technician)

            job = RepairJob(
                legacy_jetpack_id=j.legacy_id, legacy_status=j.raw_status,
                customer=customer, machine=machine, title=j.title or "(untitled)", stage=j.stage,
                technician=tech, work_requested=j.work_requested, condition_on_arrival=j.condition,
                items_received=j.items_received, accessories=j.accessories,
                quote_value=j.quote_value, quote_accepted_at=j.accepted_at,
                bench_time_cost=j.bench_time_cost, parts_cost=j.parts_cost,
                received_at=j.received_at,
            )
            # Old Jetpack quotes don't record when stages changed: use last-updated as the best guess.
            if j.stage == Stage.RETURNED:
                job.returned_at = j.updated_at or j.received_at
            elif j.stage == Stage.IN_PROGRESS:
                job.started_at = j.updated_at
            elif j.stage == Stage.TESTING:
                job.testing_at = j.updated_at
            if j.received_at:
                job.created_at = j.received_at
            job.save()
            stats["jobs_created"] += 1
            if j.stage != Stage.RETURNED:
                stats["jobs_not_returned"] += 1

            StageChange.objects.create(job=job, from_stage="", to_stage=j.stage,
                                       changed_at=j.updated_at or job.created_at)
            for label, text in (("Imported from Jetpack CRM - quote notes", j.quote_notes),
                                ("Imported from Jetpack CRM - bench log", j.bench_log)):
                if text:
                    JobNote.objects.create(job=job, text=f"[{label}]\n{text}",
                                           created_at=j.received_at or job.created_at)
            if j.raw_status:
                JobNote.objects.create(job=job, text=f"[Jetpack repair status was: {j.raw_status}]",
                                       created_at=j.updated_at or job.created_at)

        stats["technicians_unmatched"] = ", ".join(sorted(stats["technicians_unmatched"])) or "none"
        return stats
