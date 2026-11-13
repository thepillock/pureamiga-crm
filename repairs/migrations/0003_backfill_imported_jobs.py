"""For jobs already imported from Jetpack CRM: pick up the repair ref from the bench log,
and split the imported bench log into one entry per date."""
from django.db import migrations

from repairs.logtext import find_repair_ref
from repairs.notes import IMPORTED_HEADER, split_note


def forwards(apps, schema_editor):
    RepairJob = apps.get_model("repairs", "RepairJob")
    JobNote = apps.get_model("repairs", "JobNote")

    used = set(RepairJob.objects.exclude(repair_ref="").values_list("repair_ref", flat=True))
    for job in RepairJob.objects.filter(legacy_jetpack_id__isnull=False, repair_ref=""):
        text = "\n".join(JobNote.objects.filter(job=job).values_list("text", flat=True)) + "\n" + job.title
        ref = find_repair_ref(text)
        if ref and ref not in used:
            job.repair_ref = ref
            job.save(update_fields=["repair_ref"])
            used.add(ref)

    for note in JobNote.objects.filter(text__startswith=IMPORTED_HEADER):
        split_note(note, JobNote)


class Migration(migrations.Migration):

    dependencies = [
        ("repairs", "0002_repair_ref_note_edits"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
