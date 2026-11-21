import django.utils.timezone
from django.db import migrations, models


def forwards(apps, schema_editor):
    from django.utils import timezone

    from repairs.money import derive_bench_time
    JobCost = apps.get_model("repairs", "JobCost")
    RepairJob = apps.get_model("repairs", "RepairJob")
    for cost in JobCost.objects.all():
        cost.date = timezone.localtime(cost.created_at).date()
        cost.save(update_fields=["date"])
    for job in RepairJob.objects.filter(payments__isnull=False).distinct():
        derive_bench_time(job, JobCost)


class Migration(migrations.Migration):

    dependencies = [
        ("repairs", "0013_repairjob_shared_with"),
    ]

    operations = [
        migrations.AlterModelOptions(name="jobcost", options={"ordering": ["date", "created_at", "pk"]}),
        migrations.AddField(
            model_name="jobcost", name="date",
            field=models.DateField(default=django.utils.timezone.localdate, help_text="When you bought it or did the work"),
        ),
        migrations.AddField(model_name="jobcost", name="supplier", field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name="jobcost", name="from_old_charge", field=models.BooleanField(default=False, editable=False)),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
