from django.db import migrations, models

STAGES = [
    ("received", "Received"),
    ("in_progress", "Being worked on"),
    ("testing", "Being tested"),
    ("completed", "Completed"),
    ("returned", "Returned"),
]


class Migration(migrations.Migration):

    dependencies = [
        ("repairs", "0011_jobattachment"),
    ]

    operations = [
        migrations.AddField(
            model_name="repairjob",
            name="completed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="repairjob",
            name="stage",
            field=models.CharField(choices=STAGES, db_index=True, default="received", max_length=20),
        ),
        migrations.AlterField(
            model_name="stagechange",
            name="from_stage",
            field=models.CharField(blank=True, choices=STAGES, max_length=20),
        ),
        migrations.AlterField(
            model_name="stagechange",
            name="to_stage",
            field=models.CharField(choices=STAGES, max_length=20),
        ),
    ]
