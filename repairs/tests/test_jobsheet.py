from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from repairs import jobsheet
from repairs.models import CHECKS, Customer, Machine, RepairJob
from repairs.summary import build_prompt
from repairs.models import JobNote

User = get_user_model()


class ChecksAndSheetTests(TestCase):
    def setUp(self):
        self.chris = User.objects.create_superuser("chris", password="a-long-test-pass")
        self.client.force_login(self.chris)
        self.customer = Customer.objects.create(first_name="Adam", last_name="Twine")
        self.machine = Machine.objects.create(customer=self.customer, model="Amiga 600",
                                              serial_number="Board 8514492315986004124297")
        self.job = RepairJob.objects.create(
            customer=self.customer, machine=self.machine, title="A600 sound", repair_ref="B23",
            work_requested="Rectify sound issues and recap", condition_on_arrival="OK. Has been recapped before.",
            items_received=["board", "lower_shield"], received_at=timezone.now(),
            customer_summary="Replaced U28 1488 buffer.\n\nSoak test whole board 12 hours")

    def save_checks(self, **values):
        return self.client.post(reverse("repairs:checks_save", args=[self.job.pk]), values)

    def test_checks_saved_and_shown(self):
        self.save_checks(power_in="Y", power_out="Y", audio_in="Fault", audio_out="Y",
                         audio_note="Filter stuck / bad quality", cd32_drive_in="n/a", serial_in="Bogus")
        self.job.refresh_from_db()
        self.assertEqual(self.job.checks, {
            "power": {"in": "Y", "out": "Y"},
            "audio": {"in": "Fault", "out": "Y", "note": "Filter stuck / bad quality"},
            "cd32_drive": {"in": "n/a"},
        })  # invalid values ignored, empty checks not stored
        rows = self.job.check_rows()
        self.assertEqual(len(rows), len(CHECKS))
        self.assertEqual(rows[4], ("audio", "Audio", "Fault", "Y", "Filter stuck / bad quality"))
        page = self.client.get(self.job.get_absolute_url())
        self.assertContains(page, 'value="Filter stuck / bad quality"')
        self.assertContains(page, "Job sheet PDF")

    def test_make_model_split(self):
        cases = [("Amiga 600", "", ("Amiga", "A600")), ("Amiga 500+", "", ("Amiga", "A500+")),
                 ("Amiga 1200", "Rev 1D4", ("Amiga", "A1200 (Rev 1D4)")), ("Amiga CD32", "", ("Amiga", "CD32")),
                 ("Commodore CDTV", "", ("Commodore", "CDTV")), ("Other", "DCE SX32", ("", "DCE SX32"))]
        for model, desc, expected in cases:
            self.machine.model, self.machine.description = model, desc
            self.assertEqual(self.job.machine_make_model, expected, model)

    def test_pdf(self):
        self.save_checks(audio_in="Fault", audio_out="Y", audio_note="Filter stuck")
        self.job.refresh_from_db()
        pdf = jobsheet.render(self.job)
        self.assertTrue(pdf.startswith(b"%PDF"))
        for text in [b"Adam Twine", b"B23", b"A600", b"Board 8514492315986004124297", b"Rectify sound issues",
                     b"Filter stuck", b"Fault", b"Replaced U28 1488 buffer", b"Board, Lower shield", b"Date Out"]:
            self.assertIn(text, pdf, text)

        resp = self.client.get(reverse("repairs:job_sheet_pdf", args=[self.job.pk]))
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertIn('filename="Repair_B23.pdf"', resp["Content-Disposition"])

    def test_pdf_copes_with_long_text_and_no_ref(self):
        self.job.repair_ref = ""
        self.job.customer_summary = "Lots of work. " * 400
        self.job.save()
        self.assertTrue(jobsheet.render(self.job).startswith(b"%PDF"))
        resp = self.client.get(reverse("repairs:job_sheet_pdf", args=[self.job.pk]))
        self.assertIn(f'filename="Repair_{self.job.ref}.pdf"', resp["Content-Disposition"])

    def test_prompt_includes_checks(self):
        self.save_checks(audio_in="Fault", audio_out="Y", audio_note="Filter stuck")
        self.job.refresh_from_db()
        JobNote.objects.create(job=self.job, text="Replaced U28")
        prompt = build_prompt(self.job)
        self.assertIn("Audio: in Fault, out Y (Filter stuck)", prompt)
        self.assertNotIn("Power:", prompt)  # unfilled checks left out

    def test_restricted_user(self):
        phil = User.objects.create_user("phil", password="a-long-test-pass")
        self.client.force_login(phil)
        self.assertEqual(self.client.get(reverse("repairs:job_sheet_pdf", args=[self.job.pk])).status_code, 404)
        self.assertEqual(self.save_checks(power_in="Y").status_code, 404)


class PcmciaCheckTests(TestCase):
    def test_pcmcia_is_a_standard_check_before_expansion(self):
        keys = [k for k, _ in CHECKS]
        self.assertEqual(keys[keys.index("pcmcia") + 1], "expansion")

    def test_fold_extra_checks(self):
        from repairs.models import fold_extra_checks
        folded = fold_extra_checks({"power": {"in": "Y"},
                                    "_extra": {"PCMCIA": {"in": "Y", "out": "Y"}, "Trapdoor": {"in": "n/a"}}})
        self.assertEqual(folded, {"power": {"in": "Y"}, "pcmcia": {"in": "Y", "out": "Y"},
                                  "_extra": {"Trapdoor": {"in": "n/a"}}})
        self.assertEqual(fold_extra_checks({"_extra": {"PCMCIA": {"in": "Y"}}}), {"pcmcia": {"in": "Y"}})
        # An existing PCMCIA result wins
        self.assertEqual(fold_extra_checks({"pcmcia": {"in": "Fault"}, "_extra": {"PCMCIA": {"in": "Y"}}}),
                         {"pcmcia": {"in": "Fault"}, "_extra": {"PCMCIA": {"in": "Y"}}})

    def test_pdf_and_page_show_pcmcia(self):
        chris = User.objects.create_superuser("chris", password="a-long-test-pass")
        self.client.force_login(chris)
        c = Customer.objects.create(first_name="Ada")
        job = RepairJob.objects.create(customer=c, machine=Machine.objects.create(customer=c, model="Amiga 600"),
                                       title="x", checks={"pcmcia": {"in": "Fault", "out": "Y", "note": "Card detect"}})
        self.assertIn(b"PCMCIA", jobsheet.render(job))
        self.assertIn(b"Card detect", jobsheet.render(job))
        self.assertContains(self.client.get(job.get_absolute_url()), 'value="Card detect"')
