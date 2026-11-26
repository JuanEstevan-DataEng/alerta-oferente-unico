"""Pruebas de la API web sobre los datos del lakehouse local."""
import pytest
from fastapi.testclient import TestClient

from app.main import app

cliente = TestClient(app)

PROCESO = {"entidad": "MUNICIPIO DE LABRANZAGRANDE", "departamento_entidad": "Boyacá", "ciudad_entidad": "No Definido",
           "modalidad_de_contratacion": "Mínima cuantía", "tipo_de_contrato": "Suministros",
           "codigo_principal_de_categoria": "V1.15101505", "precio_base": 80_000_000,
           "descripcion": "Suministro de combustible para la maquinaria amarilla del municipio"}


def test_salud():
    r = cliente.get("/salud")
    assert r.status_code == 200 and r.json()["estado"] == "ok"


@pytest.mark.parametrize("conjunto", ["vigentes", "2026"])
def test_lista_ordenada_y_paginada(conjunto):
    r = cliente.get("/api/alertas", params={"conjunto": conjunto, "tamano": 10})
    datos = r.json()
    assert r.status_code == 200 and len(datos["registros"]) <= 10
    prioridades = [x["prioridad"] for x in datos["registros"]]
    assert prioridades == sorted(prioridades)
    for x in datos["registros"]:
        assert 1 <= x["riesgo_pct"] <= 99


def test_filtros_y_solo_alertas():
    filtros = cliente.get("/api/filtros", params={"conjunto": "2026"}).json()
    dep = filtros["departamentos"][0]
    datos = cliente.get("/api/alertas", params={"conjunto": "2026", "departamento": dep, "solo_alertas": True}).json()
    assert all(x["departamento"] == dep and x["alerta"] for x in datos["registros"])


def test_ficha_y_404():
    primero = cliente.get("/api/alertas", params={"conjunto": "2026", "tamano": 1}).json()["registros"][0]
    ficha = cliente.get(f"/api/proceso/{primero['id_del_proceso']}", params={"conjunto": "2026"}).json()
    assert ficha["factores"] and ficha["terminos_clave"]
    assert cliente.get("/api/proceso/NO-EXISTE").status_code == 404


def test_simulador_es_monotono_en_el_historial():
    """El mismo proceso tiene más prioridad en una entidad con historial de oferente único alto.

    Se compara el puntaje de prioridad (sin calibrar): la calibración isotónica es escalonada y
    puede asignar el mismo porcentaje a puntajes distintos del tramo superior.
    """
    alto = cliente.post("/api/puntuar", json=PROCESO).json()
    bajo = cliente.post("/api/puntuar", json={**PROCESO, "entidad": "ENTIDAD NUEVA SIN HISTORIAL"}).json()
    assert alto["puntaje_prioridad"] > bajo["puntaje_prioridad"]
    assert alto["riesgo_pct"] >= bajo["riesgo_pct"]
    assert alto["factores"]


def test_simulador_valida_entradas():
    assert cliente.post("/api/puntuar", json={**PROCESO, "precio_base": -5}).status_code == 422


def test_descarga_csv():
    r = cliente.get("/api/descargar", params={"conjunto": "vigentes", "solo_alertas": True})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")


@pytest.mark.parametrize("orden,columna", [("riesgo", "riesgo_pct"), ("precio", "precio_base"), ("monto", "monto_en_juego")])
def test_orden_alternativo(orden, columna):
    """Reordenar la vista no cambia el modelo: la prioridad frente a pares se conserva en cada fila."""
    datos = cliente.get("/api/alertas", params={"conjunto": "2026", "orden": orden, "tamano": 50}).json()["registros"]
    valores = [x[columna] for x in datos if x[columna] is not None]
    assert valores == sorted(valores, reverse=True)
    por_defecto = {x["id_del_proceso"]: x["prioridad"]
                   for x in cliente.get("/api/alertas", params={"conjunto": "2026", "tamano": 200}).json()["registros"]}
    assert all(por_defecto.get(x["id_del_proceso"], x["prioridad"]) == x["prioridad"] for x in datos)
    for x in datos:
        if x["precio_base"] is not None:
            assert x["monto_en_juego"] == pytest.approx(x["riesgo_pct"] / 100 * x["precio_base"], abs=1)


def test_orden_invalido():
    assert cliente.get("/api/alertas", params={"orden": "robado"}).status_code == 422


def test_solo_nuevos():
    """La lista vigente marca los procesos que entraron hoy y permite filtrarlos."""
    todos = cliente.get("/api/alertas", params={"tamano": 200}).json()
    if not todos["registros"] or "nuevo" not in todos["registros"][0]:
        pytest.skip("gold anterior a la marca de nuevos")
    nuevos = cliente.get("/api/alertas", params={"solo_nuevos": True, "tamano": 200}).json()
    assert nuevos["total"] <= todos["total"]
    assert all(x["nuevo"] for x in nuevos["registros"])


def test_busqueda_por_palabra_completa():
    """«cali» no debe encontrar «calidad», «localizado» ni «Calima» (hallazgo de la validación con la usuaria)."""
    datos = cliente.get("/api/alertas", params={"buscar": "cali", "tamano": 200}).json()["registros"]
    import re
    for x in datos:
        texto = f"{x['entidad']} {x['municipio']} {x['objeto']}".lower()
        assert re.search(r"(?<!\w)cali(?!\w)", texto), texto[:120]


def test_busqueda_sin_tildes():
    con = cliente.get("/api/alertas", params={"conjunto": "2026", "buscar": "Bogotá"}).json()["total"]
    sin = cliente.get("/api/alertas", params={"conjunto": "2026", "buscar": "bogota"}).json()["total"]
    assert con == sin > 0


def test_filtro_de_municipio():
    municipios = cliente.get("/api/filtros", params={"conjunto": "2026", "departamento": "Valle del Cauca"}).json()["municipios"]
    assert "Cali" in municipios and "No Definido" not in municipios
    for escrito in ["Cali", "santiago de cali"]:
        datos = cliente.get("/api/alertas", params={"conjunto": "2026", "municipio": escrito, "tamano": 200}).json()
        assert datos["total"] > 0 and {x["municipio"] for x in datos["registros"]} == {"Cali"}


@pytest.mark.parametrize("conjunto", ["vigentes", "2026"])
def test_alerta_coincide_con_el_riesgo_mostrado(conjunto):
    """Una sola métrica para el usuario: tiene alerta todo proceso con riesgo mostrado ≥ umbral, y ninguno por debajo."""
    umbral = cliente.get("/api/resumen").json()["vigentes"]["umbral_alerta_riesgo_pct"]
    datos = cliente.get("/api/alertas", params={"conjunto": conjunto, "orden": "riesgo", "tamano": 200, "pagina": 2}).json()["registros"]
    assert all(x["alerta"] == (x["riesgo_pct"] >= umbral) for x in datos)
    ficha = cliente.get(f"/api/proceso/{datos[0]['id_del_proceso']}", params={"conjunto": conjunto}).json()
    assert "_texto" not in ficha and "_municipio" not in ficha
