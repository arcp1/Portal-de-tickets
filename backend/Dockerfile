FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# fonts-dejavu-core: la tipografía de las etiquetas QR (services/etiqueta_service.py).
# Sin ella Pillow cae a su letra por defecto y la etiqueta sale fea pero sale.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt

COPY . .

# El backend no corre como root.
#
# Con `cap_drop: ALL` un root sin capacidades ya no puede gran cosa, pero sigue
# siendo dueño de todo lo que tenga montado: el codigo fuente entra por un bind
# desde el host, y un fallo de ejecucion remota bastaria para reescribirlo. Con
# un usuario propio, lo unico que puede tocar son las dos carpetas donde de
# verdad escribe.
#
# Los directorios se crean y se asignan **aqui**, antes de que existan los
# volumenes: Docker copia el propietario de la imagen al crear un volumen
# nombrado por primera vez, asi que de esta forma nacen ya con el dueño bueno.
RUN useradd --system --create-home --uid 10001 portal \
    && mkdir -p /app/adjuntos /app/documentos \
    && chown -R portal:portal /app/adjuntos /app/documentos

USER portal

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
