# VideoConvert

Microapp web para convertir un video de YouTube a MP3 (audio) o MP4 (video).
Backend en FastAPI + yt-dlp, frontend estático sin dependencias.

## Requisitos

- Python 3.10 o superior
- [FFmpeg](https://ffmpeg.org/download.html) instalado y disponible en el PATH
  (sin él fallan todas las conversiones a MP3 y la mayoría de MP4)
- Un runtime de JavaScript en el PATH: [Deno](https://deno.com/) (recomendado)
  o Node.js. YouTube lo exige para entregar los formatos de video; sin él,
  yt-dlp responde "Requested format is not available".

## Instalación

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   ·   Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

## Uso

```bash
uvicorn main:app --reload
```

Abrir <http://127.0.0.1:8000>.

## Límites

| Límite | Valor | Dónde cambiarlo |
|---|---|---|
| Duración máxima | 60 min | `MAX_DURATION` en `main.py` |
| Tamaño máximo | 500 MB | `MAX_FILESIZE` en `main.py` |
| Conversiones simultáneas | 2 | `MAX_CONCURRENT` en `main.py` |

Solo se aceptan enlaces a un video individual (`watch?v=`, `youtu.be/`,
`/shorts/`, `/embed/`, `/live/`); las playlists y canales se rechazan.

## Notas

- Mantén `yt-dlp` actualizado (`pip install -U yt-dlp`): YouTube cambia con
  frecuencia y las versiones viejas dejan de funcionar.
- En servidores con IP de centro de datos, YouTube puede bloquear las descargas
  ("Sign in to confirm you're not a bot").
- Úsalo solo con videos propios o con permiso de descarga.
