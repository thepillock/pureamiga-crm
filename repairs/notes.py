"""Splitting a bench-log note into separate dated entries."""
from datetime import datetime, time
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

from .logtext import split_log

IMPORTED_HEADER = "[Imported from Jetpack CRM - bench log]"


def split_note(note, note_model=None):
    """Replace one note with one entry per date line in its text. Returns how many entries were added.

    Text before the first date stays in the original note (keeping its date); if there is none, the
    original note is removed. ``note_model`` lets data migrations pass their historical model.
    """
    note_model = note_model or type(note)
    text = note.text
    header = ""
    if text.startswith(IMPORTED_HEADER):
        header, text = IMPORTED_HEADER, text[len(IMPORTED_HEADER):].lstrip("\n")
    tz = ZoneInfo(settings.TIME_ZONE)
    default_year = timezone.localtime(note.created_at, tz).year if note.created_at else None
    entries = split_log(text, default_year=default_year)
    dated = [(d, body) for d, body in entries if d is not None]
    if not dated:
        return 0
    preamble = "\n".join(body for d, body in entries if d is None).strip()
    for d, body in dated:
        note_model.objects.create(
            job_id=note.job_id, author_id=note.author_id, text=body or "(no details)",
            created_at=datetime.combine(d, time(12, 0), tzinfo=tz),
        )
    if preamble:
        note.text = f"{header}\n{preamble}" if header else preamble
        note.save(update_fields=["text"])
    else:
        note.delete()
    return len(dated)
