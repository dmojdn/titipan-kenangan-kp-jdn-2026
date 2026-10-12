import os
from app import create_app, seed_data

app = create_app()

if __name__ == "__main__":
    # Semai data ujian automatik jika database masih kosong
    seed_data(app)
    
    port = int(os.getenv("PORT", 5000))
    print(f"=== TITIPAN KENANGAN KP JDN ===")
    print(f"Aplikasi sedia di: http://127.0.0.1:{port}")
    print(f"Portal Warga:      http://127.0.0.1:{port}/")
    print(f"Dashboard Admin:   http://127.0.0.1:{port}/admin")
    print(f"Tetapan Drive:     http://127.0.0.1:{port}/admin/drive-setup")
    print(f"================================")
    app.run(host="127.0.0.1", port=port, debug=True)
