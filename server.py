import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from flask import Flask, jsonify, make_response, request, send_from_directory

BASE_DIR = Path(__file__).resolve().parent
JOBS_DIR = BASE_DIR / "generated_clips"
JOBS_DIR.mkdir(exist_ok=True)

app = Flask(__name__, static_folder=str(BASE_DIR))
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


def safe_name(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", text).strip("-") or "clip"


def get_duration(video_path: str) -> float:
    res = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            video_path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(res.stdout.strip() or 0)


def pick_moments(info: dict, duration: float, count: int, clip_len: int = 25) -> list[tuple[float, float, str]]:
    moments = []
    heatmap = info.get("heatmap") or []

    if heatmap and duration > clip_len:
        ranked = sorted(heatmap, key=lambda x: x.get("value", 0), reverse=True)
        for item in ranked:
            center = (float(item["start_time"]) + float(item["end_time"])) / 2.0
            start = max(0.0, min(duration - clip_len, center - clip_len / 2.0))
            end = min(duration, start + clip_len)
            if all(abs(start - s) >= clip_len * 0.8 for s, _, _ in moments):
                moments.append((round(start, 1), round(end, 1), f"Momento viral #{len(moments) + 1}"))
            if len(moments) >= count:
                break

    if len(moments) < count and duration > 3:
        actual_len = min(float(clip_len), duration)
        step = max(actual_len, duration / (count + 1))
        for i in range(count):
            start = max(0.0, min(duration - actual_len, (i + 1) * step - actual_len / 2.0))
            end = min(duration, start + actual_len)
            if all(abs(start - s) >= max(4.0, actual_len * 0.4) for s, _, _ in moments):
                moments.append((round(start, 1), round(end, 1), f"Clip #{len(moments) + 1}"))
            if len(moments) >= count:
                break

    return moments or [(0.0, min(duration, float(clip_len)), "Clip #1")]


@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/api/health", methods=["GET", "OPTIONS"])
def health():
    if request.method == "OPTIONS":
        return make_response("", 204)
    return jsonify({
        "ok": True,
        "yt_dlp": shutil.which("yt-dlp") is not None,
        "ffmpeg": shutil.which("ffmpeg") is not None,
    })


@app.route("/clips/<job_id>/<filename>")
def serve_clip(job_id: str, filename: str):
    return send_from_directory(JOBS_DIR / safe_name(job_id), filename, as_attachment=False)


@app.route("/api/auto-clips", methods=["POST", "OPTIONS"])
def auto_clips():
    if request.method == "OPTIONS":
        return make_response("", 204)

    if not shutil.which("ffmpeg"):
        return jsonify({"error": "Falta instalar ffmpeg en el servidor."}), 500

    uploaded_file = request.files.get("file")
    if uploaded_file:
        count = max(1, min(6, int(request.form.get("count") or 3)))
        clip_len = max(10, min(60, int(request.form.get("clipLen") or 25)))
        ratio = request.form.get("ratio") or "9:16"
        url = ""
    else:
        data = request.get_json(silent=True) or {}
        url = (data.get("url") or "").strip()
        count = max(1, min(6, int(data.get("count") or 3)))
        clip_len = max(10, min(60, int(data.get("clipLen") or 25)))
        ratio = data.get("ratio") or "9:16"

    if not uploaded_file and not url:
        return jsonify({"error": "Sube un archivo de video o pega un enlace válido."}), 400

    job_id = uuid.uuid4().hex[:8]
    out_dir = JOBS_DIR / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="cliplink_auto_")
    raw_path = os.path.join(tmp_dir, "source.mp4")

    try:
        info = {}
        video_title = "Tu video"

        if uploaded_file:
            uploaded_file.save(raw_path)
            video_title = os.path.splitext(uploaded_file.filename or "Video subido")[0]
        else:
            if not shutil.which("yt-dlp"):
                return jsonify({"error": "Falta instalar yt-dlp en el servidor."}), 500
            info_proc = subprocess.run(
                ["yt-dlp", "--dump-json", "--no-playlist", url],
                capture_output=True,
                text=True,
                timeout=45,
                check=True,
            )
            info = json.loads(info_proc.stdout.splitlines()[0])
            video_title = info.get("title") or "Video"

            subprocess.run(
                [
                    "yt-dlp",
                    "--no-playlist",
                    "-f",
                    "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                    "--merge-output-format",
                    "mp4",
                    "-o",
                    raw_path,
                    url,
                ],
                capture_output=True,
                text=True,
                timeout=300,
                check=True,
            )

        duration = get_duration(raw_path)
        moments = pick_moments(info, duration, count, clip_len)

        vf = "crop=ih*9/16:ih:(iw-ih*9/16)*0.5:0,scale=720:1280" if ratio == "9:16" else "scale=1280:720"
        results = []

        for idx, (start, end, label) in enumerate(moments, start=1):
            fname = f"clip_{idx}.mp4"
            out_file = out_dir / fname
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    str(start),
                    "-to",
                    str(end),
                    "-i",
                    raw_path,
                    "-vf",
                    vf,
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-threads",
                    "1",
                    "-crf",
                    "25",
                    "-c:a",
                    "aac",
                    str(out_file),
                ],
                capture_output=True,
                text=True,
                timeout=180,
                check=True,
            )
            results.append({
                "title": label,
                "start": start,
                "end": end,
                "url": f"/clips/{job_id}/{fname}",
                "filename": fname,
            })

        return jsonify({
            "videoTitle": video_title,
            "clips": results,
        })
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or str(exc))[-400:]
        return jsonify({"error": f"Error al procesar el video: {err}"}), 500
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"ClipLink Automático listo en http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
