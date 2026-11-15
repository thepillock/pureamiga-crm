from decimal import Decimal

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
    r"^[A-Z]?\d{2}[a-z]?$",
    "Two digits, or a letter and two digits, e.g. 36 or B55 (add a letter for a follow-up job, e.g. B16a).")


# The checks on the printed job sheet, in order.
CHECKS = [
    ("power", "Power"), ("boots", "Boots"), ("rgb_video", "RGB Video"), ("comp_video", "Comp Video"),
    ("audio", "Audio"), ("int_fdd", "Int FDD"), ("ext_fdd", "Ext FDD Port"), ("serial", "Serial Port"),
    ("parallel", "Parallel Port"), ("mouse", "Mouse Port"), ("joystick", "Joystick Port"), ("ide", "IDE Port"),
    ("cd32_drive", "CD32 Drive"), ("keyboard", "Keyboard"), ("memory", "Memory"), ("cias", "CIAs"),
    ("soak_test", "Soak Test"), ("pcmcia", "PCMCIA"), ("expansion", "Expansion"),
]
CHECK_RESULTS = ["Y", "Fault", "n/a"]
MAX_CUSTOM_CHECKS = 12
CUSTOM_CHECKS_KEY = "_extra"  # {label: {in, out, note}}: custom checks, incl. extra rows imported from old sheets


def fold_extra_checks(checks, known=None):
    """Move imported extra checks (checks["_extra"], keyed by the sheet's label) into standard checks
    whose label matches, e.g. "PCMCIA" -> checks["pcmcia"]. Returns a new dict."""
    checks = dict(checks or {})
    extra = dict(checks.pop("_extra", None) or {})
    by_label = {label.lower(): key for key, label in (known or CHECKS)}
    for label in list(extra):
        key = by_label.get(label.strip().lower())
        if key and not checks.get(key):
            checks[key] = extra.pop(label)
    if extra:
        checks["_extra"] = extra
    return checks


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
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, editable=False,
        related_name="customers_created",
    )

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
        "Repair ref", max_length=4, blank=True, db_index=True, validators=[repair_ref_validator],
        help_text="Given when a job becomes a repair: 36, A04, B55…",
    )
    stage = models.CharField(max_length=20, choices=Stage.choices, default=Stage.RECEIVED, db_index=True)
    technician = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="repair_jobs",
    )
    holder = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="held_jobs",
        verbose_name="With", help_text="Who has the job now",
    )

    # Intake
    work_requested = models.TextField(blank=True)
    condition_on_arrival = models.TextField(blank=True)
    items_received = models.JSONField(default=list, blank=True)
    accessories = models.TextField(blank=True, help_text="Accelerators, drives, cables etc. that came with it")

    # Money

    # When it entered each stage
    received_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    testing_at = models.DateTimeField(null=True, blank=True)
    returned_at = models.DateTimeField(null=True, blank=True)

    return_tracking = models.CharField("Return tracking no.", max_length=100, blank=True)
    checks = models.JSONField(default=dict, blank=True, help_text="Job sheet checks: {key: {in, out, note}}")
    customer_summary = models.TextField(
        blank=True, help_text="Plain-English summary of the work for the customer; printed on the job sheet")
    customer_summary_generated = models.TextField(blank=True, editable=False)  # last draft from Claude
    customer_summary_generated_at = models.DateTimeField(null=True, blank=True, editable=False)
    legacy_status = models.CharField(max_length=100, blank=True, editable=False)
    legacy_jetpack_id = models.PositiveIntegerField(null=True, blank=True, unique=True, editable=False)

    class Meta:
        ordering = ["-received_at", "-pk"]
        permissions = [("view_all_jobs", "Can see every job, not just ones they have held")]

    def __str__(self):
        return f"{self.ref} {self.title}"

    def check_rows(self):
        """[(key, label, in, out, note)] for every check on the job sheet."""
        rows = []
        for key, label in CHECKS:
            c = (self.checks or {}).get(key, {})
            rows.append((key, label, c.get("in", ""), c.get("out", ""), c.get("note", "")))
        return rows

    def custom_check_rows(self):
        """[(label, in, out, note)] for the job's own extra checks, in the order they were added."""
        custom = (self.checks or {}).get(CUSTOM_CHECKS_KEY) or {}
        return [(label, c.get("in", ""), c.get("out", ""), c.get("note", "")) for label, c in custom.items()]

    @property
    def machine_make_model(self):
        """('Amiga', 'A600') style split for the job sheet."""
        m = self.machine
        if m.model.startswith("Amiga "):
            rest = m.model[len("Amiga "):]
            make, model = "Amiga", (rest if rest.startswith("CD") else f"A{rest}")
        elif m.model.startswith("Commodore "):
            make, model = "Commodore", m.model[len("Commodore "):]
        else:
            return "", m.description or m.model
        return make, f"{model} ({m.description})" if m.description else model

    @property
    def summary_edited(self):
        """True if the summary has been changed by hand since it was last generated."""
        return bool(self.customer_summary.strip()) and self.customer_summary != self.customer_summary_generated

    @property
    def total_paid(self):
        return sum((p.amount for p in self.payments.all()), Decimal("0.00"))

    @property
    def total_costs(self):
        return sum((c.amount for c in self.costs.all()), Decimal("0.00"))

    def hand_to(self, user, by=None, when=None):
        """Make ``user`` the current holder and record the handover."""
        if user == self.holder:
            return
        when = when or timezone.now()
        old = self.holder
        self.holder = user
        self.save(update_fields=["holder", "updated_at"])
        HolderChange.objects.create(job=self, from_user=old, to_user=user, changed_by=by, changed_at=when)

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


class HolderChange(models.Model):
    """A job being handed from one person to another."""
    job = models.ForeignKey(RepairJob, on_delete=models.CASCADE, related_name="holder_changes")
    from_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="+")
    to_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="+")
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")
    changed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["changed_at"]

    def __str__(self):
        return f"{self.job.ref}: {self.from_user} → {self.to_user}"


class CostKind(models.TextChoices):
    BENCH_TIME = "bench_time", "Bench time"
    PARTS = "parts", "Parts"
    POSTAGE = "postage", "Postage"
    PACKAGING = "packaging", "Packaging"
    OTHER = "other", "Other"


class JobCost(models.Model):
    job = models.ForeignKey(RepairJob, on_delete=models.CASCADE, related_name="costs")
    kind = models.CharField("Type", max_length=20, choices=CostKind.choices, default=CostKind.PARTS)
    description = models.CharField(max_length=200, blank=True)
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"{self.job.ref} {self.get_kind_display()} £{self.amount}"


class PaymentMethod(models.TextChoices):
    BANK_TRANSFER = "bank_transfer", "Bank transfer"
    PAYPAL = "paypal", "PayPal"
    CARD = "card", "Card"
    CASH = "cash", "Cash"
    OTHER = "other", "Other"
    NOT_RECORDED = "not_recorded", "Not recorded"


class Payment(models.Model):
    """Money received from the customer for a job."""
    job = models.ForeignKey(RepairJob, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    paid_on = models.DateField("Date", default=timezone.localdate)
    method = models.CharField(max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.BANK_TRANSFER)
    reference = models.CharField(max_length=200, blank=True, help_text="Transaction ID, note, etc.")
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="+")
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["paid_on", "pk"]
        verbose_name = "charge"

    def __str__(self):
        return f"{self.job.ref} £{self.amount} {self.get_method_display()}"


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
