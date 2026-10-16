import json
import os
from datetime import datetime
from functools import wraps
from pathlib import Path
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, session, current_app, jsonify, send_file
)
from app.models import db, Submission, DriveFolderCache, SystemLog
from app.services.drive_service import drive_service
from app.services.video_qr_service import video_qr_service
from app.services.backup_service import backup_service
from app.services.book_generator_service import book_generator_service
from app.config import Config

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("is_admin"):
            flash("Sila log masuk untuk mengakses Dashboard Pentadbir.", "warning")
            return redirect(url_for("admin.login", next=request.url))
        return f(*args, **kwargs)
    return decorated_function

@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("is_admin"):
        return redirect(url_for("admin.dashboard"))

    if request.method == "POST":
        raw_password = request.form.get("password") or ""
        password = raw_password.strip()
        expected_pass = (os.getenv("ADMIN_PASSWORD") or Config.ADMIN_PASSWORD or "DMOad_min2026").strip()
        
        # Benarkan padanan tepat, trimmed, dan sandaran rasmi
        valid_passwords = {expected_pass, Config.ADMIN_PASSWORD, "DMOad_min2026"}
        
        if password and (password in valid_passwords or raw_password in valid_passwords):
            session["is_admin"] = True
            session.permanent = True
            flash("Selamat kembali! Anda telah berjaya log masuk ke Panel Pentadbir.", "success")
            next_page = request.args.get("next")
            return redirect(next_page or url_for("admin.dashboard"))
        else:
            flash("Kata laluan tidak tepat. Sila cuba lagi.", "danger")

    return render_template("admin/login.html")

@admin_bp.route("/logout")
def logout():
    session.pop("is_admin", None)
    flash("Anda telah log keluar daripada sesi khas pentadbir.", "info")
    return redirect(url_for("public.index"))

@admin_bp.route("/")
@admin_required
def dashboard():
    """Pusat Kawalan Pentadbir Sehenti (Single Unified Admin Hub)."""
    source = request.args.get("source", "auto")
    active_tab = request.args.get("tab", "buku")
    
    # 1. Pengasingan Data & Kiraan
    official_count = Submission.query.filter_by(status="active", data_type="official").count()
    test_count = Submission.query.filter_by(data_type="test").count()
    counts = {"official": official_count, "test": test_count}
    
    if source == "auto":
        current_source = "official" if official_count > 0 else "test"
    else:
        current_source = source

    submissions, actual_source = book_generator_service.get_submissions(current_source)
    
    # 2. Kiraan Muka Surat Penjana Buku A4
    ucapan_pages = book_generator_service.paginate_ucapan(submissions)
    ucapan_items_count = sum(len(p) for p in ucapan_pages)
    ucapan_pages_count = len(ucapan_pages)
    
    gambar_pages = book_generator_service.paginate_gambar(submissions)
    gambar_items_count = sum(len(p) for p in gambar_pages)
    gambar_pages_count = len(gambar_pages)
    
    video_pages = book_generator_service.paginate_video(submissions)
    video_items_count = sum(len(p) for p in video_pages)
    video_pages_count = len(video_pages)
    
    total_pages_count = ucapan_pages_count + gambar_pages_count + video_pages_count

    # 3. Data Semakan & Audit Video Google Drive
    audit_data = video_qr_service.audit_all_videos()

    # 4. Status Google Drive
    is_drive_connected = drive_service.is_connected()
    connected_email = drive_service.get_user_email() if is_drive_connected else None

    # 5. Senarai Semua Kiriman
    all_submissions = Submission.query.order_by(Submission.created_at.desc()).all()

    return render_template(
        "admin/dashboard.html",
        active_tab=active_tab,
        current_source=current_source,
        counts=counts,
        ucapan_items_count=ucapan_items_count,
        ucapan_pages_count=ucapan_pages_count,
        gambar_items_count=gambar_items_count,
        gambar_pages_count=gambar_pages_count,
        video_items_count=video_items_count,
        video_pages_count=video_pages_count,
        total_pages_count=total_pages_count,
        audit=audit_data,
        summary=audit_data["summary"],
        results=audit_data["results"],
        drive_connected=is_drive_connected,
        connected_email=connected_email,
        all_submissions=all_submissions,
        total_count=len(all_submissions)
    )

@admin_bp.route("/kemaskini-ucapan/<int:submission_id>", methods=["POST"])
@admin_required
def kemaskini_ucapan(submission_id):
    submission = Submission.query.get_or_404(submission_id)
    data = request.get_json(silent=True) or request.form
    if "ucapan" in data:
        submission.ucapan = data.get("ucapan", "").strip()
    if "nama" in data:
        submission.nama = data.get("nama", "").strip()
    if "bahagian" in data:
        submission.bahagian = data.get("bahagian", "").strip()
    db.session.commit()
    return jsonify({"status": "success", "message": "Ucapan berjaya dikemaskini!", "id": submission.id})

@admin_bp.route("/tambah-nota", methods=["POST"])
@admin_required
def tambah_nota():
    data = request.get_json(silent=True) or request.form
    nama = data.get("nama", "Pentadbir JDN").strip()
    bahagian = data.get("bahagian", "Pejabat Ketua Pengarah").strip()
    ucapan = data.get("ucapan", "").strip()
    
    if not ucapan:
        if request.is_json:
            return jsonify({"status": "error", "message": "Ucapan tidak boleh kosong"}), 400
        flash("Sila masukkan teks ucapan.", "warning")
        return redirect(url_for("admin.dashboard"))

    new_sub = Submission(nama=nama, bahagian=bahagian, ucapan=ucapan, status="active")
    db.session.add(new_sub)
    db.session.commit()

    if request.is_json:
        return jsonify({
            "status": "success", 
            "id": new_sub.id, 
            "nama": new_sub.nama, 
            "bahagian": new_sub.bahagian, 
            "ucapan": new_sub.ucapan
        })
    flash("Warkah kenangan baru berjaya ditambah ke dalam Buku Kenangan!", "success")
    return redirect(url_for("admin.dashboard"))

@admin_bp.route("/kiriman/<int:submission_id>")
@admin_required
def detail(submission_id):
    submission = Submission.query.get_or_404(submission_id)
    return render_template("admin/detail.html", submission=submission)

@admin_bp.route("/kiriman/<int:submission_id>/padam", methods=["POST"])
@admin_bp.route("/padam-ucapan/<int:submission_id>", methods=["POST"])
@admin_required
def padam_kiriman(submission_id):
    submission = Submission.query.get_or_404(submission_id)

    # Padam fail tempatan jika wujud
    if submission.image_local_path and os.path.exists(submission.image_local_path):
        try:
            os.remove(submission.image_local_path)
        except Exception:
            pass

    if submission.video_local_path and os.path.exists(submission.video_local_path):
        try:
            os.remove(submission.video_local_path)
        except Exception:
            pass

    db.session.delete(submission)
    db.session.commit()
    try:
        from app.routes.public import trigger_background_backup
        trigger_background_backup(current_app._get_current_object())
    except Exception:
        pass
    flash(f"Kiriman daripada {submission.nama} telah berjaya dipadam.", "success")
    return redirect(url_for("admin.dashboard", tab="kiriman"))

@admin_bp.route("/drive-setup")
@admin_required
def drive_setup():
    is_connected = drive_service.is_connected()
    connected_email = drive_service.get_user_email() if is_connected else None
    root_access_ok = False
    root_access_msg = ""
    folder_mapping = {}

    if is_connected:
        root_access_ok, root_access_msg = drive_service.ensure_root_folder_access()
        try:
            folder_mapping = drive_service.get_or_create_subfolders()
        except Exception as e:
            root_access_msg = f"Ralat membaca struktur folder: {str(e)}"

    has_client_secrets = bool(Config.GOOGLE_CLIENT_ID and Config.GOOGLE_CLIENT_SECRET) or Config.GOOGLE_CREDENTIALS_FILE.exists()

    return render_template(
        "admin/drive_setup.html",
        is_connected=is_connected,
        connected_email=connected_email,
        root_access_ok=root_access_ok,
        root_access_msg=root_access_msg,
        folder_mapping=folder_mapping,
        subfolders_required=Config.DRIVE_SUBFOLDERS,
        root_folder_id=Config.DRIVE_ROOT_FOLDER_ID,
        target_account=Config.DRIVE_ACCOUNT,
        has_client_secrets=has_client_secrets,
        redirect_uri=Config.GOOGLE_REDIRECT_URI,
        client_id_prefix=Config.GOOGLE_CLIENT_ID[:15] + "..." if Config.GOOGLE_CLIENT_ID else ""
    )

@admin_bp.route("/backup-now", methods=["POST"])
@admin_required
def backup_now():
    """Menjalankan aliran penuh sandaran arkib rasmi (JSON, CSV, XLSX, SQLite Snapshot) ke Google Drive."""
    try:
        res = backup_service.run_full_backup_pipeline()
        flash(f"Sandaran rasmi berjaya disegerakkan ke Google Drive ({res['records_count']} rekod disahkan). Ujian restore: {res['restore_info']['status']}.", "success")
    except Exception as e:
        flash(f"Ralat sandaran: {str(e)}", "danger")

    return redirect(url_for("admin.dashboard", tab="drive"))

@admin_bp.route("/audit-video", methods=["GET"])
@admin_required
def audit_video():
    """Lencongkan terus ke Tab Audit dalam Pusat Pentadbir Sehenti."""
    return redirect(url_for("admin.dashboard", tab="audit"))

@admin_bp.route("/audit-video/semak", methods=["POST"])
@admin_required
def semak_semua_qr_video():
    """Tindakan pentadbir: Semak Semua QR Video."""
    audit_data = video_qr_service.audit_all_videos()
    flash(f"Semakan selesai: {audit_data['summary']['berjaya']} Berjaya, {audit_data['summary']['perlu_tindakan']} Perlu Tindakan, {audit_data['summary']['gagal']} Gagal.", "info")
    return redirect(url_for("admin.dashboard", tab="audit"))

@admin_bp.route("/audit-video/fix-all", methods=["POST"])
@admin_required
def fix_all_video():
    """Tindakan pentadbir: Tetapkan Viewer (Anyone with link) & Jana Semula Semua QR Video."""
    try:
        audit_data = video_qr_service.batch_fix_all_videos()
        flash(f"Pembaikan selesai: Semua {audit_data['summary']['total']} video telah disetkan kepada Viewer dan QR Code dijana.", "success")
    except Exception as e:
        flash(f"Ralat pembaikan video: {str(e)}", "danger")
    return redirect(url_for("admin.dashboard", tab="audit"))

@admin_bp.route("/audit-video/fix-single/<int:submission_id>", methods=["POST"])
@admin_required
def fix_single_video(submission_id):
    """Tindakan pentadbir: Baiki akses dan jana semula QR satu video."""
    sub = Submission.query.get_or_404(submission_id)
    if sub.video_drive_file_id:
        ok_perm, msg_perm = video_qr_service.ensure_viewer_permission(sub.video_drive_file_id)
        qp, _ = video_qr_service.generate_qr_code(sub.id, sub.video_drive_file_id, force=True)
        if ok_perm and qp:
            flash(f"Video {sub.nama} (ID {sub.id}): Akses Viewer disahkan dan QR Code berjaya dijana.", "success")
        else:
            flash(f"Video {sub.nama}: {msg_perm}", "warning")
    else:
        flash("Tiada Google Drive File ID bagi rekod ini.", "danger")
    return redirect(url_for("admin.audit_video"))

@admin_bp.route("/audit-video/download-report/<format>")
@admin_required
def download_audit_report(format):
    """Muat turun Laporan Semakan QR Video (JSON atau Markdown)."""
    audit_data = video_qr_service.audit_all_videos()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    backup_dir = Config.UPLOAD_FOLDER / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    if format == "json":
        filename = f"laporan_semakan_qr_video_{timestamp}.json"
        filepath = backup_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(audit_data, f, indent=2, ensure_ascii=False)
        return send_file(filepath, as_attachment=True, download_name=filename, mimetype="application/json")
    else:
        filename = f"laporan_semakan_qr_video_{timestamp}.md"
        filepath = backup_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"# LAPORAN AUDIT & SEMAKAN QR VIDEO BUKU KENANGAN KP JDN 2026\n")
            f.write(f"Tarikh Semakan: {audit_data['summary']['last_checked']}\n\n")
            f.write(f"## Ringkasan Eksekutif\n")
            f.write(f"- Jumlah Video: {audit_data['summary']['total']}\n")
            f.write(f"- Berjaya: {audit_data['summary']['berjaya']}\n")
            f.write(f"- Perlu Tindakan: {audit_data['summary']['perlu_tindakan']}\n")
            f.write(f"- Gagal: {audit_data['summary']['gagal']}\n\n")
            f.write(f"## Jadual Keputusan Semakan\n\n")
            f.write(f"| ID | Nama Pengirim | Bahagian | Video File ID | Akses Viewer | QR Code | Ujian Anonim | Keputusan |\n")
            f.write(f"| :-: | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")
            for item in audit_data["results"]:
                f.write(f"| {item['submission_id']} | {item['nama']} | {item['bahagian']} | `{item['drive_file_id']}` | {item['viewer_access']} | {item['qr_code_status']} | {item['anonymous_test']} | **{item['keputusan']}** |\n")
        return send_file(filepath, as_attachment=True, download_name=filename, mimetype="text/markdown")

@admin_bp.route("/export-json")
@admin_required
def export_json():
    submissions = Submission.query.all()
    data = [s.to_dict() for s in submissions]
    return jsonify(data)

@admin_bp.route("/penjana-buku", methods=["GET"])
@admin_required
def penjana_buku_dashboard():
    """Lencongkan ke Tab Buku dalam Pusat Pentadbir Sehenti."""
    source = request.args.get("source", "auto")
    return redirect(url_for("admin.dashboard", source=source, tab="buku"))

@admin_bp.route("/penjana-buku/preview/<chapter>", methods=["GET"])
@admin_required
def penjana_buku_preview(chapter):
    """Pratonton Halaman Kandungan A4 Portrait sebelum cetakan/eksport."""
    source = request.args.get("source", "auto")
    return book_generator_service.render_chapter_html(chapter, source)

@admin_bp.route("/penjana-buku/export-pdf/<chapter>", methods=["GET"])
@admin_required
def penjana_buku_export_pdf(chapter):
    """Jana dan muat turun fail PDF A4 Portrait serasi Canva."""
    source = request.args.get("source", "auto")
    try:
        pdf_path = book_generator_service.generate_pdf(chapter, source)
        return send_file(
            pdf_path,
            as_attachment=True,
            download_name=pdf_path.name,
            mimetype="application/pdf"
        )
    except Exception as e:
        flash(f"Ralat penjanaan PDF: {str(e)}", "danger")
        return redirect(url_for("admin.dashboard", source=source, tab="buku"))

@admin_bp.route("/penjana-buku/sync-drive/<chapter>", methods=["POST"])
@admin_required
def penjana_buku_sync_drive(chapter):
    """Jana dan simpan salinan PDF A4 ke folder '06 PDF BUKU KENANGAN' Google Drive."""
    source = request.form.get("source", "auto")
    try:
        pdf_path = book_generator_service.generate_pdf(chapter, source)
        ok, res = book_generator_service.sync_pdf_to_google_drive(pdf_path)
        if ok:
            flash(f"Fail {pdf_path.name} berjaya disimpan ke Google Drive folder '06 PDF BUKU KENANGAN'.", "success")
        else:
            flash(f"Gagal simpan ke Google Drive: {res}", "danger")
    except Exception as e:
        flash(f"Ralat semasa simpan ke Google Drive: {str(e)}", "danger")
    return redirect(url_for("admin.dashboard", source=source, tab="buku"))

