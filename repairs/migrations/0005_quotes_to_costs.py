"""Quotes are no longer tracked. For jobs imported from Jetpack CRM, the quoted price becomes a cost line
(unless the job already has itemised costs - in the Jetpack data the quote is bench time + parts)."""
from django.conf import settings
from django.db import migrations


def quotes_to_costs(apps, schema_editor):
    RepairJob = apps.get_model("repairs", "RepairJob")
    JobCost = apps.get_model("repairs", "JobCost")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    importer = User.objects.filter(is_superuser=True).order_by("pk").first()
    jobs = RepairJob.objects.filter(legacy_jetpack_id__isnull=False, quote_value__gt=0)
    for job in jobs:
        if JobCost.objects.filter(job=job).exists():
            continue
        JobCost.objects.create(
            job=job, kind="other", amount=job.quote_value, description="Quoted price (from Jetpack CRM)",
            added_by_id=job.technician_id or (importer.pk if importer else None),
            created_at=job.quote_accepted_at or job.received_at or job.created_at,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("repairs", "0004_holder_costs"),
    ]

    operations = [
        migrations.RunPython(quotes_to_costs, migrations.RunPython.noop),
        migrations.RemoveField(model_name="repairjob", name="quote_value"),
        migrations.RemoveField(model_name="repairjob", name="quote_accepted_at"),
    ]
