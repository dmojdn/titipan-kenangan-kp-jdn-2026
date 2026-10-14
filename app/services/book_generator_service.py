import os
import math
import subprocess
import logging
from datetime import datetime
from pathlib import Path
from flask import render_template, current_app
from PIL import Image

from app.config import Config, BASE_DIR
from app.models import db, Submission
from app.services.drive_service import drive_service
from app.services.video_qr_service import video_qr_service

logger = logging.getLogger(__name__)

PDF_OUTPUT_DIR = BASE_DIR / "uploads" / "pdf_buku"
PDF_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

class BookGeneratorService:
    def __init__(self):
        self.edge_path = self._find_browser_path()

    def _find_browser_path(self):
        candidates = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
        ]
        for p in candidates:
            if os.path.exists(p):
                return p
        return None

    def get_submissions(self, source="auto"):
        """
        Dapatkan senarai submissions mengikut sumber data:
        - 'official': Rekod rasmi sahaja (data_type='official')
        - 'test': Rekod dummy sahaja (data_type='test')
        - 'all': Semua rekod
        - 'auto': Jika data rasmi wujud guna rasmi, jika tiada guna test untuk pengujian
        """
        if source == "official":
            return Submission.query.filter_by(status="active", data_type="official").order_by(Submission.created_at.asc()).all(), "official"
        elif source == "test":
            return Submission.query.filter_by(data_type="test").order_by(Submission.id.asc()).all(), "test"
        elif source == "all":
            return Submission.query.filter_by(status="active").order_by(Submission.created_at.asc()).all(), "all"
        else: # auto
            official = Submission.query.filter_by(status="active", data_type="official").order_by(Submission.created_at.asc()).all()
            if official and len(official) > 0:
                return official, "official"
            # Fallback ke dummy data untuk tujuan semakan layout/design pentadbir
            test_data = Submission.query.filter_by(data_type="test").order_by(Submission.id.asc()).all()
            return test_data, "test"

    def paginate_ucapan(self, submissions):
        """
        Algoritma Pengukuran Ruang Dinamik Bab Titipan Ucapan A4:
        Mengukur berat teks setiap warkah (panjang aksara + baris + perenggan).
        Muatan 1 halaman A4 ~ 100 mata.
        - Ucapan pendek (<=140 aksara): 16 mata (muat sehingga 6-8 per halaman)
        - Ucapan sederhana (141-300 aksara): 28 mata (muat 4-6 per halaman)
        - Ucapan panjang (301-650 aksara): 50 mata (muat 2-3 per halaman)
        - Ucapan sangat panjang (>650 aksara): 100 mata (1 halaman khas tersendiri)
        Memastikan:
        1. Tiada teks dipotong atau diringkaskan.
        2. Nama pengirim tidak berpisah daripada teks.
        3. Bilangan halaman dijana secara dinamik.
        """
        text_subs = [s for s in submissions if s.ucapan and s.ucapan.strip()]
        
        pages = []
        current_page = []
        current_weight = 0

        for s in text_subs:
            text = s.ucapan.strip()
            char_count = len(text)
            newlines = text.count('\n')

            # Tentukan berat warkah
            if char_count <= 140 and newlines <= 1:
                weight = 15
                card_type = "short"
            elif char_count <= 300 and newlines <= 3:
                weight = 25
                card_type = "medium"
            elif char_count <= 650:
                weight = 48
                card_type = "long"
            else:
                weight = 100
                card_type = "very-long"

            # Jika warkah sangat panjang dan halaman semasa sudah ada warkah lain, mulakan halaman baru
            if current_page and (current_weight + weight > 100):
                pages.append(current_page)
                current_page = []
                current_weight = 0

            current_page.append({
                "submission": s,
                "text": text,
                "char_count": char_count,
                "card_type": card_type,
                "weight": weight
            })
            current_weight += weight

        if current_page:
            pages.append(current_page)

        return pages

    def paginate_gambar(self, submissions):
        """
        Susun atur fleksibel Bab Galeri Gambar A4:
        Menganalisis orientasi gambar sebenar (Landscape vs Portrait) menggunakan PIL.
        Menyusun imej ke dalam layout majalah seimbang (4 hingga 6 imej per halaman).
        Kekalkan nisbah aspek asal 100% tanpa herotan atau pemotongan wajah.
        """
        img_subs = [s for s in submissions if s.image_filename]
        
        items = []
        for s in img_subs:
            img_path = Config.UPLOAD_IMAGES_FOLDER / s.image_filename
            orientation = "landscape"
            width, height = 1200, 800
            
            if img_path.exists():
                try:
                    with Image.open(img_path) as im:
                        width, height = im.size
                        orientation = "portrait" if height > width * 1.15 else "landscape"
                except Exception as e:
                    logger.warning(f"Gagal baca dimensi gambar {s.image_filename}: {e}")

            img_uri = img_path.resolve().as_uri() if img_path.exists() else ""
            items.append({
                "submission": s,
                "filename": s.image_filename,
                "filepath": str(img_path),
                "img_src": img_uri,
                "orientation": orientation,
                "width": width,
                "height": height,
                "caption_name": s.nama,
                "caption_dept": s.bahagian if s.bahagian and s.bahagian != '-' else 'Jabatan Digital Negara'
            })

        # Kumpulkan ke dalam halaman (Maksimum 6 gambar per halaman untuk visual luas & premium)
        pages = []
        items_per_page = 6
        for i in range(0, len(items), items_per_page):
            chunk = items[i:i + items_per_page]
            pages.append(chunk)

        return pages

    def paginate_video(self, submissions):
        """
        Susun atur Bab Galeri Video A4:
        Setiap halaman memuatkan sehingga 4 video (Grid 2x2 yang seimbang).
        Mengandungi:
        - Thumbnail video
        - Nama & Bahagian pengirim
        - Kod QR Google Drive yang disahkan (resolusi tinggi)
        - Pautan tontonan rasmi
        - Teks panduan imbasan
        """
        vid_subs = [s for s in submissions if s.video_filename]
        
        items = []
        for s in vid_subs:
            file_id = s.video_drive_file_id
            view_url = video_qr_service.get_video_view_url(file_id) if file_id else ""
            
            # Pastikan QR code sedia
            qr_path = ""
            if file_id:
                qp, _ = video_qr_service.generate_qr_code(s.id, file_id)
                qr_path = qp or ""

            # Semak jika ada gambar thumbnail atau guna video frame/placeholder
            thumb_path = ""
            if s.image_filename:
                thumb_path = str(Config.UPLOAD_IMAGES_FOLDER / s.image_filename)

            qr_uri = Path(qr_path).resolve().as_uri() if (qr_path and Path(qr_path).exists()) else ""
            thumb_uri = Path(thumb_path).resolve().as_uri() if (thumb_path and Path(thumb_path).exists()) else ""

            items.append({
                "submission": s,
                "filename": s.video_filename,
                "file_id": file_id,
                "view_url": view_url,
                "qr_path": qr_path,
                "qr_filename": Path(qr_path).name if qr_path else "",
                "qr_src": qr_uri,
                "thumb_path": thumb_path,
                "thumb_src": thumb_uri,
                "caption_name": s.nama,
                "caption_dept": s.bahagian if s.bahagian and s.bahagian != '-' else 'Jabatan Digital Negara'
            })

        # Kumpulkan 4 video setiap halaman A4
        pages = []
        items_per_page = 4
        for i in range(0, len(items), items_per_page):
            chunk = items[i:i + items_per_page]
            pages.append(chunk)

        return pages

    def render_chapter_html(self, chapter, source="auto"):
        """
        Jana kandungan HTML lengkap bagi sesuatu bab sebelum dieksport ke PDF.
        """
        from flask import has_request_context

        def _do_render():
            submissions, actual_source = self.get_submissions(source)
            
            if chapter == "ucapan":
                pages = self.paginate_ucapan(submissions)
                return render_template(
                    "admin/buku_kenangan/bab_ucapan.html",
                    pages=pages,
                    total_pages=len(pages),
                    data_source=actual_source,
                    timestamp=datetime.now().strftime("%d %B %Y")
                )
            elif chapter == "gambar":
                pages = self.paginate_gambar(submissions)
                return render_template(
                    "admin/buku_kenangan/bab_gambar.html",
                    pages=pages,
                    total_pages=len(pages),
                    data_source=actual_source,
                    timestamp=datetime.now().strftime("%d %B %Y")
                )
            elif chapter == "video":
                pages = self.paginate_video(submissions)
                return render_template(
                    "admin/buku_kenangan/bab_video.html",
                    pages=pages,
                    total_pages=len(pages),
                    data_source=actual_source,
                    timestamp=datetime.now().strftime("%d %B %Y")
                )
            else: # gabungan lengkap
                pages_ucapan = self.paginate_ucapan(submissions)
                pages_gambar = self.paginate_gambar(submissions)
                pages_video = self.paginate_video(submissions)
                return render_template(
                    "admin/buku_kenangan/buku_lengkap.html",
                    pages_ucapan=pages_ucapan,
                    pages_gambar=pages_gambar,
                    pages_video=pages_video,
                    total_pages=len(pages_ucapan) + len(pages_gambar) + len(pages_video),
                    data_source=actual_source,
                    timestamp=datetime.now().strftime("%d %B %Y")
                )

        if not has_request_context():
            with current_app.test_request_context():
                return _do_render()
        return _do_render()

    def generate_pdf(self, chapter, source="auto"):
        """
        Eksport bab terpilih ke format PDF A4 Portrait melalui Microsoft Edge Headless.
        Menghasilkan PDF berkualiti tinggi yang serasi untuk diimport ke Canva.
        """
        if not self.edge_path:
            raise RuntimeError("Pelayar Microsoft Edge / Chromium tidak ditemui untuk penjanaan PDF.")

        html_content = self.render_chapter_html(chapter, source)

        filename_map = {
            "ucapan": "01_Titipan_Ucapan_KP_JDN.pdf",
            "gambar": "02_Galeri_Gambar_KP_JDN.pdf",
            "video": "03_Galeri_Video_KP_JDN.pdf",
            "lengkap": "04_Kandungan_Kenangan_Lengkap.pdf"
        }
        pdf_filename = filename_map.get(chapter, "Buku_Kenangan_KP_JDN.pdf")
        output_pdf = PDF_OUTPUT_DIR / pdf_filename

        # Tulis fail HTML sementara
        temp_html = PDF_OUTPUT_DIR / f"_temp_print_{chapter}.html"
        temp_html.write_text(html_content, encoding="utf-8")

        cmd = [
            self.edge_path,
            "--headless",
            "--disable-gpu",
            "--allow-file-access-from-files",
            "--no-pdf-header-footer",
            f"--print-to-pdf={output_pdf.resolve()}",
            str(temp_html.resolve())
        ]

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if proc.returncode != 0:
                raise RuntimeError(f"Edge gagal menjana PDF: {proc.stderr}")

            # Bersihkan fail HTML sementara
            if temp_html.exists():
                temp_html.unlink()

            logger.info(f"PDF A4 berjaya dijana: {output_pdf.name} ({output_pdf.stat().st_size} bytes)")
            return output_pdf
        except Exception as e:
            logger.error(f"Ralat penjanaan PDF bagi {chapter}: {e}")
            raise

    def sync_pdf_to_google_drive(self, pdf_path):
        """
        Muat naik fail PDF ke folder Google Drive '06 PDF BUKU KENANGAN'.
        """
        if not drive_service.is_connected():
            return False, "Google Drive belum disambungkan"

        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            return False, "Fail PDF tidak ditemui"

        fid, link = drive_service.upload_file(
            local_path=pdf_path,
            target_subfolder_name="06 PDF BUKU KENANGAN",
            custom_name=pdf_path.name,
            mime_type="application/pdf"
        )
        return True, {"file_id": fid, "link": link}

book_generator_service = BookGeneratorService()
