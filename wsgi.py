"""
Titik Masuk Pengeluaran (Production Entry Point) WSGI
Aplikasi: Titipan Kenangan KP JDN
"""
import os
from app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"Memulakan pelayan produksi pada port {port}...")
    
    # Cuba gunakan Waitress (WSGI pengeluaran berprestasi tinggi untuk Windows/Linux)
    try:
        from waitress import serve
        print(f"Menjalankan pelayan pengeluaran Waitress di: http://0.0.0.0:{port}")
        serve(app, host="0.0.0.0", port=port, threads=8)
    except ImportError:
        # Fallback jika waitress tiada
        app.run(host="0.0.0.0", port=port, debug=False)
