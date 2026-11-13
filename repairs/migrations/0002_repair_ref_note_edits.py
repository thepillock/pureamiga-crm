import django.core.validators
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("repairs", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="repairjob",
            name="repair_ref",
            field=models.CharField(
                blank=True, db_index=True, help_text="Given when a job becomes a repair: 36, A04, B55…",
                max_length=3, verbose_name="Repair ref",
                validators=[django.core.validators.RegexValidator(
                    "^[A-Z]?\\d{2}$", "Two digits, or a letter and two digits, e.g. 36 or B55.")],
            ),
        ),
        migrations.AddField(
            model_name="jobnote",
            name="edited_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AlterField(
            model_name="jobnote",
            name="created_at",
            field=models.DateTimeField(default=django.utils.timezone.now, verbose_name="Date"),
        ),
    ]
