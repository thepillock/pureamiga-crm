from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

from .logtext import has_date_lines


class Stage(models.TextChoices):
    RECEIVED = "received", "Received"
    IN_PROGRESS = "in_progress", "Being worked on"
    TESTING = "testing", "Being tested"
    RETURNED = "returned", "Returned"


STAGE_ORDER = [s.value for s in Stage]

# Which timestamp is set when a job enters each stage.
STAGE_TIMESTAMP = {
    Stage.RECEIVED: "received_at",
    Stage.IN_PROGRESS: "started_at",
    Stage.TESTING: "testing_at",
    Stage.RETURNED: "returned_at",
}

MACHINE_MODELS = [
    "Amiga 500", "Amiga 500+", "Amiga 600", "Amiga 1000", "Amiga 1200", "Amiga 1500",
    "Amiga 2000", "Amiga 3000", "Amiga 4000", "Amiga CD32", "Commodore CDTV", "Other", "Unknown",
]

ITEMS_RECEIVED_CHOICES = [
    ("board", "Board"),
    ("lower_shield", "Lower shield"),
    ("upper_shield", "Upper shield"),
    ("case", "Case"),
    ("keyboard", "Keyboard"),
    ("floppy", "Floppy"),
    ("psu", "PSU"),
    ("original_box", "Original box"),
    ("accessories", "Accessories (see list)"),
]


repair_ref_validator = RegexValidator(
    r"^[A-Z]?\d{2}$", "Two digits, or a letter and two digits, e.g. 36 or B55.")


class TimeStamped(models.Model):
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Customer(TimeStamped):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True, db_index=True)
    phone = models.CharField(max_length=50, blank=True)
    address_line1 = models.CharField("Address line 1", max_length=200, blank=True)
    address_line2 = models.CharField("Address line 2", max_length=200, blank=True)
    city = models.CharField(max_length=100, blank=True)
    county = models.CharField(max_length=100, blank=True)
    postcode = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=100, blank=True, default="United Kingdom")
    notes = models.TextField(blank=True)
    legacy_jetpack_id = models.PositiveIntegerField(null=True, blank=True, unique=True, editable=False)

    class Meta:
        ordering = ["last_name", "first_name"]

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def address(self):
        parts = [self.address_line1, self.address_line2, self.city, self.county, self.postcode, self.country]
        return "\n".join(p for p in parts if p)

    def get_absolute_url(self):
        return reverse("repairs:customer_detail", args=[self.pk])


class Machine(TimeStamped):
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="machines")
    model = models.CharField(max_length=50, choices=[(m, m) for m in MACHINE_MODELS])
    description = models.CharField(
        max_length=200, blank=True,
        help_text="Anything beyond the model, e.g. 'DCE SX32 plus riser' or 'Rev 1D4'",
    )
    serial_number = models.CharField(max_length=100, blank=True, db_index=True)
    notes = models.TextField(blank=True, help_text="Fitted upgrades, known history, etc.")

    class Meta:
        ordering = ["model", "serial_number"]

    def __str__(self):
        """One line, for dropdowns: 'Amiga 1200 (Rev 1D4) - 3456789'."""
        return f"{self.display_model} - {self.serial_number}" if self.serial_number else self.display_model

    @property
    def display_model(self):
        """Make/model without the serial, e.g. 'Amiga 1200 (Rev 1D4)' or 'DCE SX32 plus riser'."""
        label = self.model if self.model not in ("Other", "Unknown") or not self.description else self.description
        if self.description and label != self.description:
            label = f"{label} ({self.description})"
        return label

    def get_absolute_url(self):
        return reverse("repairs:machine_detail", args=[self.pk])


class RepairJob(TimeStamped):
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="jobs")
    machine = models.ForeignKey(Machine, on_delete=models.PROTECT, related_name="jobs")
    title = models.CharField(max_length=200, help_text="Short summary, e.g. 'A1200 premium recap'")
    repair_ref = models.CharField(
        "Repair ref", max_length=3, blank=True, db_index=True, validators=[repair_ref_validator],
        help_text="Given when a job becomes a repair: 36, A04, B55…",
    )
    stage = models.CharField(max_length=20, choices=Stage.choices, default=Stage.RECEIVED, db_index=True)
    technician = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="repair_jobs",
    )

    # Intake
    work_requested = models.TextField(blank=True)
    condition_on_arrival = models.TextField(blank=True)
    items_received = models.JSONField(default=list, blank=True)
    accessories = models.TextField(blank=True, help_text="Accelerators, drives, cables etc. that came with it")

    # Money
    quote_value = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    quote_accepted_at = models.DateTimeField(null=True, blank=True)
    bench_time_cost = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    parts_cost = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    # When it entered each stage
    received_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    testing_at = models.DateTimeField(null=True, blank=True)
    returned_at = models.DateTimeField(null=True, blank=True)

    return_tracking = models.CharField("Return tracking no.", max_length=100, blank=True)
    legacy_status = models.CharField(max_length=100, blank=True, editable=False)
    legacy_jetpack_id = models.PositiveIntegerField(null=True, blank=True, unique=True, editable=False)

    class Meta:
        ordering = ["-received_at", "-pk"]

    def __str__(self):
        return f"{self.ref} {self.title}"

    @property
    def ref(self):
        return f"PA{self.pk:04d}" if self.pk else "PA----"

    def get_absolute_url(self):
        return reverse("repairs:job_detail", args=[self.pk])

    def get_items_received_display(self):
        labels = dict(ITEMS_RECEIVED_CHOICES)
        return [labels.get(i, i) for i in self.items_received or []]

    @property
    def stage_entered_at(self):
        return getattr(self, STAGE_TIMESTAMP[Stage(self.stage)]) or self.created_at

    @property
    def days_in_stage(self):
        return (timezone.now() - self.stage_entered_at).days

    def next_stage(self):
        i = STAGE_ORDER.index(self.stage)
        return Stage(STAGE_ORDER[i + 1]) if i + 1 < len(STAGE_ORDER) else None

    def previous_stage(self):
        i = STAGE_ORDER.index(self.stage)
        return Stage(STAGE_ORDER[i - 1]) if i > 0 else None

    def set_stage(self, new_stage, user=None, when=None):
        """Move the job to a stage, stamp the time and record the change."""
        new_stage = Stage(new_stage)
        if new_stage == self.stage:
            return
        when = when or timezone.now()
        old = self.stage
        self.stage = new_stage
        setattr(self, STAGE_TIMESTAMP[new_stage], when)
        if new_stage == Stage.IN_PROGRESS and self.technician_id is None and user is not None:
            self.technician = user
        self.save()
        StageChange.objects.create(job=self, from_stage=old, to_stage=new_stage, changed_by=user, changed_at=when)


class StageChange(models.Model):
    job = models.ForeignKey(RepairJob, on_delete=models.CASCADE, related_name="stage_changes")
    from_stage = models.CharField(max_length=20, choices=Stage.choices, blank=True)
    to_stage = models.CharField(max_length=20, choices=Stage.choices)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    changed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["changed_at"]

    def __str__(self):
        return f"{self.job.ref}: {self.get_from_stage_display()} → {self.get_to_stage_display()}"


class JobNote(models.Model):
    """Bench log entry."""
    job = models.ForeignKey(RepairJob, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField("Date", default=timezone.now)
    edited_at = models.DateTimeField(null=True, blank=True, editable=False)
    text = models.TextField()

    @property
    def can_split(self):
        return has_date_lines(self.text)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"{self.job.ref} note {self.created_at:%Y-%m-%d}"
