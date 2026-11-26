"""Capa bronze: ingesta desde la API Socrata de SECOP II (datos.gov.co, recurso p6dx-8zbt).

Se guardan los registros tal como llegan (texto), particionados por tipo de consulta y fecha de
ingesta, en formato Parquet:

    lakehouse/bronze/publicados/fecha_ingesta=AAAA-MM-DD/desde_X_hasta_Y.parquet   procesos publicados
    lakehouse/bronze/adjudicados/fecha_ingesta=AAAA-MM-DD/desde_X_hasta_Y.parquet  procesos adjudicados

Un archivo por consulta: dos ingestas el mismo día (p. ej. una recuperación y la diaria) no se
sobrescriben. Si un proceso aparece en varias, silver conserva la versión de la ingesta más reciente.

Los publicados son los que se puntúan; los adjudicados actualizan el historial de las entidades.
"""
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from oferente_unico.transformaciones import COLUMNAS_API, MODALIDADES_COMPETITIVAS, RECURSO_PROCESOS  # noqa: E402

TAMANO_PAGINA = 50_000
MODALIDADES_SQL = ",".join(f"'{m}'" for m in MODALIDADES_COMPETITIVAS)


def consultar(params, intentos=5):
    """Consulta SoQL con reintentos y espera exponencial. El token es opcional."""
    cabeceras = {}
    if os.environ.get("SOCRATA_APP_TOKEN"):
        cabeceras["X-App-Token"] = os.environ["SOCRATA_APP_TOKEN"]
    for intento in range(intentos):
        try:
            r = requests.get(RECURSO_PROCESOS, params=params, headers=cabeceras, timeout=120)
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if intento == intentos - 1:
                raise
            time.sleep(2 ** intento)


def descargar(where):
    """Descarga paginada de todos los registros que cumplen el filtro."""
    paginas, desplazamiento = [], 0
    while True:
        lote = consultar({"$select": ",".join(COLUMNAS_API), "$where": where,
                          "$order": "id_del_proceso", "$limit": TAMANO_PAGINA, "$offset": desplazamiento})
        if not lote:
            break
        paginas.append(pd.DataFrame.from_records(lote))
        desplazamiento += TAMANO_PAGINA
        if len(lote) < TAMANO_PAGINA:
            break
    if not paginas:
        return pd.DataFrame(columns=COLUMNAS_API)
    datos = pd.concat(paginas, ignore_index=True)
    if "urlproceso" in datos:
        datos["urlproceso"] = datos["urlproceso"].map(lambda v: v.get("url") if isinstance(v, dict) else v)
    return datos.astype(str).replace({"nan": None})


def filtro_publicados(desde, hasta):
    return (f"modalidad_de_contratacion in({MODALIDADES_SQL}) "
            f"AND fecha_de_publicacion_del >= '{desde}T00:00:00' AND fecha_de_publicacion_del < '{hasta}T00:00:00'")


def filtro_adjudicados(desde, hasta):
    # Misma población del entrenamiento: adjudicados con al menos una oferta
    return (f"modalidad_de_contratacion in({MODALIDADES_SQL}) AND adjudicado='Si' AND proveedores_unicos_con >= 1 "
            f"AND fecha_adjudicacion >= '{desde}T00:00:00' AND fecha_adjudicacion < '{hasta}T00:00:00'")


def ingerir(lakehouse, desde, hasta, fecha_ingesta):
    """Descarga publicados y adjudicados en [desde, hasta) y los escribe en la capa bronze."""
    resumen = {}
    for tipo, filtro in [("publicados", filtro_publicados), ("adjudicados", filtro_adjudicados)]:
        inicio = time.time()
        datos = descargar(filtro(desde, hasta))
        destino = Path(lakehouse) / "bronze" / tipo / f"fecha_ingesta={fecha_ingesta}"
        destino.mkdir(parents=True, exist_ok=True)
        datos.to_parquet(destino / f"desde_{desde}_hasta_{hasta}.parquet", index=False)
        resumen[tipo] = len(datos)
        print(f"  bronze/{tipo}: {len(datos):,} registros ({desde} a {hasta}) en {time.time() - inicio:.0f} s")
    return resumen
