from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from repairs import jetpack_import as ji
from repairs.models import Customer, Machine, RepairJob, Stage

FIXTURE = Path(__file__).parent / "fixtures" / "mini_dump.sql"


class CleaningTests(SimpleTestCase):
    def test_clean_undoes_wordpress_escaping(self):
        self.assertEqual(ji.clean("Won\\'t boot \\\"at all\\\" &amp; more"), 'Won\'t boot "at all" & more')

    def test_normalise_model(self):
        self.assertEqual(ji.normalise_model("Amiga A1200"), ("Amiga 1200", ""))
        self.assertEqual(ji.normalise_model("A500+"), ("Amiga 500+", ""))
        self.assertEqual(ji.normalise_model("Amiga 500"), ("Amiga 500", ""))
        self.assertEqual(ji.normalise_model("CDTV & RGB2HDMI"), ("Commodore CDTV", "CDTV & RGB2HDMI"))
        self.assertEqual(ji.normalise_model("SupraRAM 500RX"), ("Other", "SupraRAM 500RX"))
        self.assertEqual(ji.normalise_model("DCE SX32 plus riser"), ("Other", "DCE SX32 plus riser"))
        self.assertEqual(ji.normalise_model(""), ("Unknown", ""))

    def test_parse_status(self):
        self.assertEqual(ji.parse_status("Chris - In test"), ("testing", "Chris"))
        self.assertEqual(ji.parse_status("Chris - Being worked on"), ("in_progress", "Chris"))
        self.assertEqual(ji.parse_status("Phil - Completed"), ("returned", "Phil"))
        self.assertEqual(ji.parse_status("Returned to customer"), ("returned", ""))
        self.assertEqual(ji.parse_status(""), ("returned", ""))

    def test_parse_items(self):
        self.assertEqual(ji.parse_items("\\'Board,Lower Shield,Accessories (see list)\\'"),
                         ["board", "lower_shield", "accessories"])

    def test_html_to_text(self):
        self.assertEqual(ji.html_to_text("<p>One<br />Two &amp; three</p>\r\n<p>Four</p>"), "One\nTwo & three\nFour")


class ImportCommandTests(TestCase):
    def run_import(self, *args):
        out = StringIO()
        call_command("import_jetpack", str(FIXTURE), *args, stdout=out)
        return out.getvalue()

    def test_dry_run_saves_nothing(self):
        output = self.run_import()
        self.assertIn("Dry run", output)
        self.assertEqual(Customer.objects.count(), 0)
        self.assertEqual(RepairJob.objects.count(), 0)

    def test_commit_imports_customers_machines_and_jobs(self):
        chris = get_user_model().objects.create_user("chris", first_name="Chris", password="x" * 16)
        self.run_import("--commit")

        self.assertEqual(Customer.objects.count(), 2)  # lead without jobs skipped
        ada = Customer.objects.get(legacy_jetpack_id=1)
        self.assertEqual(ada.last_name, "O'Test")
        self.assertEqual(ada.email, "ada@example.com")

        self.assertEqual(RepairJob.objects.count(), 3)  # orphan quote skipped
        first = RepairJob.objects.get(legacy_jetpack_id=10)
        self.assertEqual(first.title, 'A1200 premium recap and "fix video"')
        self.assertEqual(first.stage, Stage.RETURNED)
        self.assertIsNotNone(first.returned_at)
        self.assertEqual(first.items_received, ["board", "lower_shield", "accessories"])
        self.assertEqual(first.bench_time_cost, Decimal("35.00"))
        self.assertTrue(first.notes.filter(text__contains="Recapped & tested").exists())

        # Same serial (case-insensitive) on the same customer -> same machine, with history.
        second = RepairJob.objects.get(legacy_jetpack_id=11)
        self.assertEqual(second.machine_id, first.machine_id)
        self.assertEqual(second.stage, Stage.TESTING)
        self.assertEqual(second.technician, chris)
        self.assertEqual(Machine.objects.count(), 2)

        sx32 = RepairJob.objects.get(legacy_jetpack_id=12)
        self.assertEqual(sx32.machine.model, "Other")
        self.assertEqual(str(sx32.machine), "DCE SX32 plus riser")

    def test_reimport_is_idempotent(self):
        self.run_import("--commit")
        output = self.run_import("--commit")
        self.assertIn("jobs_existing: 3", output)
        self.assertEqual(RepairJob.objects.count(), 3)
        self.assertEqual(Customer.objects.count(), 2)
