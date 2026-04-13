# Spike — Detección y Censura de Rostros en Tiempo Real con OpenCV

| Campo | Detalle |
|---|---|
| **Proyecto** | Internet de las Cosas |
| **Tecnología evaluada** | OpenCV — Haar Cascade Classifier |
| **Lenguaje** | Python 3.x |
| **Estado** | Completado |

---

## Tabla de Contenidos

1. [Objetivo](#objetivo)
2. [Contexto / Problema](#contexto--problema)
3. [Solución Implementada](#solución-implementada)
   - [Origen del modelo](#origen-del-modelo--haar-cascade-classifier)
   - [Fundamento teórico](#fundamento-teórico-del-algoritmo)
   - [Pipeline implementado](#funcionamiento-del-pipeline-implementado)
4. [Resultados / Conclusiones](#resultados--conclusiones)
5. [Limitaciones Encontradas](#limitaciones-encontradas)

---

## Objetivo

Investigar y validar la viabilidad técnica de implementar un sistema de detección de rostros en tiempo real utilizando la cámara de un computador, aplicando censura pixelada automática sobre las regiones detectadas, evaluando su rendimiento y limitaciones como base para una futura implementación en hardware embebido (Raspberry Pi 5).

---

## Contexto / Problema

En el contexto de sistemas IoT orientados a privacidad, surge la necesidad de procesar video en tiempo real directamente en el dispositivo de captura, sin depender de servicios externos en la nube. El problema central es determinar si un algoritmo clásico de visión computacional es suficiente para cubrir este caso de uso, o si se requiere un modelo basado en redes neuronales.

La pregunta que guía este spike es:

> ¿Puede el algoritmo Haar Cascade de OpenCV detectar rostros con suficiente precisión y velocidad para un sistema de censura automática en tiempo real?

---

## Solución Implementada

### Origen del modelo — Haar Cascade Classifier

El algoritmo utilizado es el **Haar Cascade Classifier**, propuesto por Paul Viola y Michael Jones en su paper *"Rapid Object Detection using a Boosted Cascade of Simple Features"* publicado en la conferencia **CVPR 2001** (IEEE Conference on Computer Vision and Pattern Recognition). Es uno de los algoritmos más influyentes en la historia de la visión computacional y fue el primero en lograr detección de rostros en tiempo real con hardware convencional de la época.

El modelo no fue entrenado durante este spike — se utiliza el clasificador **pre-entrenado** que OpenCV distribuye junto con su instalación, ubicado en:

```
cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
```

Este archivo `.xml` contiene los pesos y parámetros de un modelo entrenado por el equipo de OpenCV sobre un dataset masivo de imágenes de rostros humanos, y representa el resultado de un proceso de entrenamiento con el algoritmo AdaBoost descrito a continuación.

---

### Fundamento teórico del algoritmo

El algoritmo Viola-Jones se compone de cuatro conceptos fundamentales que trabajan en conjunto:

#### 1. Características Haar (Haar-like features)

Son patrones rectangulares de contraste claro/oscuro inspirados en las funciones wavelet de Haar. El algoritmo analiza miles de estas características sobre cada región de la imagen, buscando patrones típicos de un rostro humano, por ejemplo:

- La zona de los ojos es más oscura que las mejillas
- El puente nasal es más claro que los ojos
- La frente tiene mayor luminosidad que las cejas

Matemáticamente, el valor de una característica Haar se calcula como la diferencia de sumas de píxeles entre regiones adyacentes:

```
valor = Σ(píxeles zona clara) - Σ(píxeles zona oscura)
```

#### 2. Imagen Integral (Integral Image)

Para calcular las miles de características Haar por frame en tiempo real, el algoritmo construye una estructura de datos llamada **imagen integral**, donde cada píxel almacena la suma acumulada de todos los píxeles que están arriba y a la izquierda de él. Esto permite calcular la suma de cualquier región rectangular en exactamente 4 operaciones, independientemente del tamaño de la región, haciendo el proceso computacionalmente viable en tiempo real.

#### 3. AdaBoost

De las más de 180,000 características Haar posibles por imagen, la gran mayoría son irrelevantes para detectar rostros. El algoritmo **AdaBoost** (Adaptive Boosting) es el método de aprendizaje automático utilizado durante el entrenamiento para seleccionar únicamente las características más discriminativas — en la implementación original, alrededor de 200 características de las 180,000 disponibles. Cada característica seleccionada se convierte en un clasificador débil, y AdaBoost los combina en un clasificador fuerte ponderando su importancia individual.

#### 4. Cascade de clasificadores (Cascade of Classifiers)

Es la clave del rendimiento en tiempo real. En lugar de evaluar todas las características sobre cada región de la imagen, el algoritmo organiza los clasificadores en etapas en cascada:

```
Región → [Etapa 1: 2 features] → ¿No es cara? → Descartar inmediatamente
                                → ¿Podría ser cara? → [Etapa 2: 10 features]
                                                    → ¿No es cara? → Descartar
                                                    → ¿Podría ser cara? → [Etapa 3...]
                                                                        → ... → CARA DETECTADA
```

El 99% de las regiones de la imagen son descartadas en las primeras etapas con muy pocas operaciones. Solo las regiones que superan todas las etapas son clasificadas como rostro, reduciendo drásticamente el costo computacional total.

---

### Funcionamiento del pipeline implementado

```python
import cv2

face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)

cap = cv2.VideoCapture(0)

print("Presiona 'q' para salir")

while True:
    ret, frame = cap.read()
    if not ret:
        break

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    faces = face_cascade.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(40, 40)
    )

    for (x, y, w, h) in faces:
        cara = frame[y:y+h, x:x+w]
        cara = cv2.resize(cara, (4, 4), interpolation=cv2.INTER_LINEAR)
        cara = cv2.resize(cara, (w, h), interpolation=cv2.INTER_NEAREST)
        frame[y:y+h, x:x+w] = cara

    cv2.putText(frame, f"Caras: {len(faces)}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

    cv2.imshow("Deteccion de caras", frame)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()
```

El pipeline se ejecuta de la siguiente manera por cada frame:

**1. Captura de video**

Se inicializa el dispositivo de cámara mediante `cv2.VideoCapture(0)`, que accede a la cámara por defecto del sistema. El loop principal captura un frame por iteración con `cap.read()`, que retorna un booleano indicando éxito y la imagen como una matriz NumPy de shape `(alto, ancho, 3)` en formato BGR.

**2. Preprocesamiento**

Cada frame se convierte a escala de grises con:

```python
gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
```

El algoritmo Haar Cascade opera exclusivamente sobre imágenes en escala de grises dado que las características Haar trabajan con contrastes de intensidad luminosa, no con información de color. Operar en escala de grises también reduce el volumen de datos procesados por frame en un 66% respecto al formato BGR original.

**3. Detección de rostros**

```python
faces = face_cascade.detectMultiScale(
    gray,
    scaleFactor=1.1,
    minNeighbors=5,
    minSize=(40, 40)
)
```

| Parámetro | Valor | Descripción |
|---|---|---|
| `scaleFactor` | `1.1` | Reduce la imagen un 10% por escala en el image pyramid. Permite detectar rostros a distintas distancias. Valores más cercanos a 1.0 aumentan precisión pero elevan el costo computacional. |
| `minNeighbors` | `5` | Número mínimo de detecciones vecinas para confirmar un rostro. Actúa como filtro de falsos positivos. Valores más altos reducen falsos positivos pero pueden perder detecciones reales. |
| `minSize` | `(40, 40)` | Descarta regiones menores a 40×40 píxeles, evitando detecciones de rostros demasiado pequeños o lejanos. |

El método retorna una lista de tuplas `(x, y, w, h)` donde `x, y` es la esquina superior izquierda del bounding box y `w, h` sus dimensiones en píxeles.

**4. Censura pixelada**

```python
cara = frame[y:y+h, x:x+w]
cara = cv2.resize(cara, (4, 4), interpolation=cv2.INTER_LINEAR)
cara = cv2.resize(cara, (w, h), interpolation=cv2.INTER_NEAREST)
frame[y:y+h, x:x+w] = cara
```

Por cada bounding box detectado se aplica un efecto de pixelado mediante doble redimensionamiento. La región detectada se reduce a 4×4 píxeles destruyendo el detalle facial, luego se escala de vuelta al tamaño original con interpolación `INTER_NEAREST` para preservar el efecto de bloques cuadrados característico de la censura pixelada. Finalmente se escribe de vuelta sobre el frame original usando slicing de NumPy.

**5. Visualización**

El frame modificado se muestra en tiempo real con `cv2.imshow()`, incluyendo un contador de rostros detectados superpuesto mediante `cv2.putText()`. El loop se interrumpe cuando el usuario presiona la tecla `q`, liberando la cámara y cerrando la ventana limpiamente.

---

## Resultados / Conclusiones

- El script funciona correctamente en condiciones controladas, detectando y censurando rostros frontales en tiempo real sin latencia perceptible.
- El consumo de recursos es bajo — el algoritmo Haar Cascade no requiere GPU y opera eficientemente sobre CPU, lo que lo hace viable para hardware embebido como Raspberry Pi 5.
- La implementación es simple y no requiere dependencias externas más allá de OpenCV, facilitando su despliegue en distintos entornos.
- Se valida la viabilidad del pipeline base: **captura → preprocesamiento → detección → censura → visualización**, reutilizable con modelos más robustos.
- El algoritmo no es suficiente para un sistema de censura confiable en condiciones no controladas debido a sus limitaciones de pose e iluminación descritas a continuación.

---

## Limitaciones Encontradas

Durante las pruebas se identificaron las siguientes limitaciones inherentes al algoritmo Haar Cascade:

| Limitación | Descripción | Impacto |
|---|---|---|
| **Dependencia de pose frontal** | El clasificador fue entrenado principalmente con rostros frontales. Rotaciones superiores a ~30° en cualquier eje resultan en fallos de detección. | Alto |
| **Sensibilidad a la iluminación** | Condiciones de contraluz, sombras fuertes o iluminación no uniforme degradan significativamente la tasa de detección. | Alto |
| **Ausencia de detección en perfil** | Rostros de perfil o en ángulos pronunciados no son detectados, lo que representa una brecha crítica para un sistema de censura confiable. | Alto |
| **Falsos positivos ocasionales** | En ciertas condiciones de textura o iluminación el algoritmo detecta regiones que no corresponden a rostros. | Medio |

Estas limitaciones motivaron la evaluación de un modelo alternativo basado en redes neuronales (**MediaPipe BlazeFace**) como siguiente paso del proceso de investigación, el cual resuelve los problemas de pose e iluminación mediante una arquitectura de deep learning optimizada para dispositivos embebidos.

---

*Spike elaborado como parte del proceso de investigación técnica del proyecto IoT.*
