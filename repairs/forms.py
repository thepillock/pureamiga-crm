from django import forms
from django.utils import timezone

from .logtext import next_repair_ref, normalise_repair_ref
from .models import ITEMS_RECEIVED_CHOICES, Customer, JobCost, JobNote, Machine, Payment, RepairJob, StageChange


def clean_repair_ref_value(value, job_pk=None):
    """Upper-case it and make sure no other job already has it."""
    value = normalise_repair_ref(value)
    if value and RepairJob.objects.filter(repair_ref=value).exclude(pk=job_pk).exists():
        raise forms.ValidationError(f"{value} is already used by another job.")
    return value


def suggested_repair_ref():
    return next_repair_ref(RepairJob.objects.exclude(repair_ref="").values_list("repair_ref", flat=True))


class ItemsReceivedField(forms.MultipleChoiceField):
    def __init__(self, **kwargs):
        kwargs.setdefault("choices", ITEMS_RECEIVED_CHOICES)
        kwargs.setdefault("widget", forms.CheckboxSelectMultiple)
        kwargs.setdefault("required", False)
        super().__init__(**kwargs)


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = [
            "first_name", "last_name", "email", "phone",
            "address_line1", "address_line2", "city", "county", "postcode", "country", "notes",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class MachineForm(forms.ModelForm):
    class Meta:
        model = Machine
        fields = ["model", "description", "serial_number", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class BookInForm(forms.ModelForm):
    """Book a machine in for a customer: pick one of their machines or describe a new one."""
    machine = forms.ModelChoiceField(queryset=Machine.objects.none(), required=False,
                                     empty_label="— New machine (fill in below) —")
    new_model = forms.ChoiceField(choices=[("", "—")] + Machine._meta.get_field("model").choices,
                                  required=False, label="Model")
    new_description = forms.CharField(required=False, label="Description",
                                      help_text="e.g. 'Rev 2B', 'SX32 plus riser'")
    new_serial = forms.CharField(required=False, label="Serial number")
    items_received = ItemsReceivedField()

    class Meta:
        model = RepairJob
        fields = [
            "machine", "title", "work_requested", "condition_on_arrival", "items_received", "accessories",
            "technician",
        ]
        widgets = {
            "work_requested": forms.Textarea(attrs={"rows": 3}),
            "condition_on_arrival": forms.Textarea(attrs={"rows": 3}),
            "accessories": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, customer, **kwargs):
        super().__init__(*args, **kwargs)
        self.customer = customer
        self.fields["machine"].queryset = customer.machines.all()

    def clean(self):
        data = super().clean()
        if not data.get("machine") and not data.get("new_model"):
            self.add_error("new_model", "Pick an existing machine or choose the model of the new one.")
        return data

    def save(self, commit=True):
        job = super().save(commit=False)
        job.customer = self.customer
        if not job.machine_id:
            job.machine = Machine.objects.create(
                customer=self.customer,
                model=self.cleaned_data["new_model"],
                description=self.cleaned_data["new_description"],
                serial_number=self.cleaned_data["new_serial"],
            )
        if commit:
            job.save()
        return job


class RepairJobForm(forms.ModelForm):
    items_received = ItemsReceivedField()

    class Meta:
        model = RepairJob
        fields = [
            "title", "repair_ref", "machine", "technician", "work_requested", "condition_on_arrival", "items_received",
            "accessories",
            "return_tracking",
        ]
        widgets = {
            "work_requested": forms.Textarea(attrs={"rows": 3}),
            "condition_on_arrival": forms.Textarea(attrs={"rows": 3}),
            "accessories": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["machine"].queryset = self.instance.customer.machines.all()
        if not self.instance.repair_ref:
            nxt = suggested_repair_ref()
            if nxt:
                self.fields["repair_ref"].help_text += f" Next free: {nxt}"

    def clean_repair_ref(self):
        return clean_repair_ref_value(self.cleaned_data.get("repair_ref"), self.instance.pk)


class JobNoteEditForm(forms.ModelForm):
    class Meta:
        model = JobNote
        fields = ["created_at", "text"]
        widgets = {
            "created_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "text": forms.Textarea(attrs={"rows": 10}),
        }


class JobNoteForm(forms.ModelForm):
    class Meta:
        model = JobNote
        fields = ["text"]
        widgets = {"text": forms.Textarea(attrs={"rows": 3, "placeholder": "Add to the work log…"})}
        labels = {"text": ""}


class JobCostForm(forms.ModelForm):
    class Meta:
        model = JobCost
        fields = ["kind", "date", "amount", "description", "supplier"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "description": forms.TextInput(attrs={"placeholder": "What it was, e.g. 2× 8520 CIA"}),
            "supplier": forms.TextInput(attrs={"placeholder": "Supplier (optional)"}),
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0", "placeholder": "0.00"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date"].required = False

    def clean_date(self):
        return self.cleaned_data.get("date") or timezone.localdate()

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount < 0:
            raise forms.ValidationError("Amount can't be negative.")
        return amount


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ["paid_on", "method", "amount", "reference"]
        widgets = {
            "paid_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0", "placeholder": "0.00"}),
            "reference": forms.TextInput(attrs={"placeholder": "Reference (optional)"}),
        }

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise forms.ValidationError("Amount must be more than zero.")
        return amount


class StageChangeForm(forms.ModelForm):
    class Meta:
        model = StageChange
        fields = ["changed_at"]
        labels = {"changed_at": "Date and time"}
        widgets = {"changed_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")}
