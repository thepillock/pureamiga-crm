"""PCMCIA is now a standard check: move PCMCIA results that were imported as extra checks into it."""
from django.db import migrations

KNOWN = {"pcmcia": "pcmcia"}  # sheet label (lower case) -> check key


def fold(apps, schema_editor):
    RepairJob = apps.get_model("repairs", "RepairJob")
    for job in RepairJob.objects.filter(checks__has_key="_extra"):
        checks = dict(job.checks)
        extra = dict(checks.pop("_extra") or {})
        for label in list(extra):
            key = KNOWN.get(label.strip().lower())
            if key and not checks.get(key):
                checks[key] = extra.pop(label)
        if extra:
            checks["_extra"] = extra
        if checks != job.checks:
            job.checks = checks
            job.save(update_fields=["checks"])


class Migration(migrations.Migration):

    dependencies = [
        ("repairs", "0009_payment_verbose_name"),
    ]

    operations = [
        migrations.RunPython(fold, migrations.RunPython.noop),
    ]
