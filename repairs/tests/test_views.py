from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from repairs.models import Customer, Machine, RepairJob, Stage


class LoginRequiredTests(TestCase):
    def test_pages_redirect_to_login(self):
        for url in ["/", "/jobs/", "/customers/", "/customers/new/"]:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 302, url)
            self.assertIn("/accounts/login/", resp["Location"])

    def test_login_page_renders(self):
        get_user_model().objects.create_user("someone", password="a-long-test-pass")
        self.assertContains(self.client.get("/accounts/login/"), "Log in")


class WorkflowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("chris", first_name="Chris", password="a-long-test-pass")
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(first_name="Ada", last_name="Lovelace", email="ada@example.com")

    def book_in(self, **extra):
        data = {
            "machine": "", "new_model": "Amiga 1200", "new_description": "Rev 1D4", "new_serial": "SN1",
            "title": "Premium recap", "work_requested": "Recap", "condition_on_arrival": "Good",
            "items_received": ["board", "case"], "accessories": "", "technician": "",
        }
        data.update(extra)
        return self.client.post(reverse("repairs:job_book_in", args=[self.customer.pk]), data)

    def test_all_pages_render(self):
        self.book_in()
        job = RepairJob.objects.get()
        for url in ["/", "/?q=ada", "/?q=PA%04d" % job.pk, "/jobs/", "/jobs/?stage=received", "/customers/",
                    "/customers/?q=love", "/customers/new/", job.get_absolute_url(),
                    reverse("repairs:job_edit", args=[job.pk]), self.customer.get_absolute_url(),
                    reverse("repairs:customer_edit", args=[self.customer.pk]),
                    reverse("repairs:job_book_in", args=[self.customer.pk]),
                    job.machine.get_absolute_url(), reverse("repairs:machine_edit", args=[job.machine.pk]),
                    "/accounts/password/"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_book_in_new_machine(self):
        resp = self.book_in()
        job = RepairJob.objects.get()
        self.assertRedirects(resp, job.get_absolute_url())
        self.assertEqual(job.stage, Stage.RECEIVED)
        self.assertIsNotNone(job.received_at)
        self.assertEqual(job.items_received, ["board", "case"])
        self.assertEqual(job.machine.serial_number, "SN1")
        self.assertEqual(job.machine.customer, self.customer)
        self.assertEqual(job.stage_changes.count(), 1)
        self.assertContains(self.client.get("/"), "Premium recap")

    def test_book_in_existing_machine(self):
        machine = Machine.objects.create(customer=self.customer, model="Amiga 600", serial_number="X")
        self.book_in(machine=str(machine.pk), new_model="")
        self.assertEqual(RepairJob.objects.get().machine, machine)
        self.assertEqual(Machine.objects.count(), 1)

    def test_book_in_needs_a_machine(self):
        resp = self.book_in(new_model="")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(RepairJob.objects.count(), 0)

    def test_cannot_book_in_someone_elses_machine(self):
        other = Customer.objects.create(first_name="Other")
        machine = Machine.objects.create(customer=other, model="Amiga 600")
        resp = self.book_in(machine=str(machine.pk), new_model="")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(RepairJob.objects.count(), 0)

    def test_moving_through_stages(self):
        self.book_in()
        job = RepairJob.objects.get()
        move = reverse("repairs:job_move", args=[job.pk])
        self.client.post(move, {"stage": "in_progress", "next": "/"})
        job.refresh_from_db()
        self.assertEqual(job.stage, Stage.IN_PROGRESS)
        self.assertIsNotNone(job.started_at)
        self.assertEqual(job.technician, self.user)  # picked up by whoever started it
        self.client.post(move, {"stage": "testing"})
        self.client.post(move, {"stage": "returned"})
        job.refresh_from_db()
        self.assertEqual(job.stage, Stage.RETURNED)
        self.assertIsNotNone(job.returned_at)
        self.assertEqual(job.stage_changes.count(), 4)

    def test_move_rejects_get_and_unsafe_redirect(self):
        self.book_in()
        job = RepairJob.objects.get()
        move = reverse("repairs:job_move", args=[job.pk])
        self.assertEqual(self.client.get(move).status_code, 405)
        resp = self.client.post(move, {"stage": "testing", "next": "//evil.example"})
        self.assertEqual(resp["Location"], job.get_absolute_url())

    def test_add_bench_note(self):
        self.book_in()
        job = RepairJob.objects.get()
        self.client.post(job.get_absolute_url(), {"text": "Replaced C407"})
        self.assertEqual(job.notes.get().author, self.user)

    def test_new_customer_then_book_in(self):
        resp = self.client.post(reverse("repairs:customer_new"), {
            "first_name": "Jay", "last_name": "Miner", "country": "United Kingdom", "book_in": "1",
        })
        jay = Customer.objects.get(first_name="Jay")
        self.assertRedirects(resp, reverse("repairs:job_book_in", args=[jay.pk]))

    @override_settings(CRM_ENVIRONMENT="test")
    def test_environment_banner(self):
        self.assertContains(self.client.get("/"), "env-banner")

    def test_no_banner_in_release(self):
        self.assertNotContains(self.client.get("/"), "env-banner")
