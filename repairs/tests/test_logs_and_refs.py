import importlib
from datetime import date

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from repairs import logtext as lt
from repairs.models import Customer, JobNote, Machine, RepairJob
from repairs.notes import IMPORTED_HEADER, split_note


class LogTextTests(SimpleTestCase):
    def test_date_lines(self):
        cases = {
            "21/2/2022": (date(2022, 2, 21), ""),
            "- 21/02/2022": (date(2022, 2, 21), ""),
            "- \xa021/2/2022": (date(2022, 2, 21), ""),
            "26/2/22": (date(2022, 2, 26), ""),
            "1-3-2023": (date(2023, 3, 1), ""),
            "12/3/2023 - parts ordered": (date(2023, 3, 12), "parts ordered"),
            "12/3/2023: parts ordered": (date(2023, 3, 12), "parts ordered"),
            "Monday 13/3/2023": (date(2023, 3, 13), ""),
            "21st February 2022": (date(2022, 2, 21), ""),
            "3 Mar 2024 - tested": (date(2024, 3, 3), "tested"),
            "21/2": (date(2022, 2, 21), ""),  # bare day/month takes the running year
        }
        for line, expected in cases.items():
            self.assertEqual(lt.parse_date_line(line, default_year=2022), expected, line)

    def test_not_date_lines(self):
        for line in ["Date Opened: 14/2/2022", "- 5-6 days", "3.5", "- 3.5", "Repair Ref A09", "- 9.9V = 9.9V",
                     "31/2/2022", "21/13/2022", "12/3/1999", "21/2 replaced caps", "1.2 tested", ""]:
            self.assertIsNone(lt.parse_date_line(line, default_year=2022), line)

    def test_split_log(self):
        text = "Unit arrived.\nRepair Ref A09\n\n21/2/2022\nRecapped\nVideo OK\n\n- 26/2/2022 - Soak tested\n\n1/3\nPosted"
        self.assertEqual(lt.split_log(text), [
            (None, "Unit arrived.\nRepair Ref A09"),
            (date(2022, 2, 21), "Recapped\nVideo OK"),
            (date(2022, 2, 26), "Soak tested"),
            (date(2022, 3, 1), "Posted"),
        ])

    def test_split_log_without_dates(self):
        self.assertEqual(lt.split_log("Just text\nmore"), [(None, "Just text\nmore")])
        self.assertFalse(lt.has_date_lines("Just text"))

    def test_find_repair_ref(self):
        self.assertEqual(lt.find_repair_ref("blah\nRepair Ref B12\n"), "B12")
        self.assertEqual(lt.find_repair_ref("Repair ref: c01"), "C01")
        self.assertEqual(lt.find_repair_ref("Assigned repair number A04 and"), "A04")
        self.assertEqual(lt.find_repair_ref("Repair A11"), "A11")
        self.assertEqual(lt.find_repair_ref("Repair Ref 36"), "36")
        self.assertEqual(lt.find_repair_ref("repair £35, repair video issue"), "")

    def test_next_repair_ref(self):
        self.assertEqual(lt.next_repair_ref([]), "01")
        self.assertEqual(lt.next_repair_ref(["36", "98"]), "99")
        self.assertEqual(lt.next_repair_ref(["99", "12"]), "A00")
        self.assertEqual(lt.next_repair_ref(["98", "A04", "B55", "C12", "b60"]), "C13")
        self.assertEqual(lt.next_repair_ref(["B99"]), "C00")


class RefAndNoteViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("chris", first_name="Chris", password="a-long-test-pass")
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(first_name="Ada")
        self.machine = Machine.objects.create(customer=self.customer, model="Amiga 1200", serial_number="3456789")
        self.job = RepairJob.objects.create(customer=self.customer, machine=self.machine, title="Recap",
                                            received_at=timezone.now())

    def edit_data(self, **extra):
        data = {"title": "Recap", "repair_ref": "", "machine": self.machine.pk, "technician": "",
                "work_requested": "", "condition_on_arrival": "", "accessories": "", "quote_value": "",
                "quote_accepted_at": "", "bench_time_cost": "", "parts_cost": "", "return_tracking": ""}
        data.update(extra)
        return data

    def test_repair_ref_saved_upper_case_and_shown_in_list(self):
        url = reverse("repairs:job_edit", args=[self.job.pk])
        self.client.post(url, self.edit_data(repair_ref="b55"))
        self.job.refresh_from_db()
        self.assertEqual(self.job.repair_ref, "B55")
        resp = self.client.get("/jobs/")
        self.assertContains(resp, "Repair ref")
        self.assertContains(resp, ">B55<")
        self.assertContains(self.client.get("/jobs/?q=b55"), "Recap")

    def test_repair_ref_format_and_uniqueness(self):
        url = reverse("repairs:job_edit", args=[self.job.pk])
        for bad in ["5", "AB1", "123", "A5"]:
            resp = self.client.post(url, self.edit_data(repair_ref=bad))
            self.assertEqual(resp.status_code, 200, bad)
        other = RepairJob.objects.create(customer=self.customer, machine=self.machine, title="Other", repair_ref="A04")
        resp = self.client.post(url, self.edit_data(repair_ref="a04"))
        self.assertContains(resp, "already used")
        self.job.refresh_from_db()
        self.assertEqual(self.job.repair_ref, "")
        # A job keeping its own ref is fine
        resp = self.client.post(reverse("repairs:job_edit", args=[other.pk]), self.edit_data(repair_ref="A04"))
        self.assertEqual(resp.status_code, 302)

    def test_next_free_suggested_and_assigned(self):
        RepairJob.objects.create(customer=self.customer, machine=self.machine, title="Old", repair_ref="B98")
        self.assertContains(self.client.get(reverse("repairs:job_edit", args=[self.job.pk])), "Next free: B99")
        self.assertContains(self.client.get(self.job.get_absolute_url()), "Assign B99")
        self.client.post(reverse("repairs:job_assign_ref", args=[self.job.pk]))
        self.job.refresh_from_db()
        self.assertEqual(self.job.repair_ref, "B99")

    def test_machine_shows_serial_on_its_own_line_without_hash(self):
        for url in ["/", "/jobs/", self.job.get_absolute_url(), self.customer.get_absolute_url()]:
            resp = self.client.get(url)
            self.assertContains(resp, '<br><span class="serial">3456789</span>', msg_prefix=url)
            self.assertNotContains(resp, "#3456789", msg_prefix=url)

    def test_edit_note_text_and_date(self):
        note = JobNote.objects.create(job=self.job, author=self.user, text="Old text")
        resp = self.client.post(reverse("repairs:note_edit", args=[note.pk]),
                                {"text": "New text", "created_at": "2024-03-05T10:30"})
        self.assertRedirects(resp, f"{self.job.get_absolute_url()}#note-{note.pk}", fetch_redirect_response=False)
        note.refresh_from_db()
        self.assertEqual(note.text, "New text")
        self.assertEqual(timezone.localtime(note.created_at).date(), date(2024, 3, 5))
        self.assertIsNotNone(note.edited_at)
        self.assertEqual(self.client.get(reverse("repairs:note_edit", args=[note.pk])).status_code, 200)

    def test_delete_note(self):
        note = JobNote.objects.create(job=self.job, text="Oops")
        self.assertEqual(self.client.get(reverse("repairs:note_delete", args=[note.pk])).status_code, 405)
        self.client.post(reverse("repairs:note_delete", args=[note.pk]))
        self.assertFalse(JobNote.objects.exists())

    def test_split_note_button(self):
        note = JobNote.objects.create(job=self.job, author=self.user, text="Arrived\n21/2/2022\nCaps\n22/2/2022\nTested")
        self.assertContains(self.client.get(self.job.get_absolute_url()), "Split by date")
        self.client.post(reverse("repairs:note_split", args=[note.pk]))
        texts = list(self.job.notes.order_by("created_at", "pk").values_list("text", flat=True))
        self.assertEqual(texts, ["Caps", "Tested", "Arrived"])  # dated 2022 entries sort before today's
        dated = self.job.notes.exclude(pk=note.pk).order_by("created_at")
        self.assertEqual([timezone.localtime(n.created_at).date() for n in dated], [date(2022, 2, 21), date(2022, 2, 22)])
        self.assertTrue(all(n.author == self.user for n in dated))
        note.refresh_from_db()
        self.assertEqual(note.text, "Arrived")

    def test_split_note_without_preamble_removes_original(self):
        note = JobNote.objects.create(job=self.job, text="21/2/2022\nCaps")
        self.assertEqual(split_note(note), 1)
        self.assertFalse(JobNote.objects.filter(pk=note.pk).exists())
        self.assertEqual(self.job.notes.get().text, "Caps")


class BackfillMigrationTests(TestCase):
    """The 0003 data migration fixes jobs imported before refs/splitting existed."""

    def test_backfill(self):
        customer = Customer.objects.create(first_name="Ada")
        machine = Machine.objects.create(customer=customer, model="Amiga 600")
        job = RepairJob.objects.create(customer=customer, machine=machine, title="Old", legacy_jetpack_id=5)
        JobNote.objects.create(job=job, text=f"{IMPORTED_HEADER}\nArrived\nRepair Ref A07\n\n1/3/2022\nCaps\n\n2/3/2022\nTested")
        native = RepairJob.objects.create(customer=customer, machine=machine, title="New", repair_ref="A08")
        JobNote.objects.create(job=native, text="21/2/2022\nLeft alone: not imported")

        migration = importlib.import_module("repairs.migrations.0003_backfill_imported_jobs")
        migration.forwards(django_apps, None)

        job.refresh_from_db()
        self.assertEqual(job.repair_ref, "A07")
        self.assertEqual(job.notes.count(), 3)
        self.assertTrue(job.notes.filter(text="Caps").exists())
        self.assertEqual(native.notes.count(), 1)
