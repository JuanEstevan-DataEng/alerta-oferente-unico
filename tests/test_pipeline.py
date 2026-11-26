"""Reglas de la capa gold del pipeline diario (no requieren datos ni Spark)."""
import pandas as pd


def test_abiertos_y_nuevos(tmp_path):
    """Solo se listan procesos con plazo abierto; la marca «nuevo» conserva la fecha de ingreso previa."""
    import json

    from pipeline.ejecutar_semana import abiertos, marcar_nuevos
    hoy = "2026-11-26"
    s = pd.DataFrame({
        "id_del_proceso": ["A", "B", "C", "D"],
        "fecha_de_publicacion_del": pd.to_datetime(["2026-11-20", "2026-11-20", "2026-11-01", "2026-11-25"]),
        "fecha_de_recepcion_de": pd.to_datetime(["2026-11-28", "2026-11-24", None, None]),
        "adjudicado": "No", "estado_del_procedimiento": "Publicado", "descripcion": "objeto"})
    assert list(abiertos(s, hoy)["id_del_proceso"]) == ["A", "D"]
    pd.DataFrame({"id_del_proceso": ["A"]}).to_parquet(tmp_path / "alertas_vigentes.parquet")
    (tmp_path / "resumen_ejecucion.json").write_text(json.dumps({"fecha_ejecucion": "2026-11-25"}))
    g = marcar_nuevos(pd.DataFrame({"id_del_proceso": ["A", "D", "E"],
                                    "fecha_publicacion": ["2026-11-20", "2026-11-25", "2026-11-10"]}), tmp_path, hoy)
    # A ya estaba; D se publicó el día de la lista anterior (no alcanzó a entrar); E es antiguo y no estaba
    assert list(g["nuevo"]) == [False, True, False]
    assert list(g["fecha_ingreso_lista"]) == ["2026-11-25", hoy, "2026-11-25"]
