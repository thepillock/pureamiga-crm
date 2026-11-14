from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("repairs", "0006_customer_summary"),
    ]

    operations = [
        migrations.AddField(
            model_name="repairjob",
            name="checks",
            field=models.JSONField(blank=True, default=dict, help_text="Job sheet checks: {key: {in, out, note}}"),
        ),
    ]
