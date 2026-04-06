## 5. Cronograma Tentativo

> Sprints de 1 semana · Releases cada 2 semanas

### Leyenda
| Etiqueta | Descripción |
|---|---|
| `must-have` | Estrictamente necesario para que el proyecto funcione |
| `nice-to-have` | Mejora opcional |
| `spike` | Tarea de investigación sobre la mayor incertidumbre técnica |
| `retro` | Retrospectiva con el profesor |
| `freeze` | Congelación de nuevas funcionalidades |

---

## Release 1 — Fundamentos y Viabilidad *(Semanas 1 y 2)*

### Sprint 1 — Definición *(Semana 1)*
| Tarea | Tipo |
|---|---|
| Crear repositorio GitHub con README.md inicial (visión, edge vs cloud, presupuesto, restricciones de hardware) | `must-have` |
| Definir backlog priorizado en GitHub Projects con etiquetas must-have / nice-to-have | `must-have` |
| Incluir diagrama de bloques: Cámara → ESP32 (detección + blur) → API REST → Storage → Dashboard | `must-have` |
| Identificar y documentar el spike arquitectónico: viabilidad de modelo facial TinyML en ESP32 | `must-have` |
| Publicar cronograma tentativo en el repositorio | `must-have` |

### Sprint 2 — El Spike *(Semana 2)*
| Tarea | Tipo |
|---|---|
| Spike: probar modelo de detección facial liviano (Edge Impulse FOMO) en ESP32-CAM | `spike` |
| Spike: medir FPS real y latencia de inferencia — decidir ESP32 vs migración a Raspberry Pi | `spike` |
| Documentar hallazgos del spike: qué funciona, qué no, decisión de hardware final | `must-have` |
| Retrospectiva Release 1 con el profesor + entrega del reporte del Spike | `retro` |

---

## Release 2 — MVP Edge: Captura, Detección y Censura *(Semanas 3 y 4)*

### Sprint 3 *(Semana 3)*
| Tarea | Tipo |
|---|---|
| Configurar captura periódica de imágenes desde ESP32-CAM (cada 5–10 s) con manejo de fallos de hardware | `must-have` |
| Integrar modelo ligero de detección facial en el dispositivo (TinyML / Edge Impulse) | `must-have` |
| Implementar conectividad WiFi en la ESP32 con reconexión automática ante pérdida de señal | `must-have` |

### Sprint 4 *(Semana 4)*
| Tarea | Tipo |
|---|---|
| Implementar censura de rostros detectados (blur, pixelado o máscara) sobre la imagen | `must-have` |
| Desarrollar capa de abstracción de procesamiento de imágenes (funciones: detectar, censurar, procesar) | `must-have` |
| Implementar manejo básico de errores: fallos en captura, conexión WiFi y envío de datos | `must-have` |
| Retrospectiva Release 2 + ajuste del backlog | `retro` |

---

## Release 3 — Backend, Almacenamiento y Dashboard *(Semanas 5 y 6)*

### Sprint 5 *(Semana 5)*
| Tarea | Tipo |
|---|---|
| Enviar imágenes censuradas desde la ESP32 al backend vía HTTP/MQTT | `must-have` |
| Desarrollar API REST: recibir imágenes, consultar listado, acceder a imagen específica | `must-have` |
| Configurar sistema de almacenamiento de archivos (servidor local o bucket en nube) para guardar imágenes procesadas | `must-have` |

### Sprint 6 *(Semana 6)*
| Tarea | Tipo |
|---|---|
| Configurar base de datos para metadata: ID de imagen, fecha/hora, ID de dispositivo, ubicación (opcional) y URL de referencia al archivo | `must-have` |
| Desarrollar dashboard web básico: listado de imágenes, visualización individual y fecha/hora | `must-have` |
| Dashboard local con opción de ver imágenes sin censura (alternar censurada/original) | `nice-to-have` |
| Retrospectiva Release 3 + ajuste final de backlog antes del freeze | `retro` |

---

## Release 4 — Pulido y Entrega Final *(Semanas 7, 8 y Finales)*

### Sprint 7 — Feature Freeze *(Semana 7)*
| Tarea | Tipo |
|---|---|
| Feature freeze: no nuevas funcionalidades a partir de este punto | `freeze` |
| Corrección de bugs críticos y estabilización del sistema end-to-end | `must-have` |
| Control de acceso y autenticación de usuarios en el dashboard | `nice-to-have` |
| Configuración remota del dispositivo desde el dashboard (frecuencia, tipo de censura, calidad) | `nice-to-have` |
| Procesamiento de video en tiempo real / streaming (si el hardware lo permite) | `nice-to-have` |
| Actualizar README con arquitectura final, decisiones tomadas y resultados del spike | `must-have` |

### Sprint 8 — Entrega Final *(Semana 8 + Finales)*
