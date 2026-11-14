import io
import json
import urllib.error
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from repairs import summary
from repairs.models import Customer, JobCost, JobNote, Machine, RepairJob
from repairs.notes import IMPORTED_HEADER

User = get_user_model()
DRAFT = "On arrival the composite output showed dark bars.\n\nWe recapped the board."


class SummaryTestBase(TestCase):
    def setUp(self):
        self.chris = User.objects.create_superuser("chris", first_name="Chris", password="a-long-test-pass")
        self.client.force_login(self.chris)
        self.customer = Customer.objects.create(first_name="Sam", last_name="Secretname",
                                                email="sam@private.example", phone="07700 900123",
                                                address_line1="1 Hidden Road", postcode="LS1 4AP")
        self.machine = Machine.objects.create(customer=self.customer, model="Amiga 1200", description="Rev 1D4",
                                              serial_number="3456789")
        self.job = RepairJob.objects.create(customer=self.customer, machine=self.machine, title="A1200 recap",
                                            work_requested="Recap please", items_received=["board", "case"],
                                            received_at=timezone.now())
        JobCost.objects.create(job=self.job, kind="parts", description="Cap kit, CXA2075", amount=Decimal("18.40"))
        JobCost.objects.create(job=self.job, kind="postage", description="Royal Mail", amount=Decimal("4.95"))
        JobNote.objects.create(job=self.job, text="Composite shows dark bars. Recapped. Replaced CXA2075.")
        JobNote.objects.create(job=self.job, text="[Jetpack repair status was: Chris - Completed]")
        JobNote.objects.create(job=self.job, text=f"{IMPORTED_HEADER}\nSoak tested 4 hours, all fine.")


class PromptTests(SummaryTestBase):
    def test_prompt_has_the_work_but_no_customer_details_or_money(self):
        prompt = summary.build_prompt(self.job)
        for wanted in ["A1200 recap", "Amiga 1200 (Rev 1D4)", "Recap please", "Board, Case", "Cap kit, CXA2075",
                       "Replaced CXA2075", "Soak tested 4 hours"]:
            self.assertIn(wanted, prompt)
        for secret in ["Sam", "Secretname", "sam@private.example", "07700", "Hidden Road", "LS1",
                       "18.40", "4.95", "Royal Mail", "Jetpack", "3456789"]:
            self.assertNotIn(secret, prompt)

    def test_empty_log_refuses(self):
        self.job.notes.all().delete()
        with self.assertRaises(summary.SummaryError):
            summary.build_prompt(self.job)


@override_settings(ANTHROPIC_API_KEY="sk-test", SUMMARY_MODEL="claude-test")
class ApiCallTests(SummaryTestBase):
    def fake_response(self, payload):
        resp = mock.MagicMock()
        resp.__enter__.return_value = io.BytesIO(json.dumps(payload).encode())
        return resp

    def test_request_shape(self):
        with mock.patch("urllib.request.urlopen",
                        return_value=self.fake_response({"content": [{"type": "text", "text": " Draft. "}]})) as m:
            self.assertEqual(summary._call_api("hello"), "Draft.")
        request = m.call_args[0][0]
        self.assertEqual(request.full_url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(request.get_header("X-api-key"), "sk-test")
        self.assertEqual(request.get_header("Anthropic-version"), "2023-06-01")
        body = json.loads(request.data)
        self.assertEqual(body["model"], "claude-test")
        self.assertEqual(body["messages"], [{"role": "user", "content": "hello"}])
        self.assertIn("Work Completed", body["system"])

    def test_http_error_is_explained(self):
        err = urllib.error.HTTPError("u", 401, "Unauthorized", {},
                                     io.BytesIO(b'{"error": {"message": "invalid x-api-key"}}'))
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaisesRegex(summary.SummaryError, "401.*invalid x-api-key.*API key"):
                summary._call_api("hello")

    def test_network_error(self):
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("no route")):
            with self.assertRaisesRegex(summary.SummaryError, "Couldn't reach Claude"):
                summary._call_api("hello")


class SummaryViewTests(SummaryTestBase):
    def test_no_key_hides_generate_button(self):
        with override_settings(ANTHROPIC_API_KEY=""):
            resp = self.client.get(self.job.get_absolute_url())
        self.assertContains(resp, "Customer summary")
        self.assertNotContains(resp, "from work log</button>")
        self.assertContains(resp, "Add an Anthropic API key")

    @override_settings(ANTHROPIC_API_KEY="sk-test")
    def test_generate_saves_draft_and_regenerates_every_time(self):
        with mock.patch("repairs.summary._call_api", return_value=DRAFT) as m:
            resp = self.client.post(reverse("repairs:summary_generate", args=[self.job.pk]))
            self.assertRedirects(resp, f"{self.job.get_absolute_url()}#summary", fetch_redirect_response=False)
            self.job.refresh_from_db()
            self.assertEqual(self.job.customer_summary, DRAFT)
            self.assertFalse(self.job.summary_edited)
            m.return_value = "Second draft."
            self.client.post(reverse("repairs:summary_generate", args=[self.job.pk]))
        self.job.refresh_from_db()
        self.assertEqual(self.job.customer_summary, "Second draft.")
        self.assertEqual(m.call_count, 2)
        page = self.client.get(self.job.get_absolute_url())
        self.assertContains(page, "Regenerate from work log")
        self.assertNotContains(page, "Replace your edited summary")

    @override_settings(ANTHROPIC_API_KEY="sk-test")
    def test_edit_then_generate_asks_first(self):
        with mock.patch("repairs.summary._call_api", return_value=DRAFT):
            self.client.post(reverse("repairs:summary_generate", args=[self.job.pk]))
        self.client.post(reverse("repairs:summary_save", args=[self.job.pk]),
                         {"customer_summary": DRAFT + "\r\n\r\nThanks for your patience."})
        self.job.refresh_from_db()
        self.assertTrue(self.job.customer_summary.endswith("\n\nThanks for your patience."))
        self.assertTrue(self.job.summary_edited)
        self.assertContains(self.client.get(self.job.get_absolute_url()), "Replace your edited summary")

    @override_settings(ANTHROPIC_API_KEY="sk-test")
    def test_error_keeps_existing_summary(self):
        self.job.customer_summary = "Keep me"
        self.job.save()
        with mock.patch("repairs.summary._call_api", side_effect=summary.SummaryError("Claude is busy")):
            resp = self.client.post(reverse("repairs:summary_generate", args=[self.job.pk]), follow=True)
        self.assertContains(resp, "Couldn&#x27;t generate a summary: Claude is busy")
        self.job.refresh_from_db()
        self.assertEqual(self.job.customer_summary, "Keep me")

    @override_settings(ANTHROPIC_API_KEY="sk-test")
    def test_restricted_user_cannot_touch_other_jobs(self):
        phil = User.objects.create_user("phil", password="a-long-test-pass")
        self.client.force_login(phil)
        with mock.patch("repairs.summary._call_api", return_value=DRAFT) as m:
            self.assertEqual(self.client.post(reverse("repairs:summary_generate", args=[self.job.pk])).status_code, 404)
        m.assert_not_called()
        self.assertEqual(self.client.post(reverse("repairs:summary_save", args=[self.job.pk]),
                                          {"customer_summary": "x"}).status_code, 404)
        self.assertEqual(self.client.get(reverse("repairs:summary_save", args=[self.job.pk])).status_code, 405)
