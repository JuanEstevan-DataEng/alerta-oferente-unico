# Alerta temprana de oferente único — despliegue

Sistema que prioriza, cada semana, los procesos de contratación pública recién publicados en SECOP II
según su probabilidad de recibir **una sola oferta**, con la explicación de cada alerta.
*Priorizar, no señalar:* el riesgo de oferente único no es evidencia de corrupción.

Curso Inteligencia Artificial (535212), UAO, 2026-2S · Dilian Mayerly Madroñero Ortega y Juan Estevan Viera Cano.

- **Aplicación (Render):** https://alerta-oferente-unico.onrender.com
- **Lakehouse (bronze, gold, estado):** https://huggingface.co/datasets/JuanEstevan-DataEng/secop-oferente-unico-lakehouse

## Arquitectura

![Arquitectura del despliegue](docs/arquitectura.png)

El diagrama se regenera con `python docs/crear_diagrama.py` (logos oficiales en `docs/logos/`).

| Componente | Archivo | Qué hace |
|---|---|---|
| Entrenamiento | `entregable_3_IA.ipynb` (Colab, GPU T4) | Selecciona el modelo (E4) y exporta `artefactos/` |
| Bronze | `pipeline/ingesta.py` | Consulta procesos publicados y adjudicados de la semana |
| Silver | `pipeline/medallon_spark.py` | PySpark: deduplicación, última versión, variables derivadas |
| Estado | `oferente_unico/puntuacion.py` | Suma al historial de cada entidad los adjudicados nuevos (sin reentrenar) |
| Gold | `oferente_unico/puntuacion.py` | Puntaje, calibración, riesgo de pares, factores SHAP (TreeSHAP nativo de LightGBM) |
| Orquestación | `pipeline/ejecutar_semana.py`, `.github/workflows/pipeline_semanal.yml`, `pipeline/dags/` | Ejecución semanal (GitHub Actions o Airflow) |
| Lakehouse remoto | `pipeline/sincronizar.py` | Repositorio de datos de Hugging Face como almacenamiento de objetos |
| Hosting | `Dockerfile`, `render.yaml` | Render (Docker, plan gratuito): descarga gold y estado al arrancar y cada hora |
| Aplicación | `app/` | API FastAPI y página web: lista, ficha, evaluación 2026, simulador |

## Uso local

```bash
uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -r requirements-pipeline.txt
# Opción A: traer el lakehouse publicado
HF_DATASET=JuanEstevan-DataEng/secop-oferente-unico-lakehouse .venv/bin/python pipeline/sincronizar.py descargar --capas bronze gold estado
# Opción B: construirlo desde cero (recupera desde el corte de los datos de entrenamiento)
.venv/bin/python pipeline/ejecutar_semana.py --desde 2026-09-17
.venv/bin/python pipeline/ejecutar_semana.py                      # semanas siguientes
.venv/bin/python pipeline/validacion_prospectiva.py
.venv/bin/uvicorn app.main:app --port 8000                        # http://localhost:8000
```

Con Docker: `docker compose up -d app` (≈ 330–430 MB de RAM; cabe en el plan gratuito de Render, 512 MB) y `docker compose --profile pipeline run --rm pipeline`.

## Verificación

| Prueba | Resultado |
|---|---|
| `tests/verificar_contra_notebook.py`: el paquete reproduce el notebook en los 40 589 procesos de 2026 | 100 % en riesgo, pares, alertas y factores |
| `tests/test_silver_spark.py`: silver en Spark igual a la versión pandas | 100 % en 16 columnas |
| `tests/test_api.py`: API web | 7 pruebas |
| `pipeline/validacion_prospectiva.py`: semanas posteriores al entrenamiento | PR-AUC 0,783 en 7 210 procesos; precisión de las 50 primeras alertas 0,86–0,96 |

## Mantenimiento

- **Cada semana:** ingesta, actualización del historial y nueva lista (automático).
- **Cada mes:** revisar la validación prospectiva; si la calibración se desvía (probabilidad media frente a tasa real), reajustar el calibrador con las semanas cuyo resultado ya se conoce.
- **Cada año:** reentrenar en Colab con el año completo más reciente y reemplazar `artefactos/` (mismas versiones de scikit-learn y LightGBM que registre `metadatos.json`).
