from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from repairs.models import Customer, JobCost, JobNote, Machine, RepairJob, Stage

User = get_user_model()
FIXTURE = Path(__file__).parent / "fixtures" / "mini_dump.sql"


def book_in_data(**extra):
    data = {"machine": "", "new_model": "Amiga 600", "new_description": "", "new_serial": "",
            "title": "Via Phil", "work_requested": "", "condition_on_arrival": "", "accessories": "",
            "technician": ""}
    data.update(extra)
    return data


class VisibilityTests(TestCase):
    def setUp(self):
        self.chris = User.objects.create_superuser("chris", first_name="Chris", password="a-long-test-pass")
        self.phil = User.objects.create_user("phil", first_name="Phil", password="a-long-test-pass")

        # Chris's own job, never near Phil
        self.direct_customer = Customer.objects.create(first_name="Direct", last_name="Person", created_by=self.chris)
        self.direct_machine = Machine.objects.create(customer=self.direct_customer, model="Amiga 4000", serial_number="D1")
        self.direct = RepairJob.objects.create(customer=self.direct_customer, machine=self.direct_machine,
                                               title="Direct job", received_at=timezone.now())
        self.direct.hand_to(self.chris, by=self.chris)
        self.direct_note = JobNote.objects.create(job=self.direct, text="secret bench note")
        self.direct_cost = JobCost.objects.create(job=self.direct, kind="parts", amount=Decimal("5"))

        # Phil creates a customer and books a machine in
        self.client.force_login(self.phil)
        self.client.post(reverse("repairs:customer_new"), {"first_name": "Postal", "last_name": "Customer",
                                                            "country": "United Kingdom"})
        self.postal_customer = Customer.objects.get(first_name="Postal")
        self.client.post(reverse("repairs:job_book_in", args=[self.postal_customer.pk]), book_in_data())
        self.via_phil = RepairJob.objects.get(title="Via Phil")

    def test_booking_in_makes_you_the_holder(self):
        self.assertEqual(self.via_phil.holder, self.phil)
        self.assertEqual(self.postal_customer.created_by, self.phil)

    def test_phil_sees_only_his_jobs_and_customers(self):
        for url in ["/", "/jobs/", "/customers/", "/?q=Direct", "/jobs/?q=D1"]:
            resp = self.client.get(url)
            self.assertNotContains(resp, "Direct job", msg_prefix=url)
            self.assertNotContains(resp, "Direct Person", msg_prefix=url)
        self.assertContains(self.client.get("/"), "Via Phil")
        self.assertContains(self.client.get("/customers/"), "Postal Customer")

    def test_phil_cannot_open_or_change_hidden_things(self):
        job = self.direct
        gets = [job.get_absolute_url(), reverse("repairs:job_edit", args=[job.pk]),
                self.direct_customer.get_absolute_url(), reverse("repairs:customer_edit", args=[self.direct_customer.pk]),
                reverse("repairs:job_book_in", args=[self.direct_customer.pk]),
                self.direct_machine.get_absolute_url(), reverse("repairs:machine_edit", args=[self.direct_machine.pk]),
                reverse("repairs:note_edit", args=[self.direct_note.pk]),
                reverse("repairs:cost_edit", args=[self.direct_cost.pk])]
        for url in gets:
            self.assertEqual(self.client.get(url).status_code, 404, url)
        posts = [(reverse("repairs:job_move", args=[job.pk]), {"stage": "testing"}),
                 (reverse("repairs:job_hand", args=[job.pk]), {"user": self.phil.pk}),
                 (reverse("repairs:job_assign_ref", args=[job.pk]), {}),
                 (reverse("repairs:cost_add", args=[job.pk]), {"kind": "postage", "amount": "1"}),
                 (reverse("repairs:note_delete", args=[self.direct_note.pk]), {}),
                 (reverse("repairs:note_split", args=[self.direct_note.pk]), {}),
                 (reverse("repairs:cost_delete", args=[self.direct_cost.pk]), {}),
                 (job.get_absolute_url(), {"text": "sneaky"})]
        for url, data in posts:
            self.assertEqual(self.client.post(url, data).status_code, 404, url)
        job.refresh_from_db()
        self.assertEqual(job.stage, Stage.RECEIVED)
        self.assertEqual(job.holder, self.chris)
        self.assertTrue(JobNote.objects.filter(pk=self.direct_note.pk).exists())
        self.assertTrue(JobCost.objects.filter(pk=self.direct_cost.pk).exists())
        self.assertEqual(Customer.objects.count(), 2)

    def test_no_admin_or_tools_for_phil(self):
        self.assertEqual(self.client.get("/tools/").status_code, 403)
        self.assertNotEqual(self.client.get("/admin/repairs/repairjob/").status_code, 200)

    def test_chris_sees_everything(self):
        self.client.force_login(self.chris)
        resp = self.client.get("/")
        self.assertContains(resp, "Direct job")
        self.assertContains(resp, "Via Phil")
        self.assertContains(resp, "With Phil")
        self.assertEqual(self.client.get(self.via_phil.get_absolute_url()).status_code, 200)

    def test_with_me_filter(self):
        self.client.force_login(self.chris)
        resp = self.client.get("/?mine=1")
        self.assertContains(resp, "Direct job")
        self.assertNotContains(resp, "Via Phil")
        resp = self.client.get("/jobs/?mine=1")
        self.assertContains(resp, "Direct job")
        self.assertNotContains(resp, "Via Phil")

    def test_handing_a_job_to_phil_and_back(self):
        self.client.force_login(self.chris)
        self.client.post(reverse("repairs:job_hand", args=[self.direct.pk]), {"user": self.phil.pk})
        self.direct.refresh_from_db()
        self.assertEqual(self.direct.holder, self.phil)
        self.assertContains(self.client.get(self.direct.get_absolute_url()), "Handed from Chris to Phil")

        self.client.force_login(self.phil)
        self.assertContains(self.client.get("/"), "Direct job")
        self.assertEqual(self.client.get(self.direct_customer.get_absolute_url()).status_code, 200)
        # Phil hands it back: he keeps sight of it, since he's been involved
        self.client.post(reverse("repairs:job_hand", args=[self.direct.pk]), {"user": self.chris.pk})
        self.direct.refresh_from_db()
        self.assertEqual(self.direct.holder, self.chris)
        self.assertEqual(self.client.get(self.direct.get_absolute_url()).status_code, 200)
        self.assertEqual(self.direct.holder_changes.count(), 3)

    def test_both_can_move_any_stage(self):
        url = reverse("repairs:job_move", args=[self.via_phil.pk])
        for stage in ["returned", "received", "testing"]:
            self.client.post(url, {"stage": stage})
            self.via_phil.refresh_from_db()
            self.assertEqual(self.via_phil.stage, stage)

    def test_phil_adds_and_edits_costs(self):
        job = self.via_phil
        add = reverse("repairs:cost_add", args=[job.pk])
        self.client.post(add, {"kind": "postage", "description": "Special Delivery", "amount": "12.50"})
        self.client.post(add, {"kind": "packaging", "description": "", "amount": "3"})
        self.client.post(add, {"kind": "other", "description": "refund?", "amount": "-5"})  # rejected
        self.assertEqual(job.costs.count(), 2)
        cost = job.costs.get(kind="postage")
        self.assertEqual(cost.added_by, self.phil)
        resp = self.client.get(job.get_absolute_url())
        self.assertContains(resp, "Total – Phil")
        self.assertContains(resp, "£15.50")
        self.assertNotContains(resp, "Total – Chris")
        self.assertNotContains(resp, "grand")         # one person: no overall total line
        self.client.force_login(self.chris)
        self.client.post(add, {"kind": "parts", "description": "Caps", "amount": "10"})
        resp = self.client.get(job.get_absolute_url())
        self.assertContains(resp, "Total – Chris")
        self.assertContains(resp, "£25.50")          # overall total
        self.client.force_login(self.phil)
        self.client.post(reverse("repairs:cost_edit", args=[cost.pk]),
                         {"kind": "postage", "description": "Tracked 48", "amount": "4.00"})
        cost.refresh_from_db()
        self.assertEqual(cost.amount, Decimal("4.00"))
        self.client.post(reverse("repairs:cost_delete", args=[cost.pk]))
        self.assertEqual(job.costs.count(), 2)  # Phil's packaging + Chris's parts

    def test_view_all_permission(self):
        Permission.objects.get(codename="view_all_jobs")  # exists
        tech = User.objects.create_user("tech", password="a-long-test-pass")
        tech.user_permissions.add(Permission.objects.get(codename="view_all_jobs"))
        self.client.force_login(tech)
        self.assertContains(self.client.get("/"), "Direct job")


class ToolsHandImportedTests(TestCase):
    def test_give_already_imported_jobs_to_phil(self):
        chris = User.objects.create_superuser("chris", password="a-long-test-pass")
        phil = User.objects.create_user("phil", first_name="Phil", password="a-long-test-pass")
        self.client.force_login(chris)
        self.client.post("/tools/", {"dump": SimpleUploadedFile("d.sql", FIXTURE.read_bytes()), "commit": "on"})
        self.assertEqual(RepairJob.objects.filter(holder__isnull=True).count(), 3)
        self.assertContains(self.client.get("/tools/"), "Imported jobs with nobody")
        self.client.post("/tools/", {"action": "hand_imported", "user": phil.pk})
        self.assertEqual(RepairJob.objects.filter(holder=phil).count(), 3)
        self.assertNotContains(self.client.get("/tools/"), "Imported jobs with nobody")

    def test_import_form_holder(self):
        chris = User.objects.create_superuser("chris", password="a-long-test-pass")
        phil = User.objects.create_user("phil", password="a-long-test-pass")
        self.client.force_login(chris)
        self.client.post("/tools/", {"dump": SimpleUploadedFile("d.sql", FIXTURE.read_bytes()), "commit": "on",
                                     "holder": phil.pk})
        self.assertEqual(RepairJob.objects.filter(holder=phil).count(), 3)


class CostFieldMigrationTests(TransactionTestCase):
    """0004 turns the old bench-time/parts cost fields into cost lines."""

    def test_costs_become_lines(self):
        executor = MigrationExecutor(connection)
        executor.migrate([("repairs", "0003_backfill_imported_jobs")])
        old = executor.loader.project_state([("repairs", "0003_backfill_imported_jobs")]).apps
        customer = old.get_model("repairs", "Customer").objects.create(first_name="Ada")
        machine = old.get_model("repairs", "Machine").objects.create(customer=customer, model="Amiga 600")
        old.get_model("repairs", "RepairJob").objects.create(
            customer=customer, machine=machine, title="Old", bench_time_cost=Decimal("35"), parts_cost=Decimal("0"))

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate([("repairs", "0004_holder_costs")])
        new = executor.loader.project_state([("repairs", "0004_holder_costs")]).apps
        lines = list(new.get_model("repairs", "JobCost").objects.values_list("kind", "amount"))
        self.assertEqual(lines, [("bench_time", Decimal("35.00"))])


class QuoteMigrationTests(TransactionTestCase):
    """0005 turns imported quotes into cost lines, skipping jobs that already have costs."""

    def test_quotes_become_cost_lines(self):
        executor = MigrationExecutor(connection)
        executor.migrate([("repairs", "0004_holder_costs")])
        old = executor.loader.project_state([("repairs", "0004_holder_costs")]).apps
        boss = old.get_model("auth", "User").objects.create(username="boss", is_superuser=True)
        Job, Cost = old.get_model("repairs", "RepairJob"), old.get_model("repairs", "JobCost")
        customer = old.get_model("repairs", "Customer").objects.create(first_name="Ada")
        machine = old.get_model("repairs", "Machine").objects.create(customer=customer, model="Amiga 600")
        quoted = Job.objects.create(customer=customer, machine=machine, title="q", legacy_jetpack_id=1,
                                    quote_value=Decimal("54"))
        itemised = Job.objects.create(customer=customer, machine=machine, title="i", legacy_jetpack_id=2,
                                      quote_value=Decimal("35"))
        Cost.objects.create(job=itemised, kind="bench_time", amount=Decimal("35"))
        Job.objects.create(customer=customer, machine=machine, title="native", quote_value=Decimal("10"))

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate([("repairs", "0005_quotes_to_costs")])
        new = executor.loader.project_state([("repairs", "0005_quotes_to_costs")]).apps
        Cost = new.get_model("repairs", "JobCost")
        self.assertEqual(list(Cost.objects.filter(job_id=quoted.pk).values_list("kind", "amount", "added_by_id")),
                         [("other", Decimal("54.00"), boss.pk)])
        self.assertEqual(Cost.objects.filter(job_id=itemised.pk).count(), 1)
        self.assertEqual(Cost.objects.count(), 2)  # native job's quote isn't turned into a cost


class ExtraChecksKeptTests(TestCase):
    def test_saving_checks_keeps_imported_extras(self):
        chris = User.objects.create_superuser("chris", password="a-long-test-pass")
        self.client.force_login(chris)
        c = Customer.objects.create(first_name="Ada")
        job = RepairJob.objects.create(customer=c, machine=Machine.objects.create(customer=c, model="Amiga 600"),
                                       title="x", checks={"_extra": {"Trapdoor": {"in": "Y"}}, "other": {"x": 1}})
        # The page always sends the custom rows back, so they're kept (and unknown keys are left alone)
        self.client.post(reverse("repairs:checks_save", args=[job.pk]),
                         {"power_in": "Y", "custom-0-label": "Trapdoor", "custom-0-in": "Y"})
        job.refresh_from_db()
        self.assertEqual(job.checks, {"other": {"x": 1}, "_extra": {"Trapdoor": {"in": "Y"}}, "power": {"in": "Y"}})
