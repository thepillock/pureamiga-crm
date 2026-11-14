"""Draft a customer-facing summary of a repair from its work log, using Claude.

Only the job title, machine, work requested, condition on arrival, items received, parts used and the
work log are sent. No customer name, email, address or phone number, and no prices.
"""
import json
import urllib.error
import urllib.request

from django.conf import settings
from django.utils import timezone

from .notes import IMPORTED_HEADER

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
TIMEOUT_SECONDS = 90

SYSTEM_PROMPT = """You write the "Work Completed" box on the printed job sheet returned with a repaired \
retro computer (mostly Commodore Amiga) from the Pure Amiga repair service in the UK.

You are given the technician's work log, the job details and the in/out checks. Write a short summary for \
the customer covering, in roughly this order: the issues found, what was done about each, parts replaced, \
and the testing done.

Style - match the example below:
- Short and to the point. Usually one or two short sentences per issue: the fault, the fix, the result.
- Plain technical language an Amiga owner understands; name components (e.g. "U28 1488 buffer", "Denise").
- Sentence fragments are fine, e.g. "Replaced CIA, machine now boots." or "Video issues, Denise chip \
faulty - replaced and now working OK."
- Short paragraphs separated by blank lines. No headings, bullets, markdown, greeting or sign-off.
- Typically 40 to 130 words. Shorter is better when there was little to do.
- British English.

Rules:
- Only state what the log, details and checks support. Never invent faults, work, parts or tests.
- Do not mention prices, costs, postage, packaging, internal handovers, the old CRM system, or anyone's name.

Example of the style (a different job):
Ultrasonic clean, replaced caps with premium polymer ones. Made good some tracks and pads around video area.

Still "crunchy" sound and audio filter stuck on - also diagnostic tests show serial port not working.

Replaced U28 1488 buffer which controls both serial port and audio filter - serial now OK, filter working \
but sound still poor quality.

Low AVREF voltage to op-amp. Replaced op-amp and passive components providing voltage drop due to \
corrosion, cleaned in this area.

Sound now OK.

External floppy drive not working - broken ferrite bead on 5V line, replaced and tested OK

Soak test whole board 12 hours"""


class SummaryError(Exception):
    pass


def is_enabled():
    return bool(settings.ANTHROPIC_API_KEY)


def build_prompt(job):
    """The text sent to Claude. Deliberately excludes the customer and any money."""
    lines = [f"Job: {job.title}", f"Machine: {job.machine.display_model}"]
    if job.work_requested:
        lines.append(f"Work requested by the customer: {job.work_requested}")
    if job.condition_on_arrival:
        lines.append(f"Condition on arrival: {job.condition_on_arrival}")
    items = job.get_items_received_display()
    if items:
        lines.append("Items received: " + ", ".join(items))
    if job.accessories:
        lines.append(f"Accessories received: {job.accessories}")
    checks = [f"{label}: in {in_ or '-'}, out {out or '-'}" + (f" ({note})" if note else "")
              for _key, label, in_, out, note in job.check_rows() if in_ or out or note]
    if checks:
        lines.append("Checks (Y = OK):\n" + "\n".join(checks))
    parts = [c.description for c in job.costs.filter(kind="parts") if c.description]
    if parts:
        lines.append("Parts recorded: " + "; ".join(parts))
    lines.append("")
    lines.append("Work log (oldest first):")
    entries = 0
    for note in job.notes.order_by("created_at", "pk"):
        text = note.text
        if text.startswith(IMPORTED_HEADER):
            text = text[len(IMPORTED_HEADER):]
        if text.startswith("[Jetpack repair status was:") or not text.strip():
            continue
        lines.append(f"--- {timezone.localtime(note.created_at):%d %b %Y}")
        lines.append(text.strip())
        entries += 1
    if not entries:
        raise SummaryError("There's nothing in the work log to summarise yet.")
    return "\n".join(lines)


def _call_api(prompt):
    body = json.dumps({
        "model": settings.SUMMARY_MODEL,
        "max_tokens": 700,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    request = urllib.request.Request(API_URL, data=body, method="POST", headers={
        "x-api-key": settings.ANTHROPIC_API_KEY,
        "anthropic-version": API_VERSION,
        "content-type": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            detail = json.load(e).get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001 - error body isn't JSON
            detail = ""
        hint = {401: " Check the API key in the container settings.",
                404: " The model name may be wrong (CRM_SUMMARY_MODEL).",
                429: " Rate limited - try again in a minute.",
                529: " Claude is busy - try again shortly."}.get(e.code, "")
        raise SummaryError(f"Claude returned an error ({e.code}). {detail}{hint}".strip()) from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise SummaryError(f"Couldn't reach Claude: {getattr(e, 'reason', e)}") from e
    text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
    if not text.strip():
        raise SummaryError("Claude returned an empty summary.")
    return text.strip()


def generate_summary(job):
    """Generate a fresh draft and save it as the job's customer summary. Returns the text."""
    if not is_enabled():
        raise SummaryError("No Anthropic API key is set.")
    text = _call_api(build_prompt(job))
    job.customer_summary = text
    job.customer_summary_generated = text
    job.customer_summary_generated_at = timezone.now()
    job.save(update_fields=["customer_summary", "customer_summary_generated",
                            "customer_summary_generated_at", "updated_at"])
    return text
