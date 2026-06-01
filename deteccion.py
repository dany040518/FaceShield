#!/usr/bin/env python3
"""
Face Detection Stream — Modo dual
  /             → Dashboard local interactivo (click para censurar/revelar, cambio de fuente)
  /video        → MJPEG local, censura selectiva
  /public       → Vista pública, solo lectura
  /video_public → MJPEG siempre censurado, sin interacción posible

Fuentes soportadas:
  0, 1, 2...    → Cámaras conectadas al dispositivo (0 = integrada, 1 = USB externa, etc.)
  http://...    → Stream MJPEG en red local
  rtsp://...    → Stream RTSP (cámaras IP)
  https://www.youtube.com/watch?v=... → Video de YouTube (requiere yt-dlp)
"""

import cv2
import numpy as np
from flask import Flask, Response, render_template_string, request, jsonify
import os
import threading
import socket
import time
import psutil
import sys
import urllib.request
import urllib.error
import subprocess
import logging
logging.getLogger("werkzeug").setLevel(logging.ERROR)
from collections import defaultdict

# ──────────────────────────────────────────────────────────────────────────────
#  OPTIMIZACIONES OpenCV (aprovecha los 4 cores del RPi 5)
# ──────────────────────────────────────────────────────────────────────────────
cv2.setUseOptimized(True)
cv2.setNumThreads(2)

# ──────────────────────────────────────────────────────────────────────────────
#  MODELO DNN — descarga automática si no existe
# ──────────────────────────────────────────────────────────────────────────────
PROTOTXT   = "deploy.prototxt"
CAFFEMODEL = "res10_300x300_ssd_iter_140000.caffemodel"

def _descargar_modelo(url: str, destino: str) -> None:
    print(f"Descargando {destino}...")
    try:
        urllib.request.urlretrieve(url, destino)
    except urllib.error.HTTPError as e:
        print(f"[ERROR] No se pudo descargar {destino}: HTTP {e.code} — {url}")
        if os.path.exists(destino):
            os.remove(destino)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"[ERROR] Sin conexión de red al descargar {destino}: {e.reason}")
        sys.exit(1)
    except OSError as e:
        print(f"[ERROR] No se pudo guardar {destino} en disco: {e}")
        sys.exit(1)

if not os.path.exists(PROTOTXT):
    _descargar_modelo(
        "https://raw.githubusercontent.com/opencv/opencv/master/samples/dnn/"
        "face_detector/deploy.prototxt",
        PROTOTXT,
    )

if not os.path.exists(CAFFEMODEL):
    _descargar_modelo(
        "https://github.com/opencv/opencv_3rdparty/raw/"
        "dnn_samples_face_detector_20170830/res10_300x300_ssd_iter_140000.caffemodel",
        CAFFEMODEL,
    )

print("Cargando red neuronal DNN...")
try:
    net = cv2.dnn.readNetFromCaffe(PROTOTXT, CAFFEMODEL)
except cv2.error as e:
    print(f"[ERROR] No se pudo cargar el modelo DNN: {e}")
    print("[ERROR] El archivo puede estar corrupto. Elimina .prototxt y .caffemodel y reinicia.")
    sys.exit(1)
print("✅ Modelo DNN cargado")

# ──────────────────────────────────────────────────────────────────────────────
#  FLASK
# ──────────────────────────────────────────────────────────────────────────────
app = Flask(__name__)

lock = threading.Lock()

frame_local_jpeg:   bytes | None = None
frame_publico_jpeg: bytes | None = None
frame_id: int = 0

coordenadas_caras: list[tuple[tuple[int,int,int,int], float]] = []
caras_visibles:    set[int] = set()

# ──────────────────────────────────────────────────────────────────────────────
#  FUENTE DE VIDEO
# ──────────────────────────────────────────────────────────────────────────────
DEFAULT_SOURCE = os.environ.get("DEFAULT_VIDEO_SOURCE", "0")

_source_lock    = threading.Lock()
_current_source: str | int = DEFAULT_SOURCE
_pending_source: str | int | None = None
_source_status:  str = "connecting"

def _get_source() -> tuple[str | int, bool]:
    with _source_lock:
        if _pending_source is not None:
            return _pending_source, True
        return _current_source, False

def _confirm_source(src: str | int, ok: bool) -> None:
    global _current_source, _pending_source, _source_status
    with _source_lock:
        _current_source = src
        _pending_source = None
        _source_status  = "ok" if ok else "error"

# ──────────────────────────────────────────────────────────────────────────────
#  YOUTUBE — resuelve URL real del stream con yt-dlp
# ──────────────────────────────────────────────────────────────────────────────
def _is_youtube_url(src: str) -> bool:
    return "youtube.com/watch" in src or "youtu.be/" in src

def _resolver_youtube(url: str) -> str | None:
    """Retorna la URL directa del stream o None si falla."""
    try:
        result = subprocess.check_output(
            ["yt-dlp", "-f", "best[ext=mp4]/best", "-g", url],
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
        return result.decode("utf-8").strip()
    except FileNotFoundError:
        print("[yt-dlp] No encontrado. Instálalo con: pip install yt-dlp")
        return None
    except subprocess.TimeoutExpired:
        print("[yt-dlp] Timeout al resolver la URL de YouTube.")
        return None
    except Exception as e:
        print(f"[yt-dlp] Error resolviendo '{url}': {e}")
        return None

# ──────────────────────────────────────────────────────────────────────────────
#  RATE LIMITING para /click
# ──────────────────────────────────────────────────────────────────────────────
_rl_store: dict[str, list[float]] = defaultdict(list)
_rl_lock  = threading.Lock()
CLICK_MAX_PER_SECOND = 8

def _permitir_click(ip: str) -> bool:
    now = time.time()
    with _rl_lock:
        ts = [t for t in _rl_store[ip] if now - t < 1.0]
        _rl_store[ip] = ts
        if len(ts) >= CLICK_MAX_PER_SECOND:
            return False
        _rl_store[ip].append(now)
        return True

# ──────────────────────────────────────────────────────────────────────────────
#  CENSURA — elipse ajustada a la forma del rostro
# ──────────────────────────────────────────────────────────────────────────────
def _pixelar_elipse(img: np.ndarray, x: int, y: int, x2: int, y2: int,
                    expand: float = 0.25) -> None:
    h_img, w_img = img.shape[:2]
    w = x2 - x
    h = y2 - y

    # Expandir bounding box un 25% en cada lado
    pad_x = int(w * expand)
    pad_y = int(h * expand)
    x  = max(0, x  - pad_x)
    y  = max(0, y  - pad_y)
    x2 = min(w_img, x2 + pad_x)
    y2 = min(h_img, y2 + pad_y)
    w  = x2 - x
    h  = y2 - y

    if w <= 0 or h <= 0:
        return

    region   = img[y:y2, x:x2].copy()
    if region.size == 0:
        return

    small    = cv2.resize(region, (6, 6), interpolation=cv2.INTER_LINEAR)
    pixelada = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)

    mascara  = np.zeros((h, w), dtype=np.uint8)
    cv2.ellipse(mascara, (w // 2, h // 2), (w // 2, h // 2), 0, 0, 360, 255, -1)
    mascara  = cv2.GaussianBlur(mascara, (15, 15), 0)

    alpha    = mascara.astype(np.float32) / 255.0
    alpha3   = np.stack([alpha, alpha, alpha], axis=-1)

    blended  = (pixelada.astype(np.float32) * alpha3 +
                img[y:y2, x:x2].astype(np.float32) * (1.0 - alpha3)).astype(np.uint8)
    img[y:y2, x:x2] = blended

# ──────────────────────────────────────────────────────────────────────────────
#  HTML — DASHBOARD LOCAL
# ──────────────────────────────────────────────────────────────────────────────
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Face Detection — DNN · Local</title>
    <link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Exo+2:wght@300;600&display=swap" rel="stylesheet">
    <style>
        :root {
            --green:#00ff88; --red:#ff3a3a; --amber:#ffb800;
            --bg:#080c10; --panel:#0d1117; --border:#1a2332;
            --text:#c9d6e3; --dim:#4a5568;
        }
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            background:var(--bg); color:var(--text);
            font-family:'Exo 2',sans-serif; min-height:100vh;
            display:flex; flex-direction:column; align-items:center;
            padding:24px 16px; gap:20px;
        }
        body::before {
            content:''; position:fixed; inset:0;
            background:repeating-linear-gradient(0deg,transparent,transparent 2px,
                rgba(0,255,136,0.015) 2px,rgba(0,255,136,0.015) 4px);
            pointer-events:none; z-index:999;
        }
        header { display:flex; align-items:center; gap:14px; width:100%; max-width:700px; }
        .logo {
            width:38px; height:38px; border:2px solid var(--green);
            border-radius:6px; display:grid; place-items:center; font-size:1.2rem;
            box-shadow:0 0 12px rgba(0,255,136,0.3);
        }
        h1 { font-family:'Share Tech Mono',monospace; font-size:1rem;
             letter-spacing:3px; color:var(--green); text-transform:uppercase; }
        .badge {
            margin-left:auto; font-family:'Share Tech Mono',monospace; font-size:0.7rem;
            padding:4px 10px; border:1px solid var(--green); border-radius:20px;
            color:var(--green); display:flex; align-items:center; gap:6px;
        }
        .dot { width:7px; height:7px; background:var(--green); border-radius:50%;
               animation:blink 1.4s infinite; }
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.1} }

        .source-panel {
            width:100%; max-width:700px; background:var(--panel);
            border:1px solid var(--border); border-radius:8px; padding:14px 16px;
            display:flex; flex-direction:column; gap:10px;
        }
        .source-label {
            font-family:'Share Tech Mono',monospace; font-size:0.65rem;
            color:var(--dim); letter-spacing:2px; text-transform:uppercase;
        }
        .source-row { display:flex; gap:8px; align-items:center; }
        .source-input {
            flex:1; background:#060a0f; border:1px solid var(--border);
            border-radius:6px; padding:8px 12px;
            font-family:'Share Tech Mono',monospace; font-size:0.82rem;
            color:var(--green); outline:none; transition:border-color 0.2s;
        }
        .source-input:focus { border-color:var(--green); }
        .source-input::placeholder { color:var(--dim); }
        .source-btn {
            background:transparent; border:1px solid var(--green); border-radius:6px;
            padding:8px 18px; font-family:'Share Tech Mono',monospace; font-size:0.78rem;
            color:var(--green); cursor:pointer; letter-spacing:1px;
            transition:background 0.15s,color 0.15s; white-space:nowrap;
        }
        .source-btn:hover  { background:var(--green); color:#080c10; }
        .source-btn:active { opacity:0.7; }
        .source-btn:disabled { opacity:0.35; cursor:not-allowed; }
        .source-status {
            font-family:'Share Tech Mono',monospace; font-size:0.7rem;
            display:flex; align-items:center; gap:7px; min-height:18px;
        }
        .source-status .indicator { width:7px; height:7px; border-radius:50%; flex-shrink:0; }
        .status-ok { color:var(--green); }
        .status-ok .indicator { background:var(--green); }
        .status-connecting { color:var(--amber); }
        .status-connecting .indicator { background:var(--amber); animation:blink 0.8s infinite; }
        .status-error { color:var(--red); }
        .status-error .indicator { background:var(--red); }
        .source-hint { font-size:0.68rem; color:var(--dim); letter-spacing:0.5px; }
        .source-hint code {
            font-family:'Share Tech Mono',monospace; color:#5a7a8a;
            background:#0a0f14; padding:1px 5px; border-radius:3px;
        }

        /* Accesos rápidos de fuente */
        .quick-sources { display:flex; gap:8px; flex-wrap:wrap; }
        .quick-btn {
            background:#0a0f14; border:1px solid var(--border); border-radius:5px;
            padding:5px 12px; font-family:'Share Tech Mono',monospace; font-size:0.68rem;
            color:var(--dim); cursor:pointer; transition:border-color 0.15s,color 0.15s;
        }
        .quick-btn:hover { border-color:var(--green); color:var(--green); }

        .video-wrap {
            position:relative; border:1px solid var(--border); border-radius:8px;
            overflow:hidden; box-shadow:0 0 0 1px rgba(0,255,136,0.08),0 0 40px rgba(0,0,0,0.8);
            cursor:crosshair; width:100%; max-width:700px;
        }
        .video-wrap::before,.video-wrap::after {
            content:''; position:absolute; width:18px; height:18px;
            border-color:var(--green); border-style:solid; z-index:10;
        }
        .video-wrap::before { top:8px; left:8px; border-width:2px 0 0 2px; }
        .video-wrap::after  { bottom:8px; right:8px; border-width:0 2px 2px 0; }
        #stream  { display:block; width:100%; height:auto; }
        #overlay { position:absolute; top:0; left:0; width:100%; height:100%; pointer-events:none; }

        .stats { display:flex; gap:12px; width:100%; max-width:700px; }
        .stat-card {
            flex:1; background:var(--panel); border:1px solid var(--border);
            border-radius:8px; padding:12px 16px; display:flex; flex-direction:column; gap:4px;
        }
        .stat-label { font-family:'Share Tech Mono',monospace; font-size:0.65rem;
                      color:var(--dim); letter-spacing:2px; text-transform:uppercase; }
        .stat-value { font-family:'Share Tech Mono',monospace; font-size:1.4rem; color:var(--green); }
        .hint { font-size:0.75rem; color:var(--dim); letter-spacing:1px; }
    </style>
</head>
<body>
<header>
    <div class="logo">📷</div>
    <h1>Face Detection · Local</h1>
    <div class="badge"><span class="dot"></span>LIVE</div>
</header>

<div class="source-panel">
    <span class="source-label">▸ Fuente de video</span>
    <div class="source-row">
        <input id="sourceInput" class="source-input" type="text"
            placeholder="0  ·  1  ·  http://ip:puerto/video  ·  youtube.com/watch?v=..."
            spellcheck="false" autocomplete="off">
        <button id="sourceBtn" class="source-btn" onclick="setSource()">CONECTAR</button>
    </div>

    <!-- Accesos rápidos -->
    <div class="quick-sources">
        <button class="quick-btn" onclick="fillSource('0')">📷 Cámara 0</button>
        <button class="quick-btn" onclick="fillSource('1')">📷 Cámara 1</button>
        <button class="quick-btn" onclick="fillSource('2')">📷 Cámara 2</button>
        <button class="quick-btn" onclick="focusYT()" title="Pega una URL de YouTube">▶ YouTube</button>
    </div>

    <div id="sourceStatus" class="source-status status-connecting">
        <span class="indicator"></span>
        <span id="sourceStatusText">Cargando estado...</span>
    </div>
    <p class="source-hint">
        Usa <code>0</code> cámara integrada · <code>1</code> cámara USB externa ·
        URL de stream en red · URL de YouTube (requiere yt-dlp instalado)
    </p>
</div>

<div class="video-wrap" id="wrapper">
    <img id="stream" src="/video" alt="stream">
    <canvas id="overlay"></canvas>
</div>

<div class="stats">
    <div class="stat-card">
        <span class="stat-label">Caras detectadas</span>
        <span class="stat-value" id="cnt">0</span>
    </div>
    <div class="stat-card">
        <span class="stat-label">Censuradas</span>
        <span class="stat-value" id="cen" style="color:#ff3a3a">0</span>
    </div>
    <div class="stat-card">
        <span class="stat-label">Motor</span>
        <span class="stat-value" style="font-size:0.85rem;margin-top:4px">
            OpenCV DNN<br>
            <small style="color:var(--dim);font-size:0.7rem">SSD ResNet-10</small>
        </span>
    </div>
</div>
<p class="hint">▸ Haz click sobre una cara para activar / quitar la censura</p>

<script>
    const stream = document.getElementById("stream");
    const canvas = document.getElementById("overlay");
    const ctx    = canvas.getContext("2d");
    const cntEl  = document.getElementById("cnt");
    const cenEl  = document.getElementById("cen");
    let caras    = [];

    function syncCanvas() {
        canvas.width  = stream.clientWidth;
        canvas.height = stream.clientHeight;
    }
    stream.addEventListener("load", syncCanvas);
    window.addEventListener("resize", syncCanvas);
    syncCanvas();

    function draw() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        if (!caras.length) return;
        const sx = canvas.width  / 640;
        const sy = canvas.height / 480;
        caras.forEach((c, i) => {
            const x = c.x  * sx, y = c.y  * sy;
            const w = (c.x2 - c.x) * sx, h = (c.y2 - c.y) * sy;
            const color = c.visible ? "#00ff88" : "#ff3a3a";

            // Elipse de contorno alineada al bounding box
            ctx.strokeStyle = color; ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.ellipse(x + w/2, y + h/2, w/2, h/2, 0, 0, Math.PI * 2);
            ctx.stroke();

            // Esquinas del bounding box
            const cs = 10; ctx.lineWidth = 2.5;
            ctx.beginPath();
            ctx.moveTo(x,     y+cs);   ctx.lineTo(x,   y);   ctx.lineTo(x+cs, y);
            ctx.moveTo(x+w-cs,y);      ctx.lineTo(x+w, y);   ctx.lineTo(x+w,  y+cs);
            ctx.moveTo(x,     y+h-cs); ctx.lineTo(x,   y+h); ctx.lineTo(x+cs, y+h);
            ctx.moveTo(x+w-cs,y+h);    ctx.lineTo(x+w, y+h); ctx.lineTo(x+w,  y+h-cs);
            ctx.stroke();

            ctx.font = "10px 'Share Tech Mono', monospace";
            ctx.fillStyle = color;
            ctx.fillText(c.visible ? `FACE_${String(i).padStart(2,"0")}` : "CENSORED", x+4, y-5);
            if (c.conf !== undefined) {
                ctx.fillStyle = "rgba(0,255,136,0.6)";
                ctx.font = "9px 'Share Tech Mono', monospace";
                ctx.fillText(`${Math.round(c.conf*100)}%`, x+4, y+h-5);
            }
        });
    }

    async function poll() {
        try {
            const res = await fetch("/caras");
            caras = await res.json();
            draw();
            cntEl.textContent = caras.length;
            cenEl.textContent = caras.filter(c => !c.visible).length;
        } catch {}
    }
    setInterval(poll, 250);

    // ── Source status ────────────────────────────────────────────────────────
    const statusEl     = document.getElementById("sourceStatus");
    const statusTextEl = document.getElementById("sourceStatusText");
    const sourceBtn    = document.getElementById("sourceBtn");
    const sourceInput  = document.getElementById("sourceInput");

    function applyStatus(data) {
        statusEl.className = "source-status";
        if (data.status === "ok") {
            statusEl.classList.add("status-ok");
            statusTextEl.textContent = `Conectado · ${data.source}`;
            sourceBtn.disabled = false;
            sourceInput.placeholder = data.source;
        } else if (data.status === "error") {
            statusEl.classList.add("status-error");
            statusTextEl.textContent = `Error de conexión · ${data.source}`;
            sourceBtn.disabled = false;
        } else {
            statusEl.classList.add("status-connecting");
            const isYT = data.source.includes("youtube") || data.source.includes("youtu.be");
            statusTextEl.textContent = isYT
                ? `Resolviendo stream de YouTube... (puede tardar ~15 s)`
                : `Conectando con ${data.source}...`;
            sourceBtn.disabled = true;
        }
    }

    async function pollStatus() {
        try {
            const res  = await fetch("/source_status");
            const data = await res.json();
            applyStatus(data);
        } catch {}
    }
    setInterval(pollStatus, 800);
    pollStatus();

    // ── Accesos rápidos ──────────────────────────────────────────────────────
    function fillSource(val) {
        sourceInput.value = val;
        sourceInput.focus();
        if (val !== '') setSource();
    }

    function focusYT() {
        sourceInput.value = '';
        sourceInput.placeholder = 'https://www.youtube.com/watch?v=...';
        sourceInput.focus();
    }

    // ── Cambio de fuente ─────────────────────────────────────────────────────
    async function setSource() {
        const raw = sourceInput.value.trim();
        if (!raw) { sourceInput.focus(); return; }

        const isCamera  = /^\d+$/.test(raw);
        const isUrl     = /^(http|https|rtsp|rtmp):\/\/.+/.test(raw);
        const isYouTube = raw.includes("youtube.com/watch") || raw.includes("youtu.be/");

        if (!isCamera && !isUrl && !isYouTube) {
            statusEl.className = "source-status status-error";
            statusTextEl.textContent = "Formato inválido. Usa un número, URL de stream o URL de YouTube.";
            return;
        }

        sourceBtn.disabled = true;
        statusEl.className = "source-status status-connecting";
        statusTextEl.textContent = isYouTube
            ? `Resolviendo stream de YouTube... (puede tardar ~15 s)`
            : `Solicitando cambio a: ${raw}...`;

        try {
            const res  = await fetch("/set_source", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ source: raw }),
            });
            const data = await res.json();
            if (!data.ok) {
                statusEl.className = "source-status status-error";
                statusTextEl.textContent = data.error || "Error desconocido";
                sourceBtn.disabled = false;
            }
        } catch {
            statusEl.className = "source-status status-error";
            statusTextEl.textContent = "No se pudo contactar al servidor.";
            sourceBtn.disabled = false;
        }
    }

    sourceInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") setSource();
    });

    document.getElementById("wrapper").addEventListener("click", async (e) => {
        const rect = stream.getBoundingClientRect();
        const mx   = (e.clientX - rect.left) * (640 / rect.width);
        const my   = (e.clientY - rect.top)  * (480 / rect.height);
        await fetch("/click", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ x: mx, y: my })
        });
    });
</script>
</body>
</html>
"""

# ──────────────────────────────────────────────────────────────────────────────
#  HTML — VISTA PÚBLICA
# ──────────────────────────────────────────────────────────────────────────────
PUBLIC_HTML = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Live Stream · Public</title>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            background:#080c10; color:#c9d6e3;
            font-family:'Courier New',monospace; min-height:100vh;
            display:flex; flex-direction:column; align-items:center;
            justify-content:center; gap:16px; padding:24px;
        }
        .live { display:flex; align-items:center; gap:8px;
                font-size:0.75rem; color:#00ff88; letter-spacing:3px; }
        .dot { width:8px; height:8px; background:#00ff88;
               border-radius:50%; animation:blink 1.4s infinite; }
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.1} }
        .frame { width:100%; max-width:700px; border:1px solid #1a2332;
                 border-radius:8px; overflow:hidden; box-shadow:0 0 40px rgba(0,0,0,0.8); }
        img { display:block; width:100%; height:auto; user-select:none; }
        footer { font-size:0.65rem; color:#4a5568; letter-spacing:2px; text-align:center; }
    </style>
</head>
<body>
    <div class="live"><span class="dot"></span>LIVE &mdash; READ ONLY</div>
    <div class="frame">
        <img src="/video_public" alt="Live Stream — Faces Censored" draggable="false">
    </div>
    <footer>All faces are permanently censored &middot; No interaction allowed</footer>
</body>
</html>
"""

# ──────────────────────────────────────────────────────────────────────────────
#  HILO DE CAPTURA Y PROCESAMIENTO
# ──────────────────────────────────────────────────────────────────────────────
def capturar_y_procesar() -> None:
    global frame_local_jpeg, frame_publico_jpeg, coordenadas_caras, caras_visibles, frame_id

    proceso  = psutil.Process(os.getpid())
    contador = 0

    while True:
        src, _ = _get_source()

        # ── Resolver fuente ──────────────────────────────────────────────────
        src_real = src
        if isinstance(src, str):
            if _is_youtube_url(src):
                print(f"[Stream] Resolviendo YouTube: {src}")
                with _source_lock:
                    _source_status = "connecting"
                resolved = _resolver_youtube(src)
                if resolved:
                    print(f"[Stream] URL resuelta: {resolved[:80]}...")
                    src_real = resolved
                else:
                    print("[Stream] No se pudo resolver el stream de YouTube.")
                    _confirm_source(src, ok=False)
                    time.sleep(10)
                    continue
            elif src.strip().isdigit():
                src_real = int(src.strip())

        cap = cv2.VideoCapture(src_real)
        es_youtube = isinstance(src, str) and _is_youtube_url(src)
        cap = cv2.VideoCapture(src_real)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 3 if es_youtube else 1)

        if not cap.isOpened():
            print(f"[Stream] No se pudo abrir '{src}'. Reintentando en 10 s...")
            _confirm_source(src, ok=False)
            time.sleep(10)
            continue

        print(f"[Stream] Conectado a '{src}'. Procesando frames...")
        _confirm_source(src, ok=True)

        while True:
            _, hay_cambio = _get_source()
            if hay_cambio:
                print("[Stream] Nueva fuente solicitada. Reconectando...")
                cap.release()
                break

            if es_youtube:
                for _ in range(2):
                    cap.grab()  # descarta frames acumulados sin decodificar

            ret, frame = cap.read()
            if not ret:
                print("[Stream] Frame perdido. Reconectando...")
                _confirm_source(src, ok=False)
                time.sleep(2)
                cap.release()
                break

            h_f, w_f = frame.shape[:2]

            # ── Detección DNN ────────────────────────────────────────────────
            try:
                blob = cv2.dnn.blobFromImage(
                    cv2.resize(frame, (300, 300)),
                    scalefactor=1.0,
                    size=(300, 300),
                    mean=(104.0, 177.0, 123.0),
                )
                net.setInput(blob)
                detections = net.forward()
            except cv2.error as e:
                print(f"[Stream] Error en inferencia DNN, frame descartado: {e}")
                continue

            nuevas_coords: list[tuple[int,int,int,int]] = []
            nuevas_confs:  list[float] = []

            for i in range(detections.shape[2]):
                conf = float(detections[0, 0, i, 2])
                if conf < 0.55:
                    continue
                box = detections[0, 0, i, 3:7] * np.array([w_f, h_f, w_f, h_f])
                x, y, x2, y2 = box.astype(int)
                x  = max(0, x);  y  = max(0, y)
                x2 = min(w_f, x2); y2 = min(h_f, y2)
                if x2 > x and y2 > y:
                    nuevas_coords.append((x, y, x2, y2))
                    nuevas_confs.append(round(conf, 2))

            with lock:
                visibles = frozenset(caras_visibles)

            # ── Frame público: TODAS las caras censuradas (elipse) ───────────
            f_pub = frame.copy()
            for (x, y, x2, y2) in nuevas_coords:
                _pixelar_elipse(f_pub, x, y, x2, y2)
            cv2.putText(f_pub, f"FACES: {len(nuevas_coords)} | CENSORED",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 136), 2)

            # ── Frame local: censura selectiva (elipse) ──────────────────────
            f_loc = frame.copy()
            for i, (x, y, x2, y2) in enumerate(nuevas_coords):
                if i not in visibles:
                    _pixelar_elipse(f_loc, x, y, x2, y2)
            cv2.putText(f_loc, f"Caras: {len(nuevas_coords)}",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 136), 2)

            ok_pub, buf_pub = cv2.imencode(".jpg", f_pub, [cv2.IMWRITE_JPEG_QUALITY, 75])
            ok_loc, buf_loc = cv2.imencode(".jpg", f_loc, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not ok_pub or not ok_loc:
                print("[Stream] Error al codificar frame JPEG, frame descartado")
                continue

            with lock:
                coordenadas_caras  = list(zip(nuevas_coords, nuevas_confs))
                caras_visibles.intersection_update(range(len(nuevas_coords)))
                frame_local_jpeg   = buf_loc.tobytes()
                frame_publico_jpeg = buf_pub.tobytes()
                frame_id          += 1

            contador += 1
            if contador % 60 == 0:
                ram = proceso.memory_info().rss / 1024 / 1024
                print(f"[Stream] RAM: {ram:.1f} MB | Caras: {len(nuevas_coords)} | Frame #{frame_id}")

# ──────────────────────────────────────────────────────────────────────────────
#  GENERADORES MJPEG
# ──────────────────────────────────────────────────────────────────────────────
def _mjpeg_generator(get_jpeg_fn):
    ultimo_id = -1
    while True:
        with lock:
            cid  = frame_id
            jpeg = get_jpeg_fn() if cid != ultimo_id else None
            if jpeg is not None:
                ultimo_id = cid

        if jpeg is not None:
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
            )
        else:
            time.sleep(0.010)

def _stream_headers(response: Response) -> Response:
    response.headers["Cache-Control"]     = "no-cache, no-store, must-revalidate"
    response.headers["X-Accel-Buffering"] = "no"
    return response

# ──────────────────────────────────────────────────────────────────────────────
#  RUTAS FLASK
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/")
def dashboard():
    return render_template_string(DASHBOARD_HTML)

@app.route("/public")
def public_view():
    return render_template_string(PUBLIC_HTML)

@app.route("/video")
def video():
    return _stream_headers(Response(
        _mjpeg_generator(lambda: frame_local_jpeg),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    ))

@app.route("/video_public")
def video_public():
    return _stream_headers(Response(
        _mjpeg_generator(lambda: frame_publico_jpeg),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    ))

@app.route("/caras")
def caras():
    with lock:
        datos = [
            {
                "x": int(x), "y": int(y), "x2": int(x2), "y2": int(y2),
                "conf": float(conf),
                "visible": i in caras_visibles,
            }
            for i, ((x, y, x2, y2), conf) in enumerate(coordenadas_caras)
        ]
    return jsonify(datos)

@app.route("/click", methods=["POST"])
def click():
    ip = request.remote_addr or "unknown"
    if not _permitir_click(ip):
        return jsonify({"ok": False, "error": "rate_limited"}), 429

    data = request.get_json(silent=True)
    if not data or "x" not in data or "y" not in data:
        return jsonify({"ok": False, "error": "bad_request"}), 400

    try:
        mx = float(data["x"])
        my = float(data["y"])
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid_coordinates"}), 400

    with lock:
        for i, ((x, y, x2, y2), _) in enumerate(coordenadas_caras):
            if x <= mx <= x2 and y <= my <= y2:
                if i in caras_visibles:
                    caras_visibles.discard(i)
                else:
                    caras_visibles.add(i)
                break

    return jsonify({"ok": True})

@app.route("/set_source", methods=["POST"])
def set_source():
    global _pending_source, _source_status

    data = request.get_json(silent=True)
    if not data or "source" not in data:
        return jsonify({"ok": False, "error": "bad_request"}), 400

    raw: str = str(data["source"]).strip()
    if not raw:
        return jsonify({"ok": False, "error": "empty_source"}), 400

    is_camera  = raw.isdigit()
    is_url     = raw.startswith(("http://", "https://", "rtsp://", "rtmp://"))
    is_youtube = "youtube.com/watch" in raw or "youtu.be/" in raw

    if not is_camera and not is_url and not is_youtube:
        return jsonify({"ok": False, "error": "invalid_source_format"}), 400

    with _source_lock:
        _pending_source = raw
        _source_status  = "connecting"

    print(f"[API] Cambio de fuente solicitado: '{raw}'")
    return jsonify({"ok": True, "source": raw})

@app.route("/source_status")
def source_status():
    with _source_lock:
        src    = _pending_source if _pending_source is not None else _current_source
        status = _source_status
    return jsonify({"source": str(src), "status": status})

# ──────────────────────────────────────────────────────────────────────────────
#  MAIN
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    hilo = threading.Thread(target=capturar_y_procesar, daemon=True)
    hilo.start()

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_local = s.getsockname()[0]
        s.close()
    except Exception:
        ip_local = "localhost"

    print("\n✅ Sistema iniciado:")
    print(f"   Local (interactivo): http://localhost:5000")
    print(f"   Red local:           http://{ip_local}:5000")
    print(f"   Vista pública:       http://{ip_local}:5000/public")
    print(f"   Stream público:      http://{ip_local}:5000/video_public")
    print("\n   [Configura Cloudflare Tunnel para acceso externo — ver README]\n")

    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
