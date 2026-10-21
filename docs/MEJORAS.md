# Mejoras de robustez — rama `fix/robustez-descargas`

Este documento explica qué se cambió, por qué, y cómo se probó.

## Resumen

| # | Problema | Impacto | Estado |
|---|---|---|---|
| 1 | Un enlace de playlist o canal descargaba **todos** sus videos | Alto: horas de descarga y GB de disco por una sola petición | Corregido |
| 2 | Sin límite de conversiones simultáneas | Alto: pocas peticiones saturan CPU, disco y red | Corregido |
| 3 | YouTube exige un runtime de JavaScript; sin él no hay formatos | Alto: **ninguna** descarga funcionaba con yt-dlp actual | Corregido |
| 4 | El MP4 podía salir en AV1 o VP9/Opus | Medio: no se reproduce en iPhone, QuickTime ni equipos antiguos | Corregido |
| 5 | Mensajes de error engañosos y sin log | Medio: imposible saber por qué falló | Corregido |
| 6 | Errores de validación se mostraban como `[object Object]` | Bajo | Corregido |
| 7 | `__pycache__` subido al repo, README vacío | Bajo | Corregido |
| 8 | El navegador carga el archivo completo en memoria | Medio con archivos grandes | **Pendiente** |

## Detalle de los cambios

### 1. Solo se aceptan videos individuales (`main.py`)

**Antes:** `valid_youtube_url` solo comprobaba el dominio y que la ruta no
estuviera vacía. Una URL como `youtube.com/playlist?list=...` o
`youtube.com/@canal` pasaba la validación. La opción `noplaylist` solo actúa
cuando la URL trae un video *y* una lista a la vez, así que con una playlist
pura yt-dlp descargaba todos los videos y la app devolvía uno cualquiera
(`files[0]`).

**Ahora:** `extract_video_id` extrae el ID de 11 caracteres de los formatos
admitidos y la descarga se hace siempre sobre la URL canónica
`https://www.youtube.com/watch?v=<ID>`:

- `youtube.com/watch?v=ID` (también con `&list=`, `&t=`, etc.)
- `youtu.be/ID`
- `youtube.com/shorts/ID`, `/embed/ID`, `/live/ID`
- dominios `www.`, `m.`, `music.` y `youtube-nocookie.com`

Cualquier otra URL (playlist, canal, búsqueda, `http://`, otros dominios)
se rechaza con un 400 y un mensaje claro.

### 2. Límite de conversiones simultáneas (`main.py`)

El endpoint es síncrono y FastAPI lo ejecuta en un pool de hasta 40 hilos.
Ahora un semáforo (`MAX_CONCURRENT = 2`) limita las conversiones en curso. Si
llega una petición con todos los cupos ocupados, responde **503** "El servidor
está ocupado…" en vez de encolarse. El cupo se libera siempre, también si la
conversión falla.

### 3. Runtime de JavaScript para YouTube (`main.py`, `requirements.txt`)

Las versiones recientes de yt-dlp necesitan ejecutar JavaScript para resolver
los formatos de YouTube. Sin un runtime, yt-dlp responde
*"Requested format is not available"* y **la app original no podía descargar
nada**.

- `requirements.txt`: `yt-dlp` → `yt-dlp[default]` (incluye `yt-dlp-ejs`).
- `main.py`: `js_runtimes` habilita Deno y Node; se usa el que esté instalado.
- Al arrancar se registra una advertencia si no hay ninguno en el PATH.

### 4. MP4 compatible: H.264 + AAC (`main.py`)

El selector original (`bestvideo+bestaudio`) elegía la mejor calidad
disponible, que en YouTube suele ser AV1 o VP9 con audio Opus. Filtrar por
`ext=mp4` no basta, porque YouTube también entrega AV1 dentro de MP4.

Nuevo orden de preferencia:

1. Video H.264 (`vcodec^=avc1`) + audio AAC (`m4a`)
2. Cualquier video + audio (alternativa si no hay H.264)
3. Archivo único MP4 ya combinado
4. Archivo único en cualquier formato, convertido a MP4 con `FFmpegVideoRemuxer`

### 5. Validaciones previas y mensajes claros (`main.py`)

Antes de descargar se leen los metadatos del video
(`extract_info(..., process=False)`) y se reutilizan para la descarga
(`process_ie_result`), sin hacer una segunda petición a YouTube. Con eso:

| Situación | Respuesta |
|---|---|
| Video de más de 60 minutos | 400 "El video supera la duración máxima de 60 minutos." |
| Transmisión en vivo o programada | 400 "No se pueden convertir transmisiones en vivo." |
| FFmpeg no instalado | 500 "FFmpeg no está instalado en el servidor." |
| Archivo mayor a 500 MB | 422 con aviso del tamaño máximo |
| Error inesperado | 422 genérico + traza completa en el log (`logger.exception`) |

Antes, un video de más de 1 hora se descartaba en silencio y el usuario veía
"comprueba que FFmpeg esté instalado". Además, se añadió `noprogress` para que
la barra de progreso de yt-dlp no llene la consola del servidor.

Los límites quedan como constantes al inicio de `main.py`: `MAX_DURATION`,
`MAX_FILESIZE` y `MAX_CONCURRENT`.

### 6. Frontend (`static/app.js`)

- Cuando FastAPI devuelve errores de validación, `detail` es una lista y se
  mostraba como `[object Object]`. Ahora solo se usa si es texto.
- El archivo de la conversión anterior se libera de memoria
  (`URL.revokeObjectURL`) al iniciar una nueva. Antes solo se liberaba si el
  usuario hacía clic en descargar.

### 7. Orden del repositorio

- `.gitignore` nuevo (`__pycache__/`, entornos virtuales, `.env`).
- Se quitó `__pycache__/main.cpython-314.pyc` del control de versiones.
- `README.md` con requisitos, instalación, uso y límites.

## Pruebas realizadas

**Validación de enlaces:** 23 casos (10 válidos y 13 inválidos, entre ellos
playlist, canal, búsqueda, `http://`, `youtube.com.evil.com`, ID corto y URL
mal formada), todos correctos.

**Respuestas del endpoint** (con yt-dlp simulado):

| Caso | Resultado |
|---|---|
| Enlace de playlist | 400 |
| Formato o calidad inválidos | 400 |
| Sin FFmpeg | 500 |
| Todos los cupos ocupados | 503 |
| Video de 2 h | 400 |
| Transmisión en vivo | 400 |
| Cupos libres después de los errores | 2 de 2 |

**Conversiones reales** contra YouTube (video de 3:33), con yt-dlp 2026.08.19,
FFmpeg 7.1 y Node 26:

| Formato | Resultado | Archivo |
|---|---|---|
| MP3 128 kbps | 200 | 3.4 MB, MP3 128 kb/s |
| MP4 360p | 200 | 11.9 MB |
| MP4 1080p | 200 | 84.4 MB, H.264 High 1920×1080 + AAC |

En todos los casos se borró la carpeta temporal después de la respuesta.

## Nuevos requisitos para ejecutar

- **FFmpeg** en el PATH (ya era necesario, ahora está documentado).
- **Deno** (recomendado) o **Node.js** en el PATH.
- `pip install -r requirements.txt` de nuevo, porque cambió a `yt-dlp[default]`.

## Pendiente

- **Descarga sin pasar por la memoria del navegador.** `app.js` hace
  `response.blob()`, que carga el archivo completo en RAM (hasta 500 MB) antes
  de mostrar el botón, sin progreso. La solución es convertir en segundo plano
  (job con ID), consultar el estado y descargar con un enlace `GET` directo.
  Es un cambio de diseño, así que se dejó para otra rama.
- **Límite por IP.** El semáforo protege el servidor, pero un solo usuario
  puede ocupar los dos cupos. Si se publica, conviene añadir `slowapi` o un
  límite en el proxy (nginx, Cloudflare).
- **Despliegue en la nube.** YouTube suele bloquear IPs de centros de datos
  ("Sign in to confirm you're not a bot"). Funciona en local; en un VPS puede
  requerir cookies o un proxy.
