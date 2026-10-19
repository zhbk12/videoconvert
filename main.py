
from pathlib import Path
from urllib.parse import urlparse
from tempfile import mkdtemp
import shutil

import yt_dlp
from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

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


def valid_youtube_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
        host = (parsed.hostname or "").lower()

        allowed = {
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "youtu.be",
            "www.youtube-nocookie.com",
        }

        return (
            parsed.scheme == "https"
            and host in allowed
            and bool(parsed.path.strip("/"))
        )
    except ValueError:
        return False


@app.get("/")
def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/convert")
def convert(
    url: str = Form(...),
    formato: str = Form(...),
    calidad: str = Form(...)
):
    url = url.strip()

    if not valid_youtube_url(url):
        raise HTTPException(
            400, "Introduce una URL válida de YouTube."
        )

    if formato not in {"mp3", "mp4"}:
        raise HTTPException(400, "Formato no válido.")

    allowed_qualities = (
        AUDIO_QUALITIES if formato == "mp3"
        else VIDEO_QUALITIES
    )

    if calidad not in allowed_qualities:
        raise HTTPException(400, "Calidad no válida.")

    workdir = Path(mkdtemp(prefix="videoconvert_"))

    options = {
        "outtmpl": str(workdir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "socket_timeout": 20,
        "retries": 1,
        "max_filesize": 500 * 1024 * 1024,
        "match_filter": yt_dlp.utils.match_filter_func(
            "duration <= 3600"
        ),
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
            "format": (
                f"bestvideo[height<={calidad}]"
                "+bestaudio/"
                f"best[height<={calidad}]"
            ),
            "merge_output_format": "mp4",
        })

    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            downloader.download([url])

        extension = f".{formato}"
        files = [
            p for p in workdir.iterdir()
            if p.is_file() and p.suffix.lower() == extension
        ]

        if not files:
            raise HTTPException(
                422,
                "No se generó el archivo. "
                "Comprueba que el video esté disponible "
                "y que FFmpeg esté instalado."
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
        raise HTTPException(
            422,
            "No se pudo procesar el video. "
            "Puede no estar disponible o la fuente "
            "puede no permitir la descarga."
        ) from error
