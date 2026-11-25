"""Capa silver (versión pandas).

Reproduce las derivaciones de EDA_SECOP_procesos.ipynb (celdas 35, 39 y 41) sobre los registros
crudos de la API de SECOP II (p6dx-8zbt). La versión distribuida en PySpark
(pipeline/medallon_spark.py) implementa las mismas reglas; esta versión sirve de referencia para
verificarla y para ejecutar el pipeline sin Spark.
"""
import re
import unicodedata

import numpy as np
import pandas as pd

RECURSO_PROCESOS = "https://www.datos.gov.co/resource/p6dx-8zbt.json"

# Modalidades en las que la ley exige concurso (las mismas del entrenamiento)
MODALIDADES_COMPETITIVAS = [
    "Licitación pública",
    "Licitación pública Obra Publica",
    "Licitación Pública Acuerdo Marco de Precios",
    "Selección Abreviada de Menor Cuantía",
    "Selección abreviada subasta inversa",
    "Concurso de méritos abierto",
    "Mínima cuantía",
]

# Columnas que se piden a la API. Solo se usan como predictores las disponibles al publicar;
# fecha_adjudicacion y proveedores_unicos_con sirven únicamente para actualizar el historial.
COLUMNAS_API = [
    "id_del_proceso", "referencia_del_proceso", "entidad", "nit_entidad", "departamento_entidad",
    "ciudad_entidad", "ordenentidad", "modalidad_de_contratacion", "tipo_de_contrato",
    "codigo_principal_de_categoria", "numero_de_lotes", "precio_base",
    "fecha_de_publicacion_del", "fecha_de_recepcion_de", "fecha_adjudicacion",
    "duracion", "unidad_de_duracion", "adjudicado", "estado_del_procedimiento", "estado_resumen",
    "proveedores_unicos_con", "descripci_n_del_procedimiento", "urlproceso",
]

FACTOR_UNIDAD = {"dia(s)": 1, "semana(s)": 7, "mes(es)": 30, "ano(s)": 365, "hora(s)": 1 / 24}
REEMPLAZOS = {"\x91": "'", "\x92": "'", "\x93": '"', "\x94": '"', "\x96": "-", "\x97": "-", "\x85": "..."}
FECHAS = ["fecha_de_publicacion_del", "fecha_de_recepcion_de", "fecha_adjudicacion"]
NUMERICAS = ["precio_base", "duracion", "numero_de_lotes", "proveedores_unicos_con"]


def normalizar_texto(s):
    """Minúsculas, sin tildes y sin espacios redundantes."""
    if pd.isna(s):
        return s
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def limpiar_texto(s):
    """Reemplaza caracteres de control de Windows-1252 y colapsa espacios."""
    if pd.isna(s):
        return s
    for malo, bueno in REEMPLAZOS.items():
        s = s.replace(malo, bueno)
    s = re.sub(r"[\x80-\x9f]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def extraer_url(valor):
    """La API entrega urlproceso como {'url': ...}."""
    if isinstance(valor, dict):
        return valor.get("url")
    return valor if isinstance(valor, str) else None


def a_silver(crudo: pd.DataFrame) -> pd.DataFrame:
    """Registros crudos de la API -> un registro por proceso con las variables derivadas."""
    base = crudo.copy()
    for c in COLUMNAS_API:
        if c not in base.columns:
            base[c] = np.nan
    if "urlproceso" in base.columns:
        base["urlproceso"] = base["urlproceso"].map(extraer_url)
    base = base[COLUMNAS_API].astype({"urlproceso": "object"}).drop_duplicates()
    for c in NUMERICAS:
        base[c] = pd.to_numeric(base[c], errors="coerce")
    for c in FECHAS:
        # El entrenamiento usó fechas a nivel de día: se descarta la hora
        base[c] = pd.to_datetime(base[c], errors="coerce").dt.tz_localize(None).dt.normalize()

    # Un registro por proceso (la API repite filas por adjudicación)
    agregacion = {c: "first" for c in COLUMNAS_API if c != "id_del_proceso"}
    agregacion["fecha_adjudicacion"] = "min"
    df = base.sort_values("id_del_proceso", kind="stable").groupby("id_del_proceso", as_index=False).agg(agregacion)

    df.loc[df["precio_base"] <= 0, "precio_base"] = np.nan
    df["dias_para_ofertar"] = (df["fecha_de_recepcion_de"] - df["fecha_de_publicacion_del"]).dt.days
    df.loc[(df["dias_para_ofertar"] < 0) | (df["dias_para_ofertar"] > 365), "dias_para_ofertar"] = np.nan
    factor = df["unidad_de_duracion"].map(normalizar_texto).map(FACTOR_UNIDAD)
    df["duracion_dias"] = df["duracion"] * factor
    df.loc[df["duracion_dias"] > 365 * 10, "duracion_dias"] = np.nan
    df["segmento_unspsc"] = df["codigo_principal_de_categoria"].str.extract(r"(\d{2})", expand=False)
    df["anio"] = df["fecha_de_publicacion_del"].dt.year
    df["mes"] = df["fecha_de_publicacion_del"].dt.month
    df["log_precio_base"] = np.log10(df["precio_base"])
    df["descripcion"] = df["descripci_n_del_procedimiento"].map(limpiar_texto)
    # Etiqueta solo para la población del entrenamiento: adjudicados con al menos una oferta.
    # En procesos abiertos, proveedores_unicos_con cuenta las respuestas recibidas hasta el momento.
    etiquetable = (df["adjudicado"] == "Si") & (df["proveedores_unicos_con"] >= 1)
    df["oferente_unico"] = np.where(etiquetable, (df["proveedores_unicos_con"] == 1).astype(float), np.nan)
    return df
