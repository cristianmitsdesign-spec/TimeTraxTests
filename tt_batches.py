"""Read the pay period export (zip, folder, or PDFs) and write results.json.

No Timetrax here: this module only turns the app's export into Timetrax grid
lines and records outcomes in the results file the Admin screen accepts.
"""
import hashlib
import json
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

ATTACHMENT_NAME = "mai-timesheet-export.json"
EXPORT_FORMAT = "mai-timesheet-export/1"
RESULTS_FORMAT = "mai-timesheet-results/1"

# Projects ending in -G are overhead (the Overhead page); everything else is Direct.
# Timetrax's default overhead lines showed 0000-00-G where the sheet says 0000-01-G.
OVERHEAD_PROJECT_MAP = {"0000-01-G": "0000-00-G"}


@dataclass
class Line:
    page: str                    # "direct" or "overhead"
    project: str
    phase: str
    activity: str
    hours: list[str]             # Sun..Sat as typed into Timetrax, "" for no hours


@dataclass
class Employee:
    name: str
    number: str
    week_ending: date
    import_job_id: str
    batch_id: str
    source: str
    lines: list[Line] = field(default_factory=list)
    total: Decimal = Decimal("0")
    problem: str = ""            # set when the batch cannot be used


def hours_text(value: Decimal) -> str:
    """8.00 -> '8', 0.50 -> '0.5', 1.25 -> '1.25'"""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def checksum(entries: list[dict]) -> str:
    """Same rule as timesheet_contract.compute_checksum."""
    rows = sorted(entries, key=lambda e: (e["date"], e["project"], e["phase"], e["activity"]))
    payload = "\n".join(
        "|".join((e["date"], e["project"], e["phase"], e["activity"],
                  format(Decimal(str(e["hours"])), ".2f"), e["source_entry_id"]))
        for e in rows
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def batch_to_lines(batch: dict) -> list[Line]:
    """Group entries by code and day; two entries on the same day add up."""
    week_end = date.fromisoformat(batch["week_ending"])
    sums: dict[tuple[str, str, str], list[Decimal]] = {}
    for e in batch["entries"]:
        day = 6 - (week_end - date.fromisoformat(e["date"])).days   # Sun=0 .. Sat=6
        if not 0 <= day <= 6:
            raise ValueError(f"entry date {e['date']} is not in the week ending {week_end}")
        key = (e["project"].strip(), e["phase"].strip(), e["activity"].strip())
        sums.setdefault(key, [Decimal("0")] * 7)[day] += Decimal(str(e["hours"]))
    lines = []
    for (project, phase, activity), days in sums.items():
        page = "overhead" if project.upper().endswith("-G") else "direct"
        project = OVERHEAD_PROJECT_MAP.get(project, project)
        lines.append(Line(page, project, phase, activity,
                          [hours_text(d) if d else "" for d in days]))
    lines.sort(key=lambda l: (l.page != "direct", l.project, l.phase, l.activity))
    return lines


def _collect_pdfs(path: Path) -> list[tuple[str, bytes]]:
    if path.is_dir():
        found = []
        for child in sorted(path.iterdir()):
            if child.suffix.lower() in (".pdf", ".zip"):
                found.extend(_collect_pdfs(child))
        return found
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            return [(name, archive.read(name)) for name in sorted(archive.namelist())
                    if name.lower().endswith(".pdf")]
    if path.suffix.lower() == ".pdf":
        return [(path.name, path.read_bytes())]
    return []


def load_week(path: Path) -> tuple[list[Employee], list[str]]:
    """Return (employees, notes). Notes list files that were skipped."""
    employees: list[Employee] = []
    notes: list[str] = []
    for label, data in _collect_pdfs(path):
        try:
            attachments = PdfReader(BytesIO(data)).attachments
        except Exception as exc:
            notes.append(f"{label}: could not open ({exc})")
            continue
        if ATTACHMENT_NAME not in attachments:
            if not Path(label).name.startswith("_summary"):
                notes.append(f"{label}: has no timesheet data inside (was it re-saved or printed to PDF?)")
            continue
        document = json.loads(attachments[ATTACHMENT_NAME][0].decode("utf-8"))
        if document.get("format") != EXPORT_FORMAT:
            notes.append(f"{label}: unknown export format {document.get('format')!r}")
            continue
        for item in document["batches"]:
            batch = item["batch"]
            emp = Employee(
                name=item.get("employee_name") or f"Employee {batch['employee_id']}",
                number=str(batch["employee_id"]),
                week_ending=date.fromisoformat(batch["week_ending"]),
                import_job_id=item["import_job_id"],
                batch_id=batch["batch_id"],
                source=label,
            )
            emp.total = sum((Decimal(str(e["hours"])) for e in batch["entries"]), Decimal("0"))
            if checksum(batch["entries"]) != batch["checksum"]:
                emp.problem = "the data in this PDF has been changed or damaged (checksum mismatch)"
            elif batch.get("correction_of"):
                emp.problem = "this is a correction batch; enter corrections in Timetrax by hand"
            else:
                try:
                    emp.lines = batch_to_lines(batch)
                except ValueError as exc:
                    emp.problem = str(exc)
            employees.append(emp)
    employees.sort(key=lambda e: e.number)
    return employees, notes


# ---------------------------------------------------------------- results.json

def results_path(folder: Path, week_ending: date) -> Path:
    return folder / f"results_WE_{week_ending.isoformat()}.json"


def load_results(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"format": RESULTS_FORMAT, "results": [], "not_entered": []}


def record_result(path: Path, emp: Employee, ok: bool, log: str,
                  before: dict | None, after: dict | None) -> None:
    """Add or replace this employee's outcome and rewrite the file.

    Only successful entries go under "results" (what the app applies). A failed
    import is final in the app until someone presses Requeue, so problems go
    under "not_entered" instead; the app ignores that list and the employee can
    simply be run again once the cause is fixed.
    """
    doc = load_results(path)
    doc["format"] = RESULTS_FORMAT
    doc["week_ending"] = emp.week_ending.isoformat()
    doc["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    doc["results"] = [r for r in doc.get("results", []) if r["import_job_id"] != emp.import_job_id]
    doc["not_entered"] = [r for r in doc.get("not_entered", [])
                          if r["import_job_id"] != emp.import_job_id]
    if ok:
        doc["results"].append({
            "import_job_id": emp.import_job_id,
            "status": "verified",
            "log": log[-100_000:],
            "before_snapshot": before,
            "after_snapshot": after,
        })
    else:
        doc["not_entered"].append({
            "import_job_id": emp.import_job_id,
            "employee": f"{emp.name} #{emp.number}",
            "log": log[-100_000:],
        })
    sources = set(doc.get("sources", []))
    sources.add(emp.source)
    doc["sources"] = sorted(sources)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    tmp.replace(path)


def done_job_ids(path: Path) -> set[str]:
    return {r["import_job_id"] for r in load_results(path).get("results", [])
            if r.get("status") == "verified"}
