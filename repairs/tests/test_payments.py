from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from repairs import logtext as lt
from repairs.models import Customer, Machine, Payment, RepairJob

User = get_user_model()


class PaymentViewTests(TestCase):
    def setUp(self):
        self.chris = User.objects.create_superuser("chris", first_name="Chris", password="a-long-test-pass")
        self.client.force_login(self.chris)
        c = Customer.objects.create(first_name="Ada")
        self.job = RepairJob.objects.create(customer=c, machine=Machine.objects.create(customer=c, model="Amiga 600"),
                                            title="Recap", received_at=timezone.now())

    def test_add_edit_delete(self):
        add = reverse("repairs:payment_add", args=[self.job.pk])
        self.client.post(add, {"paid_on": "2026-11-14", "method": "paypal", "amount": "45.00", "reference": "TX123"})
        self.client.post(add, {"paid_on": "2026-11-15", "method": "cash", "amount": "5"})
        self.client.post(add, {"paid_on": "2026-11-15", "method": "cash", "amount": "0"})  # rejected
        self.assertEqual(self.job.payments.count(), 2)
        page = self.client.get(self.job.get_absolute_url())
        self.assertNotContains(page, "Total charged")  # charges are kept but no longer shown on the job page
        p = self.job.payments.get(method="paypal")
        self.assertEqual(p.added_by, self.chris)
        self.client.post(reverse("repairs:payment_edit", args=[p.pk]),
                         {"paid_on": "2026-11-14", "method": "bank_transfer", "amount": "40", "reference": ""})
        p.refresh_from_db()
        self.assertEqual((p.method, p.amount), ("bank_transfer", Decimal("40.00")))
        self.client.post(reverse("repairs:payment_delete", args=[p.pk]))
        self.assertEqual(self.job.payments.count(), 1)

    def test_restricted_user(self):
        p = Payment.objects.create(job=self.job, amount=Decimal("10"))
        self.client.force_login(User.objects.create_user("phil", password="a-long-test-pass"))
        self.assertEqual(self.client.post(reverse("repairs:payment_add", args=[self.job.pk]),
                                          {"paid_on": "2026-11-14", "method": "cash", "amount": "1"}).status_code, 404)
        self.assertEqual(self.client.get(reverse("repairs:payment_edit", args=[p.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("repairs:payment_delete", args=[p.pk])).status_code, 404)


class RefSuffixTests(SimpleTestCase):
    def test_normalise_and_next(self):
        self.assertEqual(lt.normalise_repair_ref(" b16A "), "B16a")
        self.assertEqual(lt.normalise_repair_ref("36a"), "36a")
        self.assertEqual(lt.normalise_repair_ref("c13"), "C13")
        self.assertTrue(lt.REPAIR_REF_RE.match("B16a"))
        self.assertFalse(lt.REPAIR_REF_RE.match("B16AA"))
        self.assertEqual(lt.next_repair_ref(["C13", "C14", "B72a", "36a"]), "C15")


class RefSuffixFormTests(TestCase):
    def test_edit_form_accepts_follow_up_ref(self):
        chris = User.objects.create_superuser("chris", password="a-long-test-pass")
        self.client.force_login(chris)
        c = Customer.objects.create(first_name="Ada")
        m = Machine.objects.create(customer=c, model="Amiga 600")
        job = RepairJob.objects.create(customer=c, machine=m, title="x")
        data = {"title": "x", "repair_ref": "b16A", "machine": m.pk, "technician": "", "work_requested": "",
                "condition_on_arrival": "", "accessories": "", "return_tracking": ""}
        self.client.post(reverse("repairs:job_edit", args=[job.pk]), data)
        job.refresh_from_db()
        self.assertEqual(job.repair_ref, "B16a")


class QuotePaymentMigrationTests(TransactionTestCase):
    """0008 turns the 'Quoted price' cost lines into payments."""

    def test_quote_lines_become_payments(self):
        executor = MigrationExecutor(connection)
        executor.migrate([("repairs", "0007_checks")])
        old = executor.loader.project_state([("repairs", "0007_checks")]).apps
        customer = old.get_model("repairs", "Customer").objects.create(first_name="Ada")
        machine = old.get_model("repairs", "Machine").objects.create(customer=customer, model="Amiga 600")
        job = old.get_model("repairs", "RepairJob").objects.create(customer=customer, machine=machine, title="q")
        Cost = old.get_model("repairs", "JobCost")
        Cost.objects.create(job=job, kind="other", amount=Decimal("54"), description="Quoted price (from Jetpack CRM)")
        Cost.objects.create(job=job, kind="parts", amount=Decimal("6"), description="Caps")

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate([("repairs", "0008_payments_ref_suffix")])
        new = executor.loader.project_state([("repairs", "0008_payments_ref_suffix")]).apps
        self.assertEqual(list(new.get_model("repairs", "JobCost").objects.values_list("kind", "amount")),
                         [("parts", Decimal("6.00"))])
        self.assertEqual(list(new.get_model("repairs", "Payment").objects.values_list("amount", "method")),
                         [(Decimal("54.00"), "not_recorded")])


class PcmciaMigrationTests(TransactionTestCase):
    """0010 moves imported PCMCIA results out of the extra checks."""

    def test_fold(self):
        executor = MigrationExecutor(connection)
        executor.migrate([("repairs", "0009_payment_verbose_name")])
        old = executor.loader.project_state([("repairs", "0009_payment_verbose_name")]).apps
        customer = old.get_model("repairs", "Customer").objects.create(first_name="Ada")
        machine = old.get_model("repairs", "Machine").objects.create(customer=customer, model="Amiga 600")
        Job = old.get_model("repairs", "RepairJob")
        a = Job.objects.create(customer=customer, machine=machine, title="a",
                               checks={"power": {"in": "Y"}, "_extra": {"PCMCIA": {"in": "Y", "out": "Y"}}})
        b = Job.objects.create(customer=customer, machine=machine, title="b",
                               checks={"_extra": {"PCMCIA": {"in": "Y"}, "Trapdoor": {"in": "n/a"}}})
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate([("repairs", "0010_pcmcia_check")])
        new = executor.loader.project_state([("repairs", "0010_pcmcia_check")]).apps
        Job = new.get_model("repairs", "RepairJob")
        self.assertEqual(Job.objects.get(pk=a.pk).checks, {"power": {"in": "Y"}, "pcmcia": {"in": "Y", "out": "Y"}})
        self.assertEqual(Job.objects.get(pk=b.pk).checks,
                         {"pcmcia": {"in": "Y"}, "_extra": {"Trapdoor": {"in": "n/a"}}})
