import os
import json
import logging
from pathlib import Path
from datetime import datetime
try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError
    GOOGLE_PACKAGES_AVAILABLE = True
except ImportError:
    Credentials = None
    Request = None
    Flow = None
    build = None
    MediaFileUpload = None
    HttpError = Exception
    GOOGLE_PACKAGES_AVAILABLE = False

from app.config import Config
from app.models import db, DriveFolderCache, SystemLog

logger = logging.getLogger(__name__)

# Skop kebenaran yang diperlukan untuk Google Drive
SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid"
]

class DriveService:
    _instance = None

    def __init__(self):
        self.root_folder_id = Config.DRIVE_ROOT_FOLDER_ID
        self.subfolder_names = Config.DRIVE_SUBFOLDERS
        self.token_path = Path(Config.GOOGLE_TOKEN_FILE)
        self.credentials_path = Path(Config.GOOGLE_CREDENTIALS_FILE)

    def get_credentials(self):
        """Memuat kredensial pengguna daripada fail token.json jika wujud dan sah."""
        if not GOOGLE_PACKAGES_AVAILABLE:
            return None

        creds = None
        if self.token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)
            except Exception as e:
                logger.error(f"Ralat membaca token.json: {e}")
                return None

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(self.token_path, "w") as token_file:
                    token_file.write(creds.to_json())
            except Exception as e:
                logger.error(f"Gagal memperbaharui (refresh) token: {e}")
                return None

        return creds if creds and creds.valid else None

    def is_connected(self):
        """Menyemak status sambungan Google Drive."""
        creds = self.get_credentials()
        return creds is not None and creds.valid

    def get_service(self):
        """Membina objek perkhidmatan Google Drive API v3."""
        creds = self.get_credentials()
        if not creds:
            return None
        return build("drive", "v3", credentials=creds, cache_discovery=False)

    def get_user_email(self):
        """Mendapatkan alamat e-mel akaun yang telah disambungkan."""
        creds = self.get_credentials()
        if not creds:
            return None
        try:
            # Gunakan oauth2 service untuk dapatkan info pengguna
            user_info_service = build("oauth2", "v2", credentials=creds, cache_discovery=False)
            user_info = user_info_service.userinfo().get().execute()
            return user_info.get("email")
        except Exception:
            return Config.DRIVE_ACCOUNT

    def create_oauth_flow(self, redirect_uri=None, state=None):
        """Mewujudkan objek OAuth Flow menggunakan Client ID & Secret dari .env atau credentials.json."""
        redirect_uri = redirect_uri or Config.GOOGLE_REDIRECT_URI

        # Jika fail credentials.json wujud, gunakan itu
        if self.credentials_path.exists():
            flow = Flow.from_client_secrets_file(
                str(self.credentials_path),
                scopes=SCOPES,
                redirect_uri=redirect_uri,
                state=state
            )
            return flow

        # Jika tiada fail, gunakan pembolehubah .env
        client_id = Config.GOOGLE_CLIENT_ID
        client_secret = Config.GOOGLE_CLIENT_SECRET

        if not client_id or not client_secret:
            raise ValueError("GOOGLE_CLIENT_ID atau GOOGLE_CLIENT_SECRET belum dikonfigurasikan.")

        client_config = {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri]
            }
        }
        flow = Flow.from_client_config(
            client_config,
            scopes=SCOPES,
            redirect_uri=redirect_uri,
            state=state
        )
        return flow

    def save_credentials_from_flow(self, flow, authorization_response):
        """Menyimpan token yang diperoleh daripada aliran pengesahan OAuth."""
        flow.fetch_token(authorization_response=authorization_response)
        creds = flow.credentials
        with open(self.token_path, "w") as token_file:
            token_file.write(creds.to_json())
        return creds

    def ensure_root_folder_access(self):
        """Menyemak sama ada akaun mempunyai akses ke Root Folder ID."""
        service = self.get_service()
        if not service:
            return False, "Perkhidmatan Google Drive belum disambungkan."

        try:
            folder = service.files().get(
                fileId=self.root_folder_id,
                fields="id, name, mimeType, trashed",
                supportsAllDrives=True
            ).execute()

            if folder.get("trashed"):
                return False, f"Folder utama ({self.root_folder_id}) berada di dalam Tong Sampah (Trashed)."

            return True, f"Akses berjaya ke folder: {folder.get('name')}"
        except HttpError as e:
            return False, f"Ralat akses Drive API: {e.reason} (Status {e.resp.status})"
        except Exception as e:
            return False, f"Ralat: {str(e)}"

    def get_or_create_subfolders(self):
        """
        Menyemak 6 folder utama dalam Root Folder ID.
        Jika belum wujud, cipta HANYA folder yang tiada. Jangan cipta pendua.
        Mengembalikan kamus: {nama_folder: folder_id}
        """
        service = self.get_service()
        if not service:
            raise RuntimeError("Google Drive belum disambungkan.")

        # Semak cache pangkalan data terlebih dahulu
        folder_map = {}
        try:
            cached_rows = DriveFolderCache.query.all()
            for row in cached_rows:
                folder_map[row.folder_name] = row.folder_id
        except Exception:
            pass

        # Semak folder sebenar di Google Drive
        query = f"'{self.root_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = service.files().list(
            q=query,
            spaces="drive",
            fields="files(id, name)",
            pageSize=50,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()

        existing_folders = {f["name"]: f["id"] for f in results.get("files", [])}

        final_mapping = {}

        for required_name in self.subfolder_names:
            if required_name in existing_folders:
                folder_id = existing_folders[required_name]
                final_mapping[required_name] = folder_id
            else:
                # Folder tiada, cipta sekarang
                metadata = {
                    "name": required_name,
                    "mimeType": "application/vnd.google-apps.folder",
                    "parents": [self.root_folder_id]
                }
                new_folder = service.files().create(
                    body=metadata,
                    fields="id, name",
                    supportsAllDrives=True
                ).execute()
                folder_id = new_folder.get("id")
                final_mapping[required_name] = folder_id
                logger.info(f"Folder baru dicipta di Drive: {required_name} (ID: {folder_id})")

            # Kemas kini cache DB
            try:
                cache_entry = DriveFolderCache.query.filter_by(folder_name=required_name).first()
                if not cache_entry:
                    cache_entry = DriveFolderCache(folder_name=required_name, folder_id=folder_id)
                    db.session.add(cache_entry)
                else:
                    cache_entry.folder_id = folder_id
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.warning(f"Gagal mengemas kini DriveFolderCache: {e}")

        return final_mapping

    def upload_file(self, local_path, target_subfolder_name, custom_name=None, mime_type=None):
        """
        Memuat naik fail tempatan terus ke subfolder yang sepadan di Google Drive.
        Mengembalikan (file_id, web_view_link).
        """
        service = self.get_service()
        if not service:
            raise RuntimeError("Perkhidmatan Google Drive belum disambungkan.")

        local_path = Path(local_path)
        if not local_path.exists():
            raise FileNotFoundError(f"Fail tidak ditemui di lokasi: {local_path}")

        folder_mapping = self.get_or_create_subfolders()
        folder_id = folder_mapping.get(target_subfolder_name)
        if not folder_id:
            raise ValueError(f"Folder '{target_subfolder_name}' tidak ditemui di Google Drive.")

        file_name = custom_name or local_path.name
        file_metadata = {
            "name": file_name,
            "parents": [folder_id]
        }

        # Muat naik dengan sokongan resumable untuk fail besar
        media = MediaFileUpload(
            str(local_path),
            mimetype=mime_type,
            resumable=True
        )

        drive_file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, name, webViewLink, webContentLink",
            supportsAllDrives=True
        ).execute()

        file_id = drive_file.get("id")
        web_link = drive_file.get("webViewLink")

        logger.info(f"Fail berjaya dimuat naik ke Drive: {file_name} -> ID: {file_id}")
        return file_id, web_link

    def upload_backup_data(self, backup_filepath, filename_prefix="backup_ucapan_jdn"):
        """
        Membuat sandaran data JSON/SQL ke folder:
        1. 01 UCAPAN & DATA
        2. 06 BACKUP LENGKAP
        """
        service = self.get_service()
        if not service:
            return False, "Google Drive belum disambungkan"

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target_name = f"{filename_prefix}_{timestamp}.json"

        results = {}
        target_folders = ["01 UCAPAN & DATA", "06 BACKUP LENGKAP"]
        for folder_name in target_folders:
            try:
                fid, link = self.upload_file(
                    backup_filepath,
                    target_subfolder_name=folder_name,
                    custom_name=target_name,
                    mime_type="application/json"
                )
                results[folder_name] = {"id": fid, "link": link}
            except Exception as e:
                results[folder_name] = {"error": str(e)}

        return True, results

drive_service = DriveService()
