import os
from pathlib import Path
from flask import Flask
from app.config import Config
from app.models import db, Submission, SystemLog

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Pastikan direktori penting sentiasa wujud
    for folder in [
        Config.INSTANCE_DIR,
        Config.UPLOAD_FOLDER,
        Config.UPLOAD_IMAGES_FOLDER,
        Config.UPLOAD_VIDEOS_FOLDER,
        Config.UPLOAD_FOLDER / "backups"
    ]:
        folder.mkdir(parents=True, exist_ok=True)

    # Inisialisasi Database
    db.init_app(app)

    # Daftarkan Blueprints
    from app.routes.public import public_bp
    from app.routes.admin import admin_bp
    from app.routes.auth_drive import auth_drive_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(auth_drive_bp)

    # Bina jadual pangkalan data jika belum wujud secara selamat (non-destructive)
    with app.app_context():
        try:
            db.create_all()
            app.logger.info("Pangkalan data sedia dan skema disahkan.")
        except Exception as db_init_err:
            app.logger.error(f"Ralat inisialisasi pangkalan data: {db_init_err}")

    return app
