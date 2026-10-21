
import logging
import re
import shutil
import threading
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from tempfile import mkdtemp

import yt_dlp
from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

logger = logging.getLogger("videoconvert")

app = FastAPI(title="VideoConvert")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app.mount(
    "/static",
    StaticFiles(directory=STATIC_DIR),
    name="static"
)

AUDIO_QUALITIES = {"128", "192", "320"}
VIDEO_QUALITIES = {"360", "480", "720", "1080"}

MAX_DURATION = 3600  # segundos
MAX_FILESIZE = 500 * 1024 * 1024
MAX_CONCURRENT = 2

# Limita cuántas conversiones corren a la vez para no saturar
# CPU, disco y ancho de banda.
conversion_slots = threading.BoundedSemaphore(MAX_CONCURRENT)

YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "www.youtube-nocookie.com",
}
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")

if shutil.which("ffmpeg") is None:
    logger.warning(
        "FFmpeg no está en el PATH: las conversiones fallarán."
    )
if not (shutil.which("deno") or shutil.which("node")):
    logger.warning(
        "No hay deno ni node en el PATH: YouTube no entregará "
        "los formatos y las descargas fallarán."
    )


def extract_video_id(url: str) -> str | None:
    """Devuelve el ID del video, o None si la URL no apunta a
    un único video (playlist, canal, búsqueda, etc.)."""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None

    if parsed.scheme != "https":
        return None

    host = (parsed.hostname or "").lower()
    parts = [p for p in parsed.path.split("/") if p]

    if host == "youtu.be":
        candidate = parts[0] if len(parts) == 1 else None
    elif host in YOUTUBE_HOSTS:
        if parts == ["watch"]:
            candidate = parse_qs(parsed.query).get("v", [None])[0]
        elif len(parts) == 2 and parts[0] in {"shorts", "embed", "live"}:
            candidate = parts[1]
        else:
            candidate = None
    else:
        candidate = None

    if candidate and VIDEO_ID.fullmatch(candidate):
        return candidate
    return None


@app.get("/")
def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/convert")
def convert(
    url: str = Form(...),
    formato: str = Form(...),
    calidad: str = Form(...)
):
    video_id = extract_video_id(url)

    if video_id is None:
        raise HTTPException(
            400,
            "Introduce el enlace de un video de YouTube "
            "(no se admiten playlists ni canales)."
        )

    if formato not in {"mp3", "mp4"}:
        raise HTTPException(400, "Formato no válido.")

    allowed_qualities = (
        AUDIO_QUALITIES if formato == "mp3"
        else VIDEO_QUALITIES
    )

    if calidad not in allowed_qualities:
        raise HTTPException(400, "Calidad no válida.")

    if shutil.which("ffmpeg") is None:
        raise HTTPException(
            500, "FFmpeg no está instalado en el servidor."
        )

    if not conversion_slots.acquire(blocking=False):
        raise HTTPException(
            503,
            "El servidor está ocupado con otras conversiones. "
            "Inténtalo de nuevo en unos minutos."
        )

    try:
        return run_conversion(video_id, formato, calidad)
    finally:
        conversion_slots.release()


def run_conversion(video_id: str, formato: str, calidad: str):
    # URL canónica: así nunca se procesa una playlist completa.
    url = f"https://www.youtube.com/watch?v={video_id}"
    workdir = Path(mkdtemp(prefix="videoconvert_"))

    options = {
        "outtmpl": str(workdir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "restrictfilenames": True,
        "socket_timeout": 20,
        "retries": 1,
        "max_filesize": MAX_FILESIZE,
        # YouTube exige un runtime de JavaScript para resolver los
        # formatos; se usa el primero disponible.
        "js_runtimes": {"deno": {}, "node": {}},
    }

    if formato == "mp3":
        options.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": calidad,
            }],
        })
    else:
        options.update({
            # Prioriza H.264 + AAC, que reproduce cualquier
            # dispositivo; AV1/VP9/Opus solo como alternativa.
            "format": (
                f"bestvideo[height<={calidad}][vcodec^=avc1]"
                "+bestaudio[ext=m4a]/"
                f"bestvideo[height<={calidad}]+bestaudio/"
                f"best[height<={calidad}][ext=mp4]/"
                f"best[height<={calidad}]"
            ),
            "merge_output_format": "mp4",
            # Si la alternativa final no es MP4, se remuxa.
            "postprocessors": [{
                "key": "FFmpegVideoRemuxer",
                "preferedformat": "mp4",
            }],
        })

    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(
                url, download=False, process=False
            )

            if info.get("is_live") or info.get("live_status") in {
                "is_live", "is_upcoming"
            }:
                raise HTTPException(
                    400,
                    "No se pueden convertir transmisiones en vivo."
                )

            duration = info.get("duration")
            if duration is None or duration > MAX_DURATION:
                raise HTTPException(
                    400,
                    "El video supera la duración máxima "
                    f"de {MAX_DURATION // 60} minutos."
                )

            downloader.process_ie_result(info, download=True)

        extension = f".{formato}"
        files = [
            p for p in workdir.iterdir()
            if p.is_file() and p.suffix.lower() == extension
        ]

        if not files:
            raise HTTPException(
                422,
                "No se generó el archivo. Es posible que el video "
                f"supere el tamaño máximo de "
                f"{MAX_FILESIZE // (1024 * 1024)} MB."
            )

        output = files[0]

        return FileResponse(
            path=output,
            media_type=(
                "audio/mpeg" if formato == "mp3"
                else "video/mp4"
            ),
            filename=f"convertido.{formato}",
            background=BackgroundTask(
                shutil.rmtree, workdir, ignore_errors=True
            ),
        )

    except HTTPException:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    except Exception as error:
        shutil.rmtree(workdir, ignore_errors=True)
        logger.exception("Falló la conversión de %s", url)
        raise HTTPException(
            422,
            "No se pudo procesar el video. "
            "Puede no estar disponible o la fuente "
            "puede no permitir la descarga."
        ) from error
