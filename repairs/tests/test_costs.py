import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from repairs.models import Customer, JobCost, Machine, Payment, RepairJob
from repairs.money import OLD_CHARGE_NOTE, derive_bench_time, tax_year

D = Decimal


class DeriveBenchTimeTests(TestCase):
    def setUp(self):
        c = Customer.objects.create(first_name="A")
        self.job = RepairJob.objects.create(customer=c, machine=Machine.objects.create(customer=c, model="A500"),
                                            repair_ref="B23")

    def charge(self, amount, day=1):
        Payment.objects.create(job=self.job, amount=amount, paid_on=datetime.date(2024, 5, day))

    def test_charge_minus_parts_is_bench_time(self):
        JobCost.objects.create(job=self.job, kind="parts", amount=D("12.50"))
        self.charge(D("40"), 1)
        self.charge(D("10"), 9)
        self.assertEqual(derive_bench_time(self.job), D("37.50"))
        line = self.job.costs.get(kind="bench_time")
        self.assertEqual((line.amount, line.description, line.date, line.from_old_charge),
                         (D("37.50"), OLD_CHARGE_NOTE, datetime.date(2024, 5, 9), True))
        self.assertEqual(self.job.total_costs, D("50.00"))
        # Re-running recalculates rather than adding another line
        derive_bench_time(self.job)
        self.assertEqual(self.job.costs.filter(kind="bench_time").count(), 1)

    def test_existing_bench_time_counts(self):
        JobCost.objects.create(job=self.job, kind="bench_time", amount=D("20"))
        self.charge(D("50"))
        derive_bench_time(self.job)
        self.assertEqual(sorted(self.job.costs.values_list("amount", flat=True)), [D("20"), D("30")])

    def test_nothing_added_when_it_doesnt_add_up(self):
        JobCost.objects.create(job=self.job, kind="parts", amount=D("76"))
        self.charge(D("52"))
        self.assertEqual(derive_bench_time(self.job), D("-24"))
        self.assertEqual(self.job.costs.count(), 1)
        self.assertIsNone(derive_bench_time(RepairJob.objects.create(customer=self.job.customer, machine=self.job.machine)))

    def test_editing_a_worked_out_line_keeps_it(self):
        user = get_user_model().objects.create_superuser("chris", password="a-long-test-pass")
        self.client.force_login(user)
        self.charge(D("40"))
        derive_bench_time(self.job)
        line = self.job.costs.get()
        self.client.post(reverse("repairs:cost_edit", args=[line.pk]),
                         {"kind": "bench_time", "date": "2024-05-01", "amount": "35", "description": "Recap"})
        line.refresh_from_db()
        self.assertFalse(line.from_old_charge)
        derive_bench_time(self.job)  # e.g. a later re-import
        self.assertEqual(list(self.job.costs.values_list("amount", flat=True)), [D("35.00"), D("5.00")])


class CostPanelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("chris", password="a-long-test-pass")
        self.client.force_login(self.user)
        c = Customer.objects.create(first_name="A")
        self.job = RepairJob.objects.create(customer=c, machine=Machine.objects.create(customer=c, model="A500"))

    def test_add_with_and_without_date_and_totals(self):
        add = reverse("repairs:cost_add", args=[self.job.pk])
        self.client.post(add, {"kind": "parts", "date": "2026-10-02", "amount": "8.40",
                               "description": "8520 CIA", "supplier": "AmigaKit"})
        self.client.post(add, {"kind": "bench_time", "amount": "45"})
        parts = self.job.costs.get(kind="parts")
        self.assertEqual((parts.date, parts.supplier), (datetime.date(2026, 10, 2), "AmigaKit"))
        self.assertIsNotNone(self.job.costs.get(kind="bench_time").date)
        page = self.client.get(self.job.get_absolute_url())
        self.assertContains(page, "Total asked")
        self.assertContains(page, "£53.40")
        self.assertContains(page, "AmigaKit")
        self.assertNotContains(page, "Add charge")


class PartsReportTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("chris", password="a-long-test-pass")
        self.client.force_login(self.user)
        c = Customer.objects.create(first_name="A")
        m = Machine.objects.create(customer=c, model="A500")
        self.job = RepairJob.objects.create(customer=c, machine=m, repair_ref="C09")
        for day, amount, kind in [((2026, 4, 5), "1", "parts"), ((2026, 4, 6), "2", "parts"),
                                  ((2027, 4, 5), "4", "parts"), ((2026, 6, 1), "50", "bench_time")]:
            JobCost.objects.create(job=self.job, kind=kind, amount=D(amount), date=datetime.date(*day),
                                   description="cap kit", supplier="Mouser")
        self.bad = RepairJob.objects.create(customer=c, machine=m, repair_ref="A65", title="Odd one")
        JobCost.objects.create(job=self.bad, kind="parts", amount=D("76"), date=datetime.date(2020, 1, 1))
        Payment.objects.create(job=self.bad, amount=D("52"))

    def test_tax_year(self):
        self.assertEqual(tax_year(datetime.date(2026, 11, 21)), (datetime.date(2026, 4, 6), datetime.date(2027, 4, 5)))
        self.assertEqual(tax_year(datetime.date(2027, 4, 5)), (datetime.date(2026, 4, 6), datetime.date(2027, 4, 5)))

    def test_range_csv_and_to_check(self):
        url = reverse("repairs:parts_report")
        page = self.client.get(url, {"from": "2026-04-06", "to": "2027-04-05"})
        self.assertEqual(page.context["total"], D("6.00"))  # parts only, inside the tax year
        self.assertContains(page, "C09")
        self.assertEqual([r["job"] for r in page.context["to_check"]], [self.bad])
        csv = self.client.get(url, {"from": "2026-04-06", "to": "2027-04-05", "csv": "1"})
        self.assertIn("text/csv", csv["Content-Type"])
        body = csv.content.decode()
        self.assertIn("2026-04-06,C09,", body)
        self.assertIn("Total,6.00", body)
        self.assertNotIn("2026-04-05", body.split("\n", 1)[1])

    def test_staff_only(self):
        phil = get_user_model().objects.create_user("phil", password="a-long-test-pass")
        self.client.force_login(phil)
        self.assertEqual(self.client.get(reverse("repairs:parts_report")).status_code, 403)
