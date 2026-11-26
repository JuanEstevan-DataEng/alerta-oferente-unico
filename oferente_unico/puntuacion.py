"""Capa gold: puntaje, calibración, riesgo relativo a pares y explicación de cada proceso.

Reproduce las secciones 3, 5, 7, 8 y 9 del notebook del Entregable III a partir de los artefactos
exportados en su sección 10, sin volver a leer los 400 000 procesos del entrenamiento.

Estado que evoluciona en cada ejecución diaria (carpeta `estado/`):
    historial_entidad.parquet           n procesos adjudicados y s con oferente único por entidad
    historial_entidad_segmento.parquet  lo mismo por entidad y segmento UNSPSC
    publicaciones.parquet               publicaciones recientes (entidad, municipio, fecha) para el
                                        tamaño del mercado y los días desde la publicación anterior
    procesos_contados.parquet           identificadores ya sumados al historial (evita contar dos veces)

Todas las variables de un proceso publicado en la fecha t usan solo información anterior a t.
"""
import json
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd

CATEGORICAS_TEXTO = ["entidad", "departamento_entidad", "ciudad_entidad", "ordenentidad",
                     "modalidad_de_contratacion", "tipo_de_contrato", "codigo_principal_de_categoria",
                     "segmento_unspsc"]
VENTANA_MERCADO = pd.Timedelta(days=365)


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


class Puntuador:
    def __init__(self, dir_artefactos, dir_estado=None):
        self.dir_art = Path(dir_artefactos)
        self.dir_estado = Path(dir_estado) if dir_estado else None
        self.meta = json.loads((self.dir_art / "metadatos.json").read_text(encoding="utf-8"))
        self.booster = lgb.Booster(model_file=str(self.dir_art / "modelo_lgbm.txt"))
        texto = joblib.load(self.dir_art / "texto_tfidf_svd.joblib")
        self.tfidf, self.svd = texto["tfidf"], texto["svd"]
        self.vocab = np.array(self.tfidf.get_feature_names_out())
        self.calibrador = joblib.load(self.dir_art / "calibrador_isotonico.joblib")

        frec = pd.read_parquet(self.dir_art / "frecuencias.parquet")
        self.frecuencias = {c: g.set_index("valor")["frecuencia"] for c, g in frec.groupby("columna")}
        pares = pd.read_parquet(self.dir_art / "pares.parquet")
        self.pares = {n: g.set_index("clave")[["sum", "count"]] for n, g in pares.groupby("nivel")}

        self.vars = self.meta["variables"]
        self.vars_texto = self.meta["variables_texto"]
        self.peso, self.p0, self.m_suav = self.meta["peso_pos"], self.meta["p0"], self.meta["m_suav"]
        self.umbral_alerta = self.meta["umbral_alerta"]
        # El mismo umbral expresado en la escala que ve el usuario (probabilidad calibrada). La isotónica es
        # escalonada: con el umbral sobre la probabilidad corregida, procesos con el mismo porcentaje mostrado
        # podían quedar unos con alerta y otros sin ella. Con este umbral, alerta = riesgo mostrado ≥ umbral.
        self.umbral_alerta_riesgo = float(self.calibrador.predict(np.array([self.umbral_alerta]))[0])
        self._cargar_estado()

    # ------------------------------------------------------------------ estado
    def _leer(self, nombre):
        if self.dir_estado and (self.dir_estado / nombre).exists():
            return pd.read_parquet(self.dir_estado / nombre)
        return None

    def _cargar_estado(self):
        ent = self._leer("historial_entidad.parquet")
        if ent is None:  # primera ejecución: estado inicial exportado por el notebook
            ent = pd.read_parquet(self.dir_art / "historial_entidad.parquet")
            seg = pd.read_parquet(self.dir_art / "historial_entidad_segmento.parquet")
            pubs = pd.read_parquet(self.dir_art / "publicaciones_365d.parquet").assign(
                entidad=None, id_del_proceso=None, cuenta_mercado=True)
            # La última publicación de cada entidad se conserva como una publicación más
            ultimas = ent.dropna(subset=["ultima_publicacion"])[["clave", "ultima_publicacion"]].rename(
                columns={"clave": "entidad", "ultima_publicacion": "fecha_publicacion"}).assign(
                municipio=None, id_del_proceso=None, cuenta_mercado=False)
            pubs = pd.concat([pubs, ultimas], ignore_index=True)
            contados = pd.DataFrame({"id_del_proceso": pd.Series(dtype=str)})
            corte = pd.Timestamp(self.meta["fecha_corte_datos"])
            ent = ent[["clave", "n", "s"]]
            seg = seg[["clave", "n", "s"]]
        else:
            seg = self._leer("historial_entidad_segmento.parquet")
            pubs = self._leer("publicaciones.parquet")
            contados = self._leer("procesos_contados.parquet")
            corte = pd.Timestamp(json.loads((self.dir_estado / "estado.json").read_text())["corte_inicial"])
        self.hist_ent = ent.set_index("clave")[["n", "s"]].astype(float)
        self.hist_seg = seg.set_index("clave")[["n", "s"]].astype(float)
        self.pubs = pubs.astype({"entidad": "object", "municipio": "object", "id_del_proceso": "object"})
        self.pubs["fecha_publicacion"] = pd.to_datetime(self.pubs["fecha_publicacion"])
        self.contados = set(contados["id_del_proceso"])
        self.corte_inicial = corte

    def guardar_estado(self):
        self.dir_estado.mkdir(parents=True, exist_ok=True)
        self.hist_ent.rename_axis("clave").reset_index().to_parquet(self.dir_estado / "historial_entidad.parquet", index=False)
        self.hist_seg.rename_axis("clave").reset_index().to_parquet(
            self.dir_estado / "historial_entidad_segmento.parquet", index=False)
        self.pubs.to_parquet(self.dir_estado / "publicaciones.parquet", index=False)
        pd.DataFrame({"id_del_proceso": sorted(self.contados)}).to_parquet(
            self.dir_estado / "procesos_contados.parquet", index=False)
        (self.dir_estado / "estado.json").write_text(json.dumps({
            "corte_inicial": str(self.corte_inicial.date()),
            "ultima_publicacion_registrada": str(self.pubs["fecha_publicacion"].max().date()),
            "procesos_sumados_al_historial": len(self.contados)}, indent=2))

    @staticmethod
    def _completar(silver):
        d = silver.copy()
        for c in CATEGORICAS_TEXTO:
            d[c] = d[c].fillna("Sin dato").astype(str)
        d["municipio"] = d["departamento_entidad"] + "|" + d["ciudad_entidad"]
        d["descripcion"] = d["descripcion"].fillna("").astype(str)
        return d

    def actualizar_estado(self, silver):
        """Suma al historial los procesos adjudicados nuevos y registra las publicaciones.

        Solo cuentan los adjudicados con al menos una oferta (la misma población del
        entrenamiento) y posteriores al corte de los datos del entrenamiento.
        """
        d = self._completar(silver)
        nuevos = d[d["fecha_adjudicacion"].notna() & d["oferente_unico"].notna()
                   & (d["fecha_adjudicacion"] > self.corte_inicial)
                   & ~d["id_del_proceso"].isin(self.contados)]
        for tabla, clave in [(self.hist_ent, nuevos["entidad"]),
                             (self.hist_seg, nuevos["entidad"] + "|" + nuevos["segmento_unspsc"])]:
            suma = pd.DataFrame({"n": 1.0, "s": nuevos["oferente_unico"].astype(float)}).groupby(clave.to_numpy()).sum()
            tabla_nueva = tabla.add(suma, fill_value=0)
            if tabla is self.hist_ent:
                self.hist_ent = tabla_nueva
            else:
                self.hist_seg = tabla_nueva
        self.contados |= set(nuevos["id_del_proceso"])

        # Publicaciones: todas sirven para "días desde la anterior"; al mercado solo suman las que
        # terminaron adjudicadas con oferentes, como en el entrenamiento
        pubs = d[["id_del_proceso", "entidad", "municipio", "fecha_de_publicacion_del"]].rename(
            columns={"fecha_de_publicacion_del": "fecha_publicacion"}).dropna(subset=["fecha_publicacion"])
        pubs["cuenta_mercado"] = pubs["id_del_proceso"].isin(self.contados)
        previas = self.pubs[~self.pubs["id_del_proceso"].isin(pubs["id_del_proceso"])]
        self.pubs = pd.concat([previas, pubs], ignore_index=True)
        limite = self.pubs["fecha_publicacion"].max() - VENTANA_MERCADO - pd.Timedelta(days=60)
        ultimas = self.pubs.sort_values("fecha_publicacion").groupby("entidad").tail(1).index
        self.pubs = self.pubs[(self.pubs["fecha_publicacion"] >= limite) | self.pubs.index.isin(ultimas)]
        return len(nuevos)

    # --------------------------------------------------------------- variables
    def _dias_desde_ultimo(self, d):
        consultas = d[["entidad", "fecha_de_publicacion_del"]].reset_index().sort_values("fecha_de_publicacion_del")
        ref = (self.pubs.dropna(subset=["entidad"])[["entidad", "fecha_publicacion"]]
               .sort_values("fecha_publicacion"))
        unido = pd.merge_asof(consultas, ref, left_on="fecha_de_publicacion_del", right_on="fecha_publicacion",
                              by="entidad", allow_exact_matches=False).set_index("index").reindex(d.index)
        return (unido["fecha_de_publicacion_del"] - unido["fecha_publicacion"]).dt.days.astype("float32")

    def _mercado_365(self, d):
        # Publicaciones del municipio en [t - 365 días, t): igual que acumulado_antes(t) - acumulado_antes(t - 365)
        ref = self.pubs[self.pubs["cuenta_mercado"]].dropna(subset=["municipio"])
        fechas = {m: np.sort(g["fecha_publicacion"].to_numpy(dtype="datetime64[ns]"))
                  for m, g in ref.groupby("municipio")}
        conteo = np.zeros(len(d), dtype="float32")
        t_todas = pd.to_datetime(d["fecha_de_publicacion_del"]).to_numpy(dtype="datetime64[ns]")
        ventana = np.timedelta64(365, "D")
        for m, posiciones in pd.Series(np.arange(len(d))).groupby(d["municipio"].to_numpy()):
            f = fechas.get(m)
            if f is None:
                continue
            t = t_todas[posiciones.to_numpy()]
            conteo[posiciones.to_numpy()] = np.searchsorted(f, t, "left") - np.searchsorted(f, t - ventana, "left")
        return conteo

    def variables(self, silver):
        """Construye las 119 variables del modelo en el mismo orden del entrenamiento."""
        d = self._completar(silver)
        X = pd.DataFrame(index=d.index)
        for c in self.meta["cat_baja"]:
            X[c] = pd.Categorical(d[c], categories=self.meta["categorias"][c])
        for c in self.meta["cat_alta"]:
            X[f"frec_{c}"] = d[c].map(self.frecuencias[c]).fillna(0).astype("float32")
        for c in self.meta["numericas"]:
            X[c] = pd.to_numeric(d[c], errors="coerce").astype("float32")

        for prefijo, clave, tabla in [("ent", d["entidad"], self.hist_ent),
                                      ("entseg", d["entidad"] + "|" + d["segmento_unspsc"], self.hist_seg)]:
            n = clave.map(tabla["n"]).fillna(0)
            s = clave.map(tabla["s"]).fillna(0)
            X[f"{prefijo}_n_prev"] = n.astype("float32")
            X[f"{prefijo}_tasa_prev"] = ((s + self.m_suav * self.p0) / (n + self.m_suav)).astype("float32")
        X["ent_dias_desde_ultimo"] = self._dias_desde_ultimo(d)

        textos = d["descripcion"].str.lower().str.replace(r"\s+", " ", regex=True).str.strip()
        self._matriz_tfidf = self.tfidf.transform(textos)
        Z = self.svd.transform(self._matriz_tfidf).astype("float32")
        X = pd.concat([X, pd.DataFrame(Z, index=d.index, columns=self.vars_texto)], axis=1)

        d["mercado_365"] = self._mercado_365(d)
        return X[self.vars], d

    # ------------------------------------------------------------------ puntaje
    def _quintil(self, valores, cortes):
        bordes = [-np.inf, *cortes, np.inf]
        q = pd.cut(pd.Series(valores), bordes, labels=[f"Q{i}" for i in range(1, len(bordes))]).astype(object)
        return q.where(pd.Series(valores).notna(), "Sin dato").astype(str).to_numpy()

    def riesgo_pares(self, d):
        d = d.copy()
        # float32 como en el entrenamiento: los cortes se calcularon sobre valores float32
        d["q_cuantia"] = self._quintil(pd.to_numeric(d["log_precio_base"], errors="coerce").to_numpy().astype("float32"),
                                       self.meta["cortes_cuantia"])
        d["q_mercado"] = self._quintil(d["mercado_365"].to_numpy().astype("float32"), self.meta["cortes_mercado"])
        d["segmento_unspsc_txt"] = d["segmento_unspsc"]
        d["modalidad_de_contratacion_txt"] = d["modalidad_de_contratacion"]
        previa = np.full(len(d), self.p0)
        for nivel, columnas in enumerate(self.meta["niveles_pares"]):
            clave = d[columnas[0]].astype(str)
            for c in columnas[1:]:
                clave = clave + "|" + d[c].astype(str)
            tabla = self.pares[nivel]
            s = clave.map(tabla["sum"]).fillna(0).to_numpy()
            n = clave.map(tabla["count"]).fillna(0).to_numpy()
            previa = (s + self.meta["m_pares"] * previa) / (n + self.meta["m_pares"])
        return previa

    def puntuar(self, silver):
        X, d = self.variables(silver)
        puntaje = self.booster.predict(X)                                     # ponderado por w
        prob = 1 / (1 + np.exp(-(logit(puntaje) - np.log(self.peso))))       # corregida
        prob_cal = self.calibrador.predict(prob)                              # calibrada (2025)
        pares = self.riesgo_pares(d)
        prioridad = logit(prob) - logit(pares) if self.meta["ordenar_por_pares"] else logit(prob)
        return X, d, {"puntaje": puntaje, "prob": prob, "prob_cal": prob_cal, "riesgo_pares": pares,
                      "prioridad": prioridad}

    def es_alerta(self, prob_cal):
        return np.asarray(prob_cal) >= self.umbral_alerta_riesgo

    # --------------------------------------------------------------- explicación
    def _describir(self, variable, valor):
        nombre = self.meta["nombres_legibles"].get(variable, variable)
        if variable == "TEXTO":
            return nombre
        if variable == "log_precio_base":
            return f"{nombre} = ${10 ** float(valor) / 1e6:,.0f} M"
        if isinstance(valor, (float, np.floating)):
            if np.isnan(valor):
                return f"{nombre} = sin dato"
            if variable.endswith("_tasa_prev"):
                return f"{nombre} = {valor:.0%}"
            return f"{nombre} = {int(valor):,}" if float(valor).is_integer() else f"{nombre} = {valor:,.2f}"
        return f"{nombre} = {valor}"

    def contribuciones(self, X):
        """Valores SHAP exactos de LightGBM (TreeSHAP nativo), con el texto agrupado en un factor."""
        c = self.booster.predict(X, pred_contrib=True)[:, :-1]               # última columna = valor base
        c = pd.DataFrame(c, columns=self.vars, index=X.index)
        c["TEXTO"] = c[self.vars_texto].sum(axis=1)
        return c.drop(columns=self.vars_texto)

    def explicar(self, X):
        contrib = self.contribuciones(X)
        factores = []
        for (i, fila), valores in zip(X.iterrows(), contrib.to_numpy()):
            orden = [j for j in np.argsort(-valores)[:3] if valores[j] > 0]
            factores.append(" | ".join(
                self._describir(contrib.columns[j], None if contrib.columns[j] == "TEXTO" else fila[contrib.columns[j]])
                for j in orden))
        terminos = []
        for r in range(self._matriz_tfidf.shape[0]):
            fila = self._matriz_tfidf[r]
            orden = np.argsort(-fila.data)[:5]
            terminos.append(", ".join(self.vocab[fila.indices[orden]]))
        return factores, terminos

    def gold(self, silver):
        """Lista priorizada y explicada (misma estructura que gold_alertas_2026.parquet)."""
        if len(silver) == 0:
            return pd.DataFrame()
        X, d, r = self.puntuar(silver)
        factores, terminos = self.explicar(X)
        salida = pd.DataFrame({
            "id_del_proceso": d["id_del_proceso"].to_numpy(),
            "referencia": d["referencia_del_proceso"].to_numpy(),
            "fecha_publicacion": d["fecha_de_publicacion_del"].dt.date.astype(str).to_numpy(),
            "fecha_cierre_ofertas": pd.to_datetime(d["fecha_de_recepcion_de"]).dt.date.astype(str).to_numpy(),
            "entidad": d["entidad"].to_numpy(),
            "nit_entidad": d["nit_entidad"].to_numpy(),
            "departamento": d["departamento_entidad"].to_numpy(),
            "municipio": d["ciudad_entidad"].to_numpy(),
            "modalidad": d["modalidad_de_contratacion"].to_numpy(),
            "tipo_contrato": d["tipo_de_contrato"].to_numpy(),
            "objeto": d["descripcion"].to_numpy(),
            "precio_base": pd.to_numeric(d["precio_base"], errors="coerce").to_numpy(),
            "dias_para_ofertar": pd.to_numeric(d["dias_para_ofertar"], errors="coerce").to_numpy(),
            "riesgo_pct": (np.clip(r["prob_cal"], 0.01, 0.99) * 100).round(1),
            "riesgo_pares_pct": (r["riesgo_pares"] * 100).round(1),
            "puntaje_prioridad": np.round(r["prioridad"], 4),
            "alerta": self.es_alerta(r["prob_cal"]),
            "factores": factores,
            "terminos_clave": terminos,
            "url": d["urlproceso"].to_numpy() if "urlproceso" in d else None,
            "estado": d["estado_resumen"].to_numpy() if "estado_resumen" in d else None,
        })
        salida = salida.sort_values("puntaje_prioridad", ascending=False, kind="stable").reset_index(drop=True)
        salida.insert(0, "prioridad", np.arange(1, len(salida) + 1))
        return salida
