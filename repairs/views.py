from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .access import (can_view_all, visible_costs, visible_customers, visible_jobs, visible_machines,
                     visible_notes)
from .forms import (BookInForm, CustomerForm, JobCostForm, JobNoteEditForm, JobNoteForm, MachineForm,
                    PaymentForm, RepairJobForm, StageChangeForm, suggested_repair_ref)
from . import attachments, jobsheet
from .models import (CHECK_RESULTS, CHECKS, CUSTOM_CHECKS_KEY, MAX_CUSTOM_CHECKS, STAGE_TIMESTAMP, JobNote, Stage,
                     StageChange)
from .notes import log_as_text, split_note
from .summary import SummaryError, generate_summary, is_enabled as summary_enabled

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
        "jobs": jobs.annotate(cost_total=Sum("costs__amount"))[:500], "q": q, "stage": stage, "mine": mine,
        "stages": Stage.choices,
    })


def _history(job):
    """Stage changes and handovers, oldest first."""
    events = [
        {"when": s.changed_at, "who": s.changed_by, "stage_change": s.pk,
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


def _halves(rows):
    mid = (len(rows) + 1) // 2
    return [rows[:mid], rows[mid:]]


def _cost_totals(job):
    """Costs added up per person, in the order each person first added one."""
    totals = {}
    for c in job.costs.select_related("added_by"):
        key = c.added_by_id
        if key not in totals:
            totals[key] = {"name": _name(c.added_by) or "not recorded", "amount": Decimal("0.00")}
        totals[key]["amount"] += c.amount
    return list(totals.values())


def _share_candidates(job):
    """People a job can be shared with: active users who can't already see everything."""
    User = get_user_model()
    return [u for u in User.objects.filter(is_active=True).order_by("first_name", "username") if not can_view_all(u)]


def job_detail(request, pk):
    job = get_object_or_404(_jobs(request), pk=pk)
    note_form = JobNoteForm()
    if request.method == "POST":
        note_form = JobNoteForm(request.POST)
        if note_form.is_valid():
            JobNote.objects.create(job=job, author=request.user, text=note_form.cleaned_data["text"])
            return redirect(job)
    User = get_user_model()
    notes = list(job.notes.select_related("author").order_by("created_at", "pk"))  # oldest first
    return render(request, "repairs/job_detail.html", {
        "job": job,
        "notes": notes,
        "log_text": log_as_text(notes),
        "steps": [{"stage": st, "at": getattr(job, STAGE_TIMESTAMP[st])} for st in Stage],
        "costs": job.costs.select_related("added_by"),
        "cost_totals": _cost_totals(job),
        "cost_form": JobCostForm(),
        "payments": job.payments.select_related("added_by"),
        "payment_form": PaymentForm(),
        "history": _history(job),
        "note_form": note_form,
        "stages": Stage,
        "hand_to_users": User.objects.filter(is_active=True).exclude(pk=job.holder_id).order_by("first_name", "username"),
        "share_candidates": _share_candidates(job),
        "shared_ids": set(job.shared_with.values_list("pk", flat=True)),
        "next_repair_ref": "" if job.repair_ref else suggested_repair_ref(),
        "summary_enabled": summary_enabled(),
        "check_results": CHECK_RESULTS,
        "attachments": job.attachments.select_related("uploaded_by"),
        "check_halves": _halves(job.check_rows()),
        "custom_checks": job.custom_check_rows(),
        "can_add_custom": len(job.custom_check_rows()) < MAX_CUSTOM_CHECKS,
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
        "jobs": jobs.select_related("machine", "technician", "holder").annotate(cost_total=Sum("costs__amount")),
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
        "jobs": visible_jobs(request.user, machine.jobs.all()).select_related("technician", "holder")
                .annotate(cost_total=Sum("costs__amount")),
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


# --- Customer summary ----------------------------------------------------------

@require_POST
def summary_save(request, pk):
    job = get_object_or_404(visible_jobs(request.user), pk=pk)
    job.customer_summary = request.POST.get("customer_summary", "").replace("\r\n", "\n").strip()
    job.save(update_fields=["customer_summary", "updated_at"])
    messages.success(request, "Customer summary saved.")
    return redirect(f"{job.get_absolute_url()}#summary")


@require_POST
def summary_generate(request, pk):
    job = get_object_or_404(visible_jobs(request.user), pk=pk)
    try:
        generate_summary(job)
        messages.success(request, "New summary drafted from the work log. Check it over and edit as needed.")
    except SummaryError as e:
        messages.error(request, f"Couldn't generate a summary: {e}")
    return redirect(f"{job.get_absolute_url()}#summary")


# --- Checks and the printed job sheet ------------------------------------------

@require_POST
def checks_save(request, pk):
    job = get_object_or_404(visible_jobs(request.user), pk=pk)
    known = {key for key, _label in CHECKS} | {CUSTOM_CHECKS_KEY}
    checks = {k: v for k, v in (job.checks or {}).items() if k not in known}
    # Custom checks: existing rows (custom-0-…) then the blank "add" row (custom-new-…). An empty name removes a row.
    custom, seen = {}, set()
    prefixes = [f"custom-{i}" for i in range(MAX_CUSTOM_CHECKS + 1)] + ["custom-new"]
    for prefix in prefixes:
        label = request.POST.get(f"{prefix}-label", "").strip()[:40]
        if not label or label.lower() in seen or len(custom) >= MAX_CUSTOM_CHECKS:
            continue
        seen.add(label.lower())
        entry = {col: v for col in ("in", "out") if (v := request.POST.get(f"{prefix}-{col}", "")) in CHECK_RESULTS}
        note = request.POST.get(f"{prefix}-note", "").strip()[:200]
        if note:
            entry["note"] = note
        custom[label] = entry
    if custom:
        checks[CUSTOM_CHECKS_KEY] = custom
    for key, _label in CHECKS:
        entry = {}
        for col in ("in", "out"):
            value = request.POST.get(f"{key}_{col}", "")
            if value in CHECK_RESULTS:
                entry[col] = value
        note = request.POST.get(f"{key}_note", "").strip()[:200]
        if note:
            entry["note"] = note
        if entry:
            checks[key] = entry
    job.checks = checks
    job.save(update_fields=["checks", "updated_at"])
    messages.success(request, "Checks saved.")
    return redirect(f"{job.get_absolute_url()}#checks")


def job_sheet_pdf(request, pk):
    job = get_object_or_404(visible_jobs(request.user).select_related("customer", "machine"), pk=pk)
    filename = f"Repair_{job.repair_ref or job.ref}.pdf"
    response = HttpResponse(jobsheet.render(job), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


# --- Payments ------------------------------------------------------------------

def _visible_payments(user):
    from .models import Payment
    return Payment.objects.filter(job__in=visible_jobs(user)).select_related("job")


@require_POST
def payment_add(request, pk):
    job = get_object_or_404(visible_jobs(request.user), pk=pk)
    form = PaymentForm(request.POST)
    if form.is_valid():
        payment = form.save(commit=False)
        payment.job, payment.added_by = job, request.user
        payment.save()
    else:
        messages.error(request, "Charge not added: " + "; ".join(e for errs in form.errors.values() for e in errs))
    return redirect(f"{job.get_absolute_url()}#costs")


def payment_edit(request, pk):
    payment = get_object_or_404(_visible_payments(request.user), pk=pk)
    form = PaymentForm(request.POST or None, instance=payment)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect(f"{payment.job.get_absolute_url()}#costs")
    return render(request, "repairs/form.html", {
        "form": form, "title": f"Edit charge · {payment.job.ref}", "cancel": f"{payment.job.get_absolute_url()}#costs",
    })


@require_POST
def payment_delete(request, pk):
    payment = get_object_or_404(_visible_payments(request.user), pk=pk)
    job = payment.job
    payment.delete()
    return redirect(f"{job.get_absolute_url()}#costs")


# --- Stage history -------------------------------------------------------------

def stage_change_edit(request, pk):
    """Correct when a job moved stage. The stage bar follows the latest move into that stage."""
    change = get_object_or_404(StageChange.objects.filter(job__in=visible_jobs(request.user)).select_related("job"),
                               pk=pk)
    job = change.job
    form = StageChangeForm(request.POST or None, instance=change)
    if request.method == "POST" and form.is_valid():
        form.save()
        stage = Stage(change.to_stage)
        latest = job.stage_changes.filter(to_stage=stage).order_by("-changed_at", "-pk").first()
        field = STAGE_TIMESTAMP[stage]
        setattr(job, field, latest.changed_at)
        job.save(update_fields=[field, "updated_at"])
        messages.success(request, f"{change.get_to_stage_display()} date updated.")
        return redirect(job)
    return render(request, "repairs/form.html", {
        "form": form,
        "title": f"{job.ref}: when did it move to {change.get_to_stage_display()}?",
        "cancel": job.get_absolute_url(),
    })


# --- Photos and letters ---------------------------------------------------------

@require_POST
def attachment_upload(request, pk):
    from .models import JobAttachment
    job = get_object_or_404(visible_jobs(request.user), pk=pk)
    files = request.FILES.getlist("files")
    caption = request.POST.get("caption", "").strip()[:200]
    added, refused = 0, []
    for f in files:
        if f.size > attachments.max_bytes():
            refused.append(f"{f.name} is over {attachments.max_bytes() // (1024 * 1024)} MB")
            continue
        head = f.read(16)
        f.seek(0)
        kind = attachments.sniff(head)
        if kind is None:
            refused.append(f"{f.name} isn't a photo (JPEG, PNG, WebP, HEIC, GIF) or a PDF")
            continue
        content_type, ext = kind
        a = JobAttachment(job=job, original_name=f.name[:255], content_type=content_type, caption=caption,
                          uploaded_by=request.user)
        a.file.save(attachments.safe_name(f.name, ext), f, save=True)
        added += 1
    if added:
        messages.success(request, f"{added} file{'s' if added != 1 else ''} added.")
    for r in refused:
        messages.error(request, f"Not added: {r}.")
    if not files:
        messages.error(request, "Choose a photo or PDF to upload.")
    return redirect(f"{job.get_absolute_url()}#files")


def _visible_attachments(user):
    from .models import JobAttachment
    return JobAttachment.objects.filter(job__in=visible_jobs(user)).select_related("job")


def attachment_file(request, pk):
    a = get_object_or_404(_visible_attachments(request.user), pk=pk)
    try:
        fh = a.file.open("rb")
    except FileNotFoundError:
        raise Http404("File missing")
    response = FileResponse(fh, content_type=a.content_type, as_attachment=not (a.is_image or
                            a.content_type == "application/pdf"), filename=a.original_name)
    response["Cache-Control"] = "private, max-age=3600"
    return response


@require_POST
def attachment_delete(request, pk):
    a = get_object_or_404(_visible_attachments(request.user), pk=pk)
    job = a.job
    a.file.delete(save=False)
    a.delete()
    messages.success(request, "File deleted.")
    return redirect(f"{job.get_absolute_url()}#files")


@require_POST
def job_share(request, pk):
    """Set who (of the people who can't see everything) can see this job."""
    job = get_object_or_404(visible_jobs(request.user), pk=pk)
    candidates = {u.pk: u for u in _share_candidates(job)}
    chosen = {int(v) for v in request.POST.getlist("users") if v.isdigit() and int(v) in candidates}
    # Only change sharing for people this form offered; anyone else stays as they were
    current = set(job.shared_with.values_list("pk", flat=True))
    job.shared_with.remove(*[candidates[i] for i in (current & set(candidates)) - chosen])
    job.shared_with.add(*[candidates[i] for i in chosen - current])
    names = ", ".join(_name(candidates[i]) for i in sorted(chosen, key=lambda i: _name(candidates[i])))
    messages.success(request, f"{job.ref} is shared with {names}." if names else f"{job.ref} isn't shared with anyone.")
    return redirect(job)
