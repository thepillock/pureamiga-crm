"""Write Jetpack CRM data (parsed by jetpack_import) into the database.

Used by the ``import_jetpack`` management command and the Tools page.
Safe to re-run: records are matched on their Jetpack IDs and skipped if already imported.
"""
from dataclasses import dataclass, field

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q

from . import jetpack_import as ji
from .models import Customer, JobNote, Machine, RepairJob, Stage, StageChange
from .notes import IMPORTED_HEADER, split_note


class _DryRun(Exception):
    pass


@dataclass
class ImportResult:
    committed: bool
    found_customers: int
    found_jobs: int
    skipped_contacts: int
    orphan_quotes: list
    stats: dict = field(default_factory=dict)

    def lines(self):
        yield (f"Found {self.found_customers} customers and {self.found_jobs} repair jobs "
               f"({self.skipped_contacts} contacts without jobs skipped, "
               f"{len(self.orphan_quotes)} quotes with no customer skipped).")
        labels = {
            "customers_created": "Customers added", "customers_existing": "Customers already imported",
            "machines_created": "Machines added", "jobs_created": "Repair jobs added",
            "jobs_existing": "Repair jobs already imported", "jobs_not_returned": "Jobs still open (not Returned)",
            "technicians_unmatched": "Technician names with no matching user",
            "log_entries_dated": "Bench log split into dated entries",
            "repair_refs_duplicated": "Repair refs used twice (left blank on the later job)",
        }
        for k, v in self.stats.items():
            yield f"{labels.get(k, k)}: {v}"


def run_import(sql_text, commit=False, include_leads=False):
    """Parse a dump and import it. With commit=False everything is rolled back (a dry run)."""
    data = ji.build(sql_text, include_leads=include_leads)
    result = ImportResult(committed=False, found_customers=len(data.customers), found_jobs=len(data.jobs),
                          skipped_contacts=data.skipped_contacts, orphan_quotes=data.orphan_quotes)
    try:
        with transaction.atomic():
            result.stats = _write(data)
            if not commit:
                raise _DryRun
    except _DryRun:
        pass
    else:
        result.committed = True
    return result


def _technician(name, cache):
    """Match a legacy technician name to an existing user; never creates accounts."""
    if not name:
        return None
    if name not in cache:
        cache[name] = get_user_model().objects.filter(Q(username__iexact=name) | Q(first_name__iexact=name)).first()
    return cache[name]


def _write(data):
    tech_cache = {}
    used_refs = set(RepairJob.objects.exclude(repair_ref="").values_list("repair_ref", flat=True))
    stats = dict(customers_created=0, customers_existing=0, machines_created=0,
                 jobs_created=0, jobs_existing=0, jobs_not_returned=0,
                 log_entries_dated=0, technicians_unmatched=set(), repair_refs_duplicated=set())
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

        tech = _technician(j.technician, tech_cache)
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
        if j.repair_ref and j.repair_ref not in used_refs:
            job.repair_ref = j.repair_ref
            used_refs.add(j.repair_ref)
        elif j.repair_ref:
            stats["repair_refs_duplicated"].add(j.repair_ref)
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
        if j.quote_notes:
            JobNote.objects.create(job=job, text=f"[Imported from Jetpack CRM - quote notes]\n{j.quote_notes}",
                                   created_at=j.received_at or job.created_at)
        if j.bench_log:
            log = JobNote.objects.create(job=job, text=f"{IMPORTED_HEADER}\n{j.bench_log}",
                                         created_at=j.received_at or job.created_at)
            stats["log_entries_dated"] += split_note(log)
        if j.raw_status:
            JobNote.objects.create(job=job, text=f"[Jetpack repair status was: {j.raw_status}]",
                                   created_at=j.updated_at or job.created_at)

    stats["technicians_unmatched"] = ", ".join(sorted(stats["technicians_unmatched"])) or "none"
    stats["repair_refs_duplicated"] = ", ".join(sorted(stats["repair_refs_duplicated"])) or "none"
    return stats
