# FaceShield

Sistema de videovigilancia con censura facial selectiva en tiempo real, implementado como solución de **Edge Computing** sobre Raspberry Pi 5.

---

## Tabla de contenidos

1. [Visión del Proyecto](#1-visión-del-proyecto)
2. [Justificación de Diseño: Edge Computing vs Cloud](#2-justificación-de-diseño-edge-computing-vs-cloud)
3. [Spike Arquitectónico — Decisión de Hardware](#3-spike-arquitectónico--decisión-de-hardware)
4. [Arquitectura Final Implementada](#4-arquitectura-final-implementada)
5. [Tecnologías Utilizadas](#5-tecnologías-utilizadas)
6. [Estado del MVP](#6-estado-del-mvp)
7. [Restricciones de Hardware](#7-restricciones-de-hardware)
8. [Presupuesto](#8-presupuesto)
9. [Cómo Ejecutar el Proyecto](#9-cómo-ejecutar-el-proyecto)
10. [Limitaciones Conocidas](#10-limitaciones-conocidas)
11. [Posibles Mejoras Futuras](#11-posibles-mejoras-futuras)
12. [Cronograma](#12-cronograma)

---

## 1. Visión del Proyecto

FaceShield es un sistema de cámara de seguridad inteligente que protege la privacidad de las personas mediante **censura facial automática en tiempo real**, ejecutada íntegramente en el dispositivo edge sin depender de servicios en la nube.

### Problema que resuelve

Los sistemas de videovigilancia tradicionales capturan y transmiten video sin ningún tipo de anonimización. Esto genera riesgos concretos: filtraciones de imágenes biométricas, interceptación de transmisiones, o uso indebido de grabaciones con identidades visibles. El problema se agrava cuando el sistema graba de forma continua a residentes del hogar, menores de edad o empleados.

### Solución implementada

FaceShield detecta automáticamente todos los rostros presentes en el video y los censura mediante pixelado de forma predeterminada. El sistema opera en dos modos simultáneos:

- **Vista local (interactiva):** el operador puede hacer clic sobre un rostro detectado para revelar o volver a censurar individualmente cada cara, con control granular en tiempo real.
- **Vista pública (solo lectura):** todos los rostros permanecen permanentemente censurados sin posibilidad de interacción. Esta vista puede compartirse en la red sin exponer información biométrica.

El principio central de privacidad por diseño garantiza que **las imágenes sin censura nunca abandonan la red local**.

### Usuarios objetivo

- Hogares que desean videovigilancia sin exponer la identidad de sus residentes
- Padres que necesitan proteger la imagen de menores de edad
- Pequeños negocios u oficinas que requieren vigilancia respetando la privacidad de empleados

---

## 2. Justificación de Diseño: Edge Computing vs Cloud

La arquitectura de FaceShield está basada en Edge Computing por razones técnicas fundamentales que hacen inadecuada la alternativa de procesamiento en la nube para este caso de uso.

### Latencia y tiempo real

La censura debe aplicarse **antes de que el frame sea transmitido**. Si el video se enviara a un servidor remoto para su procesamiento y retorno, cualquier latencia de red introduciría frames sin censurar visibles para observadores del stream. El procesamiento local en la Raspberry Pi garantiza latencia mínima y predecible, sin dependencia de la calidad de la conexión a internet.

### Privacidad por diseño

Este es el argumento más crítico: si el video sin procesar se enviara a la nube, el proveedor del servicio o un atacante con acceso al canal tendría acceso a imágenes con rostros identificables. Al procesar en el edge, **los frames originales sin censura nunca salen de la red local**. El único video que sale del dispositivo ya tiene todos los rostros pixelados. Incluso si el stream fuera interceptado, el atacante obtendría únicamente video censurado.

### Optimización del ancho de banda

Transmitir video HD sin procesar de forma continua hacia la nube requiere decenas de megabits por segundo. El procesamiento local reduce la demanda de red a la transmisión de frames JPEG ya procesados, consumiendo una fracción del ancho de banda.

### Resiliencia ante fallos de conectividad

Un sistema de seguridad que depende de internet pierde su función principal exactamente cuando la conectividad falla. FaceShield opera completamente de manera local: sin internet, el sistema de detección, censura y dashboard siguen funcionando sin interrupción.

### Costo operativo

No se incurre en costos recurrentes de servicios cloud por procesamiento, almacenamiento o transferencia de datos. El costo del sistema es el hardware one-time del dispositivo edge.

---

## 3. Spike Arquitectónico — Decisión de Hardware

> Documento completo del spike: [spike_deteccion_rostros.md](spike_deteccion_rostros.md)

### 3.1 Hipótesis inicial

La arquitectura original planteaba usar la **ESP32-CAM** como nodo edge único: captura de imágenes y ejecución de un modelo de detección facial ligero (TinyML) directamente en el microcontrolador. Este enfoque habría maximizado la autonomía del nodo y minimizado el costo de hardware.

### 3.2 Evaluación técnica

Se realizó un spike técnico para validar la viabilidad de ejecutar detección facial en el ESP32. El proceso incluyó la implementación y prueba del algoritmo **Haar Cascade Classifier de OpenCV**, el modelo clásico de menor costo computacional disponible.

**Resultados del spike con Haar Cascade:**

| Limitación identificada | Descripción | Impacto |
|---|---|---|
| Dependencia de pose frontal | Rotaciones superiores a ~30° generan fallos de detección | Alto |
| Sensibilidad a la iluminación | Contraluz y sombras degradan la detección significativamente | Alto |
| Sin detección de perfil | Rostros laterales no son detectados en ninguna condición | Alto |
| Falsos positivos ocasionales | Ciertas texturas activan el detector incorrectamente | Medio |

### 3.3 Conclusión sobre el ESP32

Más allá del algoritmo utilizado, las restricciones de hardware del ESP32 hacen inviable la ejecución de modelos DNN modernos con el rendimiento necesario para censura en tiempo real:

| Recurso | ESP32 | Requerimiento mínimo para DNN |
|---|---|---|
| RAM | ~520 KB | >100 MB para SSD ResNet-10 |
| CPU | Xtensa LX6 240 MHz | Cortex-A suficientemente rápido |
| Procesamiento de video | ~5-10 FPS con Haar Cascade | ~15+ FPS para censura fluida |

La ESP32-CAM puede capturar y transmitir video con eficiencia, pero no puede procesar inferencia de red neuronal profunda con el rendimiento requerido.

### 3.4 Decisión arquitectónica: sistema híbrido

Se adoptó una **arquitectura híbrida** que mantiene el principio de edge computing pero distribuye responsabilidades según las capacidades reales del hardware:

- **ESP32-CAM:** conserva su rol como nodo de captura y transmisión de video vía stream MJPEG/HTTP
- **Raspberry Pi 5:** asume el procesamiento edge — inferencia DNN, censura y dashboard local

El modelo de detección adoptado fue **OpenCV DNN con SSD ResNet-10 (formato Caffe)**, significativamente más robusto que Haar Cascade en condiciones de iluminación variable y variaciones de pose.

Esta arquitectura mantiene todo el procesamiento sensible dentro de la red local. La Raspberry Pi sigue siendo un dispositivo **edge**: no se utiliza procesamiento en la nube en ningún punto del pipeline.

---

## 4. Arquitectura Final Implementada

### 4.1 Diagrama de flujo

```
                          RED LOCAL
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│   Fuente de video                Raspberry Pi 5 (nodo edge)    │
│                                                                 │
│  ┌─────────────────┐             ┌───────────────────────────┐  │
│  │   ESP32-CAM     │  stream     │  Hilo de captura          │  │
│  │   (MJPEG/HTTP)  │───────────► │  └─ OpenCV DNN            │  │
│  └─────────────────┘            │     (SSD ResNet-10)       │  │
│           o                     │  └─ Pixelado (censura)    │  │
│  ┌─────────────────┐            │  └─ Frame dual (local/pub) │  │
│  │   Cámara USB    │───────────► │                           │  │
│  │   (índice 0)    │            │  Flask :5000              │  │
│  └─────────────────┘            └──────────────┬────────────┘  │
│                                                │               │
│                              ┌─────────────────┴────────────┐  │
│                              │                              │  │
│                   Vista local (interactiva)    Vista pública │  │
│                                                             │  │
│              ┌──────────────────────┐   ┌────────────────┐  │  │
│              │  /                   │   │  /public       │  │  │
│              │  Dashboard           │   │  Solo lectura  │  │  │
│              │  Click → toggle      │   │  Siempre       │  │  │
│              │  censura por cara    │   │  censurado     │  │  │
│              │                      │   │                │  │  │
│              │  /video              │   │  /video_public │  │  │
│              │  Stream MJPEG        │   │  Stream MJPEG  │  │  │
│              │  censura selectiva   │   │  sin censura   │  │  │
│              │                      │   │  removible     │  │  │
│              └──────────────────────┘   └────────────────┘  │  │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 Componentes del sistema

#### ESP32-CAM — Nodo de captura

Actúa como fuente de video del sistema. Transmite el stream MJPEG por HTTP dentro de la red local. No realiza ningún procesamiento de imagen: su única responsabilidad es capturar y transmitir los frames crudos.

Alternativamente, puede usarse cualquier cámara compatible con OpenCV como fuente de video (cámara USB, cámara integrada, o cualquier stream RTSP/HTTP).

#### Raspberry Pi 5 — Nodo Edge principal

Ejecuta todo el procesamiento sensible del sistema:

- **Hilo de captura y procesamiento:** consume el stream de video, ejecuta inferencia DNN en cada frame, aplica pixelado sobre los rostros detectados y mantiene dos versiones del frame actualizadas en memoria (frame local con censura selectiva y frame público con censura total).
- **Servidor Flask:** sirve el dashboard local, la vista pública y los streams MJPEG. Expone endpoints para control de censura y cambio de fuente de video.

#### Dashboard local (`/`)

Interfaz interactiva accesible en la red local. Muestra el stream con censura selectiva. El operador puede hacer clic directamente sobre cualquier cara detectada para alternar entre censura y visibilidad individual. Incluye panel de cambio de fuente de video en caliente.

#### Vista pública (`/public` y `/video_public`)

Interfaz de solo lectura con todos los rostros permanentemente censurados. No expone controles de interacción. Puede compartirse con personas fuera del nodo de operación sin riesgo de revelar identidades.

### 4.3 Endpoints disponibles

| Endpoint | Método | Descripción |
|---|---|---|
| `/` | GET | Dashboard local interactivo |
| `/video` | GET | Stream MJPEG con censura selectiva |
| `/public` | GET | Vista pública de solo lectura |
| `/video_public` | GET | Stream MJPEG siempre censurado |
| `/caras` | GET | JSON con coordenadas y estado de visibilidad de cada cara detectada |
| `/click` | POST | Alterna censura de una cara según coordenadas `{x, y}` |
| `/set_source` | POST | Cambia la fuente de video `{source: "url o índice"}` |
| `/source_status` | GET | Estado actual de conexión a la fuente de video |

### 4.4 Flujo de datos y privacidad

```
Frame crudo (con rostros visibles)
    │
    ▼
[OpenCV DNN — SSD ResNet-10]
    │ detecta bounding boxes
    ▼
[Módulo de pixelado]
    │ genera dos versiones en memoria:
    ├─ Frame local: solo pixela caras no marcadas como visibles
    └─ Frame público: pixela TODOS los rostros sin excepción
    │
    ▼
[Codificación JPEG]
    │
    ▼
Los frames originales sin censurar NUNCA se transmiten fuera del dispositivo
```

---

## 5. Tecnologías Utilizadas

| Tecnología | Versión | Rol en el sistema |
|---|---|---|
| Python | 3.11 | Lenguaje principal de la aplicación |
| Flask | última estable | Servidor web, streaming MJPEG, API de control |
| OpenCV (`opencv-python-headless`) | última estable | Captura de video, inferencia DNN, pixelado |
| Modelo DNN | SSD ResNet-10 (Caffe) | Detección facial robusta en condiciones variables |
| NumPy | última estable | Manipulación de arrays de imagen |
| psutil | última estable | Monitoreo de RAM en el hilo de captura |
| Docker | — | Contenedorización y despliegue reproducible |
| Docker Compose | — | Orquestación local del contenedor |

### Modelo de detección facial

El sistema utiliza el modelo **SSD ResNet-10** en formato Caffe (`res10_300x300_ssd_iter_140000.caffemodel` + `deploy.prototxt`), distribuido por el equipo de OpenCV. Este modelo fue seleccionado después del spike por su balance entre rendimiento en CPU y robustez:

- Opera con imágenes redimensionadas a 300×300 px para inferencia
- Umbral de confianza configurado en 0.55 (ajustable)
- Funciona en CPU sin requerimientos de GPU
- Compatible con la arquitectura ARM de la Raspberry Pi 5
- El procesamiento se optimiza a 2 hilos de OpenCV, dejando los 2 núcleos restantes para Flask y el streaming

---

## 6. Estado del MVP

### Funcionalidades implementadas ✅

| Funcionalidad | Descripción |
|---|---|
| Detección facial en tiempo real | Inferencia DNN por cada frame capturado |
| Censura automática completa | Todos los rostros pixelados por defecto en la vista pública |
| Censura selectiva por click | El operador puede revelar/censurar caras individualmente desde el dashboard |
| Streaming MJPEG dual | Stream local (censura selectiva) y stream público (siempre censurado) simultáneos |
| Dashboard local interactivo | Interfaz con visualización en tiempo real, contador de caras y panel de fuente |
| Vista pública de solo lectura | Interfaz sin controles, siempre censurada, apta para compartir |
| Cambio de fuente de video en caliente | El operador puede cambiar la fuente (URL o cámara) sin reiniciar la aplicación |
| Reconexión automática | El hilo de captura se reconecta automáticamente ante pérdida de conexión con la fuente |
| Manejo de errores | Inferencia DNN, codificación JPEG, descarga/carga de modelos y endpoints protegidos |
| Rate limiting | Protección básica contra abuso en el endpoint `/click` (8 clicks/segundo por IP) |
| Contenedor Docker | Imagen reproducible con modelos incluidos, lista para despliegue en RPi |

### Fuera del alcance del MVP ❌

| Funcionalidad | Razón de exclusión |
|---|---|
| Autenticación de usuarios | Fuera del alcance del MVP académico |
| Historial de capturas / almacenamiento | No implementado; el sistema es stateless entre sesiones |
| Base de datos de metadata | No implementada |
| Reconocimiento facial de personas registradas | Solo se realiza detección, no reconocimiento de identidades |
| Notificaciones o alertas | No implementadas |
| Configuración remota del dispositivo | No implementada en el alcance actual |
| Integración end-to-end con ESP32-CAM física | La ESP32-CAM se usa como fuente externa de stream; la integración de hardware fue validada conceptualmente |

---

## 7. Restricciones de Hardware

### 7.1 ESP32 — Contexto histórico (motivó el spike)

La propuesta inicial utilizaba el ESP32 como nodo edge único. Las restricciones identificadas durante el spike determinaron la necesidad de la arquitectura híbrida actual:

| Restricción | Detalle |
|---|---|
| RAM limitada | ~520 KB de RAM disponible — insuficiente para cargar modelos DNN |
| Almacenamiento flash | ~4 MB típicos — no permite almacenar pesos de modelos de detección |
| CPU Xtensa LX6 | No suficiente para inferencia DNN en tiempo real a fps aceptables |
| Sin aceleración de hardware para ML | No cuenta con NPU ni DSP para inferencia de redes neuronales |

**Capacidad real del ESP32 en este proyecto:** captura de video y transmisión MJPEG por HTTP dentro de la red local. Este es el rol en el que el ESP32 sí opera de forma efectiva.

### 7.2 Raspberry Pi 5 — Nodo edge actual

| Característica | Detalle | Relevancia para el sistema |
|---|---|---|
| CPU | Cortex-A76 quad-core 2.4 GHz | Inferencia DNN en CPU a ~15–25 FPS para 640×480 |
| RAM | 4 GB / 8 GB LPDDR4X | Suficiente para modelo SSD ResNet-10 + Flask + streaming |
| Sin GPU para ML | No cuenta con acelerador de inferencia dedicado | OpenCV DNN opera sobre CPU; rendimiento adecuado para el caso de uso |
| Hilos disponibles | 4 cores | OpenCV usa 2 hilos; Flask y streaming usan los 2 restantes |
| Ecosistema | Compatible con Python, OpenCV, Flask, Docker | Permite reutilizar el stack estándar de desarrollo |
| Consumo energético | ~5–10W en operación | Factible para funcionamiento continuo 24/7 |

**Consideración de temperatura:** en operación continua con inferencia DNN, la RPi 5 puede requerir disipador o ventilación activa para mantener rendimiento estable.

---

## 8. Presupuesto

| Componente | Rol en el sistema | Costo aproximado (COP) |
|---|---|---|
| ESP32-CAM | Nodo de captura de video y transmisión MJPEG | $50.000 – $85.000 |
| Raspberry Pi 5 (4 GB) | Nodo edge principal: detección, censura, dashboard | $250.000 – $350.000 |
| MicroSD (32 GB+) | Almacenamiento del sistema operativo de la RPi | $25.000 – $40.000 |
| Fuente de alimentación RPi | Alimentación estable para operación continua | $25.000 – $40.000 |
| Cables y accesorios ESP32 | Alimentación y conectores | $10.000 – $15.000 |
| **Total estimado** | | **$360.000 – $530.000** |

> El costo más significativo es la Raspberry Pi 5, que es el componente que hace viable la inferencia DNN en tiempo real. El ESP32-CAM es un componente de bajo costo que puede reemplazarse por cualquier cámara compatible con OpenCV.

---

## 9. Cómo Ejecutar el Proyecto

> Los modelos DNN (`deploy.prototxt` y `res10_300x300_ssd_iter_140000.caffemodel`) están incluidos en el repositorio. No se requiere descarga manual al ejecutar localmente.

### 9.1 Con Docker (recomendado para Raspberry Pi)

**Requisitos previos:** Docker y Docker Compose instalados.

```bash
# Desde la raíz del repositorio
docker compose -f docker/docker-compose.yml up --build
```

Por defecto, el contenedor usa la cámara local (`/dev/video0`). Para usar el stream de una ESP32-CAM:

```bash
# Edita docker/docker-compose.yml antes de ejecutar:
# environment:
#   - DEFAULT_VIDEO_SOURCE=http://192.168.1.x/stream

docker compose -f docker/docker-compose.yml up --build
```

El servicio queda disponible en `http://<IP-del-dispositivo>:5001`

> **Nota:** el `docker compose build` descarga los modelos DNN desde internet (~10 MB). La ejecución posterior no requiere conexión.

### 9.2 Ejecución local con Python

**Requisitos previos:** Python 3.11+

```bash
# Instalar dependencias
pip install flask opencv-python-headless numpy psutil

# (Opcional) Configurar fuente de video
export DEFAULT_VIDEO_SOURCE=http://192.168.1.x/stream   # ESP32-CAM
# o bien
export DEFAULT_VIDEO_SOURCE=0                            # Cámara local

# Ejecutar desde la raíz del repositorio
python deteccion.py
```

El sistema queda disponible en:

| URL | Descripción |
|---|---|
| `http://localhost:5000` | Dashboard local interactivo |
| `http://localhost:5000/public` | Vista pública, siempre censurada |
| `http://localhost:5000/video` | Stream MJPEG local |
| `http://localhost:5000/video_public` | Stream MJPEG público |

### 9.3 Variable de entorno

| Variable | Valores aceptados | Descripción |
|---|---|---|
| `DEFAULT_VIDEO_SOURCE` | URL (`http://...`, `rtsp://...`) o índice numérico (`0`, `1`) | Fuente de video inicial al arrancar el sistema |

Si no se define, el sistema intenta conectarse a la última fuente conocida configurada en el código. La fuente puede cambiarse en caliente desde el dashboard sin reiniciar.

---

## 10. Limitaciones Conocidas

| Limitación | Descripción |
|---|---|
| Sin autenticación | Cualquier dispositivo en la red puede acceder al dashboard y cambiar la fuente de video. No se recomienda exponer el servicio directamente a internet sin medidas adicionales. |
| Sistema sin estado persistente | Al reiniciar la aplicación, el estado de caras visibles/ocultas se pierde. El sistema no almacena historial de sesiones ni capturas. |
| Solo detección, no reconocimiento | El sistema detecta la presencia de rostros pero no identifica a las personas. No hay base de datos de personas autorizadas: la visibilidad se controla manualmente por el operador. |
| Rendimiento dependiente de la cámara | La calidad de detección varía con la resolución, el ángulo y las condiciones de iluminación de la fuente de video. |
| Integración ESP32-CAM como hardware físico | La comunicación con la ESP32-CAM se realiza vía stream HTTP. La integración end-to-end de hardware fue validada conceptualmente en el spike; el sistema acepta cualquier fuente MJPEG compatible. |
| Docker requiere acceso a `/dev/video0` | Si se usa cámara local en Docker, el dispositivo debe existir y estar accesible. Para streams de red esto no es necesario. |

---

## 11. Posibles Mejoras Futuras

| Mejora | Descripción |
|---|---|
| Autenticación básica | Agregar protección por contraseña al dashboard local para evitar acceso no autorizado en redes compartidas |
| Historial de capturas | Guardar capturas periódicas censuradas en almacenamiento local con visualización por fecha |
| Reconocimiento facial local | Integrar comparación con base de datos local (sin cloud) para censurar automáticamente solo a personas no registradas |
| Alertas locales | Notificación cuando se detectan rostros desconocidos o cuando el conteo supera un umbral |
| Soporte RTSP nativo | Mejorar la integración con cámaras IP estándar mediante RTSP |
| Interfaz de configuración | Panel para ajustar parámetros (umbral de confianza, calidad de video, frecuencia de captura) sin editar código |
| Optimización con aceleración hardware | Explorar OpenCV con soporte para NEON (ARM) o modelos convertidos a TFLite para mayor eficiencia en RPi |

---

## 12. Cronograma

El proyecto siguió una metodología de sprints semanales con releases cada dos semanas.

| Release | Período | Enfoque | Estado |
|---|---|---|---|
| Release 1 — Fundamentos y Viabilidad | Semanas 1–2 | Definición del proyecto, spike técnico, decisión de hardware | ✅ Completado |
| Release 2 — MVP Edge: Captura, Detección y Censura | Semanas 3–4 | Implementación del pipeline de detección y censura | ✅ Completado |
| Release 3 — Dashboard y Streaming | Semanas 5–6 | Dashboard local, vista pública, streaming MJPEG dual | ✅ Completado |
| Release 4 — Estabilización y Entrega | Semanas 7–8 | Manejo de errores, Docker, documentación final | ✅ Completado |

> Cronograma detallado por sprint: [cronograma.md](cronograma.md)

> **Ajuste al plan original:** el Release 3 originalmente incluía un backend REST con base de datos y almacenamiento en la nube. Tras la decisión arquitectónica del spike y los tiempos disponibles, el alcance se ajustó para priorizar un sistema edge completamente funcional y demostrable sobre la RPi, sin dependencias de infraestructura cloud.