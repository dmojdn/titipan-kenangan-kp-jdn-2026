import os
from app import create_app

app = create_app()

if __name__ == "__main__":
    
    port = int(os.getenv("PORT", 5000))
    print(f"=== TITIPAN KENANGAN KP JDN ===")
    print(f"Aplikasi sedia di: http://127.0.0.1:{port} / http://localhost:{port}")
    print(f"Akses Wi-Fi/LAN:   http://10.34.10.244:{port}")
    print(f"Portal Warga:      http://127.0.0.1:{port}/")
    print(f"Dashboard Admin:   http://127.0.0.1:{port}/admin")
    print(f"================================")
    app.run(host="0.0.0.0", port=port, debug=True)
