import os
from flask import Blueprint, redirect, request, session, url_for, flash, current_app, render_template
from app.services.drive_service import drive_service
from app.models import db, DriveFolderCache, SystemLog
from app.config import Config

auth_drive_bp = Blueprint("auth_drive", __name__, url_prefix="/admin/oauth")

@auth_drive_bp.route("/authorize")
def authorize():
    """Memulakan proses OAuth 2.0 dengan menghantar pengguna ke skrin Google Consent."""
    # Pastikan pengguna telah log masuk pentadbir
    if not session.get("is_admin"):
        flash("Sila log masuk sebagai pentadbir terlebih dahulu.", "warning")
        return redirect(url_for("admin.login", next=request.url))

    try:
        # Benarkan HTTP untuk persekitaran pembangunan tempatan (local testing)
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

        flow = drive_service.create_oauth_flow()
        authorization_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent"
        )
        session["oauth_state"] = state
        session["code_verifier"] = getattr(flow, "code_verifier", None)
        return redirect(authorization_url)
    except Exception as e:
        flash(f"Gagal memulakan OAuth Google Drive: {str(e)}", "danger")
        return redirect(url_for("admin.drive_setup"))

@auth_drive_bp.route("/callback")
def callback():
    """Menerima kod kebenaran dari Google dan menyimpan token.json."""
    if not session.get("is_admin"):
        flash("Sila log masuk semula.", "warning")
        return redirect(url_for("admin.login"))

    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    try:
        state = session.get("oauth_state")
        code_verifier = session.get("code_verifier")
        flow = drive_service.create_oauth_flow(state=state)
        if code_verifier:
            flow.code_verifier = code_verifier
        flow.fetch_token(authorization_response=request.url)
        creds = flow.credentials

        # Simpan token ke fail token.json
        with open(Config.GOOGLE_TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

        log = SystemLog(
            action="oauth_connected",
            status="success",
            details="Akaun Google Drive berjaya dihubungkan melalui OAuth 2.0."
        )
        db.session.add(log)
        db.session.commit()

        # Sahkan capaian Root Folder dan 6 subfolder
        access_ok, msg = drive_service.ensure_root_folder_access()
        if access_ok:
            folder_map = drive_service.get_or_create_subfolders()
            flash(f"Sambungan Google Drive BERJAYA! 6 Folder utama telah disahkan di Drive.", "success")
        else:
            flash(f"Token berjaya disimpan, tetapi semakan Root Folder menunjukkan: {msg}", "warning")

        return redirect(url_for("admin.drive_setup"))
    except Exception as e:
        current_app.logger.error(f"Ralat semasa pengesahan OAuth: {e}", exc_info=True)
        flash(f"Ralat semasa pengesahan OAuth: {str(e)}", "danger")
        return redirect(url_for("admin.drive_setup"))

@auth_drive_bp.route("/disconnect", methods=["POST"])
def disconnect():
    """Memutuskan sambungan Google Drive dengan memadamkan fail token."""
    if not session.get("is_admin"):
        flash("Akses pentadbir diperlukan.", "warning")
        return redirect(url_for("admin.login"))

    if Config.GOOGLE_TOKEN_FILE.exists():
        try:
            Config.GOOGLE_TOKEN_FILE.unlink()
            # Bersihkan cache folder
            DriveFolderCache.query.delete()
            db.session.commit()
            flash("Sambungan Google Drive telah berjaya diputuskan (token.json dipadam).", "info")
        except Exception as e:
            flash(f"Gagal memadam fail token: {e}", "danger")
    else:
        flash("Tiada fail token yang aktif ditemui.", "info")

    return redirect(url_for("admin.drive_setup"))

@auth_drive_bp.route("/sync-now", methods=["POST"])
def sync_now():
    """Menyelaraskan fail tempatan yang belum dimuat naik ke Google Drive."""
    if not session.get("is_admin"):
        flash("Akses pentadbir diperlukan.", "warning")
        return redirect(url_for("admin.login"))

    if not drive_service.is_connected():
        flash("Google Drive belum disambungkan. Sila sambungkan terlebih dahulu.", "warning")
        return redirect(url_for("admin.drive_setup"))

    from app.models import Submission
    pending_images = Submission.query.filter_by(image_sync_status="pending").all()
    pending_videos = Submission.query.filter_by(video_sync_status="pending").all()

    img_count = 0
    vid_count = 0

    for s in pending_images:
        if s.image_local_path and os.path.exists(s.image_local_path):
            try:
                fid, link = drive_service.upload_file(
                    local_path=s.image_local_path,
                    target_subfolder_name="02 GAMBAR KENANGAN",
                    custom_name=f"[{s.id}] {s.nama} - {s.image_filename}"
                )
                s.image_drive_file_id = fid
                s.image_drive_link = link
                s.image_sync_status = "synced"
                img_count += 1
            except Exception as e:
                s.image_sync_status = "failed"
                current_app.logger.error(f"Sync gagal untuk gambar {s.id}: {e}")

    for s in pending_videos:
        if s.video_local_path and os.path.exists(s.video_local_path):
            try:
                fid, link = drive_service.upload_file(
                    local_path=s.video_local_path,
                    target_subfolder_name="03 VIDEO KENANGAN",
                    custom_name=f"[{s.id}] {s.nama} - {s.video_filename}"
                )
                s.video_drive_file_id = fid
                s.video_drive_link = link
                s.video_sync_status = "synced"
                vid_count += 1
            except Exception as e:
                s.video_sync_status = "failed"
                current_app.logger.error(f"Sync gagal untuk video {s.id}: {e}")

    db.session.commit()
    flash(f"Penyelarasan selesai! Gambar berjaya: {img_count}, Video berjaya: {vid_count}.", "success")
    return redirect(url_for("admin.dashboard"))
