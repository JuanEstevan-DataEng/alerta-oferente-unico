"""Verifica que el paquete de inferencia reproduce los resultados del notebook del Entregable III.

Uso:  python tests/verificar_contra_notebook.py RUTA/secop_procesos_limpio.parquet RUTA/gold_alertas_2026.parquet

1. Exacta: se recalcula el historial y el mercado municipal con la lógica del notebook (que usa la
   historia completa en cada fecha) y se inyectan en las variables del paquete. Todo lo demás
   (categorías, frecuencias, texto, modelo, calibración y pares) debe coincidir con el notebook.
2. Con el estado exportado: para los procesos publicados en la última semana antes del corte, el
   estado inicial de los artefactos debe dar prácticamente el mismo riesgo.
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from oferente_unico.puntuacion import CATEGORICAS_TEXTO, Puntuador  # noqa: E402

ruta_datos, ruta_gold = sys.argv[1], sys.argv[2]
p = Puntuador(RAIZ / "artefactos")
gold_nb = pd.read_parquet(ruta_gold).set_index("id_del_proceso")

df = pd.read_parquet(ruta_datos)
for c in df.columns:
    if isinstance(df[c].dtype, pd.StringDtype):
        df[c] = df[c].astype(object)
for c in ["fecha_de_publicacion_del", "fecha_de_recepcion_de", "fecha_adjudicacion"]:
    df[c] = pd.to_datetime(df[c]).astype("datetime64[ns]")
df = df[df["fecha_de_publicacion_del"].notna()].sort_values("fecha_de_publicacion_del", kind="stable").reset_index(drop=True)
df["anio"], df["mes"] = df["anio"].astype(int), df["mes"].astype(int)
for c in CATEGORICAS_TEXTO:
    df[c] = df[c].fillna("Sin dato").astype(str)

# ---- historial y mercado exactos (lógica del notebook, §3 y §8)
P0, M = p.p0, p.m_suav


def clave(datos, cols):
    k = datos[cols[0]].astype(str)
    for c in cols[1:]:
        k = k + "|" + datos[c].astype(str)
    return k


def historial(cols, pref):
    ev = df.loc[df["fecha_adjudicacion"].notna(), ["fecha_adjudicacion", "oferente_unico"]].copy()
    ev["clave"] = clave(df.loc[ev.index], cols)
    ev = ev.sort_values("fecha_adjudicacion", kind="stable")
    ev["n_prev"] = ev.groupby("clave").cumcount() + 1
    ev["s_prev"] = ev.groupby("clave")["oferente_unico"].cumsum()
    q = pd.DataFrame({"fila": df.index, "clave": clave(df, cols), "fecha": df["fecha_de_publicacion_del"]}).sort_values("fecha", kind="stable")
    u = pd.merge_asof(q, ev[["clave", "fecha_adjudicacion", "n_prev", "s_prev"]], left_on="fecha",
                      right_on="fecha_adjudicacion", by="clave", allow_exact_matches=False).set_index("fila").reindex(df.index)
    n, s = u["n_prev"].fillna(0), u["s_prev"].fillna(0)
    df[f"{pref}_n_prev"] = n.astype("float32")
    df[f"{pref}_tasa_prev"] = ((s + M * P0) / (n + M)).astype("float32")


historial(["entidad"], "ent")
historial(["entidad", "segmento_unspsc"], "entseg")
pubs = df[["entidad", "fecha_de_publicacion_del"]].rename(columns={"fecha_de_publicacion_del": "fa"}).sort_values("fa", kind="stable")
q = pd.DataFrame({"fila": df.index, "entidad": df["entidad"], "f": df["fecha_de_publicacion_del"]}).sort_values("f", kind="stable")
u = pd.merge_asof(q, pubs, left_on="f", right_on="fa", by="entidad", allow_exact_matches=False).set_index("fila").reindex(df.index)
df["ent_dias_desde_ultimo"] = (u["f"] - u["fa"]).dt.days.astype("float32")

df["municipio"] = df["departamento_entidad"] + "|" + df["ciudad_entidad"]
pm = df[["municipio", "fecha_de_publicacion_del"]].rename(columns={"fecha_de_publicacion_del": "f"}).sort_values("f", kind="stable")
pm["acum"] = pm.groupby("municipio").cumcount() + 1


def acumulado_antes(fechas):
    qq = pd.DataFrame({"fila": df.index, "municipio": df["municipio"], "fc": fechas}).sort_values("fc", kind="stable")
    uu = pd.merge_asof(qq, pm, left_on="fc", right_on="f", by="municipio", allow_exact_matches=False)
    return uu.set_index("fila").reindex(df.index)["acum"].fillna(0)


f = df["fecha_de_publicacion_del"]
df["mercado_exacto"] = (acumulado_antes(f) - acumulado_antes(f - pd.Timedelta(days=365))).astype("float32")

# ---- 1. verificación exacta sobre todo 2026
prueba = df[df["anio"] == 2026].copy()
inicio = time.time()
X, d = p.variables(prueba)
for c in ["ent_n_prev", "ent_tasa_prev", "entseg_n_prev", "entseg_tasa_prev", "ent_dias_desde_ultimo"]:
    X[c] = prueba[c].to_numpy()
d["mercado_365"] = prueba["mercado_exacto"].to_numpy()
puntaje = p.booster.predict(X)
prob = 1 / (1 + np.exp(-(np.log(np.clip(puntaje, 1e-6, 1 - 1e-6) / (1 - np.clip(puntaje, 1e-6, 1 - 1e-6))) - np.log(p.peso))))
riesgo = (np.clip(p.calibrador.predict(prob), 0.01, 0.99) * 100).round(1)
pares = (p.riesgo_pares(d) * 100).round(1)
ref = gold_nb.loc[prueba["id_del_proceso"]]
dif_r = np.abs(riesgo - ref["riesgo_pct"].to_numpy())
dif_p = np.abs(pares - ref["riesgo_pares_pct"].to_numpy())
alerta = prob >= p.umbral_alerta
print(f"[1] {len(prueba):,} procesos de 2026 en {time.time() - inicio:.0f} s")
print(f"    riesgo calibrado: coincide (|dif| <= 0,1) en {np.mean(dif_r <= 0.1):.2%}; dif. máx {dif_r.max():.2f} pts")
print(f"    riesgo de pares:  coincide (|dif| <= 0,1) en {np.mean(dif_p <= 0.1):.2%}; dif. máx {dif_p.max():.2f} pts")
print(f"    alerta:           coincide en {np.mean(alerta == ref['alerta'].to_numpy()):.2%}")
muestra = prueba.head(200)
Xm, _ = p.variables(muestra)
for c in ["ent_n_prev", "ent_tasa_prev", "entseg_n_prev", "entseg_tasa_prev", "ent_dias_desde_ultimo"]:
    Xm[c] = muestra[c].to_numpy()
factores, _ = p.explicar(Xm)
print(f"    factores SHAP:    coinciden en {np.mean(np.array(factores) == ref['factores'].to_numpy()[:200]):.0%} de 200")

# ---- 2. estado exportado: última semana antes del corte
corte = pd.Timestamp(p.meta["fecha_corte_datos"])
ultima = df[df["fecha_de_publicacion_del"] > corte - pd.Timedelta(days=7)]
X2, d2, r2 = p.puntuar(ultima)
ref2 = gold_nb.loc[ultima["id_del_proceso"]]
dif2 = np.abs(np.clip(r2["prob_cal"], 0.01, 0.99) * 100 - ref2["riesgo_pct"].to_numpy())
print(f"[2] {len(ultima):,} procesos de la última semana con el estado exportado: "
      f"mediana |dif| {np.median(dif2):.2f} pts, percentil 95 {np.percentile(dif2, 95):.2f} pts")
for c in ["ent_n_prev", "ent_dias_desde_ultimo"]:
    print(f"    {c}: igual en {np.mean(np.isclose(X2[c].to_numpy(), ultima[c].to_numpy(), equal_nan=True)):.0%}")
print(f"    mercado_365: igual en {np.mean(d2['mercado_365'] == ultima['mercado_exacto'].to_numpy()):.0%}")
