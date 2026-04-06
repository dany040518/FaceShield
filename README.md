# FaceShield
## 1. Visión del Proyecto

El proyecto propone el desarrollo de una cámara de seguridad inteligente que integra técnicas de inteligencia artificial para proteger la privacidad de las personas dentro de un entorno doméstico. El problema principal que busca resolver es la exposición innecesaria de la identidad de las personas en los sistemas tradicionales de videovigilancia, los cuales capturan y transmiten imágenes sin ningún tipo de anonimización, lo que puede derivar en riesgos de seguridad, filtraciones de datos o uso indebido de información sensible como los rostros.

La solución planteada consiste en un dispositivo capaz de detectar y reconocer rostros en tiempo real, con el objetivo de difuminar únicamente aquellos que pertenecen a personas previamente registradas como miembros del hogar. De esta manera, se logra un equilibrio entre seguridad y privacidad, ya que el sistema sigue permitiendo la vigilancia del entorno sin comprometer la identidad de los residentes.

Este sistema está dirigido principalmente a usuarios domésticos que desean implementar medidas de seguridad sin sacrificar su privacidad, aunque también puede ser aplicado en pequeños negocios u oficinas donde se requiera proteger la identidad de empleados o familiares. Su valor diferencial radica en que no solo realiza detección facial, sino que aplica anonimización selectiva, lo cual no es común en soluciones tradicionales.

- Usuarios objetivo
  - Hogares (familias que quieren privacidad)
  - Oficinas pequeñas
  - Negocios que desean proteger identidad de empleados
  - Padres que quieren proteger la identidad de menores
 
## 2. Justificación de Diseño (Edge vs Cloud)
   
La decisión de implementar este sistema utilizando computación en el borde (edge computing) responde a varios factores técnicos fundamentales. En primer lugar, el procesamiento local permite reducir significativamente la latencia, lo cual es crucial en un sistema de videovigilancia que debe operar en tiempo real y de manera continua. Al ejecutar los algoritmos directamente en el dispositivo, se evita el retraso asociado al envío de datos a servidores remotos y su posterior procesamiento.

En segundo lugar, esta arquitectura contribuye a la optimización del ancho de banda. Si el procesamiento se realizara en la nube, sería necesario transmitir constantemente video sin procesar, lo que implicaría un alto consumo de datos. En cambio, al procesar la información localmente, solo se envía el contenido ya filtrado o relevante, reduciendo considerablemente la carga de red.

Otro aspecto clave es la seguridad y la privacidad. Al realizar la detección y difuminado de rostros directamente en el dispositivo, las imágenes sin censura nunca abandonan el entorno local. Esto minimiza el riesgo de ataques como la interceptación de datos (man-in-the-middle) o accesos no autorizados a información sensible. Incluso en caso de que el sistema sea comprometido, las imagenes que veran ya estaran censuradas.

Adicionalmente, el enfoque en edge computing permite que el sistema sea más resiliente, ya que puede seguir funcionando incluso sin conexión a internet. Esto garantiza una operación continua, característica esencial en dispositivos de seguridad. Finalmente, también se logra una reducción en los costos operativos, al evitar el uso constante de servicios de procesamiento en la nube.

## 3. Presupuesto

| Componente      | Descripción                                                                    | Costo aproximado       |
| --------------- | ------------------------------------------------------------------------------ | ---------------------- |
| ESP32           | Microcontrolador principal para procesamiento en edge                          | $30.000 – $60.000 COP  |
| Cámara          | Cámara integrada del ESP32 (si no se reutiliza la existente)                   | $20.000 – $25.000 COP |
| Fuente y cables | Alimentación y conexiones                                                      | $10.000 COP  |
| Nube (AWS) Free Tier    | Uso de servicios como almacenamiento (S3), servidor (EC2 o Lambda) y dashboard | $0 – $60.000 COP / mes |

Presupesto total de 60.000 - 95.000 COP

## 4. Restricciones del Hardware

El sistema presenta varias limitaciones derivadas del uso del microcontrolador ESP32 como dispositivo principal de procesamiento. En primer lugar, la capacidad de procesamiento es reducida, lo que dificulta la ejecución de modelos de inteligencia artificial complejos, especialmente aquellos relacionados con reconocimiento facial en tiempo real. Por esta razón, es necesario utilizar modelos optimizados y de bajo consumo computacional, como los diseñados para entornos de TinyML.

Una limitación crítica está relacionada con el procesamiento de video en tiempo real. Debido a las restricciones del ESP32, procesar un flujo continuo de video cuadro por cuadro resulta altamente demandante y, en muchos casos, inviable sin afectar el rendimiento del sistema. Por ello, se plantea como alternativa técnica la captura de imágenes en intervalos de tiempo (por ejemplo, cada 2 segundos) para su procesamiento individual. Esta estrategia reduce significativamente la carga computacional, permitiendo mantener un funcionamiento estable sin comprometer completamente la funcionalidad del sistema.

En cuanto a la memoria, el ESP32 cuenta con recursos limitados tanto en RAM (~520 KB) como en almacenamiento flash (~4MB típicamente), lo que restringe el tamaño de los modelos que pueden implementarse y la cantidad de datos que pueden manejarse localmente. Esto implica que no es viable almacenar grandes volúmenes de información directamente en el dispositivo.

Respecto al almacenamiento, en esta propuesta se plantea el uso de servicios en la nube de AWS, como almacenamiento en S3, lo que permite guardar registros de video o imágenes de manera escalable. Sin embargo, esto introduce la necesidad de gestionar correctamente los costos y definir políticas de retención de datos, como la eliminación automática después de cierto tiempo.

Finalmente, es importante tener en cuenta que, aunque el ESP32 es adecuado para un prototipo funcional, existe la posibilidad de que su rendimiento no sea suficiente para cumplir con todos los requerimientos del sistema. En ese caso, se considerará la migración a una plataforma con mayor capacidad de procesamiento, como una Raspberry Pi, la cual permitiría implementar procesamiento de video en tiempo real y modelos de inteligencia artificial más avanzados.

## 5. Diagrama de bloques / Arquitectura propuesta

![Arquitectura](/archivos/ArquitecturaEnBloques.png)

El sistema se organiza en una arquitectura distribuida compuesta por tres bloques principales: fuente de datos, dispositivo edge y backend en la nube, además de una capa de visualización.

En el bloque de datos, la cámara de seguridad actúa como un sensor que genera imágenes crudas del entorno. Esta no realiza procesamiento, sino que provee la información al dispositivo edge.

El dispositivo edge (ESP32) es el encargado de controlar la captura de imágenes y ejecutar el procesamiento local. En este nivel se realiza la detección de rostros y su posterior censura, garantizando que los datos sensibles sean anonimizados antes de salir del dispositivo. Este enfoque sigue el paradigma de edge computing, reduciendo riesgos de privacidad y exposición de información biométrica.

Una vez procesadas, las imágenes son enviadas mediante protocolos HTTP/HTTPS o MQTT al backend en la nube, donde se gestionan a través de una API REST. Esta API actúa como intermediaria entre el dispositivo y los sistemas de almacenamiento.

Dentro del backend se separan claramente dos componentes de persistencia:

Una base de datos, encargada de almacenar la metadata de cada imagen (como fecha, identificador y URL).
Un sistema de almacenamiento de archivos (storage), donde se guardan las imágenes censuradas.

Esta separación permite mejorar la escalabilidad, el rendimiento y el mantenimiento del sistema, siguiendo buenas prácticas de arquitectura.

El dashboard web consume la API REST para consultar la información almacenada y visualizar las imágenes, permitiendo al usuario acceder al histórico de capturas.

Adicionalmente, como funcionalidad opcional (nice-to-have), se propone un dashboard local que permite acceder a las imágenes sin censura dentro de la red local, brindando al usuario mayor control sobre su privacidad.


## 4. Cronograma

[Cronograma](cronograma.md)


