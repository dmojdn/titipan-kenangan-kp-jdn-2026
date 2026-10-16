import os
import uuid
from datetime import datetime
from pathlib import Path
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, send_from_directory, session
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

@public_bp.app_template_filter("time_ago")
def time_ago_filter(dt):
    if not dt:
        return "Baru sahaja"
    diff = datetime.now() - dt
    seconds = int(diff.total_seconds())
    if seconds < 60:
        return "Baru sahaja"
    elif seconds < 3600:
        mins = max(1, seconds // 60)
        return f"{mins} minit yang lalu"
    elif seconds < 86400:
        hrs = max(1, seconds // 3600)
        return f"{hrs} jam yang lalu"
    elif seconds < 86400 * 7:
        days = max(1, seconds // 86400)
        return f"{days} hari yang lalu"
    else:
        return dt.strftime("%d %b")

@public_bp.route("/")
def index():
    # 1. Semua ucapan dalam bentuk teks yang terkini (hanya data rasmi)
    recent_text_submissions = (
        Submission.query.filter_by(status="active", data_type="official")
        .filter(Submission.ucapan.isnot(None), Submission.ucapan != "")
        .order_by(Submission.created_at.desc())
        .limit(4)
        .all()
    )

    # 2. Semua ucapan yang dikirim melalui foto dan video yang terkini (hanya data rasmi)
    recent_media_submissions = (
        Submission.query.filter_by(status="active", data_type="official")
        .filter((Submission.image_filename.isnot(None)) | (Submission.video_filename.isnot(None)))
        .order_by(Submission.created_at.desc())
        .limit(8)
        .all()
    )

    total_submissions = Submission.query.filter_by(status="active", data_type="official").count()
    total_ucapan = (
        Submission.query.filter_by(status="active", data_type="official")
        .filter(Submission.ucapan.isnot(None), Submission.ucapan != "")
        .count()
    )
    total_media = (
        Submission.query.filter_by(status="active", data_type="official")
        .filter((Submission.image_filename.isnot(None)) | (Submission.video_filename.isnot(None)))
        .count()
    )

    return render_template(
        "index.html",
        bahagian_list=BAHAGIAN_JDN,
        recent_text_submissions=recent_text_submissions,
        recent_media_submissions=recent_media_submissions,
        total_submissions=total_submissions,
        total_ucapan=total_ucapan,
        total_media=total_media,
        active_page="home"
    )

@public_bp.route("/titip-ucapan")
def titip_ucapan():
    """Halaman khusus Titip Ucapan & himpunan semua ucapan teks terkini (hanya data rasmi)."""
    all_text_submissions = (
        Submission.query.filter_by(status="active", data_type="official")
        .filter(Submission.ucapan.isnot(None), Submission.ucapan != "")
        .order_by(Submission.created_at.desc())
        .all()
    )
    total_submissions = Submission.query.filter_by(status="active", data_type="official").count()
    return render_template(
        "titip_ucapan.html",
        bahagian_list=BAHAGIAN_JDN,
        all_text_submissions=all_text_submissions,
        total_submissions=total_submissions,
        active_page="titip_ucapan"
    )

@public_bp.route("/kenangan")
def kenangan():
    """Halaman khusus Galeri Kenangan (semua foto & video terkini rasmi)."""
    all_media_submissions = (
        Submission.query.filter_by(status="active", data_type="official")
        .filter((Submission.image_filename.isnot(None)) | (Submission.video_filename.isnot(None)))
        .order_by(Submission.created_at.desc())
        .all()
    )
    total_media = len(all_media_submissions)
    return render_template(
        "kenangan.html",
        all_media_submissions=all_media_submissions,
        total_media=total_media,
        active_page="kenangan"
    )

@public_bp.route("/uploads/images/<filename>")
def serve_image(filename):
    file_path = current_app.config["UPLOAD_IMAGES_FOLDER"] / filename
    if not file_path.exists():
        sub = Submission.query.filter_by(image_filename=filename).first()
        if sub and sub.image_drive_file_id:
            try:
                from googleapiclient.http import MediaIoBaseDownload
                service = drive_service.get_service()
                if service:
                    req = service.files().get_media(fileId=sub.image_drive_file_id)
                    with open(file_path, "wb") as f:
                        downloader = MediaIoBaseDownload(f, req)
                        downloader.next_chunk()
            except Exception as e:
                current_app.logger.warning(f"Gagal muat turun gambar dari Drive: {e}")
    if file_path.exists():
        return send_from_directory(current_app.config["UPLOAD_IMAGES_FOLDER"], filename)
    return "", 404

@public_bp.route("/uploads/videos/<filename>")
def serve_video(filename):
    return send_from_directory(current_app.config["UPLOAD_VIDEOS_FOLDER"], filename)

@public_bp.route("/uploads/qrcodes/<filename>")
def serve_qrcode(filename):
    qr_dir = Path(current_app.config["UPLOAD_FOLDER"]) / "qrcodes"
    return send_from_directory(qr_dir, filename)

@public_bp.route("/hantar", methods=["POST"])
def hantar_ucapan():
    nama = request.form.get("nama", "").strip()
    bahagian = request.form.get("bahagian", "").strip()
    jawatan = request.form.get("jawatan", "").strip()
    ucapan = request.form.get("ucapan", "").strip()

    # Validasi input wajib: Hanya Nama yang wajib diisi (Bahagian adalah pilihan)
    if not nama:
        flash("Sila lengkapkan Nama anda.", "danger")
        return redirect(url_for("public.index"))

    if not bahagian:
        bahagian = "-"

    # Semak lampiran fail gambar & video
    image_file = request.files.get("gambar")
    has_image = bool(image_file and image_file.filename and image_file.filename.strip())

    video_file = request.files.get("video")
    has_video = bool(video_file and video_file.filename and video_file.filename.strip())

    has_ucapan = bool(ucapan)

    # Validasi sekurang-kurangnya satu pilihan disertakan: Teks, Gambar, atau Video
    if not has_ucapan and not has_image and not has_video:
        flash("Sila sertakan sekurang-kurangnya salah satu pilihan: Teks Ucapan, Gambar Kenangan, atau Video Ucapan (anda juga boleh memilih ketiga-tiganya).", "warning")
        return redirect(url_for("public.index"))
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

    # Simpan ke pangkalan data tempatan dahulu sebagai data rasmi
    submission = Submission(
        nama=nama,
        bahagian=bahagian,
        jawatan=jawatan or None,
        ucapan=ucapan or "",
        status="active",
        data_type="official",
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

        # 2. Muat naik video ke "03 VIDEO KENANGAN" & Jana QR Code
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

                # Tetapkan kebenaran Viewer dan jana QR code secara automatik
                try:
                    from app.services.video_qr_service import video_qr_service
                    video_qr_service.ensure_viewer_permission(fid)
                    video_qr_service.generate_qr_code(submission.id, fid)
                except Exception as qr_err:
                    current_app.logger.warning(f"Gagal menjana QR/Viewer untuk video {fid}: {qr_err}")
            except Exception as e:
                submission.video_sync_status = "failed"
                current_app.logger.error(f"Gagal memuat naik video ke Drive: {e}")

        db.session.commit()

        # Segerakkan arkib penuh secara automatik di latar belakang (Background Backup Sync)
        try:
            trigger_background_backup(current_app._get_current_object())
        except Exception:
            pass

    return redirect(url_for("public.kejayaan", submission_id=submission.id))

@public_bp.route("/upload-media-pengarah", methods=["POST"])
def upload_media_pengarah():
    # Hanya pentadbir yang boleh muat naik media pengarah (akses khas)
    if not session.get("is_admin"):
        flash("Akses terhad: Sila log masuk pentadbir terlebih dahulu untuk memuat naik media pengarah.", "warning")
        return redirect(url_for("admin.login"))

    files = request.files.getlist("media_files")
    
    # Juga semak jika dihantar melalui input tunggal
    if not files or all(not f or f.filename == "" for f in files):
        gambar = request.files.get("gambar")
        video = request.files.get("video")
        files = [f for f in [gambar, video] if f and f.filename]

    valid_files = [f for f in files if f and f.filename and f.filename.strip()]

    if not valid_files:
        flash("Sila pilih sekurang-kurangnya satu fail gambar atau video pengarah untuk dimuat naik.", "warning")
        return redirect(request.referrer or url_for("public.kenangan"))

    uploaded_count = 0
    drive_ready = drive_service.is_connected()

    for file in valid_files:
        filename = file.filename
        orig_name = secure_filename(filename)
        if not orig_name:
            orig_name = f"media_{datetime_prefix()}"
        ext = orig_name.rsplit(".", 1)[1].lower() if "." in orig_name else ""

        is_image = allowed_file(filename, current_app.config["ALLOWED_IMAGE_EXTENSIONS"])
        is_video = allowed_file(filename, current_app.config["ALLOWED_VIDEO_EXTENSIONS"])

        if not is_image and not is_video:
            continue

        saved_image_name = None
        saved_image_path = None
        image_sync_status = "none"
        saved_video_name = None
        saved_video_path = None
        video_sync_status = "none"

        if is_image:
            unique_name = f"KP_IMG_{datetime_prefix()}_{uuid.uuid4().hex[:6]}.{ext}"
            dest_path = current_app.config["UPLOAD_IMAGES_FOLDER"] / unique_name
            file.save(str(dest_path))
            saved_image_name = unique_name
            saved_image_path = str(dest_path)
            image_sync_status = "pending"
        elif is_video:
            unique_name = f"KP_VID_{datetime_prefix()}_{uuid.uuid4().hex[:6]}.{ext}"
            dest_path = current_app.config["UPLOAD_VIDEOS_FOLDER"] / unique_name
            file.save(str(dest_path))
            saved_video_name = unique_name
            saved_video_path = str(dest_path)
            video_sync_status = "pending"

        # Simpan ke pangkalan data atas nama Jabatan Digital Negara sahaja (tanpa nama individu)
        submission = Submission(
            nama="Jabatan Digital Negara",
            bahagian="Jabatan Digital Negara",
            jawatan=None,
            ucapan="",
            image_filename=saved_image_name,
            image_local_path=saved_image_path,
            image_sync_status=image_sync_status,
            video_filename=saved_video_name,
            video_local_path=saved_video_path,
            video_sync_status=video_sync_status,
            ip_address=request.remote_addr,
            status="active",
            data_type="official"
        )
        db.session.add(submission)
        db.session.commit()
        uploaded_count += 1

        # Muat naik ke Google Drive jika sambungan aktif
        if drive_ready:
            try:
                if saved_image_path and image_sync_status == "pending":
                    fid, flink = drive_service.upload_file(
                        local_path=saved_image_path,
                        target_subfolder_name="02 GAMBAR KENANGAN",
                        custom_name=f"[PENGARAH JDN] {saved_image_name}"
                    )
                    submission.image_drive_file_id = fid
                    submission.image_drive_link = flink
                    submission.image_sync_status = "synced"

                if saved_video_path and video_sync_status == "pending":
                    fid, flink = drive_service.upload_file(
                        local_path=saved_video_path,
                        target_subfolder_name="03 VIDEO KENANGAN",
                        custom_name=f"[PENGARAH JDN] {saved_video_name}"
                    )
                    submission.video_drive_file_id = fid
                    submission.video_drive_link = flink
                    submission.video_sync_status = "synced"

                    # Tetapkan Viewer dan jana QR code
                    try:
                        from app.services.video_qr_service import video_qr_service
                        video_qr_service.ensure_viewer_permission(fid)
                        video_qr_service.generate_qr_code(submission.id, fid)
                    except Exception as qr_err:
                        current_app.logger.warning(f"Gagal menjana QR media pengarah: {qr_err}")

                db.session.commit()
            except Exception as e:
                current_app.logger.error(f"Gagal memuat naik ke Drive: {e}")

    if uploaded_count > 0:
        # Segerakkan arkib penuh secara automatik di latar belakang
        try:
            trigger_background_backup(current_app._get_current_object())
        except Exception:
            pass
        flash(f"Alhamdulillah! Sebanyak {uploaded_count} fail foto/video pengarah telah berjaya dimuat naik atas nama Jabatan Digital Negara.", "success")
    else:
        flash("Format fail tidak disokong. Sila pilih gambar (JPG, PNG, WebP) atau video (MP4, MOV, WebM).", "warning")

    return redirect(request.referrer or url_for("public.kenangan"))

@public_bp.route("/kejayaan/<int:submission_id>")
def kejayaan(submission_id):
    submission = Submission.query.get_or_404(submission_id)
    return render_template("success.html", submission=submission)

def datetime_prefix():
    from datetime import datetime
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def trigger_background_backup(app_instance):
    import threading
    def _run_bg():
        with app_instance.app_context():
            try:
                from app.services.backup_service import backup_service
                backup_service.run_full_backup_pipeline()
            except Exception as e:
                app_instance.logger.warning(f"Background backup sync error: {e}")
    threading.Thread(target=_run_bg, daemon=True).start()

