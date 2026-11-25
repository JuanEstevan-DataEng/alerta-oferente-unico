# Aplicación web de la alerta temprana de oferente único.
# Compatible con Hugging Face Spaces (SDK Docker, puerto 7860, usuario sin privilegios).
FROM python:3.12-slim

# LightGBM necesita OpenMP
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 usuario
WORKDIR /home/usuario/app

COPY --chown=usuario requirements-app.txt .
RUN pip install --no-cache-dir -r requirements-app.txt

COPY --chown=usuario oferente_unico/ oferente_unico/
COPY --chown=usuario pipeline/__init__.py pipeline/sincronizar.py pipeline/
COPY --chown=usuario app/ app/
COPY --chown=usuario artefactos/ artefactos/
# Copia de la capa gold y del estado: la aplicación funciona aunque el lakehouse remoto no responda
COPY --chown=usuario lakehouse/gold/ lakehouse/gold/
COPY --chown=usuario lakehouse/estado/ lakehouse/estado/

USER usuario
ENV PYTHONUNBUFFERED=1 LAKEHOUSE=/home/usuario/app/lakehouse ARTEFACTOS=/home/usuario/app/artefactos
EXPOSE 7860
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:7860/salud')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"]
