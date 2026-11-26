"""Aplicación web: lista priorizada y explicada de procesos con riesgo de oferente único.

    uvicorn app.main:app --port 8000          (desde la carpeta despliegue/)

Lee la capa gold del lakehouse (alertas de la semana), la evaluación de 2026 y la validación
prospectiva, y expone el modelo para puntuar un proceso hipotético (simulador).
Variables de entorno: LAKEHOUSE (carpeta del lakehouse) y ARTEFACTOS (carpeta de artefactos).
"""
import io
import json
import os
import sys
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from oferente_unico.puntuacion import Puntuador  # noqa: E402

LAKEHOUSE = Path(os.environ.get("LAKEHOUSE", RAIZ / "lakehouse"))
ARTEFACTOS = Path(os.environ.get("ARTEFACTOS", RAIZ / "artefactos"))
ESTATICOS = Path(__file__).parent / "static"

HF_DATASET = os.environ.get("HF_DATASET")  # lakehouse remoto (opcional)
INTERVALO_SINCRONIZACION_S = 3600


async def _sincronizar_periodicamente():
    # La aplicación solo lee: descarga las capas gold y estado que publica el pipeline semanal
    import asyncio

    from pipeline.sincronizar import descargar
    while True:
        try:
            await asyncio.to_thread(descargar, HF_DATASET, LAKEHOUSE, ["gold", "estado"])
        except Exception as error:  # noqa: BLE001 - un fallo de red no debe tumbar la aplicación
            print(f"Sincronización fallida: {error}")
        await asyncio.sleep(INTERVALO_SINCRONIZACION_S)


@asynccontextmanager
async def ciclo_de_vida(_):
    import asyncio
    if HF_DATASET and not (LAKEHOUSE / "gold" / "alertas_vigentes.parquet").exists():
        # Primer arranque sin datos locales: se espera la descarga antes de atender solicitudes
        from pipeline.sincronizar import descargar
        await asyncio.to_thread(descargar, HF_DATASET, LAKEHOUSE, ["gold", "estado"])
    tarea = asyncio.create_task(_sincronizar_periodicamente()) if HF_DATASET else None
    # Precarga del modelo en segundo plano: el primer uso del simulador no espera la carga
    asyncio.create_task(asyncio.to_thread(puntuador))
    yield
    if tarea:
        tarea.cancel()


app = FastAPI(title="Alerta temprana de oferente único — SECOP II",
              description="Prioriza procesos de contratación pública para revisión humana. "
                          "El riesgo de oferente único no es evidencia de corrupción.",
              version="3.0", lifespan=ciclo_de_vida)

CONJUNTOS = {"vigentes": "alertas_vigentes.parquet", "2026": "evaluacion_2026.parquet"}
COLUMNAS_LISTA = ["prioridad", "id_del_proceso", "fecha_publicacion", "entidad", "departamento", "municipio",
                  "modalidad", "objeto", "precio_base", "monto_en_juego", "riesgo_pct", "riesgo_pares_pct", "alerta",
                  "resultado_observado", "estado", "url"]

# Criterios de orden de la lista. El modelo y la columna «prioridad» no cambian: solo se reordena la vista.
#   prioridad  riesgo relativo a procesos comparables (pares), el orden con equidad territorial (por defecto)
#   riesgo     probabilidad calibrada de recibir una sola oferta
#   precio     precio base del proceso
#   monto      monto en juego = probabilidad calibrada x precio base (riesgo ponderado por el valor del proceso)
Orden = Literal["prioridad", "riesgo", "precio", "monto"]
COLUMNA_ORDEN = {"riesgo": "riesgo_pct", "precio": "precio_base", "monto": "monto_en_juego"}


def _firma(ruta):
    return ruta.stat().st_mtime if ruta.exists() else 0


@lru_cache(maxsize=4)
def _leer(nombre, firma):
    ruta = LAKEHOUSE / "gold" / nombre
    if not ruta.exists():
        return pd.DataFrame()
    return pd.read_parquet(ruta)


def datos(conjunto):
    if conjunto not in CONJUNTOS:
        raise HTTPException(404, f"Conjunto desconocido: {conjunto}")
    ruta = LAKEHOUSE / "gold" / CONJUNTOS[conjunto]
    return _leer(CONJUNTOS[conjunto], _firma(ruta))


@lru_cache(maxsize=1)
def _puntuador(firma):
    return Puntuador(ARTEFACTOS, LAKEHOUSE / "estado")


def puntuador():
    return _puntuador(_firma(LAKEHOUSE / "estado" / "estado.json"))


def _json(ruta, defecto=None):
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else defecto


def _limpio(registros):
    # NaN -> None para JSON
    return json.loads(pd.DataFrame(registros).to_json(orient="records", force_ascii=False))


def ordenar(df, orden="prioridad"):
    df = df.assign(monto_en_juego=(df["riesgo_pct"] / 100 * df["precio_base"]).round(0))
    if orden == "prioridad":
        return df.sort_values("prioridad", kind="stable")
    # Empates (la calibración isotónica es escalonada) y faltantes: se resuelven con la prioridad frente a pares
    return df.sort_values([COLUMNA_ORDEN[orden], "prioridad"], ascending=[False, True], na_position="last", kind="stable")


def filtrar(df, departamento, modalidad, solo_alertas, buscar):
    if departamento:
        df = df[df["departamento"] == departamento]
    if modalidad:
        df = df[df["modalidad"] == modalidad]
    if solo_alertas:
        df = df[df["alerta"]]
    if buscar:
        patron = buscar.strip().lower()
        df = df[df["entidad"].str.lower().str.contains(patron, regex=False)
                | df["objeto"].str.lower().str.contains(patron, regex=False)
                | df["municipio"].str.lower().str.contains(patron, regex=False)]
    return df


@app.get("/salud")
def salud():
    return {"estado": "ok", "vigentes": len(datos("vigentes")), "evaluacion_2026": len(datos("2026"))}


@app.get("/api/resumen")
def resumen():
    meta = _json(ARTEFACTOS / "metadatos.json", {})
    vig, ev = datos("vigentes"), datos("2026")
    ejec = _json(LAKEHOUSE / "gold" / "resumen_ejecucion.json", {})
    prosp = _json(LAKEHOUSE / "gold" / "validacion_prospectiva" / "resumen.json")
    semanas = LAKEHOUSE / "gold" / "validacion_prospectiva" / "por_semana.csv"
    top100 = (ev.head(100)["resultado_observado"] == "1 oferta").mean() if len(ev) else None
    return {
        "ejecucion": ejec,
        "vigentes": {"procesos": len(vig), "alertas": int(vig["alerta"].sum()) if len(vig) else 0},
        "modelo": {"nombre": meta.get("modelo"), "fecha_corte_datos": meta.get("fecha_corte_datos"),
                   "metricas_prueba_2026": meta.get("metricas_prueba_2026"),
                   "puntos_operacion": meta.get("puntos_operacion_prueba_2026"),
                   "precision_100_primeros_2026": top100},
        "validacion_prospectiva": prosp,
        "validacion_por_semana": _limpio(pd.read_csv(semanas)) if semanas.exists() else [],
    }


@app.get("/api/filtros")
def filtros(conjunto: str = "vigentes"):
    df = datos(conjunto)
    if df.empty:
        return {"departamentos": [], "modalidades": []}
    return {"departamentos": sorted(df["departamento"].dropna().unique().tolist()),
            "modalidades": sorted(df["modalidad"].dropna().unique().tolist())}


@app.get("/api/alertas")
def alertas(conjunto: str = "vigentes", departamento: Optional[str] = None, modalidad: Optional[str] = None,
            solo_alertas: bool = False, buscar: Optional[str] = None, orden: Orden = "prioridad",
            pagina: int = Query(1, ge=1), tamano: int = Query(25, ge=1, le=200)):
    df = ordenar(filtrar(datos(conjunto), departamento, modalidad, solo_alertas, buscar), orden)
    total = len(df)
    bloque = df.iloc[(pagina - 1) * tamano: pagina * tamano]
    cols = [c for c in COLUMNAS_LISTA if c in bloque.columns]
    extra = {}
    if "resultado_observado" in df.columns and total:
        extra["precision_observada"] = float((df["resultado_observado"] == "1 oferta").mean())
    return {"total": total, "pagina": pagina, "tamano": tamano, "registros": _limpio(bloque[cols]), **extra}


@app.get("/api/proceso/{id_del_proceso}")
def proceso(id_del_proceso: str, conjunto: str = "vigentes"):
    df = datos(conjunto)
    fila = ordenar(df[df["id_del_proceso"] == id_del_proceso])
    if fila.empty:
        raise HTTPException(404, "Proceso no encontrado")
    return _limpio(fila)[0]


@app.get("/api/descargar")
def descargar(conjunto: str = "vigentes", departamento: Optional[str] = None, modalidad: Optional[str] = None,
              solo_alertas: bool = False, buscar: Optional[str] = None, orden: Orden = "prioridad"):
    df = ordenar(filtrar(datos(conjunto), departamento, modalidad, solo_alertas, buscar), orden)

    def bloques(tamano=5000):
        # Se envía por bloques para no materializar el archivo completo en memoria
        for inicio in range(0, max(len(df), 1), tamano):
            buffer = io.StringIO()
            df.iloc[inicio:inicio + tamano].to_csv(buffer, index=False, header=inicio == 0)
            yield (("﻿" if inicio == 0 else "") + buffer.getvalue()).encode("utf-8")

    nombre = f"alertas_oferente_unico_{conjunto}.csv"
    return StreamingResponse(bloques(), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


class ProcesoHipotetico(BaseModel):
    entidad: str = Field(..., examples=["MUNICIPIO DE LABRANZAGRANDE"])
    departamento_entidad: str = Field(..., examples=["Boyacá"])
    ciudad_entidad: str = Field(..., examples=["Labranzagrande"])
    ordenentidad: str = Field("Territorial")
    modalidad_de_contratacion: str = Field(..., examples=["Mínima cuantía"])
    tipo_de_contrato: str = Field(..., examples=["Suministros"])
    codigo_principal_de_categoria: Optional[str] = Field(None, examples=["V1.15101505"])
    precio_base: float = Field(..., gt=0)
    duracion_dias: float = Field(30, ge=0)
    dias_para_ofertar: float = Field(3, ge=0)
    numero_de_lotes: int = Field(0, ge=0)
    descripcion: str = Field(..., min_length=5)


@app.post("/api/puntuar")
def puntuar(p: ProcesoHipotetico):
    """Puntúa un proceso como si se publicara hoy (usa el historial vigente de la entidad)."""
    hoy = pd.Timestamp.today().normalize()
    registro = p.model_dump()
    registro.update({
        "id_del_proceso": "SIMULADO", "referencia_del_proceso": None, "nit_entidad": None,
        "fecha_de_publicacion_del": hoy, "fecha_de_recepcion_de": hoy + pd.Timedelta(days=p.dias_para_ofertar),
        "segmento_unspsc": (pd.Series([p.codigo_principal_de_categoria]).str.extract(r"(\d{2})", expand=False)[0]
                            if p.codigo_principal_de_categoria else None),
        "anio": hoy.year, "mes": hoy.month, "log_precio_base": float(np.log10(p.precio_base)),
        "urlproceso": None, "estado_resumen": "Simulación",
    })
    gold = puntuador().gold(pd.DataFrame([registro]))
    salida = _limpio(gold)[0]
    salida["umbral_alerta_pct"] = round(puntuador().umbral_alerta * 100, 1)
    return salida


@app.get("/")
def inicio():
    return FileResponse(ESTATICOS / "index.html")


app.mount("/static", StaticFiles(directory=ESTATICOS), name="static")
