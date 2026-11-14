"""Payments, and repair refs with a follow-up letter (B16a).

The Jetpack "quote" turned out to be what the customer paid, so the "Quoted price (from Jetpack CRM)" cost lines
made by migration 0005 / the importer become payments instead."""
import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

QUOTE_DESCRIPTION = "Quoted price (from Jetpack CRM)"


def quote_costs_to_payments(apps, schema_editor):
    JobCost = apps.get_model("repairs", "JobCost")
    Payment = apps.get_model("repairs", "Payment")
    for cost in JobCost.objects.filter(kind="other", description=QUOTE_DESCRIPTION):
        Payment.objects.create(job_id=cost.job_id, amount=cost.amount, paid_on=cost.created_at.date(),
                               method="not_recorded", reference="From Jetpack quote", added_by_id=cost.added_by_id)
        cost.delete()


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("repairs", "0007_checks"),
    ]

    operations = [
        migrations.AlterField(
            model_name="repairjob",
            name="repair_ref",
            field=models.CharField(
                blank=True, db_index=True, help_text="Given when a job becomes a repair: 36, A04, B55…",
                max_length=4, verbose_name="Repair ref",
                validators=[django.core.validators.RegexValidator(
                    "^[A-Z]?\\d{2}[a-z]?$",
                    "Two digits, or a letter and two digits, e.g. 36 or B55 "
                    "(add a letter for a follow-up job, e.g. B16a).")],
            ),
        ),
        migrations.CreateModel(
            name="Payment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=8)),
                ("paid_on", models.DateField(default=django.utils.timezone.localdate, verbose_name="Date")),
                ("method", models.CharField(choices=[("bank_transfer", "Bank transfer"), ("paypal", "PayPal"),
                                                     ("card", "Card"), ("cash", "Cash"), ("other", "Other"),
                                                     ("not_recorded", "Not recorded")],
                                            default="bank_transfer", max_length=20)),
                ("reference", models.CharField(blank=True, help_text="Transaction ID, note, etc.", max_length=200)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("added_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                               related_name="+", to=settings.AUTH_USER_MODEL)),
                ("job", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="payments",
                                          to="repairs.repairjob")),
            ],
            options={"ordering": ["paid_on", "pk"]},
        ),
        migrations.RunPython(quote_costs_to_payments, migrations.RunPython.noop),
    ]
