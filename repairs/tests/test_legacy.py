from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from repairs.legacy import FINANCE_REF, JETPACK_QUOTE_REF, MARKER, load
from repairs.models import Customer, JobCost, Machine, Payment, RepairJob, Stage

User = get_user_model()


def item(ref, customer="Lee Dobson", **extra):
    base = {"ref": ref, "customer": customer, "date_in": "2023-04-07", "date_out": "2023-05-01",
            "machine": {"model": "Amiga 600", "description": "", "serial": "Board 123"},
            "items_received": ["board", "lower_shield"], "accessories": "", "items_text": "Board and lower shield",
            "condition": "Clean", "work_requested": "Recap and check\nplease", "work_completed": "Recapped. Soak tested.",
            "log": ["Parts used: A600 cap kit", "Tested: Yes"], "costs": [], "payments": [], "money_notes": [],
            "checks": {}}
    base.update(extra)
    return base


class LegacyLoadTests(TestCase):
    def setUp(self):
        self.chris = User.objects.create_superuser("chris", first_name="Chris", password="x" * 20)
        self.lee = Customer.objects.create(first_name="Lee", last_name="Dobson")

    def test_creates_new_repair(self):
        data = {"jobs": [item("B16a", costs=[{"amount": 6.0, "date": "2023-04-08", "description": "Caps - RS"}],
                              payments=[{"amount": 40.0, "date": "2023-05-02"}], money_notes=["Payment: Not yet paid - £30"])]}
        result = load(data, self.chris, commit=True)
        self.assertTrue(result.committed)
        job = RepairJob.objects.get(repair_ref="B16a")
        self.assertEqual(job.customer, self.lee)  # exact (case-insensitive) name match
        self.assertEqual((job.stage, job.holder, job.technician, job.legacy_status), (Stage.RETURNED, self.chris, self.chris, MARKER))
        self.assertEqual(job.title, "Recap and check")
        self.assertEqual(timezone.localtime(job.received_at).date().isoformat(), "2023-04-07")
        self.assertEqual(timezone.localtime(job.returned_at).date().isoformat(), "2023-05-01")
        self.assertEqual(job.customer_summary, "Recapped. Soak tested.")
        self.assertEqual(job.items_received, ["board", "lower_shield"])
        note = job.notes.get()
        self.assertIn("Parts used: A600 cap kit", note.text)
        self.assertIn("Not yet paid", note.text)
        self.assertEqual(list(job.costs.values_list("kind", "amount")), [("parts", Decimal("6.00"))])
        self.assertEqual(list(job.payments.values_list("amount", "reference")), [(Decimal("40.00"), FINANCE_REF)])

    def test_dry_run_and_rerun(self):
        data = {"jobs": [item("01", customer="New Person")]}
        load(data, self.chris, commit=False)
        self.assertFalse(RepairJob.objects.exists())
        load(data, self.chris, commit=True)
        result = load(data, self.chris, commit=True)
        self.assertEqual(result.stats["jobs_already_loaded"], 1)
        self.assertEqual(RepairJob.objects.count(), 1)
        self.assertEqual(Customer.objects.filter(first_name="New").count(), 1)
        self.assertEqual(Machine.objects.count(), 1)

    def test_identical_finance_rows_are_both_kept(self):
        two = [{"amount": 25.0, "date": "2023-05-02"}, {"amount": 25.0, "date": "2023-05-02"}]
        data = {"jobs": [item("16", payments=two)]}
        load(data, self.chris, commit=True)
        load(data, self.chris, commit=True)
        self.assertEqual(RepairJob.objects.get(repair_ref="16").payments.count(), 2)

    def test_fills_gaps_on_jetpack_job_without_touching_log(self):
        job = RepairJob.objects.create(customer=self.lee, machine=Machine.objects.create(customer=self.lee, model="Amiga 600"),
                                       title="Jetpack job", repair_ref="A02", legacy_jetpack_id=7, stage=Stage.RETURNED,
                                       returned_at=timezone.now(), condition_on_arrival="Already known")
        job.notes.create(text="original log")
        job.stage_changes.create(from_stage="", to_stage=Stage.RETURNED, changed_at=job.returned_at)
        Payment.objects.create(job=job, amount=Decimal("25"), reference=JETPACK_QUOTE_REF)
        data = {"jobs": [item("A02", customer="Someone Else", checks={"power": {"in": "Y", "out": "Y"}},
                              payments=[{"amount": 37.0, "date": "2021-06-01"}],
                              costs=[{"amount": 6.0, "date": "2021-05-01", "description": "Caps"}])]}
        load(data, self.chris, commit=True)
        job.refresh_from_db()
        self.assertEqual(job.customer, self.lee)                       # customer untouched
        self.assertEqual(job.condition_on_arrival, "Already known")    # never overwritten
        self.assertEqual(job.customer_summary, "Recapped. Soak tested.")
        self.assertEqual(job.checks, {"power": {"in": "Y", "out": "Y"}})
        self.assertEqual(timezone.localtime(job.returned_at).date().isoformat(), "2023-05-01")  # real date replaces guess
        self.assertEqual(timezone.localtime(job.stage_changes.get().changed_at).date().isoformat(), "2023-05-01")
        self.assertEqual(list(job.notes.values_list("text", flat=True)), ["original log"])
        self.assertEqual(list(job.payments.values_list("amount", "reference")), [(Decimal("37.00"), FINANCE_REF)])
        self.assertEqual(job.costs.get().amount, Decimal("6.00"))

    def test_keeps_jetpack_parts_costs(self):
        job = RepairJob.objects.create(customer=self.lee, machine=Machine.objects.create(customer=self.lee, model="Amiga 600"),
                                       title="j", repair_ref="A14", legacy_jetpack_id=17)
        JobCost.objects.create(job=job, kind="parts", amount=Decimal("5"))
        result = load({"jobs": [item("A14", costs=[{"amount": 12.0, "date": None, "description": "Caps"}])]},
                      self.chris, commit=True)
        self.assertEqual(job.costs.count(), 1)
        self.assertTrue(any("A14" in n for n in result.notes))

    def test_conflict_with_job_made_in_app(self):
        RepairJob.objects.create(customer=self.lee, machine=Machine.objects.create(customer=self.lee, model="Amiga 600"),
                                 title="Made by hand", repair_ref="C14")
        result = load({"jobs": [item("C14")]}, self.chris, commit=True)
        self.assertEqual(len(result.conflicts), 1)
        self.assertEqual(RepairJob.objects.get(repair_ref="C14").title, "Made by hand")
