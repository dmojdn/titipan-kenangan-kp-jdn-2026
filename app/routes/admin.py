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
        password = request.form.get("password", "")
        if password == Config.ADMIN_PASSWORD:
            session["is_admin"] = True
            session.permanent = True
            flash("Selamat kembali! Anda telah berjaya log masuk pentadbir.", "success")
            next_page = request.args.get("next")
            return redirect(next_page or url_for("admin.dashboard"))
        else:
            flash("Kata laluan pentadbir tidak tepat. Sila cuba lagi.", "danger")

    return render_template("admin/login.html")

@admin_bp.route("/logout")
def logout():
    session.pop("is_admin", None)
    flash("Anda telah log keluar daripada sesi pentadbir.", "info")
    return redirect(url_for("admin.login"))

@admin_bp.route("/")
@admin_required
def dashboard():
    filter_type = request.args.get("filter", "all")
    bahagian_filter = request.args.get("bahagian", "")

    query = Submission.query

    if filter_type == "image":
        query = query.filter(Submission.image_filename.isnot(None))
    elif filter_type == "video":
        query = query.filter(Submission.video_filename.isnot(None))
    elif filter_type == "pending_sync":
        query = query.filter(
            (Submission.image_sync_status == "pending") |
            (Submission.video_sync_status == "pending")
        )

    if bahagian_filter:
        query = query.filter(Submission.bahagian == bahagian_filter)

    submissions = query.order_by(Submission.created_at.desc()).all()

    # Statistik Keseluruhan
    total_count = Submission.query.count()
    images_count = Submission.query.filter(Submission.image_filename.isnot(None)).count()
    videos_count = Submission.query.filter(Submission.video_filename.isnot(None)).count()
    pending_sync_count = Submission.query.filter(
        (Submission.image_sync_status == "pending") |
        (Submission.video_sync_status == "pending")
    ).count()

    is_drive_connected = drive_service.is_connected()
    connected_email = drive_service.get_user_email() if is_drive_connected else None

    # Dapatkan senarai bahagian unik untuk penapis
    bahagian_list = [row[0] for row in db.session.query(Submission.bahagian).distinct().all() if row[0]]

    return render_template(
        "admin/dashboard.html",
        submissions=submissions,
        total_count=total_count,
        images_count=images_count,
        videos_count=videos_count,
        pending_sync_count=pending_sync_count,
        is_drive_connected=is_drive_connected,
        connected_email=connected_email,
        current_filter=filter_type,
        bahagian_filter=bahagian_filter,
        bahagian_list=bahagian_list
    )

@admin_bp.route("/kiriman/<int:submission_id>")
@admin_required
def detail(submission_id):
    submission = Submission.query.get_or_404(submission_id)
    return render_template("admin/detail.html", submission=submission)

@admin_bp.route("/kiriman/<int:submission_id>/padam", methods=["POST"])
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
    flash(f"Kiriman daripada {submission.nama} telah berjaya dipadam.", "success")
    return redirect(url_for("admin.dashboard"))

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
    """Menjana fail sandaran JSON semua ucapan dan memuat naik ke Google Drive."""
    submissions = Submission.query.all()
    backup_data = {
        "timestamp": datetime.now().isoformat(),
        "total_records": len(submissions),
        "target_account": Config.DRIVE_ACCOUNT,
        "root_folder_id": Config.DRIVE_ROOT_FOLDER_ID,
        "data": [s.to_dict() for s in submissions]
    }

    backup_dir = Config.UPLOAD_FOLDER / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    filename = f"backup_ucapan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    backup_path = backup_dir / filename

    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(backup_data, f, ensure_ascii=False, indent=2)

    drive_msg = ""
    if drive_service.is_connected():
        success, res = drive_service.upload_backup_data(str(backup_path))
        if success:
            drive_msg = " dan berjaya dimuat naik ke folder '01 UCAPAN & DATA' serta '06 BACKUP LENGKAP' di Google Drive."
        else:
            drive_msg = f", tetapi muat naik ke Drive gagal: {res}"
    else:
        drive_msg = " (Google Drive belum disambungkan, fail disimpan secara tempatan)."

    flash(f"Sandaran pangkalan data berjaya dijana ({filename}){drive_msg}", "success")
    return redirect(url_for("admin.drive_setup"))

@admin_bp.route("/export-json")
@admin_required
def export_json():
    submissions = Submission.query.all()
    data = [s.to_dict() for s in submissions]
    return jsonify(data)
