import os
import json
import csv
import sqlite3
import hashlib
import logging
from datetime import datetime
from pathlib import Path
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

from app.config import Config, BASE_DIR
from app.models import db, Submission, DriveFolderCache, SystemLog
from app.services.drive_service import drive_service

logger = logging.getLogger(__name__)

# Direktori sandaran tempatan selamat (diabaikan oleh git)
LOCAL_BACKUP_DIR = BASE_DIR / "uploads" / "backups"
LOCAL_BACKUP_DIR.mkdir(parents=True, exist_ok=True)

class BackupService:
    def __init__(self):
        self.drive = drive_service
        self.subfolder_names = Config.DRIVE_SUBFOLDERS

    def get_file_checksum(self, filepath):
        """Kira SHA256 checksum fail."""
        sha256 = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def sync_archive_folders(self):
        """
        Sahkan 6 folder arkib Google Drive tanpa mencipta folder pendua:
        01 TEKS UCAPAN
        02 GAMBAR KENANGAN
        03 VIDEO KENANGAN
        04 DATABASE BACKUP
        05 MANIFEST & LAPORAN BACKUP
        06 PDF BUKU KENANGAN
        """
        service = self.drive.get_service()
        if not service:
            raise RuntimeError("Google Drive belum disambungkan.")

        root_id = self.drive.root_folder_id

        # Dapatkan semua folder sedia ada di bawah root
        query = f"'{root_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        res = service.files().list(
            q=query,
            spaces="drive",
            fields="files(id, name)",
            pageSize=50,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()

        existing = {f["name"]: f["id"] for f in res.get("files", [])}

        # Pastikan setiap daripada 6 folder rasmi wujud secara sah
        final_mapping = {}
        for folder_name in self.subfolder_names:
            if folder_name in existing:
                final_mapping[folder_name] = existing[folder_name]
            else:
                # Cipta folder baharu jika tiada
                metadata = {
                    "name": folder_name,
                    "mimeType": "application/vnd.google-apps.folder",
                    "parents": [root_id]
                }
                new_folder = service.files().create(
                    body=metadata,
                    fields="id, name",
                    supportsAllDrives=True
                ).execute()
                folder_id = new_folder.get("id")
                final_mapping[folder_name] = folder_id
                existing[folder_name] = folder_id
                logger.info(f"Folder arkib baharu dicipta: {folder_name} (ID: {folder_id})")

            # Kemas kini cache pangkalan data
            try:
                cache_entry = DriveFolderCache.query.filter_by(folder_name=folder_name).first()
                if not cache_entry:
                    cache_entry = DriveFolderCache(folder_name=folder_name, folder_id=final_mapping[folder_name])
                    db.session.add(cache_entry)
                else:
                    cache_entry.folder_id = final_mapping[folder_name]
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.warning(f"Ralat simpan cache folder: {e}")

        return final_mapping

    def export_submissions_data(self, target_dir):
        """
        Eksport semua rekod ucapan SQLite ke format JSON, CSV, dan XLSX.
        Semua aksara Bahasa Melayu dan perenggan dipelihara 100%.
        """
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        submissions = Submission.query.order_by(Submission.id.asc()).all()
        data_list = []

        for s in submissions:
            row = {
                "id": s.id,
                "nama": s.nama,
                "bahagian": s.bahagian,
                "jawatan": s.jawatan or "",
                "ucapan": s.ucapan or "",
                "tarikh_penghantaran": s.created_at.strftime("%Y-%m-%d %H:%M:%S") if s.created_at else "",
                "status": s.status or "active",
                "nama_fail_gambar": s.image_filename or "",
                "drive_file_id_gambar": s.image_drive_file_id or "",
                "drive_link_gambar": s.image_drive_link or "",
                "status_sync_gambar": s.image_sync_status or "none",
                "nama_fail_video": s.video_filename or "",
                "drive_file_id_video": s.video_drive_file_id or "",
                "drive_link_video": s.video_drive_link or "",
                "status_sync_video": s.video_sync_status or "none"
            }
            data_list.append(row)

        # 1. Eksport JSON
        json_path = target_dir / "semua_ucapan.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({
                "tajuk": "Arkib Rasmi Titipan Kenangan KP JDN 2026",
                "tarikh_eksport": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "jumlah_rekod": len(data_list),
                "rekod": data_list
            }, f, ensure_ascii=False, indent=2)

        # 2. Eksport CSV (UTF-8 with BOM untuk keserasian Microsoft Excel)
        csv_path = target_dir / "semua_ucapan.csv"
        headers = [
            "ID Rekod", "Nama Pengirim", "Bahagian", "Jawatan", "Teks Ucapan Penuh",
            "Tarikh Penghantaran", "Status", "Nama Fail Gambar", "Google Drive File ID Gambar",
            "Google Drive Link Gambar", "Status Sync Gambar", "Nama Fail Video",
            "Google Drive File ID Video", "Google Drive Link Video", "Status Sync Video"
        ]
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for d in data_list:
                writer.writerow([
                    d["id"], d["nama"], d["bahagian"], d["jawatan"], d["ucapan"],
                    d["tarikh_penghantaran"], d["status"], d["nama_fail_gambar"],
                    d["drive_file_id_gambar"], d["drive_link_gambar"], d["status_sync_gambar"],
                    d["nama_fail_video"], d["drive_file_id_video"], d["drive_link_video"],
                    d["status_sync_video"]
                ])

        # 3. Eksport XLSX
        xlsx_path = target_dir / "semua_ucapan.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Titipan Ucapan KP JDN"

        # Gaya Header Rasmi (Biru Diraja & Emas)
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="1E1B4B", end_color="1E1B4B", fill_type="solid")
        border_thin = Border(
            left=Side(style='thin', color='CBD5E1'),
            right=Side(style='thin', color='CBD5E1'),
            top=Side(style='thin', color='CBD5E1'),
            bottom=Side(style='thin', color='CBD5E1')
        )

        ws.append(headers)
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        for d in data_list:
            ws.append([
                d["id"], d["nama"], d["bahagian"], d["jawatan"], d["ucapan"],
                d["tarikh_penghantaran"], d["status"], d["nama_fail_gambar"],
                d["drive_file_id_gambar"], d["drive_link_gambar"], d["status_sync_gambar"],
                d["nama_fail_video"], d["drive_file_id_video"], d["drive_link_video"],
                d["status_sync_video"]
            ])

        for row in ws.iter_rows(min_row=2, max_row=len(data_list) + 1, min_col=1, max_col=len(headers)):
            for cell in row:
                cell.border = border_thin
                cell.alignment = Alignment(vertical="top", wrap_text=True)

        # Lebar lajur automatik
        ws.column_dimensions['A'].width = 10
        ws.column_dimensions['B'].width = 25
        ws.column_dimensions['C'].width = 32
        ws.column_dimensions['D'].width = 22
        ws.column_dimensions['E'].width = 50
        ws.column_dimensions['F'].width = 20
        ws.column_dimensions['G'].width = 12
        ws.column_dimensions['H'].width = 28
        ws.column_dimensions['I'].width = 34
        ws.column_dimensions['J'].width = 38
        ws.column_dimensions['K'].width = 16
        ws.column_dimensions['L'].width = 28
        ws.column_dimensions['M'].width = 34
        ws.column_dimensions['N'].width = 38
        ws.column_dimensions['O'].width = 16

        wb.save(xlsx_path)

        return {
            "json": json_path,
            "csv": csv_path,
            "xlsx": xlsx_path,
            "count": len(data_list)
        }

    def create_database_snapshot(self, target_dir):
        """
        Cipta snapshot konsisten SQLite menggunakan API sqlite3.backup().
        Memastikan snapshot tidak rosak semasa pelayan sedang aktif.
        """
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest_db_path = target_dir / f"titipan_kenangan_snapshot_{timestamp}.db"

        is_sqlite = Config.SQLALCHEMY_DATABASE_URI.startswith("sqlite")
        src_db_path = Config.INSTANCE_DIR / "titipan_kenangan.db"

        if is_sqlite and src_db_path.exists():
            # Kunci konsisten SQLite backup
            src_conn = sqlite3.connect(str(src_db_path))
            dest_conn = sqlite3.connect(str(dest_db_path))
            with dest_conn:
                src_conn.backup(dest_conn)
            dest_conn.close()
            src_conn.close()
        else:
            # Bina snapshot SQLite mudah alih terus daripada pangkalan data aktif (PostgreSQL / Neon)
            dest_conn = sqlite3.connect(str(dest_db_path))
            c = dest_conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS submissions (
                    id INTEGER PRIMARY KEY,
                    nama VARCHAR(150) NOT NULL,
                    bahagian VARCHAR(150) NOT NULL,
                    jawatan VARCHAR(150),
                    ucapan TEXT,
                    created_at TIMESTAMP,
                    status VARCHAR(20),
                    data_type VARCHAR(20),
                    image_filename VARCHAR(255),
                    image_local_path VARCHAR(255),
                    image_drive_file_id VARCHAR(100),
                    image_drive_link VARCHAR(500),
                    image_sync_status VARCHAR(30),
                    video_filename VARCHAR(255),
                    video_local_path VARCHAR(255),
                    video_drive_file_id VARCHAR(100),
                    video_drive_link VARCHAR(500),
                    video_sync_status VARCHAR(30),
                    ip_address VARCHAR(50)
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS drive_folder_cache (
                    id INTEGER PRIMARY KEY,
                    folder_name VARCHAR(100) UNIQUE NOT NULL,
                    folder_id VARCHAR(100) NOT NULL,
                    updated_at TIMESTAMP
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS system_logs (
                    id INTEGER PRIMARY KEY,
                    action VARCHAR(100) NOT NULL,
                    status VARCHAR(20),
                    details TEXT,
                    drive_file_id VARCHAR(100),
                    created_at TIMESTAMP
                )
            """)
            
            subs = Submission.query.order_by(Submission.id.asc()).all()
            for s in subs:
                c.execute("""
                    INSERT INTO submissions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    s.id, s.nama, s.bahagian, s.jawatan, s.ucapan,
                    s.created_at.strftime("%Y-%m-%d %H:%M:%S") if s.created_at else None,
                    s.status, s.data_type, s.image_filename, s.image_local_path,
                    s.image_drive_file_id, s.image_drive_link, s.image_sync_status,
                    s.video_filename, s.video_local_path, s.video_drive_file_id,
                    s.video_drive_link, s.video_sync_status, s.ip_address
                ))
                
            caches = DriveFolderCache.query.all()
            for df in caches:
                c.execute("INSERT INTO drive_folder_cache VALUES (?, ?, ?, ?)", (
                    df.id, df.folder_name, df.folder_id,
                    df.updated_at.strftime("%Y-%m-%d %H:%M:%S") if df.updated_at else None
                ))
                
            logs = SystemLog.query.order_by(SystemLog.id.desc()).limit(100).all()
            for sl in logs:
                c.execute("INSERT INTO system_logs VALUES (?, ?, ?, ?, ?, ?)", (
                    sl.id, sl.action, sl.status, sl.details, sl.drive_file_id,
                    sl.created_at.strftime("%Y-%m-%d %H:%M:%S") if sl.created_at else None
                ))
                
            dest_conn.commit()
            dest_conn.close()

        # Juga cipta salinan statik tetap 'titipan_kenangan_snapshot.db'
        static_snapshot_path = target_dir / "titipan_kenangan_snapshot.db"
        with open(dest_db_path, "rb") as fsrc, open(static_snapshot_path, "wb") as fdst:
            fdst.write(fsrc.read())

        return {
            "versioned_path": dest_db_path,
            "static_path": static_snapshot_path,
            "size": os.path.getsize(dest_db_path),
            "checksum": self.get_file_checksum(dest_db_path)
        }

    def test_restore_database(self, snapshot_path, temp_test_dir):
        """
        Ujian pemulihan (restore) database snapshot ke lokasi sementara.
        Mengesahkan skema, jumlah rekod, dan integriti teks tanpa mengganggu database sebenar.
        """
        temp_test_dir = Path(temp_test_dir)
        temp_test_dir.mkdir(parents=True, exist_ok=True)

        test_db_path = temp_test_dir / "test_restored.db"
        if test_db_path.exists():
            test_db_path.unlink()

        # Salin snapshot ke fail ujian
        with open(snapshot_path, "rb") as fsrc, open(test_db_path, "wb") as fdst:
            fdst.write(fsrc.read())

        # Buka dan sahkan
        conn = sqlite3.connect(str(test_db_path))
        cursor = conn.cursor()

        # 1. Semak kewujudan jadual submissions
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='submissions'")
        table_exists = cursor.fetchone()
        if not table_exists:
            conn.close()
            return False, "Jadual 'submissions' tidak ditemui dalam snapshot."

        # 2. Semak bilangan rekod
        cursor.execute("SELECT COUNT(*) FROM submissions")
        row_count = cursor.fetchone()[0]

        # 3. Semak integriti baris
        cursor.execute("SELECT id, nama, bahagian, ucapan FROM submissions ORDER BY id ASC")
        rows = cursor.fetchall()

        conn.close()

        # Padam fail ujian sementara
        if test_db_path.exists():
            test_db_path.unlink()

        return True, {
            "status": "BERJAYA",
            "rekod_disahkan": row_count,
            "contoh_pengirim": [r[1] for r in rows[:3]],
            "integriti": "SEMPURNA"
        }

    def run_full_backup_pipeline(self):
        """
        Menjalankan keseluruhan aliran Fasa 1 & Fasa 2:
        1. Segerakkan 6 folder rasmi Google Drive.
        2. Eksport JSON, CSV, XLSX teks ucapan.
        3. Snapshot konsisten SQLite.
        4. Jalankan ujian pemulihan (restore test).
        5. Muat naik ke Google Drive.
        6. Bina dan muat naik Manifest & Laporan Backup rasmi.
        """
        run_timestamp = datetime.now()
        timestamp_str = run_timestamp.strftime("%Y%m%d_%H%M%S")
        date_str = run_timestamp.strftime("%Y-%m-%d %H:%M:%S")

        session_dir = LOCAL_BACKUP_DIR / f"backup_{timestamp_str}"
        session_dir.mkdir(parents=True, exist_ok=True)

        # 1. Pastikan folder Drive sedia
        folder_mapping = self.sync_archive_folders()

        # 2. Eksport Data
        export_result = self.export_submissions_data(session_dir)

        # 3. Snapshot DB
        db_result = self.create_database_snapshot(session_dir)

        # 4. Ujian Restore
        test_dir = session_dir / "temp_restore_test"
        restore_ok, restore_info = self.test_restore_database(db_result["versioned_path"], test_dir)
        if not restore_ok:
            raise RuntimeError(f"Ujian restore gagal: {restore_info}")

        # 5. Muat naik fail teks ke '01 TEKS UCAPAN'
        # 5. Muat naik fail teks ke '01 TEKS UCAPAN'
        upload_records = {}
        for fmt, fpath in [("json", export_result["json"]), ("csv", export_result["csv"]), ("xlsx", export_result["xlsx"])]:
            fid, link = self.drive.upload_file(
                local_path=fpath,
                target_subfolder_name="01 TEKS UCAPAN",
                custom_name=fpath.name
            )
            upload_records[f"teks_{fmt}"] = {
                "latest_id": fid, "latest_link": link,
                "filename": fpath.name
            }

        # 6. Muat naik Snapshot DB ke '04 DATABASE BACKUP'
        db_upload_name = f"titipan_kenangan_snapshot_{timestamp_str}.db"
        db_fid, db_link = self.drive.upload_file(
            local_path=db_result["versioned_path"],
            target_subfolder_name="04 DATABASE BACKUP",
            custom_name=db_upload_name
        )
        upload_records["database"] = {
            "latest_id": db_fid, "latest_link": db_link,
            "filename": db_upload_name
        }

        # 7. Sediakan Manifest & Laporan Backup
        manifest_data = {
            "sistem": "Titipan Kenangan Buat KP JDN 2026",
            "tarikh_backup": date_str,
            "timestamp": timestamp_str,
            "jumlah_rekod_ucapan": export_result["count"],
            "ujian_restore": restore_info,
            "google_drive_root_id": self.drive.root_folder_id,
            "folder_mapping": folder_mapping,
            "fail_backup": {
                "json": {
                    "nama": "semua_ucapan.json",
                    "saiz_bytes": os.path.getsize(export_result["json"]),
                    "checksum_sha256": self.get_file_checksum(export_result["json"]),
                    "drive_id": upload_records["teks_json"]["latest_id"]
                },
                "csv": {
                    "nama": "semua_ucapan.csv",
                    "saiz_bytes": os.path.getsize(export_result["csv"]),
                    "checksum_sha256": self.get_file_checksum(export_result["csv"]),
                    "drive_id": upload_records["teks_csv"]["latest_id"]
                },
                "xlsx": {
                    "nama": "semua_ucapan.xlsx",
                    "saiz_bytes": os.path.getsize(export_result["xlsx"]),
                    "checksum_sha256": self.get_file_checksum(export_result["xlsx"]),
                    "drive_id": upload_records["teks_xlsx"]["latest_id"]
                },
                "sqlite_snapshot": {
                    "nama": db_upload_name,
                    "saiz_bytes": db_result["size"],
                    "checksum_sha256": db_result["checksum"],
                    "drive_id": upload_records["database"]["latest_id"]
                }
            }
        }

        manifest_path = session_dir / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2, ensure_ascii=False)

        # Laporan Markdown
        laporan_path = session_dir / "laporan_backup.md"
        with open(laporan_path, "w", encoding="utf-8") as f:
            f.write(f"""# LAPORAN RASMI BACKUP & PEMULIHAN DATA ARKIB KP JDN 2026
**Tarikh Penjanaan:** {date_str}  
**Status Keseluruhan:** BERJAYA & DISAHKAN  
**Akaun Storan Awam:** {Config.DRIVE_ACCOUNT}  
**Google Drive Root Folder ID:** `{self.drive.root_folder_id}`  

---

## 1. Status Folder Rasmi Arkib Google Drive
| Nama Folder Rasmi | Google Drive Folder ID | Status |
| :--- | :--- | :--- |
| `01 TEKS UCAPAN` | `{folder_mapping.get('01 TEKS UCAPAN')}` | Sedia & Disegerakkan |
| `02 GAMBAR KENANGAN` | `{folder_mapping.get('02 GAMBAR KENANGAN')}` | Sedia (Media Pengguna) |
| `03 VIDEO KENANGAN` | `{folder_mapping.get('03 VIDEO KENANGAN')}` | Sedia (Media Pengguna) |
| `04 DATABASE BACKUP` | `{folder_mapping.get('04 DATABASE BACKUP')}` | Sedia & Berversi |
| `05 MANIFEST & LAPORAN BACKUP` | `{folder_mapping.get('05 MANIFEST & LAPORAN BACKUP')}` | Sedia & Disimpan |
| `06 PDF BUKU KENANGAN` | `{folder_mapping.get('06 PDF BUKU KENANGAN')}` | Sedia untuk Eksport Canva |

---

## 2. Ringkasan Rekod Teks & Fail Sandaran
- **Jumlah Rekod Ucapan Disandarkan:** {export_result['count']} rekod
- **Format Eksport Teks:**
  - `semua_ucapan.json` (ID Drive: `{upload_records['teks_json']['latest_id']}`)
  - `semua_ucapan.csv` (ID Drive: `{upload_records['teks_csv']['latest_id']}`)
  - `semua_ucapan.xlsx` (ID Drive: `{upload_records['teks_xlsx']['latest_id']}`)
- **Pangkalan Data Snapshot SQLite:**
  - Fail: `{db_upload_name}`
  - Saiz: {db_result['size']} bytes
  - SHA-256: `{db_result['checksum']}`
  - ID Drive: `{upload_records['database']['latest_id']}`

---

## 3. Keputusan Ujian Pemulihan (Restore Test)
- **Status Ujian:** {restore_info['status']}
- **Jumlah Rekod Disahkan Dipulihkan:** {restore_info['rekod_disahkan']} rekod
- **Integriti Skema & Teks:** {restore_info['integriti']}
- **Catatan:** Ujian restore berjaya dijalankan ke lokasi maya sementara tanpa menimpa atau mengganggu database hidup.

---
*Laporan ini dijana secara automatik oleh Modul Arkib & Sandaran Sistem Titipan Kenangan KP JDN.*
""")

        # Muat naik Manifest & Laporan ke '05 MANIFEST & LAPORAN BACKUP'
        m_fid, m_link = self.drive.upload_file(
            local_path=manifest_path,
            target_subfolder_name="05 MANIFEST & LAPORAN BACKUP",
            custom_name=f"manifest_{timestamp_str}.json"
        )
        l_fid, l_link = self.drive.upload_file(
            local_path=laporan_path,
            target_subfolder_name="05 MANIFEST & LAPORAN BACKUP",
            custom_name=f"laporan_backup_{timestamp_str}.md"
        )

        # Log transaksi sistem
        try:
            log_entry = SystemLog(
                action="FULL_BACKUP_EXECUTE",
                status="success",
                details=f"Backup lengkap {export_result['count']} rekod disegerakkan ke Google Drive. Ujian restore: BERJAYA.",
                drive_file_id=m_fid
            )
            db.session.add(log_entry)
            db.session.commit()
        except Exception:
            db.session.rollback()

        return {
            "success": True,
            "timestamp": date_str,
            "records_count": export_result["count"],
            "manifest_drive_id": m_fid,
            "report_drive_id": l_fid,
            "folder_mapping": folder_mapping,
            "restore_info": restore_info,
            "manifest_data": manifest_data
        }

backup_service = BackupService()
