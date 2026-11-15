"""Who can see what.

Users with the ``repairs.view_all_jobs`` permission (and superusers) see everything.
Everyone else sees only jobs they hold now, have ever held, or that are shared with them, the customers of those jobs
(plus customers they created themselves), and those customers' machines.
"""
from django.db.models import Q

from .models import Customer, HolderChange, JobCost, JobNote, Machine, RepairJob


def can_view_all(user):
    return user.is_authenticated and user.has_perm("repairs.view_all_jobs")


def visible_jobs(user, qs=None):
    qs = RepairJob.objects.all() if qs is None else qs
    if can_view_all(user):
        return qs
    held = HolderChange.objects.filter(to_user=user).values("job_id")
    shared = RepairJob.shared_with.through.objects.filter(user=user).values("repairjob_id")
    return qs.filter(Q(holder=user) | Q(pk__in=held) | Q(pk__in=shared))


def visible_customers(user, qs=None):
    qs = Customer.objects.all() if qs is None else qs
    if can_view_all(user):
        return qs
    return qs.filter(Q(created_by=user) | Q(pk__in=visible_jobs(user).values("customer_id")))


def visible_machines(user, qs=None):
    qs = Machine.objects.all() if qs is None else qs
    if can_view_all(user):
        return qs
    return qs.filter(customer__in=visible_customers(user))


def visible_notes(user):
    return JobNote.objects.filter(job__in=visible_jobs(user))


def visible_costs(user):
    return JobCost.objects.filter(job__in=visible_jobs(user))
