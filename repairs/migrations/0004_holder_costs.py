import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def costs_to_lines(apps, schema_editor):
    """The old bench-time and parts cost fields become cost lines."""
    RepairJob = apps.get_model("repairs", "RepairJob")
    JobCost = apps.get_model("repairs", "JobCost")
    for job in RepairJob.objects.exclude(bench_time_cost__isnull=True, parts_cost__isnull=True):
        for kind, amount in (("bench_time", job.bench_time_cost), ("parts", job.parts_cost)):
            if amount:
                JobCost.objects.create(job=job, kind=kind, amount=amount,
                                       created_at=job.received_at or job.created_at)


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("repairs", "0003_backfill_imported_jobs"),
    ]

    operations = [
        migrations.AddField(
            model_name="customer",
            name="created_by",
            field=models.ForeignKey(blank=True, editable=False, null=True,
                                    on_delete=django.db.models.deletion.SET_NULL,
                                    related_name="customers_created", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="repairjob",
            name="holder",
            field=models.ForeignKey(blank=True, help_text="Who has the job now", null=True,
                                    on_delete=django.db.models.deletion.SET_NULL, related_name="held_jobs",
                                    to=settings.AUTH_USER_MODEL, verbose_name="With"),
        ),
        migrations.AlterModelOptions(
            name="repairjob",
            options={
                "ordering": ["-received_at", "-pk"],
                "permissions": [("view_all_jobs", "Can see every job, not just ones they have held")],
            },
        ),
        migrations.CreateModel(
            name="HolderChange",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("changed_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("changed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                                 related_name="+", to=settings.AUTH_USER_MODEL)),
                ("from_user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                                related_name="+", to=settings.AUTH_USER_MODEL)),
                ("job", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                          related_name="holder_changes", to="repairs.repairjob")),
                ("to_user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                              related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["changed_at"]},
        ),
        migrations.CreateModel(
            name="JobCost",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("bench_time", "Bench time"), ("parts", "Parts"),
                                                   ("postage", "Postage"), ("packaging", "Packaging"),
                                                   ("other", "Other")],
                                          default="parts", max_length=20, verbose_name="Type")),
                ("description", models.CharField(blank=True, max_length=200)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=8)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("added_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                               related_name="+", to=settings.AUTH_USER_MODEL)),
                ("job", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="costs",
                                          to="repairs.repairjob")),
            ],
            options={"ordering": ["created_at", "pk"]},
        ),
        migrations.RunPython(costs_to_lines, migrations.RunPython.noop),
        migrations.RemoveField(model_name="repairjob", name="bench_time_cost"),
        migrations.RemoveField(model_name="repairjob", name="parts_cost"),
    ]
