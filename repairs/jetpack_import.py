"""Read Jetpack CRM (Zero BS CRM) data out of a phpMyAdmin MySQL dump.

Pure Python with no Django imports, so it can be tested on its own. The Django
management command ``import_jetpack`` turns the result into database rows.

Jetpack CRM object types: 1 = contact, 3 = quote. Pure Amiga used quotes as
repair jobs, with custom fields for the machine and the repair status.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

OBJ_CONTACT = "1"
OBJ_QUOTE = "3"

WANTED_TABLES = ("zbs_contacts", "zbs_quotes", "zbs_customfields", "zbs_object_links")

# "Parts sent" checklist values, mapped to the new checklist keys.
ITEMS_RECEIVED = {
    "board": "board",
    "lower shield": "lower_shield",
    "upper shield": "upper_shield",
    "case": "case",
    "keyboard": "keyboard",
    "floppy": "floppy",
    "psu": "psu",
    "original box": "original_box",
    "accessories (see list)": "accessories",
}

# Normalised machine model names, matched against the free-text "make-model" field.
MODEL_PATTERNS = [
    (r"\b(?:amiga\s*)?a?\s*500\s*\+|500\s*plus", "Amiga 500+"),
    (r"\b(?:amiga\s*)?a?\s*500\b", "Amiga 500"),
    (r"\b(?:amiga\s*)?a?\s*600\b", "Amiga 600"),
    (r"\b(?:amiga\s*)?a?\s*1000\b", "Amiga 1000"),
    (r"\b(?:amiga\s*)?a?\s*1200\b", "Amiga 1200"),
    (r"\b(?:amiga\s*)?a?\s*1500\b", "Amiga 1500"),
    (r"\b(?:amiga\s*)?a?\s*2000\b", "Amiga 2000"),
    (r"\b(?:amiga\s*)?a?\s*3000\b", "Amiga 3000"),
    (r"\b(?:amiga\s*)?a?\s*4000\b", "Amiga 4000"),
    (r"\bcd\s*32\b", "Amiga CD32"),
    (r"\bcdtv\b", "Commodore CDTV"),
]


# --------------------------------------------------------------------------- dump parsing

def _parse_values(s: str, i: int) -> tuple[list[list[str | None]], int]:
    """Parse the tuples of a MySQL ``INSERT ... VALUES (...),(...);`` starting at i."""
    rows: list[list[str | None]] = []
    n = len(s)
    while i < n:
        while i < n and s[i] in " ,\n\r\t":
            i += 1
        if i >= n or s[i] == ";":
            break
        if s[i] != "(":
            raise ValueError("Unexpected SQL near: %r" % s[i:i + 60])
        i += 1
        row: list[str | None] = []
        while True:
            while s[i] == " ":
                i += 1
            if s[i] == "'":
                i += 1
                buf = []
                while True:
                    c = s[i]
                    if c == "\\":
                        nx = s[i + 1]
                        buf.append({"n": "\n", "r": "\r", "t": "\t", "0": "\0", "Z": "\x1a"}.get(nx, nx))
                        i += 2
                    elif c == "'":
                        if s[i + 1] == "'":
                            buf.append("'")
                            i += 2
                        else:
                            i += 1
                            break
                    else:
                        buf.append(c)
                        i += 1
                row.append("".join(buf))
            else:
                j = i
                while s[j] not in ",)":
                    j += 1
                tok = s[i:j].strip()
                i = j
                row.append(None if tok == "NULL" else tok)
            if s[i] == ",":
                i += 1
                continue
            if s[i] == ")":
                i += 1
                break
        rows.append(row)
    return rows, i


def read_tables(sql: str, wanted=WANTED_TABLES) -> dict[str, list[dict]]:
    """Return {short_table_name: [row dicts]} for the wanted tables, whatever the WP prefix."""
    out: dict[str, list[dict]] = {t: [] for t in wanted}
    pattern = re.compile(r"INSERT INTO `[A-Za-z0-9_]*?_(%s)` \(([^)]*)\) VALUES\s*" % "|".join(wanted))
    pos = 0
    while True:
        m = pattern.search(sql, pos)
        if not m:
            break
        cols = [c.strip(" `") for c in m.group(2).split(",")]
        rows, pos = _parse_values(sql, m.end())
        out[m.group(1)].extend(dict(zip(cols, r)) for r in rows)
    return out


# --------------------------------------------------------------------------- cleaning

def clean(text: str | None) -> str:
    """Undo WordPress slash-escaping and HTML entities."""
    if not text:
        return ""
    text = text.replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\")
    return html.unescape(text).replace("\r\n", "\n").strip()


def html_to_text(text: str | None) -> str:
    text = clean(text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>|</li>|</div>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "- ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def epoch(value: str | None) -> datetime | None:
    try:
        v = int(value or 0)
    except ValueError:
        return None
    return datetime.fromtimestamp(v, tz=timezone.utc) if v > 0 else None


def money(value: str | None) -> Decimal | None:
    value = (value or "").strip().lstrip("£")
    if not value:
        return None
    try:
        return Decimal(value).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def normalise_model(raw: str) -> tuple[str, str]:
    """Return (model, extra description). Unknown kit becomes model 'Other'."""
    raw = clean(raw)
    if not raw:
        return "Unknown", ""
    for pat, name in MODEL_PATTERNS:
        if re.search(pat, raw, re.I):
            # Keep the original text as the description if it said more than the model.
            rest = raw if re.sub(r"[^a-z0-9]", "", raw.lower()) not in {
                re.sub(r"[^a-z0-9]", "", name.lower()),
                re.sub(r"[^a-z0-9]", "", name.lower().replace("amiga ", "a")),
                re.sub(r"[^a-z0-9]", "", name.lower().replace("amiga ", "amiga a")),
            } else ""
            return name, rest
    return "Other", raw


def parse_items(raw: str) -> list[str]:
    raw = clean(raw).strip("'\" ")
    items = []
    for part in raw.split(","):
        key = ITEMS_RECEIVED.get(part.strip(" '\"").lower())
        if key and key not in items:
            items.append(key)
    return items


def parse_status(raw: str) -> tuple[str, str]:
    """'Chris - In test' -> ('testing', 'Chris'). Jobs without a status are historic -> returned."""
    raw = clean(raw)
    tech = ""
    if " - " in raw:
        tech, raw = (p.strip() for p in raw.split(" - ", 1))
    s = raw.lower()
    if "worked on" in s or "progress" in s:
        stage = "in_progress"
    elif "test" in s:
        stage = "testing"
    elif "received" in s:
        stage = "received"
    else:  # "Returned to customer", "Completed", or blank
        stage = "returned"
    return stage, tech


# --------------------------------------------------------------------------- transform

@dataclass
class Customer:
    legacy_id: int
    first_name: str
    last_name: str
    email: str
    phone: str
    address_line1: str
    address_line2: str
    city: str
    county: str
    postcode: str
    country: str
    created_at: datetime | None


@dataclass
class Job:
    legacy_id: int
    customer_legacy_id: int
    title: str
    model: str
    model_detail: str
    serial_number: str
    stage: str
    technician: str
    raw_status: str
    work_requested: str
    condition: str
    accessories: str
    items_received: list[str]
    quote_value: Decimal | None
    bench_time_cost: Decimal | None
    parts_cost: Decimal | None
    received_at: datetime | None
    accepted_at: datetime | None
    updated_at: datetime | None
    bench_log: str
    quote_notes: str


@dataclass
class ImportData:
    customers: list[Customer] = field(default_factory=list)
    jobs: list[Job] = field(default_factory=list)
    skipped_contacts: int = 0
    orphan_quotes: list[int] = field(default_factory=list)


def build(sql: str, include_leads: bool = False) -> ImportData:
    t = read_tables(sql)
    links = {}
    for l in t["zbs_object_links"]:
        if l["zbsol_objtype_from"] == OBJ_QUOTE and l["zbsol_objtype_to"] == OBJ_CONTACT:
            links[int(l["zbsol_objid_from"])] = int(l["zbsol_objid_to"])

    cf: dict[int, dict[str, str]] = {}
    for r in t["zbs_customfields"]:
        if r["zbscf_objtype"] == OBJ_QUOTE:
            cf.setdefault(int(r["zbscf_objid"]), {})[r["zbscf_objkey"]] = r["zbscf_objval"] or ""

    data = ImportData()
    contacts_with_jobs = set(links.values())

    for c in t["zbs_contacts"]:
        cid = int(c["ID"])
        if cid not in contacts_with_jobs and not include_leads:
            data.skipped_contacts += 1
            continue
        phone = next((clean(c.get(k)) for k in ("zbsc_mobtel", "zbsc_hometel", "zbsc_worktel") if clean(c.get(k))), "")
        data.customers.append(Customer(
            legacy_id=cid,
            first_name=clean(c.get("zbsc_fname")),
            last_name=clean(c.get("zbsc_lname")),
            email=clean(c.get("zbsc_email")).lower(),
            phone=phone,
            address_line1=clean(c.get("zbsc_addr1")),
            address_line2=clean(c.get("zbsc_addr2")),
            city=clean(c.get("zbsc_city")),
            county=clean(c.get("zbsc_county")),
            postcode=clean(c.get("zbsc_postcode")).upper(),
            country=clean(c.get("zbsc_country")),
            created_at=epoch(c.get("zbsc_created")),
        ))

    for q in t["zbs_quotes"]:
        qid = int(q["ID"])
        if qid not in links:
            data.orphan_quotes.append(qid)
            continue
        f = cf.get(qid, {})
        model, detail = normalise_model(f.get("make-model", ""))
        stage, tech = parse_status(f.get("repair-status", ""))
        data.jobs.append(Job(
            legacy_id=qid,
            customer_legacy_id=links[qid],
            title=clean(q.get("zbsq_title")),
            model=model,
            model_detail=detail,
            serial_number=clean(f.get("serial-number")),
            stage=stage,
            technician=tech,
            raw_status=clean(f.get("repair-status")),
            work_requested=clean(f.get("work-requested")),
            condition=clean(f.get("condition")),
            accessories=clean(f.get("accessories")),
            items_received=parse_items(f.get("parts-sent", "")),
            quote_value=money(q.get("zbsq_value")),
            bench_time_cost=money(f.get("bench-time-cost")),
            parts_cost=money(f.get("parts-cost")),
            received_at=epoch(q.get("zbsq_date")) or epoch(q.get("zbsq_created")),
            accepted_at=epoch(q.get("zbsq_accepted")),
            updated_at=epoch(q.get("zbsq_lastupdated")),
            bench_log=html_to_text(q.get("zbsq_content")),
            quote_notes=clean(q.get("zbsq_notes")),
        ))
    return data
