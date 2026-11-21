import datetime
import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from repairs.models import Customer, JobNote, Machine, RepairJob
from repairs.notes import log_as_text


class CopyLogTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("chris", password="a-long-test-pass")
        c = Customer.objects.create(first_name="A", last_name="B")
        self.job = RepairJob.objects.create(customer=c, machine=Machine.objects.create(customer=c, model="A500"))
        tz = timezone.get_current_timezone()
        for day, text in [(3, "Second entry\nover two lines\n"), (1, "First entry")]:
            n = JobNote.objects.create(job=self.job, text=text)
            JobNote.objects.filter(pk=n.pk).update(created_at=datetime.datetime(2026, 11, day, 10, tzinfo=tz))

    def test_format(self):
        notes = self.job.notes.order_by("created_at")
        self.assertEqual(log_as_text(notes),
                         "Sun 1 Nov 2026\nFirst entry\n--\nTue 3 Nov 2026\nSecond entry\nover two lines")

    def test_button_and_text_on_page(self):
        self.client.force_login(self.user)
        page = self.client.get(self.job.get_absolute_url()).content.decode()
        self.assertIn('id="copy-log"', page)
        blob = page.split('<script id="log-text" type="application/json">')[1].split("</script>")[0]
        self.assertTrue(json.loads(blob).startswith("Sun 1 Nov 2026\nFirst entry\n--\n"))

    def test_no_button_when_log_empty(self):
        self.job.notes.all().delete()
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(self.job.get_absolute_url()), 'id="copy-log"')
