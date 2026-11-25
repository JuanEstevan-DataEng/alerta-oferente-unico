"""Ejecución semanal del pipeline medallón: bronze -> silver -> gold.

    python pipeline/ejecutar_semana.py                      # última semana, silver con Spark
    python pipeline/ejecutar_semana.py --motor pandas       # sin Spark (p. ej. en un contenedor liviano)
    python pipeline/ejecutar_semana.py --desde 2026-09-17   # recuperar un periodo (primera ejecución)

Pasos:
    1. bronze  Procesos competitivos publicados y adjudicados en el periodo (API de SECOP II).
    2. silver  Consolidación y variables derivadas sobre toda la historia de bronze (Spark).
    3. estado  Suma al historial de cada entidad los procesos adjudicados nuevos (sin reentrenar).
    4. gold    Puntaje, calibración, riesgo relativo a pares y explicación de los procesos publicados
               en la última semana que siguen recibiendo ofertas.
"""
import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from oferente_unico.puntuacion import Puntuador  # noqa: E402
from oferente_unico.transformaciones import a_silver  # noqa: E402
from pipeline.ingesta import ingerir  # noqa: E402


def silver_pandas(lakehouse):
    partes = []
    for tipo in ("publicados", "adjudicados"):
        for archivo in sorted((Path(lakehouse) / "bronze" / tipo).glob("fecha_ingesta=*/parte.parquet")):
            partes.append(pd.read_parquet(archivo).assign(fecha_ingesta=archivo.parent.name.split("=")[1]))
    crudo = pd.concat(partes, ignore_index=True)
    ultima = crudo.groupby("id_del_proceso")["fecha_ingesta"].transform("max")
    silver = a_silver(crudo[crudo["fecha_ingesta"] == ultima].drop(columns="fecha_ingesta"))
    destino = Path(lakehouse) / "silver" / "procesos_pandas.parquet"
    destino.parent.mkdir(parents=True, exist_ok=True)
    silver.to_parquet(destino, index=False)
    print(f"  silver/procesos: {len(silver):,} procesos consolidados (pandas)")
    return silver


def leer_silver_spark(ruta):
    # Se lee sin interpretar las particiones (anio nulo para procesos sin fecha) y se recalcula
    silver = pd.read_parquet(ruta, partitioning=None)
    silver["anio"] = silver["fecha_de_publicacion_del"].dt.year
    for c in ["fecha_de_publicacion_del", "fecha_de_recepcion_de", "fecha_adjudicacion"]:
        silver[c] = pd.to_datetime(silver[c]).dt.tz_localize(None)
    return silver


def main():
    args = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    args.add_argument("--lakehouse", default=str(RAIZ / "lakehouse"))
    args.add_argument("--desde", help="inicio de la ingesta (AAAA-MM-DD); por defecto, hace 7 días")
    args.add_argument("--hasta", default=str(date.today() + timedelta(days=1)))
    args.add_argument("--motor", choices=["spark", "pandas"], default="spark")
    args.add_argument("--sin-ingesta", action="store_true", help="reprocesar bronze sin consultar la API")
    a = args.parse_args()
    lakehouse = Path(a.lakehouse)
    desde = a.desde or str(date.today() - timedelta(days=7))
    hoy = str(date.today())
    t0 = time.time()

    print(f"[1/4] bronze ({desde} a {a.hasta})")
    if not a.sin_ingesta:
        ingerir(lakehouse, desde, a.hasta, hoy)

    print(f"[2/4] silver con {a.motor}")
    if a.motor == "spark":
        from pipeline.medallon_spark import construir_silver
        silver = leer_silver_spark(construir_silver(lakehouse))
    else:
        silver = silver_pandas(lakehouse)

    print("[3/4] estado del historial")
    puntuador = Puntuador(RAIZ / "artefactos", lakehouse / "estado")
    sumados = puntuador.actualizar_estado(silver)
    puntuador.guardar_estado()
    print(f"  {sumados:,} procesos adjudicados nuevos sumados al historial de las entidades")

    print("[4/4] gold")
    inicio_semana = pd.Timestamp(hoy) - pd.Timedelta(days=7)
    abiertos = silver[(silver["fecha_de_publicacion_del"] >= inicio_semana)
                      & (silver["adjudicado"] == "No")
                      & ~silver["estado_del_procedimiento"].isin(["Cancelado", "Suspendido", "Seleccionado"])
                      & silver["descripcion"].notna()]
    gold = puntuador.gold(abiertos.reset_index(drop=True))
    destino = lakehouse / "gold"
    destino.mkdir(parents=True, exist_ok=True)
    semana = pd.Timestamp(hoy).strftime("%G-S%V")
    if len(gold):
        gold.insert(1, "semana", semana)
        gold.to_parquet(destino / f"alertas_{semana}.parquet", index=False)
        gold.to_parquet(destino / "alertas_vigentes.parquet", index=False)
    resumen = {"semana": semana, "fecha_ejecucion": hoy, "periodo_ingesta": [desde, a.hasta], "motor": a.motor,
               "procesos_silver": int(len(silver)), "procesos_puntuados": int(len(gold)),
               "alertas": int(gold["alerta"].sum()) if len(gold) else 0,
               "adjudicados_sumados_historial": int(sumados), "duracion_s": round(time.time() - t0, 1)}
    (destino / "resumen_ejecucion.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2))
    print(f"  gold/alertas_{semana}.parquet: {resumen['procesos_puntuados']:,} procesos, "
          f"{resumen['alertas']:,} alertas | total {resumen['duracion_s']} s")


if __name__ == "__main__":
    main()
