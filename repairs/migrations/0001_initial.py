import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

STAGES = [
    ("received", "Received"),
    ("in_progress", "Being worked on"),
    ("testing", "Being tested"),
    ("returned", "Returned"),
]

MODELS = [(m, m) for m in [
    "Amiga 500", "Amiga 500+", "Amiga 600", "Amiga 1000", "Amiga 1200", "Amiga 1500",
    "Amiga 2000", "Amiga 3000", "Amiga 4000", "Amiga CD32", "Commodore CDTV", "Other", "Unknown",
]]


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Customer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("first_name", models.CharField(max_length=100)),
                ("last_name", models.CharField(blank=True, max_length=100)),
                ("email", models.EmailField(blank=True, db_index=True, max_length=254)),
                ("phone", models.CharField(blank=True, max_length=50)),
                ("address_line1", models.CharField(blank=True, max_length=200, verbose_name="Address line 1")),
                ("address_line2", models.CharField(blank=True, max_length=200, verbose_name="Address line 2")),
                ("city", models.CharField(blank=True, max_length=100)),
                ("county", models.CharField(blank=True, max_length=100)),
                ("postcode", models.CharField(blank=True, max_length=20)),
                ("country", models.CharField(blank=True, default="United Kingdom", max_length=100)),
                ("notes", models.TextField(blank=True)),
                ("legacy_jetpack_id", models.PositiveIntegerField(blank=True, editable=False, null=True, unique=True)),
            ],
            options={"ordering": ["last_name", "first_name"]},
        ),
        migrations.CreateModel(
            name="Machine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("model", models.CharField(choices=MODELS, max_length=50)),
                ("description", models.CharField(blank=True, help_text="Anything beyond the model, e.g. 'DCE SX32 plus riser' or 'Rev 1D4'", max_length=200)),
                ("serial_number", models.CharField(blank=True, db_index=True, max_length=100)),
                ("notes", models.TextField(blank=True, help_text="Fitted upgrades, known history, etc.")),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="machines", to="repairs.customer")),
            ],
            options={"ordering": ["model", "serial_number"]},
        ),
        migrations.CreateModel(
            name="RepairJob",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("title", models.CharField(help_text="Short summary, e.g. 'A1200 premium recap'", max_length=200)),
                ("stage", models.CharField(choices=STAGES, db_index=True, default="received", max_length=20)),
                ("work_requested", models.TextField(blank=True)),
                ("condition_on_arrival", models.TextField(blank=True)),
                ("items_received", models.JSONField(blank=True, default=list)),
                ("accessories", models.TextField(blank=True, help_text="Accelerators, drives, cables etc. that came with it")),
                ("quote_value", models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ("quote_accepted_at", models.DateTimeField(blank=True, null=True)),
                ("bench_time_cost", models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ("parts_cost", models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ("received_at", models.DateTimeField(blank=True, null=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("testing_at", models.DateTimeField(blank=True, null=True)),
                ("returned_at", models.DateTimeField(blank=True, null=True)),
                ("return_tracking", models.CharField(blank=True, max_length=100, verbose_name="Return tracking no.")),
                ("legacy_status", models.CharField(blank=True, editable=False, max_length=100)),
                ("legacy_jetpack_id", models.PositiveIntegerField(blank=True, editable=False, null=True, unique=True)),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="jobs", to="repairs.customer")),
                ("machine", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="jobs", to="repairs.machine")),
                ("technician", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="repair_jobs", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-received_at", "-pk"]},
        ),
        migrations.CreateModel(
            name="StageChange",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("from_stage", models.CharField(blank=True, choices=STAGES, max_length=20)),
                ("to_stage", models.CharField(choices=STAGES, max_length=20)),
                ("changed_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("changed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ("job", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="stage_changes", to="repairs.repairjob")),
            ],
            options={"ordering": ["changed_at"]},
        ),
        migrations.CreateModel(
            name="JobNote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("text", models.TextField()),
                ("author", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ("job", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="notes", to="repairs.repairjob")),
            ],
            options={"ordering": ["created_at", "pk"]},
        ),
    ]
