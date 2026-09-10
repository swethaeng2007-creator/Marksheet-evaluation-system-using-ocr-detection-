# Automated Answer Script Evaluation and Secure Mark Aggregation System

Automates extraction of the booklet serial number and question-wise marks from
Amrita University's pink evaluation sheet, gives examiners a verification
dashboard to fix any OCR errors, and produces one consolidated, editable
Excel workbook of confirmed marks — with a tamper-evident audit trail.

## How it works

1. **Scan Sheet** — upload a phone photo/scan of a filled sheet.
2. **Preprocess** (`ocr_engine.py`) — OpenCV auto-rotates sideways photos,
   denoises, boosts contrast (CLAHE), finds the page's quadrilateral and
   perspective-warps it to a fixed canonical size (1400×1900).
3. **Cropped, per-field OCR** — instead of OCR-ing the whole page, each
   field (Sl.No. box, every question cell, each subtotal box, grand total)
   is cropped individually using coordinates from `roi_config.json`, then
   run through EasyOCR on just that small crop. This is both faster and far
   more accurate than whole-page OCR for small handwritten digits.
4. **Structured JSON** — booklet number + per-question value + confidence
   score for every field, calculated total, and a mismatch flag if the
   calculated total ≠ handwritten grand total.
5. **Review dashboard** — every value under 80% confidence is highlighted
   red. The examiner can edit any field inline (auto-saves), see the
   calculated vs handwritten grand total live, then click **Confirm & Save**.
6. **Audit Chain** — every confirmation is appended to a SHA-256 hash-linked
   log (`data/audit_chain.json`). Editing a past entry would break the hash
   chain from that point forward, so the `/audit` page can always show
   whether the log is intact.
7. **Excel export** — every confirmation rebuilds `exports/marks_master.xlsx`
   (one row per booklet, one column per question, mismatch rows highlighted).
   Download anytime from the sidebar. You can open it, tweak any value by
   hand, and treat it as the final source of truth — the workbook is a
   plain, fully-editable `.xlsx`, not locked in any way.

## Setup

```bash
cd answer_eval_system
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open **http://localhost:5000**. First run downloads EasyOCR's English model
weights (needs internet, only happens once).

## Calibrate ROI (do this first, for your own scans)

`roi_config.json` ships with a rough starter layout, but real accuracy comes
from calibrating against your own scanner/phone output:

1. Go to **Calibrate ROI** in the sidebar.
2. Load one clean reference photo (not saved anywhere — just used as a guide).
3. Pick a field in the list (`sl_no`, `grand_total`, `subtotal:block1`,
   `question:1a`, `question:1b`, …), drag a rectangle over exactly that box
   on the image.
4. Repeat for every field, then click **Save Calibration**.

Coordinates are stored as fractions (0–1) of the canonical page, so one
calibration works for every future scan of the same printed template —
you only need to redo this if the university changes the sheet's layout.

## Project structure

```
answer_eval_system/
├── app.py                 # Flask routes
├── ocr_engine.py          # OpenCV preprocessing + ROI crop + EasyOCR
├── data_store.py          # records, hash-linked audit chain, Excel export
├── roi_config.json        # generated on first run; edit via /calibrate
├── requirements.txt
├── templates/
│   ├── base.html           # sidebar layout
│   ├── index.html          # Scan Sheet
│   ├── review.html         # Review Queue → single booklet dashboard
│   ├── queue.html          # Review Queue list
│   ├── audit.html          # Audit Chain viewer
│   └── calibrate.html      # ROI calibration canvas
├── static/
│   ├── css/style.css
│   └── js/{main,review,calibrate}.js
├── uploads/                # saved scanned images
├── exports/marks_master.xlsx  # consolidated output (built on each confirm)
└── data/
    ├── records.json         # all booklets (pending + confirmed)
    └── audit_chain.json      # hash-linked confirmation log
```

## Notes / next steps for the report

- **Why cropped OCR instead of whole-page OCR**: EasyOCR (like most scene-text
  OCR) is tuned for finding text in a busy image; on a form with 60+ tiny
  handwritten digit boxes, whole-page detection frequently merges or drops
  cells. Cropping each field first turns "find text anywhere" into "read this
  one number", which is both faster per image and meaningfully more accurate.
- **Confidence threshold (80%)** is easy to tune — see `low-conf` checks in
  `review.html` / `ocr_engine.py`.
- **Handling scale** ("the number of data can be huge"): every confirm both
  updates `records.json` and regenerates the Excel workbook from *all*
  confirmed records, so the workbook always reflects the current state no
  matter how many booklets have been processed. For very large volumes
  (thousands of booklets), swapping `records.json` for SQLite would be the
  natural next step — the `data_store.py` functions are written so that swap
  only touches that one file.
- **Security/integrity**: the audit chain gives you a lightweight way to
  demonstrate in your report that marks weren't silently altered after
  confirmation, without needing a real blockchain.
