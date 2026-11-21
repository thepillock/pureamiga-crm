"""What was asked for on a job: parts (passed on at cost) plus bench time."""
from datetime import date
from decimal import Decimal

from django.db.models import Sum

OLD_CHARGE_NOTE = "Worked out from the old charge"


def derive_bench_time(job, JobCost=None):
    """Older jobs recorded what the customer was asked for as one charge. Parts were passed on at cost, so the
    rest of that charge was bench time: add it as a bench-time line. Safe to re-run (it recalculates).

    Returns charge minus costs: positive = bench time added, 0 = nothing to add, negative = doesn't add up,
    None = no old charge. JobCost can be passed in so migrations can use their historical model."""
    if JobCost is None:
        from .models import JobCost
    job.costs.filter(from_old_charge=True).delete()
    charged = job.payments.aggregate(s=Sum("amount"))["s"]
    if charged is None:
        return None
    rest = charged - (job.costs.aggregate(s=Sum("amount"))["s"] or Decimal("0"))
    if rest > 0:
        JobCost.objects.create(job=job, kind="bench_time", amount=rest, description=OLD_CHARGE_NOTE,
                               date=job.payments.order_by("-paid_on").first().paid_on, from_old_charge=True)
    return rest


def tax_year(today):
    """The UK tax year (6 April to 5 April) containing today."""
    start_year = today.year if (today.month, today.day) >= (4, 6) else today.year - 1
    return date(start_year, 4, 6), date(start_year + 1, 4, 5)
