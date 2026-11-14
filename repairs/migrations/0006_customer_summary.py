from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("repairs", "0005_quotes_to_costs"),
    ]

    operations = [
        migrations.AddField(
            model_name="repairjob",
            name="customer_summary",
            field=models.TextField(
                blank=True,
                help_text="Plain-English summary of the work for the customer; printed on the job sheet"),
        ),
        migrations.AddField(
            model_name="repairjob",
            name="customer_summary_generated",
            field=models.TextField(blank=True, editable=False),
        ),
        migrations.AddField(
            model_name="repairjob",
            name="customer_summary_generated_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
    ]
