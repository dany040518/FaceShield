FROM python:3.11-slim

# Dependencias del sistema que necesita OpenCV
RUN apt-get update && apt-get install -y \
    libglib2.0-0 \
    libgl1 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    wget \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY docker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Descargar los modelos DNN al construir la imagen
RUN wget -q -O deploy.prototxt \
    "https://raw.githubusercontent.com/opencv/opencv/master/samples/dnn/face_detector/deploy.prototxt" && \
    wget -q -O res10_300x300_ssd_iter_140000.caffemodel \
    "https://github.com/opencv/opencv_3rdparty/raw/dnn_samples_face_detector_20170830/res10_300x300_ssd_iter_140000.caffemodel"

COPY deteccion.py .

EXPOSE 5000

CMD ["python", "deteccion.py"]