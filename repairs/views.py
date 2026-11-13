from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .access import (visible_costs, visible_customers, visible_jobs, visible_machines,
                     visible_notes)
from .forms import (BookInForm, CustomerForm, JobCostForm, JobNoteEditForm, JobNoteForm, MachineForm,
                    RepairJobForm, suggested_repair_ref)
from .models import STAGE_TIMESTAMP, JobNote, Stage, StageChange
from .notes import split_note

RETURNED_ON_BOARD_DAYS = 14


def _jobs(request):
    return visible_jobs(request.user).select_related("customer", "machine", "technician", "holder")


def _safe_next(request, default):
    nxt = request.POST.get("next", "")
    return nxt if nxt.startswith("/") and not nxt.startswith("//") else default


def board(request):
    """Kanban board: one column per stage. Returned jobs only show for a couple of weeks."""
    jobs = _jobs(request)
    q = request.GET.get("q", "").strip()
    mine = request.GET.get("mine") == "1"
    if q:
        jobs = jobs.filter(_job_search(q))
    if mine:
        jobs = jobs.filter(holder=request.user)
    columns = []
    for stage in Stage:
        stage_jobs = jobs.filter(stage=stage)
        if stage == Stage.RETURNED and not q:
            cutoff = timezone.now() - timedelta(days=RETURNED_ON_BOARD_DAYS)
            stage_jobs = stage_jobs.filter(returned_at__gte=cutoff)
        columns.append({"stage": stage, "jobs": list(stage_jobs.order_by("received_at", "pk"))})
    return render(request, "repairs/board.html", {
        "columns": columns, "q": q, "mine": mine, "returned_days": RETURNED_ON_BOARD_DAYS,
    })


def _job_search(q):
    cond = (
        Q(title__icontains=q) | Q(customer__first_name__icontains=q) | Q(customer__last_name__icontains=q)
        | Q(customer__email__icontains=q) | Q(machine__serial_number__icontains=q)
        | Q(machine__model__icontains=q) | Q(machine__description__icontains=q)
        | Q(repair_ref__iexact=q)
    )
    ref = q.upper().removeprefix("PA")
    if ref.isdigit():
        cond |= Q(pk=int(ref))
    return cond


def job_list(request):
    jobs = _jobs(request)
    q = request.GET.get("q", "").strip()
    stage = request.GET.get("stage", "")
    mine = request.GET.get("mine") == "1"
    if q:
        jobs = jobs.filter(_job_search(q))
    if stage in Stage.values:
        jobs = jobs.filter(stage=stage)
    if mine:
        jobs = jobs.filter(holder=request.user)
    return render(request, "repairs/job_list.html", {
        "jobs": jobs[:500], "q": q, "stage": stage, "mine": mine, "stages": Stage.choices,
    })


def _history(job):
    """Stage changes and handovers, oldest first."""
    events = [
        {"when": s.changed_at, "who": s.changed_by,
         "text": (f"{s.get_from_stage_display()} → " if s.from_stage else "") + s.get_to_stage_display()}
        for s in job.stage_changes.select_related("changed_by")
    ]
    for h in job.holder_changes.select_related("from_user", "to_user", "changed_by"):
        to = _name(h.to_user) or "nobody"
        text = f"Handed from {_name(h.from_user)} to {to}" if h.from_user else f"With {to}"
        events.append({"when": h.changed_at, "who": h.changed_by, "text": text})
    return sorted(events, key=lambda e: e["when"])


def _name(user):
    return (user.get_short_name() or user.username) if user else ""


def _cost_totals(job):
    """Costs added up per person, in the order each person first added one."""
    totals = {}
    for c in job.costs.select_related("added_by"):
        key = c.added_by_id
        if key not in totals:
            totals[key] = {"name": _name(c.added_by) or "not recorded", "amount": Decimal("0.00")}
        totals[key]["amount"] += c.amount
    return list(totals.values())


def job_detail(request, pk):
    job = get_object_or_404(_jobs(request), pk=pk)
    note_form = JobNoteForm()
    if request.method == "POST":
        note_form = JobNoteForm(request.POST)
        if note_form.is_valid():
            JobNote.objects.create(job=job, author=request.user, text=note_form.cleaned_data["text"])
            return redirect(job)
    User = get_user_model()
    return render(request, "repairs/job_detail.html", {
        "job": job,
        "notes": job.notes.select_related("author").order_by("-created_at", "-pk"),  # newest first
        "steps": [{"stage": st, "at": getattr(job, STAGE_TIMESTAMP[st])} for st in Stage],
        "costs": job.costs.select_related("added_by"),
        "cost_totals": _cost_totals(job),
        "cost_form": JobCostForm(),
        "history": _history(job),
        "note_form": note_form,
        "stages": Stage,
        "hand_to_users": User.objects.filter(is_active=True).exclude(pk=job.holder_id).order_by("first_name", "username"),
        "next_repair_ref": "" if job.repair_ref else suggested_repair_ref(),
    })


def job_edit(request, pk):
    job = get_object_or_404(visible_jobs(request.user), pk=pk)
    form = RepairJobForm(request.POST or None, instance=job)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"{job.ref} saved.")
        return redirect(job)
    return render(request, "repairs/form.html", {"form": form, "title": f"Edit {job.ref}", "cancel": job.get_absolute_url()})


@require_POST
def job_move(request, pk):
    job = get_object_or_404(visible_jobs(request.user), pk=pk)
    stage = request.POST.get("stage")
    if stage in Stage.values:
        job.set_stage(stage, user=request.user)
        messages.success(request, f"{job.ref} moved to {job.get_stage_display()}.")
    return redirect(_safe_next(request, job.get_absolute_url()))


@require_POST
def job_hand(request, pk):
    """Pass the job to someone else (or take it yourself)."""
    job = get_object_or_404(visible_jobs(request.user), pk=pk)
    to = get_object_or_404(get_user_model(), pk=request.POST.get("user"), is_active=True)
    job.hand_to(to, by=request.user)
    messages.success(request, f"{job.ref} is now with {_name(to)}.")
    return redirect(_safe_next(request, job.get_absolute_url()))


def job_book_in(request, customer_pk):
    customer = get_object_or_404(visible_customers(request.user), pk=customer_pk)
    initial = {}
    if request.GET.get("machine"):
        initial["machine"] = request.GET["machine"]
    form = BookInForm(request.POST or None, customer=customer, initial=initial)
    if request.method == "POST" and form.is_valid():
        job = form.save(commit=False)
        job.received_at = timezone.now()
        job.save()
        StageChange.objects.create(job=job, from_stage="", to_stage=Stage.RECEIVED, changed_by=request.user,
                                   changed_at=job.received_at)
        job.hand_to(request.user, by=request.user, when=job.received_at)
        messages.success(request, f"Booked in as {job.ref}.")
        return redirect(job)
    return render(request, "repairs/book_in.html", {"form": form, "customer": customer})


def customer_list(request):
    customers = visible_customers(request.user).annotate(job_count=Count("jobs"))
    q = request.GET.get("q", "").strip()
    if q:
        customers = customers.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q)
            | Q(phone__icontains=q) | Q(postcode__icontains=q)
        )
    return render(request, "repairs/customer_list.html", {"customers": customers[:500], "q": q})


def customer_detail(request, pk):
    customer = get_object_or_404(visible_customers(request.user), pk=pk)
    jobs = visible_jobs(request.user, customer.jobs.all())
    return render(request, "repairs/customer_detail.html", {
        "customer": customer,
        "machines": customer.machines.annotate(job_count=Count("jobs", filter=Q(jobs__in=jobs))),
        "jobs": jobs.select_related("machine", "technician", "holder"),
    })


def customer_edit(request, pk=None):
    customer = get_object_or_404(visible_customers(request.user), pk=pk) if pk else None
    form = CustomerForm(request.POST or None, instance=customer)
    if request.method == "POST" and form.is_valid():
        customer = form.save(commit=False)
        if pk is None:
            customer.created_by = request.user
        customer.save()
        if pk is None and request.POST.get("book_in"):
            return redirect("repairs:job_book_in", customer_pk=customer.pk)
        return redirect(customer)
    return render(request, "repairs/form.html", {
        "form": form,
        "title": f"Edit {customer}" if customer else "New customer",
        "cancel": customer.get_absolute_url() if customer else "/customers/",
        "offer_book_in": pk is None,
    })


def machine_detail(request, pk):
    machine = get_object_or_404(visible_machines(request.user).select_related("customer"), pk=pk)
    return render(request, "repairs/machine_detail.html", {
        "machine": machine,
        "jobs": visible_jobs(request.user, machine.jobs.all()).select_related("technician", "holder"),
    })


def machine_edit(request, pk):
    machine = get_object_or_404(visible_machines(request.user), pk=pk)
    form = MachineForm(request.POST or None, instance=machine)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect(machine)
    return render(request, "repairs/form.html", {"form": form, "title": f"Edit {machine}", "cancel": machine.get_absolute_url()})


@require_POST
def job_assign_ref(request, pk):
    """Give the job the next free repair ref."""
    job = get_object_or_404(visible_jobs(request.user), pk=pk)
    if not job.repair_ref:
        ref = suggested_repair_ref()
        if ref:
            job.repair_ref = ref
            job.save(update_fields=["repair_ref", "updated_at"])
            messages.success(request, f"Repair ref {ref} assigned to {job.ref}.")
    return redirect(job)


# --- Bench log -----------------------------------------------------------------

def note_edit(request, pk):
    note = get_object_or_404(visible_notes(request.user).select_related("job"), pk=pk)
    form = JobNoteEditForm(request.POST or None, instance=note)
    if request.method == "POST" and form.is_valid():
        note = form.save(commit=False)
        note.edited_at = timezone.now()
        note.save()
        return redirect(f"{note.job.get_absolute_url()}#note-{note.pk}")
    return render(request, "repairs/note_edit.html", {"form": form, "note": note, "job": note.job})


@require_POST
def note_delete(request, pk):
    note = get_object_or_404(visible_notes(request.user).select_related("job"), pk=pk)
    job = note.job
    note.delete()
    messages.success(request, "Log entry deleted.")
    return redirect(job)


@require_POST
def note_split(request, pk):
    note = get_object_or_404(visible_notes(request.user).select_related("job"), pk=pk)
    job = note.job
    added = split_note(note)
    if added:
        messages.success(request, f"Split into {added} dated entr{'y' if added == 1 else 'ies'}.")
    else:
        messages.info(request, "No date lines found to split on.")
    return redirect(job)


# --- Costs ---------------------------------------------------------------------

@require_POST
def cost_add(request, pk):
    job = get_object_or_404(visible_jobs(request.user), pk=pk)
    form = JobCostForm(request.POST)
    if form.is_valid():
        cost = form.save(commit=False)
        cost.job, cost.added_by = job, request.user
        cost.save()
    else:
        messages.error(request, "Cost not added: " + "; ".join(e for errs in form.errors.values() for e in errs))
    return redirect(f"{job.get_absolute_url()}#costs")


def cost_edit(request, pk):
    cost = get_object_or_404(visible_costs(request.user).select_related("job"), pk=pk)
    form = JobCostForm(request.POST or None, instance=cost)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect(f"{cost.job.get_absolute_url()}#costs")
    return render(request, "repairs/form.html", {
        "form": form, "title": f"Edit cost · {cost.job.ref}", "cancel": f"{cost.job.get_absolute_url()}#costs",
    })


@require_POST
def cost_delete(request, pk):
    cost = get_object_or_404(visible_costs(request.user).select_related("job"), pk=pk)
    job = cost.job
    cost.delete()
    return redirect(f"{job.get_absolute_url()}#costs")
