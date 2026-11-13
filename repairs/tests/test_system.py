import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase, override_settings

from repairs.models import Customer, RepairJob

FIXTURE = Path(__file__).parent / "fixtures" / "mini_dump.sql"
User = get_user_model()


class ZeroConfigTests(TestCase):
    def test_secret_key_generated_into_data_dir(self):
        key_file = Path(settings.DATA_DIR) / "secret_key"
        self.assertTrue(key_file.exists())
        self.assertEqual(key_file.read_text().strip(), settings.SECRET_KEY)
        self.assertEqual(key_file.stat().st_mode & 0o777, 0o600)

    def test_healthz_needs_no_login(self):
        resp = self.client.get("/healthz")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b"ok")

    def test_any_host_accepted(self):
        User.objects.create_user("u", password="a-long-test-pass")
        self.assertEqual(self.client.get("/accounts/login/", HTTP_HOST="192.168.1.55:3300").status_code, 200)

    def test_cookies_secure_only_over_https(self):
        User.objects.create_user("u", password="a-long-test-pass")
        creds = {"username": "u", "password": "a-long-test-pass"}
        resp = self.client.post("/accounts/login/", creds, secure=True)
        self.assertTrue(resp.cookies[settings.SESSION_COOKIE_NAME]["secure"])
        self.client.logout()
        resp = self.client.post("/accounts/login/", creds)
        self.assertFalse(resp.cookies[settings.SESSION_COOKIE_NAME]["secure"])


class FirstRunSetupTests(TestCase):
    def test_login_sends_to_setup_when_no_accounts(self):
        self.assertRedirects(self.client.get("/accounts/login/"), "/setup/")

    def test_setup_creates_admin_and_then_closes(self):
        resp = self.client.post("/setup/", {
            "username": "chris", "first_name": "Chris",
            "password1": "correct-horse-battery", "password2": "correct-horse-battery",
        })
        self.assertRedirects(resp, "/tools/")
        user = User.objects.get()
        self.assertTrue(user.is_superuser and user.is_staff)
        self.assertEqual(user.first_name, "Chris")
        self.client.logout()
        self.assertRedirects(self.client.get("/setup/"), "/accounts/login/")
        self.client.post("/setup/", {"username": "intruder", "password1": "x" * 20, "password2": "x" * 20})
        self.assertEqual(User.objects.count(), 1)

    def test_setup_enforces_password_rules(self):
        self.client.post("/setup/", {"username": "chris", "first_name": "C", "password1": "short", "password2": "short"})
        self.assertEqual(User.objects.count(), 0)


class ToolsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("chris", first_name="Chris", password="a-long-test-pass", is_staff=True)
        self.client.force_login(self.admin)

    def upload(self, **extra):
        data = {"dump": SimpleUploadedFile("dump.sql", FIXTURE.read_bytes())}
        data.update(extra)
        return self.client.post("/tools/", data)

    def test_non_staff_forbidden(self):
        User.objects.create_user("tech", password="a-long-test-pass")
        self.client.login(username="tech", password="a-long-test-pass")
        self.assertEqual(self.client.get("/tools/").status_code, 403)
        self.assertEqual(self.client.post("/tools/backup/").status_code, 403)

    def test_tools_page_renders(self):
        self.assertContains(self.client.get("/tools/"), "Import from Jetpack CRM")

    def test_import_dry_run_then_commit(self):
        resp = self.upload()
        self.assertContains(resp, "Dry run")
        self.assertEqual(RepairJob.objects.count(), 0)
        resp = self.upload(commit="on")
        self.assertContains(resp, "Imported.")
        self.assertEqual(RepairJob.objects.count(), 3)
        self.assertEqual(Customer.objects.count(), 2)



class BackupTests(TransactionTestCase):
    """No wrapping transaction here: SQLite's backup waits on an open write transaction,
    which TestCase always has (real requests don't)."""

    def test_backup_download(self):
        admin = User.objects.create_user("chris", password="a-long-test-pass", is_staff=True)
        self.client.force_login(admin)
        with tempfile.TemporaryDirectory() as tmp, override_settings(DATA_DIR=tmp):
            resp = self.client.post("/tools/backup/")
            self.assertEqual(resp.status_code, 200)
            self.assertIn("attachment", resp["Content-Disposition"])
            resp.close()
            self.assertEqual(len(list((Path(tmp) / "backups").glob("crm-*.sqlite3"))), 1)
