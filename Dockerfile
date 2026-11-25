# Aplicación web de la alerta temprana de oferente único.
# La capa gold y el estado se descargan al arrancar desde el lakehouse publicado (HF_DATASET);
# si se monta un lakehouse local (docker compose), se usa ese.
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
RUN mkdir -p lakehouse && chown usuario lakehouse

USER usuario
ENV PYTHONUNBUFFERED=1 PORT=7860 MALLOC_ARENA_MAX=2 \
    LAKEHOUSE=/home/usuario/app/lakehouse ARTEFACTOS=/home/usuario/app/artefactos \
    HF_DATASET=JuanEstevan-DataEng/secop-oferente-unico-lakehouse
EXPOSE 7860
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ[\"PORT\"]}/salud')"
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
