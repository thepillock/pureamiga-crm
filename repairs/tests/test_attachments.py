import shutil
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from repairs.attachments import sniff
from repairs.models import Customer, JobAttachment, Machine, RepairJob

User = get_user_model()
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


class AttachmentTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        self.chris = User.objects.create_superuser("chris", first_name="Chris", password="a-long-test-pass")
        self.client.force_login(self.chris)
        c = Customer.objects.create(first_name="Ada")
        self.job = RepairJob.objects.create(customer=c, machine=Machine.objects.create(customer=c, model="Amiga 600"),
                                            title="x")
        self.url = reverse("repairs:attachment_upload", args=[self.job.pk])

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def upload(self, *files, caption=""):
        return self.client.post(self.url, {"files": list(files), "caption": caption}, follow=True)

    def test_sniff(self):
        self.assertEqual(sniff(PNG[:16]), ("image/png", ".png"))
        self.assertEqual(sniff(b"\xff\xd8\xff\xe0" + b"\0" * 12), ("image/jpeg", ".jpg"))
        self.assertEqual(sniff(b"RIFF\0\0\0\0WEBPVP8 "), ("image/webp", ".webp"))
        self.assertEqual(sniff(b"\0\0\0\x18ftypheic\0\0\0\0"), ("image/heic", ".heic"))
        self.assertEqual(sniff(PDF[:16]), ("application/pdf", ".pdf"))
        self.assertIsNone(sniff(b"<svg xmlns=...>"))
        self.assertIsNone(sniff(b"<html><script>"))

    def test_upload_view_and_delete(self):
        resp = self.upload(SimpleUploadedFile("Letter from Ada.png", PNG, "image/png"),
                           SimpleUploadedFile("scan.pdf", PDF, "application/pdf"), caption="Customer's letter")
        self.assertContains(resp, "2 files added")
        self.assertEqual(self.job.attachments.count(), 2)
        img = self.job.attachments.get(content_type="image/png")
        self.assertEqual((img.original_name, img.caption, img.uploaded_by), ("Letter from Ada.png", "Customer's letter", self.chris))
        self.assertTrue(img.file.name.startswith(f"jobs/{self.job.pk}/"))
        page = self.client.get(self.job.get_absolute_url())
        self.assertContains(page, "Photos &amp; letters")
        self.assertContains(page, f'<img src="{img.get_absolute_url()}"')

        resp = self.client.get(img.get_absolute_url())
        self.assertEqual(resp["Content-Type"], "image/png")
        self.assertEqual(b"".join(resp.streaming_content), PNG)
        pdf = self.job.attachments.get(content_type="application/pdf")
        self.assertIn("inline", self.client.get(pdf.get_absolute_url())["Content-Disposition"])

        path = Path(img.file.path)
        self.client.post(reverse("repairs:attachment_delete", args=[img.pk]))
        self.assertFalse(path.exists())
        self.assertEqual(self.job.attachments.count(), 1)

    def test_refuses_other_files_whatever_they_claim(self):
        resp = self.upload(SimpleUploadedFile("evil.png", b"<svg onload=alert(1)>", "image/png"),
                           SimpleUploadedFile("notes.txt", b"hello", "text/plain"))
        self.assertContains(resp, "Not added: evil.png")
        self.assertContains(resp, "Not added: notes.txt")
        self.assertFalse(JobAttachment.objects.exists())

    @override_settings(MAX_ATTACHMENT_BYTES=100)
    def test_size_limit(self):
        resp = self.upload(SimpleUploadedFile("big.png", PNG + b"\0" * 200, "image/png"))
        self.assertContains(resp, "is over")
        self.assertFalse(JobAttachment.objects.exists())

    def test_restricted_user_and_login(self):
        self.upload(SimpleUploadedFile("a.png", PNG, "image/png"))
        a = JobAttachment.objects.get()
        self.client.force_login(User.objects.create_user("phil", password="a-long-test-pass"))
        self.assertEqual(self.client.get(a.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.post(reverse("repairs:attachment_delete", args=[a.pk])).status_code, 404)
        self.assertEqual(self.client.post(self.url, {"files": [SimpleUploadedFile("b.png", PNG)]}).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(a.get_absolute_url()).status_code, 302)  # to login
