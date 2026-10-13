from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Submission(db.Model):
    __tablename__ = "submissions"

    id = db.Column(db.Integer, primary_key=True)
    nama = db.Column(db.String(150), nullable=False)
    bahagian = db.Column(db.String(150), nullable=False)
    jawatan = db.Column(db.String(150), nullable=True)
    ucapan = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    status = db.Column(db.String(20), default="active")  # active, archived, reviewed

    # Fail Gambar
    image_filename = db.Column(db.String(255), nullable=True)
    image_local_path = db.Column(db.String(255), nullable=True)
    image_drive_file_id = db.Column(db.String(100), nullable=True)
    image_drive_link = db.Column(db.String(500), nullable=True)
    image_sync_status = db.Column(db.String(30), default="none")  # none, pending, synced, failed

    # Fail Video
    video_filename = db.Column(db.String(255), nullable=True)
    video_local_path = db.Column(db.String(255), nullable=True)
    video_drive_file_id = db.Column(db.String(100), nullable=True)
    video_drive_link = db.Column(db.String(500), nullable=True)
    video_sync_status = db.Column(db.String(30), default="none")  # none, pending, synced, failed

    ip_address = db.Column(db.String(50), nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "nama": self.nama,
            "bahagian": self.bahagian,
            "jawatan": self.jawatan,
            "ucapan": self.ucapan,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "status": self.status,
            "image": {
                "filename": self.image_filename,
                "sync_status": self.image_sync_status,
                "drive_link": self.image_drive_link
            } if self.image_filename else None,
            "video": {
                "filename": self.video_filename,
                "sync_status": self.video_sync_status,
                "drive_link": self.video_drive_link
            } if self.video_filename else None
        }

class DriveFolderCache(db.Model):
    __tablename__ = "drive_folder_cache"

    id = db.Column(db.Integer, primary_key=True)
    folder_name = db.Column(db.String(100), unique=True, nullable=False)
    folder_id = db.Column(db.String(100), nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

class SystemLog(db.Model):
    __tablename__ = "system_logs"

    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default="info")  # info, success, warning, error
    details = db.Column(db.Text, nullable=True)
    drive_file_id = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
