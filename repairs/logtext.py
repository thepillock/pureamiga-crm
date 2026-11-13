"""Pure-Python helpers for bench-log text: splitting a free-text log into dated entries,
and finding repair references. No Django imports, so data migrations can use them too.

A log typically looks like:

    Unit arrived and tested ...        <- preamble (kept as its own entry)
    21/2/2022                          <- a date on its own line starts a new entry
    Removed old caps ...
    - 26/2/2022 - Soak tested          <- bullet + date + text on the same line also works
"""
from __future__ import annotations

import re
from datetime import date

REPAIR_REF_RE = re.compile(r"^[A-Z]?\d{2}$")
_REF_IN_TEXT = re.compile(
    r"(?i)\brepair\s+(?:(?:ref(?:erence)?|number|no\.?)\s*:?\s*([A-Z]?\d{2})|([A-Z]\d{2}))\b")

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_BULLET = r"(?:[-•*–]\s*)?"
_WEEKDAY = r"(?:(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*,?\s+)?"
_REST = r"(?:\s*(?:[-–:]|\s)\s*(?P<rest>\S.*))?"
_NUMERIC = re.compile(
    r"^\s*" + _BULLET + _WEEKDAY +
    r"(?P<d>\d{1,2})(?P<sep>[/.\-])(?P<m>\d{1,2})(?:[/.\-](?P<y>\d{4}|\d{2}))?:?" + _REST + r"\s*$", re.I)
_WORDY = re.compile(
    r"^\s*" + _BULLET + _WEEKDAY +
    r"(?P<d>\d{1,2})(?:st|nd|rd|th)?\s+(?P<mon>[a-z]{3,9})\.?,?\s+(?P<y>\d{4}):?" + _REST + r"\s*$", re.I)


def normalise_repair_ref(value: str) -> str:
    return (value or "").strip().upper()


def find_repair_ref(text: str) -> str:
    """First 'Repair Ref B12' / 'Repair number A04' / 'Repair A11' style reference in some text."""
    m = _REF_IN_TEXT.search(text or "")
    return (m.group(1) or m.group(2)).upper() if m else ""


def _ref_key(ref: str):
    letter = ref[0] if ref[0].isalpha() else ""
    return (ord(letter) - 64 if letter else 0, int(ref[-2:]))


def next_repair_ref(existing) -> str:
    """Next reference after the highest used: 01..99, then A00..A99, B00.. and so on."""
    refs = [r for r in (normalise_repair_ref(x) for x in existing) if REPAIR_REF_RE.match(r)]
    if not refs:
        return "01"
    letter, num = max(_ref_key(r) for r in refs)
    if num < 99:
        num += 1
    else:
        letter, num = letter + 1, 0
    if letter > 26:
        return ""
    return f"{chr(64 + letter) if letter else ''}{num:02d}"


def parse_date_line(line: str, default_year: int | None = None):
    """If the line is a date (optionally a bullet, optionally followed by text), return (date, rest)."""
    line = line.replace("\xa0", " ")
    m = _NUMERIC.match(line)
    if m:
        day, month = int(m["d"]), int(m["m"])
        year = m["y"]
        # A bare day/month (no year) only counts as "21/2" on its own: not "5-6 days" or "3.5".
        if year is None and (m["rest"] or m["sep"] != "/"):
            return None
    else:
        m = _WORDY.match(line)
        if not m or m["mon"][:3].lower() not in _MONTHS:
            return None
        day, month, year = int(m["d"]), _MONTHS[m["mon"][:3].lower()], m["y"]
    if year is None:
        if default_year is None:
            return None
        year = default_year
    else:
        year = int(year)
        if year < 100:
            year += 2000
    if not 2000 <= year <= 2100:
        return None
    try:
        return date(year, month, day), (m["rest"] or "").strip()
    except ValueError:
        return None


def split_log(text: str, default_year: int | None = None):
    """Split a log into [(date or None, text)], one entry per date line.

    Text before the first date line comes back with date None. Returns a single
    (None, text) entry when the log has no date lines.
    """
    entries = []
    current_date, lines = None, []
    year = default_year

    def flush():
        body = "\n".join(lines).strip("\n")
        if body.strip() or current_date is not None:
            entries.append((current_date, body.strip()))

    for line in (text or "").replace("\r\n", "\n").split("\n"):
        parsed = parse_date_line(line, default_year=year)
        if parsed:
            flush()
            current_date, rest = parsed
            year = current_date.year
            lines = [rest] if rest else []
        else:
            lines.append(line)
    flush()
    if not any(d for d, _ in entries):
        return [(None, (text or "").strip())]
    return entries


def has_date_lines(text: str) -> bool:
    return any(d for d, _ in split_log(text))
