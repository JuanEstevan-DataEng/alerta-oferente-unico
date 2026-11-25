"""La capa silver en Spark debe producir lo mismo que la versión de referencia en pandas.

Requiere datos en lakehouse/bronze (una ejecución previa del pipeline) y Java para Spark.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

RAIZ = Path(__file__).resolve().parents[1]
LAKEHOUSE = RAIZ / "lakehouse"
pytestmark = pytest.mark.skipif(not (LAKEHOUSE / "bronze").exists(), reason="sin datos en bronze")

COMPARAR = ["entidad", "modalidad_de_contratacion", "tipo_de_contrato", "segmento_unspsc", "precio_base",
            "log_precio_base", "dias_para_ofertar", "duracion_dias", "numero_de_lotes", "anio", "mes",
            "descripcion", "fecha_de_publicacion_del", "fecha_adjudicacion", "oferente_unico", "adjudicado"]


def test_spark_igual_a_pandas(tmp_path):
    from pipeline.ejecutar_semana import leer_silver_spark, silver_pandas
    from pipeline.medallon_spark import a_silver, crear_sesion, leer_bronze

    referencia = silver_pandas(LAKEHOUSE).set_index("id_del_proceso").sort_index()
    spark = crear_sesion("prueba_silver")
    try:
        # Se lee como lo hace el pipeline: Parquet escrito por Spark y leído con pandas
        a_silver(leer_bronze(spark, LAKEHOUSE)).write.parquet(str(tmp_path / "silver"))
    finally:
        spark.stop()
    distribuido = leer_silver_spark(tmp_path / "silver").set_index("id_del_proceso").sort_index()

    assert distribuido.index.equals(referencia.index)
    for c in COMPARAR:
        a, b = distribuido[c], referencia[c]
        if c.startswith("fecha"):
            a, b = pd.to_datetime(a).dt.tz_localize(None), pd.to_datetime(b)
            iguales = (a == b) | (a.isna() & b.isna())
        elif pd.api.types.is_numeric_dtype(b) or pd.api.types.is_numeric_dtype(a):
            iguales = np.isclose(a.astype(float), b.astype(float), equal_nan=True)
        else:
            iguales = (a.fillna("<nulo>") == b.fillna("<nulo>"))
        assert np.mean(iguales) == 1.0, f"{c}: {np.mean(iguales):.4%} iguales"
