"""The printed customer repair sheet, as a PDF (A4), laid out like the original Excel sheet."""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib.colors import black
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Frame, KeepInFrame, Paragraph

LOGO = Path(__file__).parent / "static" / "repairs" / "pure-amiga-logo.png"

PAGE_W, PAGE_H = A4
S = 0.62          # positions below are in the original sheet's pixel grid (960 wide); S converts to points
TOP = 6           # extra space above everything, in points
LABEL = "Helvetica"
VALUE = "Helvetica-Bold"


def _pt(x, y):
    """Sheet pixel coords (from top-left) -> PDF points (from bottom-left)."""
    return x * S, PAGE_H - TOP - y * S


def _box(c, x1, y1, x2, y2):
    (ax, ay), (bx, by) = _pt(x1, y2), _pt(x2, y1)
    c.rect(ax, ay, bx - ax, by - ay)


def _label(c, right_x, y, *lines):
    """Right-aligned label, one line per argument, starting near the top of a box at y."""
    for i, line in enumerate(lines):
        x, yy = _pt(right_x, y + 14 + i * 19.5)
        c.setFont(LABEL, 8.5)
        c.drawRightString(x, yy, line)


def _style(size):
    return ParagraphStyle("v", fontName=VALUE, fontSize=size, leading=size * 1.3)


def _text(c, x1, y1, x2, y2, text, size=8.5, align_middle=False):
    """Bold text inside a box, wrapped, shrunk to fit if it's too long."""
    if not text:
        return
    if (y2 - y1) < 30 and "\n" not in str(text):  # one-line box: draw directly, shrink only to fit the width
        _cell(c, x1, y1, x2, y2, str(text).strip(), bold=True, size=size)
        return
    html = escape(str(text).strip()).replace("\n", "<br/>")
    (ax, ay), (bx, by) = _pt(x1, y2), _pt(x2, y1)
    pad = 2.5
    frame = Frame(ax, ay, bx - ax, by - ay, leftPadding=pad, rightPadding=pad,
                  topPadding=pad if not align_middle else 1, bottomPadding=1, showBoundary=0)
    frame.addFromList([KeepInFrame(bx - ax - 2 * pad, by - ay - pad - 1, [Paragraph(html, _style(size))],
                                   mode="shrink")], c)


def _cell(c, x1, y1, x2, y2, text, bold=False, centre=False, size=8):
    if not text:
        return
    font = VALUE if bold else LABEL
    x, y = _pt(x1, y2)
    c.setFont(font, size)
    if centre:
        c.drawCentredString(x + (x2 - x1) * S / 2, y + ((y2 - y1) * S - size * 0.7) / 2, text)
    else:
        # Notes can be long: shrink to fit the cell width
        width = (x2 - x1) * S - 5
        while size > 5 and c.stringWidth(text, font, size) > width:
            size -= 0.25
        c.setFont(font, size)
        c.drawString(x + 2.5, y + ((y2 - y1) * S - size * 0.7) / 2, text)


def _parts_sent(job):
    items = ", ".join(job.get_items_received_display())
    return "\n\n".join(p for p in [items, job.accessories.strip()] if p)


def render(job):
    """Return the job sheet as PDF bytes."""
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, pageCompression=0)
    # The customer only ever sees the repair number (e.g. A95); our internal PA ref stays off the sheet.
    ref = job.repair_ref
    c.setTitle(f"Pure Amiga repair sheet {ref}".strip())
    c.setAuthor("Pure Amiga")
    c.setLineWidth(0.8)
    c.setStrokeColor(black)

    # Logo (keeps its proportions)
    if LOGO.exists():
        x, y = _pt(40, 152)
        c.drawImage(ImageReader(str(LOGO)), x, y, width=370 * S, height=82 * S, mask="auto",
                    preserveAspectRatio=True, anchor="sw")

    make, model = job.machine_make_model
    received = job.received_at and timezone.localtime(job.received_at)
    returned = job.returned_at and timezone.localtime(job.returned_at)

    # Right-hand column: customer, date in, job number, work requested, condition, work completed
    right = [
        (75, 115, ("Customer", "Name"), job.customer.full_name),
        (135, 154, ("Date In",), received and f"{received:%-d %b %Y}"),
        (173, 193, ("Job Number",), ref),
        (211, 387, ("Work", "Requested"), job.work_requested),
        (406, 563, ("Condition,", "screws", "etc"), job.condition_on_arrival),
        (582, 1031, ("Work", "Completed"), job.customer_summary),
    ]
    for y1, y2, labels, value in right:
        _box(c, 567, y1, 893, y2)
        _label(c, 555, y1 - (3 if len(labels) == 1 else 7), *labels)
        _text(c, 567, y1, 893, y2, value)

    # Left-hand column: make, model, S/N, parts sent
    left = [
        (211, 232, "Make", make),
        (250, 271, "Model", model),
        (289, 310, "S/N", job.machine.serial_number),
        (328, 466, "Parts Sent", _parts_sent(job)),
    ]
    for y1, y2, label, value in left:
        _box(c, 133, y1, 469, y2)
        _label(c, 120, y1 - 3, label)
        _text(c, 133, y1, 469, y2, value)

    # Checks table
    cols = [133, 190, 242, 469]
    _label(c, 120, 481, "Checks")
    for x, title in ((150, "In"), (198, "Out"), (252, "Notes")):
        px, py = _pt(x, 499)
        c.setFont(LABEL, 8.5)
        c.drawString(px, py, title)
    row_h, top = 19.5, 504
    rows = job.check_rows() + [("", label, in_, out, note) for label, in_, out, note in job.custom_check_rows()]
    bottom = top + len(rows) * row_h
    _box(c, cols[0], top, cols[-1], bottom)  # draw the grid once so shared edges aren't doubled
    for x in cols[1:-1]:
        c.line(*_pt(x, top), *_pt(x, bottom))
    for i in range(1, len(rows)):
        c.line(*_pt(cols[0], top + i * row_h), *_pt(cols[-1], top + i * row_h))
    for i, (_key, label, in_, out, note) in enumerate(rows):
        y1, y2 = top + i * row_h, top + (i + 1) * row_h
        _label(c, 120, y1 - 1, label)
        _cell(c, cols[0], y1, cols[1], y2, in_, centre=True)
        _cell(c, cols[1], y1, cols[2], y2, out, centre=True)
        _cell(c, cols[2], y1, cols[3], y2, note, bold=True)

    # Date out: under the checks table (which grows with custom checks)
    y = max(894, bottom + 20)
    _box(c, 133, y, 469, y + 20)
    _label(c, 120, y - 3, "Date Out")
    _text(c, 133, y, 469, y + 20, returned and f"{returned:%-d %b %Y}")

    c.showPage()
    c.save()
    return buf.getvalue()
