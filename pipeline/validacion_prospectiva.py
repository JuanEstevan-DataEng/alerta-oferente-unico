"""Validación prospectiva del sistema desplegado (después de la fecha de corte del entrenamiento).

Para cada semana entre el corte de los datos y hoy, simula la ejecución semanal con la información
que existía ese día:
    - el historial solo suma los procesos adjudicados ANTES de la fecha de ejecución;
    - se puntúan los procesos publicados en los 7 días previos;
y compara la lista con el resultado que hoy ya se conoce (adjudicados con al menos una oferta).

    python pipeline/validacion_prospectiva.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from oferente_unico.puntuacion import Puntuador  # noqa: E402
from pipeline.ejecutar_semana import leer_silver_spark  # noqa: E402


def precision_en_k(y, s, k):
    return float(np.mean(y[np.argsort(-s, kind="stable")[:k]])) if len(y) >= k else np.nan


def pr_auc(y, s):
    orden = np.argsort(-s, kind="stable")
    y = y[orden]
    tp = np.cumsum(y)
    precision = tp / np.arange(1, len(y) + 1)
    return float(np.sum(precision * y) / max(y.sum(), 1))  # precisión promedio


def main():
    lakehouse = RAIZ / "lakehouse"
    silver = leer_silver_spark(lakehouse / "silver" / "procesos")
    meta = json.loads((RAIZ / "artefactos" / "metadatos.json").read_text())
    corte = pd.Timestamp(meta["fecha_corte_datos"])
    filas, todas = [], []
    for ejecucion in pd.date_range(corte + pd.Timedelta(days=8), pd.Timestamp.today() - pd.Timedelta(days=21), freq="7D"):
        # Información disponible el día de la ejecución
        visto = silver[silver["fecha_de_publicacion_del"] < ejecucion].copy()
        futuro = visto["fecha_adjudicacion"] >= ejecucion
        visto.loc[futuro, ["fecha_adjudicacion", "oferente_unico"]] = np.nan
        visto.loc[futuro, "adjudicado"] = "No"
        p = Puntuador(RAIZ / "artefactos")  # estado inicial del entrenamiento
        p.actualizar_estado(visto)

        semana = silver[(silver["fecha_de_publicacion_del"] >= ejecucion - pd.Timedelta(days=7))
                        & (silver["fecha_de_publicacion_del"] < ejecucion) & silver["descripcion"].notna()]
        semana = semana.reset_index(drop=True)
        _, _, r = p.puntuar(semana)
        evaluable = semana["oferente_unico"].notna().to_numpy()  # hoy ya se conoce el resultado
        y = semana["oferente_unico"].to_numpy()[evaluable].astype(int)
        prob, prioridad = r["prob"][evaluable], r["prioridad"][evaluable]
        alerta = p.es_alerta(r["prob_cal"][evaluable])
        filas.append({"ejecucion": str(ejecucion.date()), "publicados": len(semana), "con_resultado": int(evaluable.sum()),
                      "tasa_real": y.mean(), "PR-AUC": pr_auc(y, prob), "P@50": precision_en_k(y, prob, 50),
                      "P@50 pares": precision_en_k(y, prioridad, 50), "alertas": int(alerta.sum()),
                      "precision_alertas": y[alerta].mean() if alerta.any() else np.nan,
                      "recall_alertas": alerta[y == 1].mean()})
        todas.append(pd.DataFrame({"y": y, "prob": prob, "prob_cal": r["prob_cal"][evaluable], "alerta": alerta}))
        print(f"  {filas[-1]['ejecucion']}: {filas[-1]['con_resultado']:,} con resultado | PR-AUC {filas[-1]['PR-AUC']:.3f} | "
              f"P@50 {filas[-1]['P@50']:.2f} | precisión alertas {filas[-1]['precision_alertas']:.2f}")

    tabla = pd.DataFrame(filas)
    t = pd.concat(todas, ignore_index=True)
    global_ = {"procesos_evaluados": len(t), "tasa_real": float(t["y"].mean()), "PR-AUC": pr_auc(t["y"].to_numpy(), t["prob"].to_numpy()),
               "precision_alertas": float(t.loc[t["alerta"], "y"].mean()), "recall_alertas": float(t.loc[t["y"] == 1, "alerta"].mean()),
               "prob_calibrada_media": float(t["prob_cal"].mean())}
    destino = lakehouse / "gold" / "validacion_prospectiva"
    destino.mkdir(parents=True, exist_ok=True)
    tabla.to_csv(destino / "por_semana.csv", index=False)
    (destino / "resumen.json").write_text(json.dumps(global_, indent=2))
    print(tabla.round(3).to_string(index=False))
    print(json.dumps({k: round(v, 3) if isinstance(v, float) else v for k, v in global_.items()}, indent=2))


if __name__ == "__main__":
    main()
