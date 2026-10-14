import os
import urllib.request
import logging
from datetime import datetime
from pathlib import Path
import qrcode
from qrcode.constants import ERROR_CORRECT_M

from app.config import Config, BASE_DIR
from app.models import db, Submission, SystemLog
from app.services.drive_service import drive_service

logger = logging.getLogger(__name__)

QR_OUTPUT_DIR = BASE_DIR / "uploads" / "qrcodes"
QR_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

class VideoQRService:
    def __init__(self):
        self.drive = drive_service

    def get_video_view_url(self, file_id):
        """Format URL tontonan rasmi Google Drive."""
        if not file_id:
            return ""
        return f"https://drive.google.com/file/d/{file_id}/view"

    def ensure_viewer_permission(self, file_id):
        """
        Tetapkan kebenaran Google Drive:
        General Access: Anyone with the link
        Role: Viewer (type: 'anyone', role: 'reader')
        Mengelakkan permission pendua dan mengesahkan pembacaan semula.
        """
        service = self.drive.get_service()
        if not service:
            return False, "Google Drive belum disambungkan."

        if not file_id:
            return False, "Google Drive File ID kosong."

        try:
            # 1. Semak kebenaran sedia ada
            perm_res = service.permissions().list(
                fileId=file_id,
                fields="permissions(id, type, role)",
                supportsAllDrives=True
            ).execute()
            perms = perm_res.get("permissions", [])

            # Semak sama ada 'anyone' dengan role 'reader' sudah ada
            for p in perms:
                if p.get("type") == "anyone" and p.get("role") in ("reader", "viewer"):
                    return True, "Kebenaran 'Anyone with link (Viewer)' sudah sedia aktif."

            # 2. Cipta kebenaran baharu jika belum wujud
            service.permissions().create(
                fileId=file_id,
                body={"type": "anyone", "role": "reader"},
                fields="id, type, role",
                supportsAllDrives=True
            ).execute()

            # 3. Sahkan pembacaan semula melalui API
            perm_check = service.permissions().list(
                fileId=file_id,
                fields="permissions(id, type, role)",
                supportsAllDrives=True
            ).execute()
            verified = any(
                p.get("type") == "anyone" and p.get("role") in ("reader", "viewer")
                for p in perm_check.get("permissions", [])
            )

            if verified:
                return True, "Kebenaran 'Anyone with link (Viewer)' berjaya dicipta & disahkan."
            else:
                return False, "Kebenaran dicipta tetapi gagal disahkan melalui API."

        except Exception as e:
            logger.error(f"Ralat tetapan permission bagi file {file_id}: {e}")
            return False, f"Ralat API: {str(e)}"

    def generate_qr_code(self, submission_id, file_id, force=False):
        """
        Jana fail imej QR Code unik bagi video dengan resolusi tinggi,
        latar putih, nisbah kontras optimum, dan quiet zone 4 modul.
        """
        if not file_id:
            return None, "File ID tidak sah"

        url = self.get_video_view_url(file_id)
        filename = f"qr_video_sub_{submission_id}_{file_id[:8]}.png"
        filepath = QR_OUTPUT_DIR / filename

        # Jika sudah wujud dan tidak dipaksa jana semula
        if filepath.exists() and not force:
            return str(filepath), url

        try:
            qr = qrcode.QRCode(
                version=1,
                error_correction=ERROR_CORRECT_M,
                box_size=12,
                border=4
            )
            qr.add_data(url)
            qr.make(fit=True)

            img = qr.make_image(fill_color="#0f172a", back_color="#ffffff")
            img.save(str(filepath))

            logger.info(f"QR Code dijana: {filename} -> {url}")
            return str(filepath), url
        except Exception as e:
            logger.error(f"Gagal menjana QR Code untuk video {file_id}: {e}")
            return None, str(e)

    def test_anonymous_access(self, file_id):
        """
        Uji akses awam terhadap pautan tontonan tanpa kuki log masuk.
        """
        if not file_id:
            return False, "Tiada File ID"

        url = self.get_video_view_url(file_id)
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            # Timeout pendek 5 saat untuk ujian rangkaian pantas
            with urllib.request.urlopen(req, timeout=5) as resp:
                status = resp.status
                if status in (200, 301, 302, 303):
                    return True, f"HTTP {status} (Boleh Dicapai Awam)"
                return False, f"HTTP {status}"
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return False, f"HTTP {e.code} (Disekat / Perlu Log Masuk)"
            return False, f"HTTP {e.code}"
        except Exception as e:
            return None, f"Ujian manual diperlukan ({str(e)})"

    def audit_single_video(self, submission):
        """
        Audit terperinci 10 kriteria bagi satu rekod video.
        Mengembalikan kamus maklumat audit lengkap.
        """
        result = {
            "submission_id": submission.id,
            "nama": submission.nama,
            "bahagian": submission.bahagian,
            "jawatan": submission.jawatan or "",
            "video_filename": submission.video_filename or "",
            "drive_file_id": submission.video_drive_file_id or "",
            "view_url": "",
            "drive_status": "Tiada di Drive",
            "drive_file_name": "",
            "drive_file_size": 0,
            "viewer_access": "Tidak Disahkan",
            "qr_code_status": "Belum Dijana",
            "qr_code_path": "",
            "anonymous_test": "Belum Diuji",
            "keputusan": "Gagal",
            "punca_masalah": [],
            "tindakan_cadangan": []
        }

        # 1. Semak kewujudan File ID
        file_id = submission.video_drive_file_id
        if not file_id:
            result["punca_masalah"].append("Google Drive File ID tiada dalam pangkalan data")
            result["tindakan_cadangan"].append("Muat naik semula video ke Google Drive")
            return result

        result["view_url"] = self.get_video_view_url(file_id)

        service = self.drive.get_service()
        if not service:
            result["drive_status"] = "Ralat Sambungan API"
            result["punca_masalah"].append("Perkhidmatan Google Drive belum disambungkan")
            result["tindakan_cadangan"].append("Sahkan Google Drive di panel pentadbir")
            return result

        # 2. Semak fail fizikal di Google Drive
        try:
            drive_file = service.files().get(
                fileId=file_id,
                fields="id, name, mimeType, size, trashed",
                supportsAllDrives=True
            ).execute()

            if drive_file.get("trashed"):
                result["drive_status"] = "Dalam Tong Sampah"
                result["punca_masalah"].append("Fail berada dalam tong sampah Google Drive")
                result["tindakan_cadangan"].append("Pulihkan fail daripada Tong Sampah Google Drive")
                return result

            result["drive_file_name"] = drive_file.get("name", "")
            result["drive_file_size"] = int(drive_file.get("size", 0))
            result["drive_status"] = "Wujud di Drive"
        except Exception as e:
            result["drive_status"] = "Tidak Ditemui"
            result["punca_masalah"].append(f"Fail tidak wujud di Google Drive ({str(e)})")
            result["tindakan_cadangan"].append("Semak semula File ID atau muat naik semula")
            return result

        # 3. Semak kebenaran akses Viewer (Anyone with the link)
        try:
            perm_res = service.permissions().list(
                fileId=file_id,
                fields="permissions(id, type, role)",
                supportsAllDrives=True
            ).execute()
            perms = perm_res.get("permissions", [])
            has_viewer = any(
                p.get("type") == "anyone" and p.get("role") in ("reader", "viewer")
                for p in perms
            )
            if has_viewer:
                result["viewer_access"] = "Disahkan (Anyone with link)"
            else:
                result["viewer_access"] = "Terhad (Perlu Tetapan Viewer)"
                result["punca_masalah"].append("Akses awam belum diaktifkan (bukan Anyone with link)")
                result["tindakan_cadangan"].append("Tekan butang 'Aktifkan Akses Viewer'")
        except Exception as e:
            result["viewer_access"] = f"Ralat Semakan ({str(e)})"
            result["punca_masalah"].append("Gagal menyemak permission melalui API")

        # 4. Semak / Jana QR Code
        qr_file = QR_OUTPUT_DIR / f"qr_video_sub_{submission.id}_{file_id[:8]}.png"
        if qr_file.exists():
            result["qr_code_status"] = "Sedia"
            result["qr_code_path"] = str(qr_file)
        else:
            # Jana automatik jika belum ada
            qp, _ = self.generate_qr_code(submission.id, file_id)
            if qp:
                result["qr_code_status"] = "Sedia (Baru Dijana)"
                result["qr_code_path"] = qp
            else:
                result["qr_code_status"] = "Gagal Dijana"
                result["punca_masalah"].append("Gagal menjana fail imej QR Code")
                result["tindakan_cadangan"].append("Jana semula QR Code")

        # 5. Ujian Akses Tanpa Log Masuk (Anonim)
        if result["viewer_access"].startswith("Disahkan"):
            is_anon, anon_msg = self.test_anonymous_access(file_id)
            if is_anon is True:
                result["anonymous_test"] = f"Boleh Ditonton ({anon_msg})"
            elif is_anon is False:
                result["anonymous_test"] = f"Disekat ({anon_msg})"
                result["punca_masalah"].append("Akses tontonan tanpa log masuk gagal dalam ujian web")
            else:
                result["anonymous_test"] = "Ujian Manual Diperlukan"

        # 6. Tentukan Keputusan Akhir
        if not result["punca_masalah"]:
            result["keputusan"] = "Berjaya"
        elif any("tidak wujud" in p.lower() or "tiada" in p.lower() for p in result["punca_masalah"]):
            result["keputusan"] = "Gagal"
        else:
            result["keputusan"] = "Perlu Tindakan"

        return result

    def audit_all_videos(self):
        """
        Audit kesemua rekod video dalam pangkalan data.
        Mengembalikan ringkasan statistik dan senarai penuh audit.
        """
        video_submissions = Submission.query.filter(
            Submission.video_filename.isnot(None),
            Submission.video_filename != ""
        ).order_by(Submission.id.asc()).all()

        results = []
        counts = {
            "total": len(video_submissions),
            "berjaya": 0,
            "perlu_tindakan": 0,
            "gagal": 0,
            "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        for sub in video_submissions:
            audit = self.audit_single_video(sub)
            results.append(audit)
            if audit["keputusan"] == "Berjaya":
                counts["berjaya"] += 1
            elif audit["keputusan"] == "Perlu Tindakan":
                counts["perlu_tindakan"] += 1
            else:
                counts["gagal"] += 1

        return {
            "summary": counts,
            "results": results
        }

    def batch_fix_all_videos(self):
        """
        Tindakan automatik pembetulan:
        1. Tetapkan Anyone with the link (Viewer) bagi semua video.
        2. Jana semula QR Code bagi semua video yang sah.
        Mengembalikan keputusan audit terkini selepas pembaikan.
        """
        video_submissions = Submission.query.filter(
            Submission.video_filename.isnot(None),
            Submission.video_filename != ""
        ).all()

        fixed_count = 0
        qr_count = 0

        for sub in video_submissions:
            if sub.video_drive_file_id:
                # 1. Tetapkan permission
                ok, _ = self.ensure_viewer_permission(sub.video_drive_file_id)
                if ok:
                    fixed_count += 1
                # 2. Jana QR
                qp, _ = self.generate_qr_code(sub.id, sub.video_drive_file_id, force=True)
                if qp:
                    qr_count += 1

        # Rekod ke SystemLog
        try:
            log = SystemLog(
                action="BATCH_FIX_VIDEO_PERMISSIONS_QR",
                status="success",
                details=f"Pembaikan automatik: {fixed_count} video disetkan ke Viewer, {qr_count} QR Code dijana."
            )
            db.session.add(log)
            db.session.commit()
        except Exception:
            db.session.rollback()

        # Pulangkan keputusan audit baharu
        return self.audit_all_videos()

video_qr_service = VideoQRService()
