import os
from pathlib import Path
from dotenv import load_dotenv

# Muat fail persekitaran .env jika wujud
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "titipan_kenangan_kp_jdn_secret_2026")
    DEBUG = os.getenv("FLASK_DEBUG", "True").lower() in ("true", "1", "t")

    # Kata laluan ringkas Dashboard Pentadbir
    ADMIN_PASSWORD = (os.getenv("ADMIN_PASSWORD") or "DMOad_min2026").strip()

    # Pangkalan Data (Menyokong Neon PostgreSQL & SQLite Tempatan)
    INSTANCE_DIR = BASE_DIR / "instance"
    raw_db_url = os.getenv("DATABASE_URL", "").strip()
    if raw_db_url:
        if raw_db_url.startswith("postgres://"):
            raw_db_url = raw_db_url.replace("postgres://", "postgresql+psycopg2://", 1)
        elif raw_db_url.startswith("postgresql://") and not raw_db_url.startswith("postgresql+"):
            raw_db_url = raw_db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
        SQLALCHEMY_DATABASE_URI = raw_db_url
        SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_pre_ping": True,
            "pool_recycle": 300,
            "pool_timeout": 30
        }
    else:
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{INSTANCE_DIR / 'titipan_kenangan.db'}"
        SQLALCHEMY_ENGINE_OPTIONS = {}
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Direktori Muat Naik Tempatan
    UPLOAD_FOLDER = BASE_DIR / "uploads"
    UPLOAD_IMAGES_FOLDER = UPLOAD_FOLDER / "images"
    UPLOAD_VIDEOS_FOLDER = UPLOAD_FOLDER / "videos"
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # Had 100MB bagi membolehkan video pendek

    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "heic"}
    ALLOWED_VIDEO_EXTENSIONS = {"mp4", "mov", "avi", "webm", "m4v"}

    # Integrasi Google Drive
    DRIVE_ACCOUNT = "dmojdn@gmail.com"
    DRIVE_ROOT_FOLDER_ID = (os.getenv("GOOGLE_DRIVE_ROOT_FOLDER_ID") or "1HIEuEkoEoiHHcEuqh-zj7AE-aFzepXUH").strip()
    GOOGLE_DRIVE_ROOT_FOLDER_ID = DRIVE_ROOT_FOLDER_ID
    GOOGLE_CLIENT_ID = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
    GOOGLE_CLIENT_SECRET = (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()
    GOOGLE_REDIRECT_URI = (os.getenv("GOOGLE_REDIRECT_URI") or "http://127.0.0.1:5000/admin/oauth/callback").strip()
    GOOGLE_TOKEN_FILE = BASE_DIR / (os.getenv("GOOGLE_TOKEN_FILE") or "token.json").strip()
    GOOGLE_CREDENTIALS_FILE = BASE_DIR / "credentials.json"

    # 6 Folder Utama Rasmi Arkib di Google Drive
    DRIVE_SUBFOLDERS = [
        "01 TEKS UCAPAN",
        "02 GAMBAR KENANGAN",
        "03 VIDEO KENANGAN",
        "04 DATABASE BACKUP",
        "05 MANIFEST & LAPORAN BACKUP",
        "06 PDF BUKU KENANGAN"
    ]
