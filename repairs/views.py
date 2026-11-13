from datetime import timedelta

from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import (BookInForm, CustomerForm, JobNoteEditForm, JobNoteForm, MachineForm, RepairJobForm,
                    suggested_repair_ref)
from .models import Customer, JobNote, Machine, RepairJob, Stage, StageChange
from .notes import split_note

RETURNED_ON_BOARD_DAYS = 14


def board(request):
    """Kanban board: one column per stage. Returned jobs only show for a couple of weeks."""
    jobs = RepairJob.objects.select_related("customer", "machine", "technician")
    q = request.GET.get("q", "").strip()
    if q:
        jobs = jobs.filter(_job_search(q))
    columns = []
    for stage in Stage:
        stage_jobs = jobs.filter(stage=stage)
        if stage == Stage.RETURNED and not q:
            cutoff = timezone.now() - timedelta(days=RETURNED_ON_BOARD_DAYS)
            stage_jobs = stage_jobs.filter(returned_at__gte=cutoff)
        columns.append({"stage": stage, "jobs": list(stage_jobs.order_by("received_at", "pk"))})
    return render(request, "repairs/board.html", {
        "columns": columns, "q": q, "returned_days": RETURNED_ON_BOARD_DAYS,
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
    jobs = RepairJob.objects.select_related("customer", "machine", "technician")
    q = request.GET.get("q", "").strip()
    stage = request.GET.get("stage", "")
    if q:
        jobs = jobs.filter(_job_search(q))
    if stage in Stage.values:
        jobs = jobs.filter(stage=stage)
    return render(request, "repairs/job_list.html", {
        "jobs": jobs[:500], "q": q, "stage": stage, "stages": Stage.choices,
    })


def job_detail(request, pk):
    job = get_object_or_404(RepairJob.objects.select_related("customer", "machine", "technician"), pk=pk)
    note_form = JobNoteForm()
    if request.method == "POST":
        note_form = JobNoteForm(request.POST)
        if note_form.is_valid():
            JobNote.objects.create(job=job, author=request.user, text=note_form.cleaned_data["text"])
            return redirect(job)
    return render(request, "repairs/job_detail.html", {
        "job": job,
        "notes": job.notes.select_related("author"),
        "history": job.stage_changes.select_related("changed_by"),
        "note_form": note_form,
        "stages": Stage,
        "next_repair_ref": "" if job.repair_ref else suggested_repair_ref(),
    })


def job_edit(request, pk):
    job = get_object_or_404(RepairJob, pk=pk)
    form = RepairJobForm(request.POST or None, instance=job)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"{job.ref} saved.")
        return redirect(job)
    return render(request, "repairs/form.html", {"form": form, "title": f"Edit {job.ref}", "cancel": job.get_absolute_url()})


@require_POST
def job_move(request, pk):
    job = get_object_or_404(RepairJob, pk=pk)
    stage = request.POST.get("stage")
    if stage in Stage.values:
        job.set_stage(stage, user=request.user)
        messages.success(request, f"{job.ref} moved to {job.get_stage_display()}.")
    nxt = request.POST.get("next", "")
    return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else job.get_absolute_url())


def job_book_in(request, customer_pk):
    customer = get_object_or_404(Customer, pk=customer_pk)
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
        messages.success(request, f"Booked in as {job.ref}.")
        return redirect(job)
    return render(request, "repairs/book_in.html", {"form": form, "customer": customer})


def customer_list(request):
    customers = Customer.objects.annotate(job_count=Count("jobs"))
    q = request.GET.get("q", "").strip()
    if q:
        customers = customers.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q)
            | Q(phone__icontains=q) | Q(postcode__icontains=q)
        )
    return render(request, "repairs/customer_list.html", {"customers": customers[:500], "q": q})


def customer_detail(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    return render(request, "repairs/customer_detail.html", {
        "customer": customer,
        "machines": customer.machines.annotate(job_count=Count("jobs")),
        "jobs": customer.jobs.select_related("machine", "technician"),
    })


def customer_edit(request, pk=None):
    customer = get_object_or_404(Customer, pk=pk) if pk else None
    form = CustomerForm(request.POST or None, instance=customer)
    if request.method == "POST" and form.is_valid():
        customer = form.save()
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
    machine = get_object_or_404(Machine.objects.select_related("customer"), pk=pk)
    return render(request, "repairs/machine_detail.html", {
        "machine": machine, "jobs": machine.jobs.select_related("technician"),
    })


def machine_edit(request, pk):
    machine = get_object_or_404(Machine, pk=pk)
    form = MachineForm(request.POST or None, instance=machine)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect(machine)
    return render(request, "repairs/form.html", {"form": form, "title": f"Edit {machine}", "cancel": machine.get_absolute_url()})


@require_POST
def job_assign_ref(request, pk):
    """Give the job the next free repair ref."""
    job = get_object_or_404(RepairJob, pk=pk)
    if not job.repair_ref:
        ref = suggested_repair_ref()
        if ref:
            job.repair_ref = ref
            job.save(update_fields=["repair_ref", "updated_at"])
            messages.success(request, f"Repair ref {ref} assigned to {job.ref}.")
    return redirect(job)


def note_edit(request, pk):
    note = get_object_or_404(JobNote.objects.select_related("job"), pk=pk)
    form = JobNoteEditForm(request.POST or None, instance=note)
    if request.method == "POST" and form.is_valid():
        note = form.save(commit=False)
        note.edited_at = timezone.now()
        note.save()
        return redirect(f"{note.job.get_absolute_url()}#note-{note.pk}")
    return render(request, "repairs/note_edit.html", {"form": form, "note": note, "job": note.job})


@require_POST
def note_delete(request, pk):
    note = get_object_or_404(JobNote.objects.select_related("job"), pk=pk)
    job = note.job
    note.delete()
    messages.success(request, "Log entry deleted.")
    return redirect(job)


@require_POST
def note_split(request, pk):
    note = get_object_or_404(JobNote.objects.select_related("job"), pk=pk)
    job = note.job
    added = split_note(note)
    if added:
        messages.success(request, f"Split into {added} dated entr{'y' if added == 1 else 'ies'}.")
    else:
        messages.info(request, "No date lines found to split on.")
    return redirect(job)
