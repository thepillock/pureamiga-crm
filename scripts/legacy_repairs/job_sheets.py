"""Read the per-repair Excel job sheets ("Computer Repair B23.xlsx") into the legacy JSON.

The sheet layout changed over the years (extra check rows, an older grid with Name/Contact Via/Collect/Post), so
fields are found by their labels, not fixed cells.
"""
import datetime as dt
import re
from pathlib import Path

import openpyxl

# Sheet check label -> CRM check key (see repairs.models.CHECKS)
CHECK_KEYS = {
    "power": "power", "psu": "power", "boots": "boots", "rgb video": "rgb_video", "comp video": "comp_video",
    "audio": "audio", "int fdd": "int_fdd", "ext fdd port": "ext_fdd", "serial port": "serial",
    "parallel port": "parallel", "mouse port": "mouse", "joystick port": "joystick", "ide port": "ide",
    "cd32 drive": "cd32_drive", "cd drive": "cd32_drive", "keyboard": "keyboard", "memory": "memory",
    "cias": "cias", "soak test": "soak_test", "soak": "soak_test", "pcmcia": "pcmcia", "expansion": "expansion",
    "expansions": "expansion",
}
RESULTS = {"y": "Y", "ok": "Y", "yes": "Y", "n/a": "n/a", "na": "n/a", "fault": "Fault", "faulty": "Fault",
           "n": "Fault", "broken": "Fault", "defect": "Fault", "no": "Fault"}
RIGHT_COLS = (8, 9)  # H / I: labels of the right-hand column


def _text(v):
    if v is None:
        return ""
    if isinstance(v, dt.datetime):
        return v.date().isoformat()
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).replace("\r\n", "\n").strip()


def _result(value):
    """('Y'|'Fault'|'n/a'|'', extra note)"""
    text = _text(value)
    key = text.lower().strip(" .")
    if key in RESULTS:
        return RESULTS[key], ""
    return "", text


def read_sheet(path):
    ws = openpyxl.load_workbook(path, data_only=True).worksheets[0]
    grid = {(c.row, c.column): c.value for row in ws.iter_rows(max_row=80, max_col=16) for c in row
            if c.value not in (None, "")}
    labels = {}
    for (r, c), v in sorted(grid.items()):
        if isinstance(v, str) and c <= 9:
            labels.setdefault(v.strip().lower(), (r, c))

    def value_right(r, c):
        limit = 7 if c not in RIGHT_COLS else 16  # left-hand labels stop before the right-hand column
        for cc in range(c + 1, limit + 1):
            if (r, cc) in grid:
                return grid[(r, cc)]
        return None

    def field(*names):
        for name in names:
            if name in labels:
                return value_right(*labels[name])
        return None

    def work(kind):  # the right-hand "Work" label followed by "Requested" / "Completed" on the next row
        for (r, c), v in grid.items():
            if isinstance(v, str) and v.strip() == "Work" and c in RIGHT_COLS:
                below = grid.get((r + 1, c))
                if isinstance(below, str) and below.strip().lower() == kind:
                    return value_right(r, c)
        return None

    sheet = {
        "customer": _text(field("customer", "name")),
        "date_in": field("date in"),
        "job_number": _text(field("job number")),
        "make": _text(field("make")),
        "model": _text(field("model")),
        "serial": _text(field("s/n")),
        "parts_sent": _text(field("parts sent", "accessories")),
        "work_requested": _text(work("requested")),
        "condition": _text(field("condition,", "condition")),
        "work_completed": _text(work("completed")),
        "date_out": field("date out"),
        "checks": {}, "extra_checks": {},
    }

    # Checks table: rows under the "Checks" header, with In / Out / Notes columns
    if "checks" in labels:
        hr, hc = labels["checks"]
        cols = {_text(grid.get((hr, c))).lower(): c for c in range(hc + 1, hc + 6)}
        cin, cout, cnote = cols.get("in"), cols.get("out"), cols.get("notes")
        has_power = any(_text(grid.get((r, hc))).lower() == "power" for r in range(hr + 1, hr + 30))
        for r in range(hr + 1, hr + 30):
            label = _text(grid.get((r, hc)))
            if not label or label.lower() in ("date out",):
                if label:
                    break
                continue
            res_in, extra_in = _result(grid.get((r, cin)))
            res_out, extra_out = _result(grid.get((r, cout)))
            note = " ".join(p for p in (_text(grid.get((r, cnote))), extra_in, extra_out) if p)
            entry = {k: v for k, v in (("in", res_in), ("out", res_out), ("note", note[:200])) if v}
            key = CHECK_KEYS.get(label.lower())
            if key == "power" and label.lower() == "psu" and has_power:
                key = None  # sheet has both Power and PSU rows: keep PSU as an extra
            if key and entry:
                sheet["checks"][key] = entry
            elif entry:
                sheet["extra_checks"][label] = entry
    return sheet


def ref_from_filename(path):
    m = re.search(r"Repair\s+([A-Za-z]?\d+[A-Za-z]?)", Path(path).stem)
    if not m:
        return None
    raw = m.group(1)
    if raw.isdigit():
        return f"{int(raw):02d}"
    return raw[0].upper() + raw[1:-1] + (raw[-1].lower() if raw[-1].isalpha() and len(raw) > 3 else raw[-1])


def _parse_month(text):
    """'May 2024' -> '2024-05-01' (sheets often only give the month)."""
    if isinstance(text, dt.datetime):
        return text.date().isoformat()
    try:
        return dt.datetime.strptime(_text(text), "%B %Y").date().isoformat()
    except ValueError:
        return None


def read_sheets(folder, jobs, report):
    """Merge the job sheets in ``folder`` into ``jobs`` (the list from convert.py), in place."""
    by_ref = {j["ref"]: j for j in jobs}
    sheets, seen = {}, {}
    for path in sorted(Path(folder).glob("*.xlsx")):
        ref = ref_from_filename(path)
        sheet = read_sheet(path)
        signature = repr(sorted((k, str(v)) for k, v in sheet.items() if k != "job_number"))
        if signature in seen:
            report["job sheets skipped (copy of another sheet)"].append(f"{path.name} = {seen[signature]}")
            continue
        seen[signature] = path.name
        sheets[ref] = sheet
    for ref, sheet in sorted(sheets.items()):
        job = by_ref.get(ref)
        if job is None:
            job = _job_from_sheet(ref, sheet, by_ref, report)
            jobs.append(job)
            by_ref[ref] = job
        job["checks"] = sheet["checks"]
        if sheet["extra_checks"]:
            job["checks"] = dict(sheet["checks"], _extra=sheet["extra_checks"])
        if sheet["work_completed"]:
            if job["work_completed"] and job["work_completed"].strip() != sheet["work_completed"].strip():
                job["log"].append(f"Work completed (repairs list): {job['work_completed']}")
            job["work_completed"] = sheet["work_completed"]  # the sheet's is the customer-facing write-up
        if not job["condition"] and sheet["condition"]:
            job["condition"] = sheet["condition"]
        if not job["date_out"] and isinstance(sheet["date_out"], dt.datetime):
            job["date_out"] = sheet["date_out"].date().isoformat()
        if not job["machine"]["serial"] and sheet["serial"]:
            job["machine"]["serial"] = sheet["serial"]
        report["job sheets merged"].append(ref)
    report["job sheets merged"] = len(report["job sheets merged"])


def _job_from_sheet(ref, sheet, by_ref, report):
    """A sheet with no row in the repairs list (e.g. follow-up A91b): build the job from the sheet itself."""
    base = by_ref.get(re.sub(r"[a-z]$", "", ref))
    customer = base["customer"] if base and base["customer"].lower() == sheet["customer"].lower() else sheet["customer"]
    machine = dict(base["machine"]) if base else {"model": "Unknown", "description": sheet["model"], "serial": sheet["serial"]}
    report["jobs created from a sheet only"].append(ref)
    return {
        "ref": ref, "row": None, "customer": customer,
        "date_in": _parse_month(sheet["date_in"]),
        "date_out": sheet["date_out"].date().isoformat() if isinstance(sheet["date_out"], dt.datetime) else None,
        "machine": machine, "items_received": [], "accessories": sheet["parts_sent"], "items_text": sheet["parts_sent"],
        "condition": sheet["condition"], "work_requested": sheet["work_requested"], "work_completed": "",
        "log": [f"Created from job sheet only (no row in the repairs list); date in on the sheet: {_text(sheet['date_in'])}"],
        "costs": [], "payments": [], "money_notes": [], "checks": {},
    }
