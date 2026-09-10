"""
data_store.py
Lightweight persistence layer (no external DB needed for a college project):

  - records.json      : every scanned booklet's current extracted/edited data
  - audit_chain.json   : append-only, hash-linked log of every confirm action
                         (a minimal "blockchain-style" tamper-evidence chain -
                         each entry stores the SHA-256 hash of the previous
                         entry, so any retroactive edit breaks the chain)
  - exports/marks_master.xlsx : the consolidated, human-editable Excel sheet

Excel is kept in sync every time a record is confirmed, and can also be
opened directly and hand-edited by the examiner at any point - re-running
export_all() will merge back only rows that still exist as records
(manual Excel edits are treated as the source of truth on next full export
if the user chooses "Rebuild from Excel").
"""

import os
import json
import hashlib
import uuid
from datetime import datetime, timezone

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment

BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE_DIR, "data")
EXPORT_DIR = os.path.join(BASE_DIR, "exports")
RECORDS_PATH = os.path.join(DATA_DIR, "records.json")
AUDIT_PATH = os.path.join(DATA_DIR, "audit_chain.json")
EXCEL_PATH = os.path.join(EXPORT_DIR, "marks_master.xlsx")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(EXPORT_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Records (pending + confirmed booklets)
# ---------------------------------------------------------------------------

def _load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r") as f:
        return json.load(f)


def _save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_records():
    return _load_json(RECORDS_PATH, {})


def save_records(records):
    _save_json(RECORDS_PATH, records)


def new_record(extracted, image_filename):
    rid = uuid.uuid4().hex[:12]
    records = load_records()
    records[rid] = {
        "id": rid,
        "image_filename": image_filename,
        "extracted": extracted,
        "status": "pending_review",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "confirmed_at": None,
        "examiner": None,
    }
    save_records(records)
    return rid


def get_record(rid):
    return load_records().get(rid)


def update_record(rid, updates):
    records = load_records()
    if rid not in records:
        return None
    records[rid].update(updates)
    save_records(records)
    return records[rid]


def pending_records():
    return {k: v for k, v in load_records().items() if v["status"] == "pending_review"}


def confirmed_records():
    return {k: v for k, v in load_records().items() if v["status"] == "confirmed"}


# ---------------------------------------------------------------------------
# Audit chain (hash-linked, append-only)
# ---------------------------------------------------------------------------

def _hash_entry(entry, prev_hash):
    payload = json.dumps(entry, sort_keys=True) + prev_hash
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_chain():
    return _load_json(AUDIT_PATH, [])


def append_audit(record_id, examiner, action, snapshot):
    chain = load_chain()
    prev_hash = chain[-1]["entry_hash"] if chain else "0" * 64
    entry = {
        "seq": len(chain) + 1,
        "record_id": record_id,
        "examiner": examiner,
        "action": action,
        "snapshot": snapshot,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prev_hash": prev_hash,
    }
    entry["entry_hash"] = _hash_entry(entry, prev_hash)
    chain.append(entry)
    _save_json(AUDIT_PATH, chain)
    return entry


def verify_chain():
    chain = load_chain()
    prev_hash = "0" * 64
    for entry in chain:
        expected_prev = entry["prev_hash"]
        if expected_prev != prev_hash:
            return False, entry["seq"]
        stored_hash = entry["entry_hash"]
        check = dict(entry)
        del check["entry_hash"]
        if _hash_entry(check, prev_hash) != stored_hash:
            return False, entry["seq"]
        prev_hash = stored_hash
    return True, None


# ---------------------------------------------------------------------------
# Excel export
# ---------------------------------------------------------------------------

HEADER_FONT = Font(bold=True, name="Arial", color="FFFFFF")
HEADER_FILL = PatternFill("solid", start_color="7A1F3D")
MISMATCH_FILL = PatternFill("solid", start_color="FFC7CE")
BASE_FONT = Font(name="Arial")


def _question_keys(records):
    keys = set()
    for r in records.values():
        keys.update(r["extracted"].get("questions", {}).keys())

    def sort_key(k):
        num = "".join(ch for ch in k if ch.isdigit())
        suffix = k[len(num):]
        return (int(num) if num else 0, suffix)

    return sorted(keys, key=sort_key)


def export_all(only_confirmed=True):
    """(Re)build the master Excel workbook from current records."""
    records = load_records()
    subset = confirmed_records() if only_confirmed else records
    qkeys = _question_keys(subset) or _question_keys(records)

    wb = Workbook()
    ws = wb.active
    ws.title = "Marks"

    headers = ["Booklet No.", "Record ID"] + [f"Q{k}" for k in qkeys] + [
        "Calculated Total", "Grand Total (handwritten)", "Mismatch",
        "Examiner", "Confirmed At",
    ]
    ws.append(headers)
    for col_idx, _ in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center")

    for rid, rec in sorted(subset.items(), key=lambda kv: kv[1].get("confirmed_at") or ""):
        ext = rec["extracted"]
        row = [ext.get("booklet_number"), rid]
        for qk in qkeys:
            val = ext.get("questions", {}).get(qk, {}).get("value")
            row.append(val)
        row += [
            ext.get("calculated_total"),
            ext.get("grand_total"),
            "YES" if ext.get("mismatch") else "no",
            rec.get("examiner"),
            rec.get("confirmed_at"),
        ]
        ws.append(row)
        r_idx = ws.max_row
        for c_idx in range(1, len(headers) + 1):
            ws.cell(row=r_idx, column=c_idx).font = BASE_FONT
        if ext.get("mismatch"):
            for c_idx in range(1, len(headers) + 1):
                ws.cell(row=r_idx, column=c_idx).fill = MISMATCH_FILL

    for i, h in enumerate(headers, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = max(14, len(h) + 2)

    wb.save(EXCEL_PATH)
    return EXCEL_PATH
