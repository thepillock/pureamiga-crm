from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("repairs", "0008_payments_ref_suffix"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="payment",
            options={"ordering": ["paid_on", "pk"], "verbose_name": "charge"},
        ),
    ]
