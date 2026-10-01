# Rumbo — panel de patrimonio, pensado para correr 24/7 en un contenedor
# detrás de un proxy inverso (Pangolin).
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
COPY demo/ ./demo/

# En contenedor escucha en todas las interfaces. La seguridad no la da el bind:
# la da PATRIMONIO_ORIGENES (el proxy), y no publicar el puerto fuera de la
# red interna/LAN-VPN. PATRIMONIO_NO_ABRIR evita intentar abrir un navegador.
ENV PATRIMONIO_NO_ABRIR=1 \
    PATRIMONIO_HOST=0.0.0.0 \
    PATRIMONIO_PUERTO=8765

EXPOSE 8765
CMD ["python", "-m", "app"]
