"""Ejecución diaria del pipeline medallón: bronze -> silver -> gold.

    python pipeline/ejecutar_semana.py                      # últimos 14 días, silver con Spark
    python pipeline/ejecutar_semana.py --motor pandas       # sin Spark (p. ej. en un contenedor liviano)
    python pipeline/ejecutar_semana.py --desde 2026-09-17   # recuperar un periodo (primera ejecución)

La ejecución era semanal; se pasó a diaria porque en la lista semanal el 38 % de los procesos (y el 49 % de
las alertas) ya había cerrado la recepción de ofertas: en mínima cuantía la mediana es de 5 días para
ofertar. La ingesta consulta los últimos 14 días para refrescar el estado de los procesos aún abiertos.

Pasos:
    1. bronze  Procesos competitivos publicados y adjudicados en el periodo (API de SECOP II).
    2. silver  Consolidación y variables derivadas sobre toda la historia de bronze (Spark).
    3. estado  Suma al historial de cada entidad los procesos adjudicados nuevos (sin reentrenar).
    4. gold    Puntaje, calibración, riesgo relativo a pares y explicación de los procesos que siguen
               recibiendo ofertas, con la marca «nuevo» para los que entran hoy a la lista.
"""
import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
DIAS_INGESTA = 14          # ventana de consulta: cubre el plazo típico para ofertar (mediana de 5 a 13 días)
DIAS_SIN_CIERRE = 7        # procesos sin fecha de cierre: se listan solo si se publicaron hace menos de 7 días
sys.path.insert(0, str(RAIZ))
from oferente_unico.puntuacion import Puntuador  # noqa: E402
from oferente_unico.transformaciones import a_silver  # noqa: E402
from pipeline.ingesta import ingerir  # noqa: E402


def silver_pandas(lakehouse):
    partes = []
    for tipo in ("publicados", "adjudicados"):
        for archivo in sorted((Path(lakehouse) / "bronze" / tipo).glob("fecha_ingesta=*/*.parquet")):
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
    args.add_argument("--desde", help=f"inicio de la ingesta (AAAA-MM-DD); por defecto, hace {DIAS_INGESTA} días")
    args.add_argument("--hasta", default=str(date.today() + timedelta(days=1)))
    args.add_argument("--motor", choices=["spark", "pandas"], default="spark")
    args.add_argument("--sin-ingesta", action="store_true", help="reprocesar bronze sin consultar la API")
    a = args.parse_args()
    lakehouse = Path(a.lakehouse)
    desde = a.desde or str(date.today() - timedelta(days=DIAS_INGESTA))
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
    gold = puntuador.gold(abiertos(silver, hoy).reset_index(drop=True))
    destino = lakehouse / "gold"
    destino.mkdir(parents=True, exist_ok=True)
    if len(gold):
        gold = marcar_nuevos(gold, destino, hoy)
        gold.insert(1, "fecha_lista", hoy)
        gold.to_parquet(destino / f"alertas_{hoy}.parquet", index=False)
        gold.to_parquet(destino / "alertas_vigentes.parquet", index=False)
    resumen = {"fecha_ejecucion": hoy, "semana": pd.Timestamp(hoy).strftime("%G-S%V"),
               "periodo_ingesta": [desde, a.hasta], "motor": a.motor,
               "procesos_silver": int(len(silver)), "procesos_puntuados": int(len(gold)),
               "alertas": int(gold["alerta"].sum()) if len(gold) else 0,
               "nuevos": int(gold["nuevo"].sum()) if len(gold) else 0,
               "alertas_nuevas": int((gold["nuevo"] & gold["alerta"]).sum()) if len(gold) else 0,
               "adjudicados_sumados_historial": int(sumados), "duracion_s": round(time.time() - t0, 1)}
    (destino / "resumen_ejecucion.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2))
    print(f"  gold/alertas_{hoy}.parquet: {resumen['procesos_puntuados']:,} procesos, {resumen['alertas']:,} alertas, "
          f"{resumen['nuevos']:,} nuevos | total {resumen['duracion_s']} s")


def abiertos(silver, hoy):
    """Procesos sin adjudicar que todavía reciben ofertas el día de la ejecución."""
    hoy = pd.Timestamp(hoy)
    cierre = silver["fecha_de_recepcion_de"]
    vigente = (cierre >= hoy) | (cierre.isna() & (silver["fecha_de_publicacion_del"] >= hoy - pd.Timedelta(days=DIAS_SIN_CIERRE)))
    return silver[vigente
                  & (silver["adjudicado"] == "No")
                  & ~silver["estado_del_procedimiento"].isin(["Cancelado", "Suspendido", "Seleccionado"])
                  & silver["descripcion"].notna()]


def marcar_nuevos(gold, destino, hoy):
    """Fecha en que cada proceso entró a la lista y marca «nuevo» para los que entran hoy.

    Un proceso ya listado conserva su fecha de ingreso. Uno que no estaba en la lista anterior pero se
    publicó antes de ella (p. ej. quedó fuera de una ventana más corta) toma la fecha de esa lista: no es
    nuevo para el usuario. Nuevo = publicado después de la lista anterior.
    """
    previa = destino / "alertas_vigentes.parquet"
    resumen = destino / "resumen_ejecucion.json"
    ingreso, fecha_previa = {}, None
    if previa.exists() and resumen.exists():
        fecha_previa = json.loads(resumen.read_text())["fecha_ejecucion"]
        ant = pd.read_parquet(previa)
        fechas = ant["fecha_ingreso_lista"] if "fecha_ingreso_lista" in ant else fecha_previa
        ingreso = dict(zip(ant["id_del_proceso"], pd.Series(fechas, index=ant.index)))
    fecha = gold["id_del_proceso"].map(ingreso)
    if fecha_previa:
        anterior = gold["fecha_publicacion"] < fecha_previa
        fecha = fecha.where(fecha.notna() | ~anterior, fecha_previa)
    gold["fecha_ingreso_lista"] = fecha.fillna(hoy)
    gold["nuevo"] = gold["fecha_ingreso_lista"] == hoy
    return gold


if __name__ == "__main__":
    main()
