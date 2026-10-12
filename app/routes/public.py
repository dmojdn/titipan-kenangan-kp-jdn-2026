import os
import uuid
from pathlib import Path
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from werkzeug.utils import secure_filename
from app.models import db, Submission, SystemLog
from app.services.drive_service import drive_service

public_bp = Blueprint("public", __name__)

# Senarai Bahagian & Unit di Jabatan Digital Negara (JDN)
BAHAGIAN_JDN = [
    "Pejabat Ketua Pengarah",
    "Bahagian Pembangunan Aplikasi Strategik",
    "Bahagian Infrastruktur & Keselamatan Siber",
    "Bahagian Data Raya & Kecerdasan Buatan",
    "Bahagian Transformasi Digital Sektor Awam",
    "Bahagian Perancangan Strategik & Antarabangsa",
    "Bahagian Khidmat Pengurusan",
    "Unit Komunikasi Korporat",
    "Unit Integriti",
    "Unit Audit Dalam",
    "Lain-lain / Rakan Strategik"
]

def allowed_file(filename, allowed_extensions):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_extensions

@public_bp.route("/")
def index():
    # Ambil 6 ucapan terkini yang diluluskan/aktif untuk paparan inspirasi
    recent_submissions = Submission.query.filter_by(status="active").order_by(Submission.created_at.desc()).limit(6).all()
    total_submissions = Submission.query.filter_by(status="active").count()
    return render_template(
        "index.html",
        bahagian_list=BAHAGIAN_JDN,
        recent_submissions=recent_submissions,
        total_submissions=total_submissions
    )

@public_bp.route("/hantar", methods=["POST"])
def hantar_ucapan():
    nama = request.form.get("nama", "").strip()
    bahagian = request.form.get("bahagian", "").strip()
    bahagian_custom = request.form.get("bahagian_custom", "").strip()
    jawatan = request.form.get("jawatan", "").strip()
    ucapan = request.form.get("ucapan", "").strip()

    if bahagian == "Lain-lain / Rakan Strategik" and bahagian_custom:
        bahagian = f"Lain-lain ({bahagian_custom})"

    # Validasi input wajib
    if not nama or not bahagian or not ucapan:
        flash("Sila lengkapkan Nama, Bahagian, dan Titipan Ucapan anda.", "danger")
        return redirect(url_for("public.index"))

    # Pengurusan Fail Gambar
    image_file = request.files.get("gambar")
    saved_image_name = None
    saved_image_path = None
    image_sync_status = "none"

    if image_file and image_file.filename:
        if allowed_file(image_file.filename, current_app.config["ALLOWED_IMAGE_EXTENSIONS"]):
            orig_name = secure_filename(image_file.filename)
            ext = orig_name.rsplit(".", 1)[1].lower()
            unique_name = f"IMG_{datetime_prefix()}_{uuid.uuid4().hex[:6]}.{ext}"
            dest_path = current_app.config["UPLOAD_IMAGES_FOLDER"] / unique_name
            image_file.save(str(dest_path))
            saved_image_name = unique_name
            saved_image_path = str(dest_path)
            image_sync_status = "pending"
        else:
            flash("Format fail gambar tidak disokong. Sila muat naik JPG, PNG, atau WebP.", "warning")
            return redirect(url_for("public.index"))

    # Pengurusan Fail Video
    video_file = request.files.get("video")
    saved_video_name = None
    saved_video_path = None
    video_sync_status = "none"

    if video_file and video_file.filename:
        if allowed_file(video_file.filename, current_app.config["ALLOWED_VIDEO_EXTENSIONS"]):
            orig_name = secure_filename(video_file.filename)
            ext = orig_name.rsplit(".", 1)[1].lower()
            unique_name = f"VID_{datetime_prefix()}_{uuid.uuid4().hex[:6]}.{ext}"
            dest_path = current_app.config["UPLOAD_VIDEOS_FOLDER"] / unique_name
            video_file.save(str(dest_path))
            saved_video_name = unique_name
            saved_video_path = str(dest_path)
            video_sync_status = "pending"
        else:
            flash("Format fail video tidak disokong. Sila muat naik MP4, MOV, atau WebM.", "warning")
            return redirect(url_for("public.index"))

    # Simpan ke pangkalan data tempatan dahulu
    submission = Submission(
        nama=nama,
        bahagian=bahagian,
        jawatan=jawatan or None,
        ucapan=ucapan,
        image_filename=saved_image_name,
        image_local_path=saved_image_path,
        image_sync_status=image_sync_status,
        video_filename=saved_video_name,
        video_local_path=saved_video_path,
        video_sync_status=video_sync_status,
        ip_address=request.remote_addr
    )
    db.session.add(submission)
    db.session.commit()

    # Percubaan automatik muat naik ke Google Drive jika sambungan aktif
    drive_ready = drive_service.is_connected()
    if drive_ready:
        # 1. Muat naik gambar ke "02 GAMBAR KENANGAN"
        if saved_image_path and image_sync_status == "pending":
            try:
                fid, flink = drive_service.upload_file(
                    local_path=saved_image_path,
                    target_subfolder_name="02 GAMBAR KENANGAN",
                    custom_name=f"[{submission.id}] {submission.nama} - {saved_image_name}"
                )
                submission.image_drive_file_id = fid
                submission.image_drive_link = flink
                submission.image_sync_status = "synced"
            except Exception as e:
                submission.image_sync_status = "failed"
                current_app.logger.error(f"Gagal memuat naik gambar ke Drive: {e}")

        # 2. Muat naik video ke "03 VIDEO KENANGAN"
        if saved_video_path and video_sync_status == "pending":
            try:
                fid, flink = drive_service.upload_file(
                    local_path=saved_video_path,
                    target_subfolder_name="03 VIDEO KENANGAN",
                    custom_name=f"[{submission.id}] {submission.nama} - {saved_video_name}"
                )
                submission.video_drive_file_id = fid
                submission.video_drive_link = flink
                submission.video_sync_status = "synced"
            except Exception as e:
                submission.video_sync_status = "failed"
                current_app.logger.error(f"Gagal memuat naik video ke Drive: {e}")

        db.session.commit()

    return redirect(url_for("public.kejayaan", submission_id=submission.id))

@public_bp.route("/kejayaan/<int:submission_id>")
def kejayaan(submission_id):
    submission = Submission.query.get_or_404(submission_id)
    return render_template("success.html", submission=submission)

def datetime_prefix():
    from datetime import datetime
    return datetime.now().strftime("%Y%m%d_%H%M%S")
