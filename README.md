# ClipLink Automático (Web + Servidor)

## Opción A: Usarlo desde tu celular (Subirlo a la nube)
1. Sube esta carpeta a un repositorio privado o público en **GitHub**.
2. Entra a **Render.com** o **Railway.app**, crea un **Web Service** conectando ese repositorio (detectará automáticamente el `Dockerfile` con `FFmpeg` y `yt-dlp`).
3. Abre la URL pública que te den en Chrome desde tu celular, pega el enlace del video y descarga tus clips.

## Opción B: Usarlo en tu computadora (Windows/Mac) o Android (Termux)
- **Windows:** Haz doble clic en `iniciar.bat` (requiere Python y FFmpeg instalados).
- **Android (Termux):**
  ```bash
  pkg install python ffmpeg -y && pip install -r requirements.txt && python server.py
  ```
  Luego abre `http://127.0.0.1:5000` en Chrome.
