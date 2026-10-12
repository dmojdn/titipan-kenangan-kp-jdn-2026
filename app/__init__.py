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

    # Bina jadual pangkalan data jika belum wujud
    with app.app_context():
        db.create_all()

    # Perintah CLI untuk menyemai data ujian sementara
    @app.cli.command("seed-demo")
    def seed_demo():
        """Menyemai contoh data sementara untuk ujian (teks, gambar & video)."""
        seed_data(app)

    return app

def seed_data(app):
    with app.app_context():
        if Submission.query.first():
            print("Data sudah wujud dalam pangkalan data.")
            return

        demo_submissions = [
            Submission(
                nama="Ahmad Farhan bin Zulkifli",
                bahagian="Bahagian Pembangunan Aplikasi Strategik",
                jawatan="Pegawai Teknologi Maklumat F48",
                ucapan="Setinggi-tinggi penghargaan dan terima kasih kepada YBhg. Dato' Sri Ketua Pengarah atas bimbingan berwawasan dalam memacu agenda pendigitalan negara. Semoga YBhg. Dato' Sri sentiasa diberkati kesihatan dan kejayaan.",
                image_sync_status="none",
                video_sync_status="none"
            ),
            Submission(
                nama="Siti Nurhaliza binti Mansor",
                bahagian="Bahagian Infrastruktur & Keselamatan Siber",
                jawatan="Penolong Pegawai Teknologi Maklumat FA32",
                ucapan="Terima kasih atas segala ilmu, teladan kepimpinan yang tegas namun penuh empati. Kenangan bersama Dato' Sri di JDN akan sentiasa mekar di ingatan kami semua.",
                image_filename="demo_kenangan_team.jpg",
                image_local_path=str(Config.UPLOAD_IMAGES_FOLDER / "demo_kenangan_team.jpg"),
                image_sync_status="pending",
                video_sync_status="none"
            ),
            Submission(
                nama="Ts. Megat Iskandar",
                bahagian="Bahagian Data Raya & Kecerdasan Buatan",
                jawatan="Ketua Penolong Pengarah F52",
                ucapan="Selamat maju jaya kepada KP JDN! Inovasi dan asas kecerdasan buatan sektor awam yang dirintis di bawah kepimpinan Dato' Sri menjadi legasi kebanggaan negara.",
                image_filename="demo_kp_amanat.jpg",
                image_local_path=str(Config.UPLOAD_IMAGES_FOLDER / "demo_kp_amanat.jpg"),
                image_sync_status="pending",
                video_filename="demo_ucapan_video.mp4",
                video_local_path=str(Config.UPLOAD_VIDEOS_FOLDER / "demo_ucapan_video.mp4"),
                video_sync_status="pending"
            )
        ]

        # Cipta fail demo dummy jika belum ada
        img_demo1 = Config.UPLOAD_IMAGES_FOLDER / "demo_kenangan_team.jpg"
        img_demo2 = Config.UPLOAD_IMAGES_FOLDER / "demo_kp_amanat.jpg"
        vid_demo = Config.UPLOAD_VIDEOS_FOLDER / "demo_ucapan_video.mp4"

        # Cipta gambar placeholder ringkas
        try:
            from PIL import Image, ImageDraw, ImageFont
            for p, title in [(img_demo1, "Kenangan Bersama Warga JDN"), (img_demo2, "Amanat Khas KP JDN")]:
                if not p.exists():
                    img = Image.new("RGB", (800, 600), color=(15, 23, 42))
                    d = ImageDraw.Draw(img)
                    d.rectangle([20, 20, 780, 580], outline=(212, 175, 55), width=3)
                    d.text((40, 280), f"Titipan Kenangan JDN: {title}", fill=(245, 245, 245))
                    img.save(p)
        except Exception:
            pass

        # Cipta fail video dummy jika belum ada
        if not vid_demo.exists():
            with open(vid_demo, "wb") as f:
                f.write(b"DEMO_MP4_HEADER_DATA_TITIPAN_KENANGAN_JDN_2026")

        for s in demo_submissions:
            db.session.add(s)

        db.session.commit()
        print("Data demo berjaya disemai (Teks, Gambar & Video).")
