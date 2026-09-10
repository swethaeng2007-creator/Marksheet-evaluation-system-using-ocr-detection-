import os
import uuid
from flask import (
    Flask, render_template, request, redirect, url_for, jsonify, send_file, flash
)
from werkzeug.utils import secure_filename

import ocr_engine
import data_store

BASE_DIR = os.path.dirname(__file__)
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXT = {"png", "jpg", "jpeg", "webp"}

app = Flask(__name__)
app.secret_key = "dev-secret-change-me"
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20MB


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


@app.route("/")
def index():
    return render_template(
        "index.html",
        pending_count=len(data_store.pending_records()),
        confirmed_count=len(data_store.confirmed_records()),
    )


@app.route("/scan", methods=["POST"])
def scan():
    if "sheet_image" not in request.files:
        flash("No file part in request.")
        return redirect(url_for("index"))
    file = request.files["sheet_image"]
    if file.filename == "" or not allowed_file(file.filename):
        flash("Please upload a PNG/JPG image of the evaluation sheet.")
        return redirect(url_for("index"))

    fname = f"{uuid.uuid4().hex[:10]}_{secure_filename(file.filename)}"
    save_path = os.path.join(UPLOAD_DIR, fname)
    file.save(save_path)

    try:
        extracted, _canonical = ocr_engine.extract_sheet(save_path)
    except Exception as exc:
        flash(f"OCR processing failed: {exc}")
        return redirect(url_for("index"))

    rid = data_store.new_record(extracted, fname)
    return redirect(url_for("review", rid=rid))


@app.route("/review/<rid>")
def review(rid):
    rec = data_store.get_record(rid)
    if rec is None:
        flash("Record not found.")
        return redirect(url_for("queue"))
    return render_template("review.html", rec=rec)


@app.route("/api/record/<rid>", methods=["POST"])
def api_update_record(rid):
    """Save manual edits from the review dashboard (auto-save on field blur)."""
    rec = data_store.get_record(rid)
    if rec is None:
        return jsonify({"error": "not found"}), 404

    payload = request.get_json(force=True)
    ext = rec["extracted"]

    for qk, val in payload.get("questions", {}).items():
        if qk in ext["questions"]:
            ext["questions"][qk]["value"] = val
            ext["questions"][qk]["manually_edited"] = True

    if "booklet_number" in payload:
        ext["booklet_number"] = payload["booklet_number"]
    if "grand_total" in payload:
        ext["grand_total"] = payload["grand_total"]

    total = 0
    for q in ext["questions"].values():
        if q.get("value") not in (None, ""):
            try:
                total += float(q["value"])
            except (TypeError, ValueError):
                pass
    ext["calculated_total"] = round(total, 2)
    ext["mismatch"] = (
        ext.get("grand_total") not in (None, "")
        and float(ext["grand_total"]) != ext["calculated_total"]
    )

    data_store.update_record(rid, {"extracted": ext})
    return jsonify({"ok": True, "calculated_total": ext["calculated_total"], "mismatch": ext["mismatch"]})


@app.route("/confirm/<rid>", methods=["POST"])
def confirm(rid):
    rec = data_store.get_record(rid)
    if rec is None:
        flash("Record not found.")
        return redirect(url_for("queue"))

    examiner = request.form.get("examiner", "").strip() or "Unspecified"
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    data_store.update_record(rid, {
        "status": "confirmed",
        "examiner": examiner,
        "confirmed_at": now,
    })
    data_store.append_audit(
        record_id=rid,
        examiner=examiner,
        action="confirm",
        snapshot=rec["extracted"],
    )
    data_store.export_all(only_confirmed=True)
    flash(f"Booklet {rec['extracted'].get('booklet_number')} confirmed and saved.")
    return redirect(url_for("queue"))


@app.route("/queue")
def queue():
    records = data_store.load_records()
    return render_template("queue.html", records=records)


@app.route("/audit")
def audit():
    chain = data_store.load_chain()
    ok, break_seq = data_store.verify_chain()
    return render_template("audit.html", chain=chain, ok=ok, break_seq=break_seq)


@app.route("/export/excel")
def export_excel():
    path = data_store.export_all(only_confirmed=True)
    return send_file(path, as_attachment=True, download_name="marks_master.xlsx")


@app.route("/calibrate")
def calibrate():
    cfg = ocr_engine.load_roi_config()
    return render_template("calibrate.html", cfg=cfg)


@app.route("/api/calibrate", methods=["POST"])
def api_calibrate():
    cfg = request.get_json(force=True)
    ocr_engine.save_roi_config(cfg)
    return jsonify({"ok": True})


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_file(os.path.join(UPLOAD_DIR, filename))



if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=5000)