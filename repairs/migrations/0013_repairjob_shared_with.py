from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("repairs", "0012_completed_stage"),
    ]

    operations = [
        migrations.AddField(
            model_name="repairjob",
            name="shared_with",
            field=models.ManyToManyField(blank=True, help_text="People who can see this job without holding it",
                                         related_name="shared_jobs", to=settings.AUTH_USER_MODEL),
        ),
    ]
