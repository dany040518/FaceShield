#!/usr/bin/env python3
"""
Face Detection Stream — Modo dual
  /         → Dashboard local interactivo (click para censurar/revelar, cambio de fuente)
  /video    → MJPEG local, censura selectiva
  /public   → Vista pública, solo lectura
  /video_public → MJPEG siempre censurado, sin interacción posible
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
from collections import defaultdict

# ──────────────────────────────────────────────────────────────────────────────
#  OPTIMIZACIONES OpenCV (aprovecha los 4 cores del RPi 5)
# ──────────────────────────────────────────────────────────────────────────────
cv2.setUseOptimized(True)
cv2.setNumThreads(2)   # deja 2 cores libres para Flask/streaming

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
            os.remove(destino)  # eliminar archivo parcialmente descargado
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

# Lock único protege todo el estado mutable compartido entre hilos
lock = threading.Lock()

# Frames pre-codificados (bytes JPEG listos para enviar)
frame_local_jpeg:   bytes | None = None
frame_publico_jpeg: bytes | None = None
frame_id: int = 0

# Estado de detecciones y censura
coordenadas_caras: list[tuple[tuple[int,int,int,int], float]] = []
caras_visibles:    set[int] = set()

# ──────────────────────────────────────────────────────────────────────────────
#  FUENTE DE VIDEO — mutable desde la ruta /set_source
#  "pending" indica que el hilo de captura debe reconectarse con la nueva fuente.
# ──────────────────────────────────────────────────────────────────────────────
DEFAULT_SOURCE = os.environ.get("DEFAULT_VIDEO_SOURCE", "http://10.151.198.60:5000/video")

_source_lock    = threading.Lock()
_current_source: str | int = DEFAULT_SOURCE   # str = URL, int = índice de cámara
_pending_source: str | int | None = None       # None = sin cambio pendiente
_source_status:  str = "connecting"            # "connecting" | "ok" | "error"

def _get_source() -> tuple[str | int, bool]:
    """Retorna (fuente_actual, hay_cambio_pendiente)."""
    with _source_lock:
        if _pending_source is not None:
            return _pending_source, True
        return _current_source, False

def _confirm_source(src: str | int, ok: bool) -> None:
    """El hilo de captura llama esto cuando termina de conectarse."""
    global _current_source, _pending_source, _source_status
    with _source_lock:
        _current_source = src
        _pending_source = None
        _source_status  = "ok" if ok else "error"

# ──────────────────────────────────────────────────────────────────────────────
#  RATE LIMITING para /click  (protección básica por IP)
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
#  HTML — DASHBOARD LOCAL (interactivo)
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
            --green:  #00ff88; --red: #ff3a3a;
            --amber:  #ffb800; --blue: #38bdf8;
            --bg:     #080c10; --panel: #0d1117;
            --border: #1a2332; --text: #c9d6e3; --dim: #4a5568;
        }
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            background: var(--bg); color: var(--text);
            font-family: 'Exo 2', sans-serif; min-height: 100vh;
            display: flex; flex-direction: column; align-items: center;
            padding: 24px 16px; gap: 20px;
        }
        body::before {
            content: ''; position: fixed; inset: 0;
            background: repeating-linear-gradient(0deg,transparent,transparent 2px,
                rgba(0,255,136,0.015) 2px,rgba(0,255,136,0.015) 4px);
            pointer-events: none; z-index: 999;
        }
        header { display:flex; align-items:center; gap:14px; width:100%; max-width:700px; }
        .logo {
            width:38px; height:38px; border:2px solid var(--green);
            border-radius:6px; display:grid; place-items:center; font-size:1.2rem;
            box-shadow:0 0 12px rgba(0,255,136,0.3);
        }
        h1 { font-family:'Share Tech Mono',monospace; font-size:1rem; letter-spacing:3px;
             color:var(--green); text-transform:uppercase; }
        .badge {
            margin-left:auto; font-family:'Share Tech Mono',monospace; font-size:0.7rem;
            padding:4px 10px; border:1px solid var(--green); border-radius:20px;
            color:var(--green); display:flex; align-items:center; gap:6px;
        }
        .dot { width:7px; height:7px; background:var(--green); border-radius:50%;
               animation:blink 1.4s infinite; }
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.1} }

        /* ── Source panel ─────────────────────────────────────────────────── */
        .source-panel {
            width:100%; max-width:700px;
            background:var(--panel); border:1px solid var(--border);
            border-radius:8px; padding:14px 16px;
            display:flex; flex-direction:column; gap:10px;
        }
        .source-row {
            display:flex; gap:8px; align-items:center;
        }
        .source-label {
            font-family:'Share Tech Mono',monospace; font-size:0.65rem;
            color:var(--dim); letter-spacing:2px; text-transform:uppercase;
            margin-bottom:2px;
        }
        .source-input {
            flex:1; background:#060a0f; border:1px solid var(--border);
            border-radius:6px; padding:8px 12px;
            font-family:'Share Tech Mono',monospace; font-size:0.82rem;
            color:var(--green); outline:none; transition:border-color 0.2s;
        }
        .source-input:focus { border-color:var(--green); }
        .source-input::placeholder { color:var(--dim); }
        .source-btn {
            background:transparent; border:1px solid var(--green);
            border-radius:6px; padding:8px 18px;
            font-family:'Share Tech Mono',monospace; font-size:0.78rem;
            color:var(--green); cursor:pointer; letter-spacing:1px;
            transition:background 0.15s, color 0.15s;
            white-space:nowrap;
        }
        .source-btn:hover  { background:var(--green); color:#080c10; }
        .source-btn:active { opacity:0.7; }
        .source-btn:disabled { opacity:0.35; cursor:not-allowed; }
        .source-status {
            font-family:'Share Tech Mono',monospace; font-size:0.7rem;
            display:flex; align-items:center; gap:7px; min-height:18px;
        }
        .source-status .indicator {
            width:7px; height:7px; border-radius:50%; flex-shrink:0;
        }
        .status-ok         { color:var(--green); }
        .status-ok .indicator         { background:var(--green); }
        .status-connecting { color:var(--amber); }
        .status-connecting .indicator { background:var(--amber); animation:blink 0.8s infinite; }
        .status-error      { color:var(--red); }
        .status-error .indicator      { background:var(--red); }
        .source-hint {
            font-size:0.68rem; color:var(--dim); letter-spacing:0.5px;
        }
        .source-hint code {
            font-family:'Share Tech Mono',monospace; color:#5a7a8a;
            background:#0a0f14; padding:1px 5px; border-radius:3px;
        }

        /* ── Video + overlay ──────────────────────────────────────────────── */
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
        #overlay { position:absolute; top:0; left:0; width:100%; height:100%;
                   pointer-events:none; }
        .stats { display:flex; gap:12px; width:100%; max-width:700px; }
        .stat-card {
            flex:1; background:var(--panel); border:1px solid var(--border);
            border-radius:8px; padding:12px 16px; display:flex;
            flex-direction:column; gap:4px;
        }
        .stat-label { font-family:'Share Tech Mono',monospace; font-size:0.65rem;
                      color:var(--dim); letter-spacing:2px; text-transform:uppercase; }
        .stat-value { font-family:'Share Tech Mono',monospace; font-size:1.4rem;
                      color:var(--green); }
        .hint { font-size:0.75rem; color:var(--dim); letter-spacing:1px; }
    </style>
</head>
<body>
<header>
    <div class="logo">📷</div>
    <h1>Face Detection · Local</h1>
    <div class="badge"><span class="dot"></span>LIVE</div>
</header>

<!-- ── Source switcher ────────────────────────────────────────────────────── -->
<div class="source-panel">
    <span class="source-label">▸ Fuente de video</span>
    <div class="source-row">
        <input
            id="sourceInput"
            class="source-input"
            type="text"
            placeholder="http://192.168.1.x:5000/video  ó  0"
            spellcheck="false"
            autocomplete="off"
        >
        <button id="sourceBtn" class="source-btn" onclick="setSource()">CONECTAR</button>
    </div>
    <div id="sourceStatus" class="source-status status-connecting">
        <span class="indicator"></span>
        <span id="sourceStatusText">Cargando estado...</span>
    </div>
    <p class="source-hint">
        Escribe una URL de stream (ej. <code>http://10.0.0.5:5000/video</code>)
        o <code>0</code> para usar la cámara del dispositivo.
    </p>
</div>

<!-- ── Video stream ───────────────────────────────────────────────────────── -->
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
            ctx.strokeStyle = color; ctx.lineWidth = 1.5;
            ctx.strokeRect(x, y, w, h);
            const cs = 10; ctx.lineWidth = 3;
            ctx.beginPath();
            ctx.moveTo(x, y+cs);     ctx.lineTo(x, y);       ctx.lineTo(x+cs, y);
            ctx.moveTo(x+w-cs, y);   ctx.lineTo(x+w, y);     ctx.lineTo(x+w, y+cs);
            ctx.moveTo(x, y+h-cs);   ctx.lineTo(x, y+h);     ctx.lineTo(x+cs, y+h);
            ctx.moveTo(x+w-cs, y+h); ctx.lineTo(x+w, y+h);   ctx.lineTo(x+w, y+h-cs);
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

    // ── Source status polling ────────────────────────────────────────────────
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
            // connecting
            statusEl.classList.add("status-connecting");
            statusTextEl.textContent = `Conectando con ${data.source}...`;
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

    // ── Set source ───────────────────────────────────────────────────────────
    async function setSource() {
        const raw = sourceInput.value.trim();
        if (!raw) return;

        // Validación mínima: solo se permiten URLs http/rtsp/rtmp o dígito numérico
        const isCamera = /^\d+$/.test(raw);
        const isUrl    = /^(http|rtsp|rtmp):\/\/.+/.test(raw);
        if (!isCamera && !isUrl) {
            statusEl.className = "source-status status-error";
            statusTextEl.textContent = "Formato inválido. Usa una URL o un número de cámara.";
            return;
        }

        sourceBtn.disabled = true;
        statusEl.className = "source-status status-connecting";
        statusTextEl.textContent = `Solicitando cambio a: ${raw}...`;

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
            // Si ok, el polling de /source_status actualizará la UI automáticamente
        } catch {
            statusEl.className = "source-status status-error";
            statusTextEl.textContent = "No se pudo contactar al servidor.";
            sourceBtn.disabled = false;
        }
    }

    // Permitir Enter en el input
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
#  HTML — VISTA PÚBLICA (solo lectura, sin JS interactivo)
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
        .live {
            display:flex; align-items:center; gap:8px;
            font-size:0.75rem; color:#00ff88; letter-spacing:3px;
        }
        .dot {
            width:8px; height:8px; background:#00ff88;
            border-radius:50%; animation:blink 1.4s infinite;
        }
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.1} }
        .frame {
            width:100%; max-width:700px;
            border:1px solid #1a2332; border-radius:8px;
            overflow:hidden; box-shadow:0 0 40px rgba(0,0,0,0.8);
        }
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
#  UTILIDAD: pixelar una región del frame en su lugar (in-place)
# ──────────────────────────────────────────────────────────────────────────────
def _pixelar(img: np.ndarray, x: int, y: int, x2: int, y2: int) -> None:
    region = img[y:y2, x:x2]
    if region.size == 0:
        return
    small = cv2.resize(region, (6, 6), interpolation=cv2.INTER_LINEAR)
    img[y:y2, x:x2] = cv2.resize(small, (x2 - x, y2 - y), interpolation=cv2.INTER_NEAREST)


# ──────────────────────────────────────────────────────────────────────────────
#  HILO DE CAPTURA Y PROCESAMIENTO
#
#  Detecta cambios en _pending_source y reconecta automáticamente.
# ──────────────────────────────────────────────────────────────────────────────
def capturar_y_procesar() -> None:
    global frame_local_jpeg, frame_publico_jpeg, coordenadas_caras, caras_visibles, frame_id

    proceso  = psutil.Process(os.getpid())
    contador = 0

    while True:   # loop externo: reconexión automática
        src, _ = _get_source()

        # Convertir a int si es un índice de cámara ("0", "1", …)
        if isinstance(src, str) and src.strip().isdigit():
            src = int(src.strip())

        cap = cv2.VideoCapture(src)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_BUFFERSIZE,   1)

        if not cap.isOpened():
            print(f"[Stream] No se pudo abrir '{src}'. Reintentando en 10 s...")
            _confirm_source(src, ok=False)
            time.sleep(10)
            continue

        print(f"[Stream] Conectado a '{src}'. Procesando frames...")
        _confirm_source(src, ok=True)

        while True:   # loop interno: frames
            # ── Detectar cambio de fuente solicitado desde la UI ───────────
            _, hay_cambio = _get_source()
            if hay_cambio:
                print("[Stream] Nueva fuente solicitada. Reconectando...")
                cap.release()
                break   # vuelve al loop externo para abrir la nueva fuente

            ret, frame = cap.read()
            if not ret:
                print("[Stream] Frame perdido. Reconectando...")
                _confirm_source(src, ok=False)
                time.sleep(2)
                cap.release()
                break

            h_f, w_f = frame.shape[:2]

            # ── Detección DNN ─────────────────────────────────────────────
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

            nuevas_coords: list[tuple[int, int, int, int]] = []
            nuevas_confs:  list[float]                      = []

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

            # ── Frame público: TODAS las caras censuradas ──────────────────
            f_pub = frame.copy()
            for (x, y, x2, y2) in nuevas_coords:
                _pixelar(f_pub, x, y, x2, y2)
            cv2.putText(
                f_pub, f"FACES: {len(nuevas_coords)} | CENSORED",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 136), 2,
            )

            # ── Frame local: censura selectiva ─────────────────────────────
            f_loc = frame.copy()
            for i, (x, y, x2, y2) in enumerate(nuevas_coords):
                if i not in visibles:
                    _pixelar(f_loc, x, y, x2, y2)
            cv2.putText(
                f_loc, f"Caras: {len(nuevas_coords)}",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 136), 2,
            )

            ok_pub, buf_pub = cv2.imencode(".jpg", f_pub, [cv2.IMWRITE_JPEG_QUALITY, 75])
            ok_loc, buf_loc = cv2.imencode(".jpg", f_loc, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not ok_pub or not ok_loc:
                print("[Stream] Error al codificar frame JPEG, frame descartado")
                continue
            jpg_pub = buf_pub.tobytes()
            jpg_loc = buf_loc.tobytes()

            with lock:
                coordenadas_caras  = list(zip(nuevas_coords, nuevas_confs))
                caras_visibles.intersection_update(range(len(nuevas_coords)))
                frame_local_jpeg   = jpg_loc
                frame_publico_jpeg = jpg_pub
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
    response.headers["Cache-Control"]    = "no-cache, no-store, must-revalidate"
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
    resp = Response(
        _mjpeg_generator(lambda: frame_local_jpeg),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )
    return _stream_headers(resp)


@app.route("/video_public")
def video_public():
    resp = Response(
        _mjpeg_generator(lambda: frame_publico_jpeg),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )
    return _stream_headers(resp)


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
    """
    Cambia la fuente de video del hilo de captura.
    Acepta JSON: { "source": "http://..." }  o  { "source": "0" }
    """
    global _pending_source, _source_status

    data = request.get_json(silent=True)
    if not data or "source" not in data:
        return jsonify({"ok": False, "error": "bad_request"}), 400

    raw: str = str(data["source"]).strip()
    if not raw:
        return jsonify({"ok": False, "error": "empty_source"}), 400

    # Validación básica en backend
    is_camera = raw.isdigit()
    is_url    = raw.startswith(("http://", "https://", "rtsp://", "rtmp://"))
    if not is_camera and not is_url:
        return jsonify({"ok": False, "error": "invalid_source_format"}), 400

    with _source_lock:
        _pending_source = raw
        _source_status  = "connecting"

    print(f"[API] Cambio de fuente solicitado: '{raw}'")
    return jsonify({"ok": True, "source": raw})


@app.route("/source_status")
def source_status():
    """Devuelve el estado actual de la fuente de video."""
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