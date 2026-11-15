"""One-off load of the old repairs spreadsheet (converted to JSON by scripts/legacy_repairs/convert.py).

- Jobs that came from Jetpack (matched on repair ref) get missing details filled in - never overwritten - and
  their work log is left alone. Their return date is replaced by the spreadsheet's real one.
- Other repairs are created: customer matched on exact name (case-insensitive) or created; machine matched on
  model + serial or created; stage Returned; with the person loading it as technician and holder.
- Finances: Money Spent -> parts cost lines (unless the job already has its own parts costs);
  Money Made -> payments, replacing the "From Jetpack quote" payment.
- Safe to re-run: jobs it created are recognised and only topped up.
"""
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction

from .logtext import normalise_repair_ref
from .models import (Customer, JobCost, JobNote, Machine, Payment, RepairJob, Stage, StageChange,
                     fold_extra_checks)

MARKER = "From repairs spreadsheet"
FINANCE_REF = "From finances sheet"
JETPACK_QUOTE_REF = "From Jetpack quote"


class _DryRun(Exception):
    pass


@dataclass
class LegacyResult:
    committed: bool = False
    stats: dict = field(default_factory=lambda: {
        "jobs_created": 0, "jetpack_jobs_updated": 0, "jobs_already_loaded": 0, "customers_created": 0,
        "customers_matched": 0, "machines_created": 0, "summaries_added": 0, "checks_added": 0,
        "cost_lines_added": 0, "payments_added": 0, "jetpack_quote_payments_replaced": 0,
    })
    conflicts: list = field(default_factory=list)
    notes: list = field(default_factory=list)


def _when(iso_date):
    if not iso_date:
        return None
    return datetime.combine(date.fromisoformat(iso_date), time(12, 0), tzinfo=ZoneInfo(settings.TIME_ZONE))


def load(data, user, commit=False):
    result = LegacyResult()
    try:
        with transaction.atomic():
            customers = {c.full_name.lower(): c for c in Customer.objects.order_by("pk")}
            for item in data["jobs"]:
                _load_one(item, user, customers, result)
            if not commit:
                raise _DryRun
    except _DryRun:
        pass
    else:
        result.committed = True
    return result


def _load_one(item, user, customers, result):
    ref = normalise_repair_ref(item["ref"])
    job = RepairJob.objects.filter(repair_ref=ref).first()
    if job and job.legacy_jetpack_id:
        result.stats["jetpack_jobs_updated"] += 1
        _enrich(job, item, user, result, from_jetpack=True)
    elif job and job.legacy_status == MARKER:
        result.stats["jobs_already_loaded"] += 1
        _enrich(job, item, user, result, from_jetpack=False)
    elif job:
        result.conflicts.append(f"{ref}: already used by {job.ref} '{job.title}' (created in the app) - skipped")
    else:
        _create(item, ref, user, customers, result)


def _create(item, ref, user, customers, result):
    name = item["customer"] or "Unknown"
    customer = customers.get(name.lower())
    if customer:
        result.stats["customers_matched"] += 1
    else:
        first, _, last = name.partition(" ")
        customer = Customer.objects.create(first_name=first, last_name=last, country="", created_by=user)
        customers[name.lower()] = customer
        result.stats["customers_created"] += 1

    m = item["machine"]
    machine = None
    if m["serial"]:
        machine = customer.machines.filter(model=m["model"], serial_number__iexact=m["serial"]).first()
    if machine is None:
        machine = Machine.objects.create(customer=customer, model=m["model"], description=m["description"][:200],
                                         serial_number=m["serial"][:100])
        result.stats["machines_created"] += 1

    received, returned = _when(item["date_in"]), _when(item["date_out"])
    title = (item["work_requested"].split("\n")[0] or f"{machine.display_model} repair")[:200]
    job = RepairJob.objects.create(
        customer=customer, machine=machine, title=title, repair_ref=ref, stage=Stage.RETURNED,
        technician=user, received_at=received, returned_at=returned, legacy_status=MARKER,
    )
    job.created_at = received or returned or job.created_at
    job.save(update_fields=["created_at"])
    StageChange.objects.create(job=job, from_stage="", to_stage=Stage.RETURNED, changed_by=user,
                               changed_at=returned or received or job.created_at)
    job.hand_to(user, by=user, when=received or returned or job.created_at)
    log = list(item.get("log", [])) + list(item.get("money_notes", []))
    if log:
        JobNote.objects.create(job=job, author=user, created_at=received or returned or job.created_at,
                               text=f"[{MARKER}]\n" + "\n".join(log))
    result.stats["jobs_created"] += 1
    _enrich(job, item, user, result, from_jetpack=False)


def _enrich(job, item, user, result, from_jetpack):
    """Fill in anything missing. Never overwrites what's already there (except Jetpack's guessed return date)."""
    changed = []
    for attr, key in (("customer_summary", "work_completed"), ("condition_on_arrival", "condition"),
                      ("work_requested", "work_requested"), ("accessories", "accessories")):
        if not getattr(job, attr) and item.get(key):
            setattr(job, attr, item[key])
            changed.append(attr)
            if attr == "customer_summary":
                result.stats["summaries_added"] += 1
    if not job.items_received and item.get("items_received"):
        job.items_received = item["items_received"]
        changed.append("items_received")
    if not job.checks and item.get("checks"):
        job.checks = fold_extra_checks(item["checks"])
        changed.append("checks")
        result.stats["checks_added"] += 1
    if not job.received_at and item.get("date_in"):
        job.received_at = _when(item["date_in"])
        changed.append("received_at")
    returned = _when(item.get("date_out"))
    if returned and job.stage == Stage.RETURNED and (from_jetpack or not job.returned_at) and job.returned_at != returned:
        job.returned_at = returned  # Jetpack only had a guess (last updated)
        changed.append("returned_at")
    if not job.machine.serial_number and item["machine"].get("serial"):
        job.machine.serial_number = item["machine"]["serial"][:100]
        job.machine.save(update_fields=["serial_number", "updated_at"])
    if changed:
        job.save(update_fields=changed + ["updated_at"])
    if "returned_at" in changed:
        # Keep the history in step: the imported "Returned" entry carried the old guessed date
        job.stage_changes.filter(to_stage=Stage.RETURNED).exclude(changed_at=returned).filter(
            from_stage="").update(changed_at=returned)

    # Costs: finance parts costs, unless the job already has parts costs of its own (e.g. itemised in Jetpack)
    finance_costs = item.get("costs", [])
    if finance_costs:
        own_parts = job.costs.filter(kind="parts").exclude(
            description__in=[c["description"] for c in finance_costs])
        if own_parts.exists():
            result.notes.append(f"{job.repair_ref}: kept its existing parts costs; finance costs not added")
        else:
            # Compare counts, so two identical finance rows give two lines - and a re-run adds none.
            wanted = Counter((Decimal(str(c["amount"])), c["description"], c["date"]) for c in finance_costs)
            for (amount, description, when), n in wanted.items():
                have = job.costs.filter(kind="parts", amount=amount, description=description).count()
                for _ in range(n - have):
                    JobCost.objects.create(job=job, kind="parts", amount=amount, description=description,
                                           added_by=user, created_at=_when(when) or job.created_at)
                    result.stats["cost_lines_added"] += 1

    # Payments: the finance sheet's Money Made replaces the Jetpack quote
    finance_payments = item.get("payments", [])
    if finance_payments:
        quote = job.payments.filter(reference=JETPACK_QUOTE_REF)
        if quote.exists():
            result.stats["jetpack_quote_payments_replaced"] += quote.count()
            quote.delete()
        fallback = (job.returned_at or job.created_at).date()
        wanted = Counter((Decimal(str(p["amount"])), date.fromisoformat(p["date"]) if p["date"] else fallback)
                         for p in finance_payments)
        for (amount, paid_on), n in wanted.items():
            have = job.payments.filter(amount=amount, paid_on=paid_on, reference=FINANCE_REF).count()
            for _ in range(n - have):
                Payment.objects.create(job=job, amount=amount, paid_on=paid_on, method="not_recorded",
                                       reference=FINANCE_REF, added_by=user)
                result.stats["payments_added"] += 1
    if from_jetpack and item.get("money_notes"):
        result.notes.append(f"{job.repair_ref}: {'; '.join(item['money_notes'])} (not added - Jetpack work log left alone)")
