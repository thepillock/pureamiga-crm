"""One-off: turn the old repairs spreadsheet + finances sheet into a JSON file for `manage.py load_legacy_repairs`.

    python scripts/legacy_repairs/convert.py REPAIRS.xlsx FINANCES.xlsx OUT.json [--sheets DIR]

Runs on a workstation (needs openpyxl); the output JSON is copied to the CRM's data folder and loaded there.
No customer data lives in this repo - only this script.

Rules agreed with Chris (Nov 2026):
- Repair refs: 1.0 -> "01"; B16a / 36a are follow-up jobs; the duplicate B72 without a date in becomes B72a.
- Names: a trailing " PA" (Pure Amiga job) is stripped; "Phil" means the existing customer "Phil Ayres".
- Finances ("Systems and Parts"): only rows whose Repair Number is a repair ref. Money Spent -> parts cost,
  Money Made -> payment. Text like "Not yet paid - £30" is kept as a note.
"""
import argparse
import datetime as dt
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from repairs.jetpack_import import normalise_model  # noqa: E402
from repairs.logtext import REPAIR_REF_RE, normalise_repair_ref  # noqa: E402

NAME_ALIASES = {"Phil": "Phil Ayres"}
SERIAL_UNKNOWN = {"", "unknown", "n/a", "none", "?"}


def ref_of(value):
    if isinstance(value, (int, float)):
        return f"{int(value):02d}"
    ref = normalise_repair_ref(str(value or ""))
    return ref if REPAIR_REF_RE.match(ref) else None


def clean(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).replace("\r\n", "\n").strip()


def iso(value):
    return value.date().isoformat() if isinstance(value, dt.datetime) else None


def customer_name(owner):
    name = re.sub(r"\s+", " ", clean(owner))
    name = re.sub(r"\s+PA$", "", name)
    return NAME_ALIASES.get(name, name)


def machine_of(raw):
    """'A600' -> ('Amiga 600', ''), 'A600HD/40' -> ('Amiga 600', 'A600HD/40'), 'CD32' -> ('Amiga CD32', '')."""
    m = re.match(r"A(500\+|500|600|1000|1200|1500|2000|3000|4000)(?![0-9])", raw)
    if m:
        return f"Amiga {m.group(1)}", "" if raw == f"A{m.group(1)}" else raw
    if raw.upper() in ("CD32", "CDTV"):
        return ("Amiga CD32" if raw.upper() == "CD32" else "Commodore CDTV"), ""
    model, description = normalise_model(raw)
    return model, description or (raw if model in ("Other", "Unknown") else "")


# --- Items sent -> checklist + leftover text -----------------------------------------------------------

_NEGATED = re.compile(r"\b(?:no|minus|without)\s+(?:the\s+)?([a-z]+(?:\s+(?:or|and)\s+[a-z]+)?(?:\s+(?:shield|shields|shielding|case))?)",
                      re.I)
_FILLER = {"only", "and", "plus", "with", "inc", "including", "the", "both", "shield", "shields", "shielding",
           "lower", "upper", "top", "bottom", "board", "mainboard", "unit", "whole", "entire", "base", "complete",
           "machine", "case", "keyboard", "floppy", "drive", "psu", "box", "boxed", "accessories", "no", "a", "of",
           "chassis", "or", "part"}


def items_received(text):
    t = text.lower()
    t_pos = _NEGATED.sub(" ", t)  # ignore "no shield", "no PSU", ...
    items = []

    def add(key):
        if key not in items:
            items.append(key)

    whole = re.search(r"\b(unit|whole|entire|complete|machine)\b", t_pos)
    if whole or re.search(r"\b(main)?board\b", t_pos):
        add("board")
    if re.search(r"\b(lower|bottom|both)\b[^,.]*\bshields?\b|\bshields?\b[^,.]*\b(lower|bottom)\b|\btop/bottom\b", t_pos):
        add("lower_shield")
    if re.search(r"\b(upper|top|both)\b[^,.]*\bshields?\b|\btop/bottom\b|\bupper and lower\b|\blower and upper\b",
                 t_pos):
        add("upper_shield")
    if whole or re.search(r"\bcase\b|\bchassis\b", t_pos):
        add("case")
    if re.search(r"\bkeyboard\b", t_pos):
        add("keyboard")
    if re.search(r"\bfloppy( drive)?\b", t_pos) and "cable" not in t_pos:
        add("floppy")
    if re.search(r"\bpsu\b", t_pos):
        add("psu")
    if re.search(r"\bbox(ed)?\b", t_pos):
        add("original_box")
    leftover = [w for w in re.findall(r"[a-z0-9/+]+", t) if w not in _FILLER]
    return items, (text if leftover or not items else "")


# --- Readers -------------------------------------------------------------------------------------------

def read_repairs(path, report):
    ws = openpyxl.load_workbook(path, data_only=True).active
    header = [clean(c.value) for c in ws[1]]
    col = {name: i for i, name in enumerate(header) if name}
    notes_col = 13  # unlabelled column N
    jobs, seen = [], Counter()
    for row_no, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if row[col["Job"]] in (None, ""):
            continue
        ref = ref_of(row[col["Job"]])
        if not ref:
            report["bad refs"].append(f"row {row_no}: {row[col['Job']]!r}")
            continue
        date_in = row[col["Date in"]]
        if ref == "B72" and not isinstance(date_in, dt.datetime):
            ref = "B72a"  # Chris: Wrangler keeps B72, Mike Parker's board swap becomes B72a
            report["renamed"].append(f"row {row_no}: B72 -> B72a (no date in)")
        seen[ref] += 1
        machine_raw = clean(row[col["Machine"]])
        model, description = machine_of(machine_raw)
        serial = clean(row[col["s/n"]])
        if serial.lower().strip(" .") in SERIAL_UNKNOWN:
            serial = ""
        items_text = clean(row[col["Items sent"]])
        items, accessories = items_received(items_text)
        log = []
        if not isinstance(date_in, dt.datetime) and date_in not in (None, ""):
            log.append(f"Date in: {clean(date_in)}")
        for label, key in (("Parts used", "Parts used"), ("Tested", "Tested"), ("Ultrasonic clean", "Ultrasonic")):
            if clean(row[col[key]]):
                log.append(f"{label}: {clean(row[col[key]])}")
        if len(row) > notes_col and clean(row[notes_col]):
            log.append(f"Notes: {clean(row[notes_col])}")
        jobs.append({
            "ref": ref, "row": row_no,
            "customer": customer_name(row[col["Owner"]]),
            "date_in": iso(date_in), "date_out": iso(row[col["Date returned"]]),
            "machine": {"model": model, "description": description, "serial": serial},
            "items_received": items, "accessories": accessories, "items_text": items_text,
            "condition": clean(row[col["Condition"]]),
            "work_requested": clean(row[col["Work requested"]]),
            "work_completed": clean(row[col["Work Completed"]]),
            "log": log,
            "costs": [], "payments": [], "money_notes": [], "checks": {},
        })
    dups = [r for r, n in seen.items() if n > 1]
    if dups:
        report["duplicate refs"].extend(dups)
    return jobs


def read_finances(path, report):
    ws = openpyxl.load_workbook(path, data_only=True)["Systems and Parts"]
    header = [clean(c.value) for c in ws[1]]
    col = {name: i for i, name in enumerate(header) if name}
    by_ref = defaultdict(lambda: {"costs": [], "payments": [], "money_notes": []})
    skipped = Counter()
    for row_no, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        raw = row[col["Repair Number"]]
        if raw in (None, ""):
            continue
        ref = ref_of(raw)
        if not ref:
            skipped[clean(raw)] += 1
            continue
        when = iso(row[col["Date"]])
        item, supplier = clean(row[col["Item"]]), clean(row[col["from"]])
        spent, made = row[col["Money Spent"]], row[col["Money Made"]]
        entry = by_ref[ref]
        if isinstance(spent, (int, float)) and spent:
            desc = " - ".join(p for p in (item, supplier) if p)
            entry["costs"].append({"amount": round(float(spent), 2), "date": when, "description": desc[:200]})
        elif clean(spent) and not isinstance(spent, (int, float)):
            entry["money_notes"].append(f"Money spent: {clean(spent)} (no amount)")
        if isinstance(made, (int, float)) and made:
            entry["payments"].append({"amount": round(float(made), 2), "date": when})
        elif clean(made) and not isinstance(made, (int, float)):
            entry["money_notes"].append(f"Payment: {clean(made)}")
    report["finance rows skipped (no repair number)"] = dict(skipped)
    return by_ref


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repairs")
    ap.add_argument("finances")
    ap.add_argument("out")
    ap.add_argument("--sheets", help="Folder of per-repair Excel job sheets ('Computer Repair B23.xlsx')")
    args = ap.parse_args()

    report = defaultdict(list)
    jobs = read_repairs(args.repairs, report)
    finance = read_finances(args.finances, report)
    refs = {j["ref"] for j in jobs}
    for job in jobs:
        f = finance.get(job["ref"])
        if f:
            job["costs"], job["payments"], job["money_notes"] = f["costs"], f["payments"], f["money_notes"]
    report["finance refs with no repair row"] = sorted(set(finance) - refs)

    if args.sheets:
        from job_sheets import read_sheets  # noqa: PLC0415
        read_sheets(Path(args.sheets), jobs, report)

    Path(args.out).write_text(json.dumps({"version": 1, "jobs": jobs}, indent=1, ensure_ascii=False))
    print(f"{len(jobs)} repairs written to {args.out}")
    print(f"  with costs: {sum(1 for j in jobs if j['costs'])}, with payments: {sum(1 for j in jobs if j['payments'])}, "
          f"with checks: {sum(1 for j in jobs if j['checks'])}")
    for key, value in report.items():
        if value:
            print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
