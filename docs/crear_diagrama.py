"""Genera docs/arquitectura.svg y docs/arquitectura.png (diagrama de la arquitectura del despliegue).

    python docs/crear_diagrama.py            (desde la carpeta despliegue/)

Los logos oficiales están en docs/logos/ y se embeben en el SVG; el PNG se rasteriza con
Chromium sin interfaz (variable CHROME, por defecto el de Playwright).
"""
import base64
import glob
import os
import re
import subprocess
from pathlib import Path

DOCS = Path(__file__).resolve().parent
LOGOS = DOCS / "logos"
W, H = 1580, 1080

GRIS, NARANJA, TEXTO, SUAVE = "#555555", "#FF9900", "#000000", "#555555"


def logo(nombre, x, y, w, h, color=None):
    ruta = LOGOS / nombre
    datos = ruta.read_bytes()
    if ruta.suffix == ".svg":
        if color:  # iconos monocromáticos de simple-icons
            datos = datos.replace(b"<svg ", f'<svg fill="{color}" '.encode(), 1)
        tipo = "image/svg+xml"
    else:
        tipo = "image/png"
    b64 = base64.b64encode(datos).decode()
    return (f'<image href="data:{tipo};base64,{b64}" x="{x}" y="{y}" width="{w}" height="{h}" '
            f'preserveAspectRatio="xMidYMid meet"/>')


def caja(x, y, w, h, punteada=False, borde=None):
    trazo = f'stroke="{borde}" stroke-width="2.6"' if borde else ""
    if punteada:
        trazo = 'stroke="#999999" stroke-width="2.2" stroke-dasharray="7 5"'
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="#EEEEEE" {trazo} filter="url(#sombra)"/>'


def texto(x, y, contenido, tam=19, color=SUAVE, ancla="start", peso="normal", estilo="normal"):
    return (f'<text x="{x}" y="{y}" font-size="{tam}" fill="{color}" text-anchor="{ancla}" '
            f'font-weight="{peso}" font-style="{estilo}">{contenido}</text>')


def titulo(x, y, contenido, ancla="start", tam=27):
    return texto(x, y, contenido, tam=tam, color=NARANJA, ancla=ancla, peso="bold")


def flecha(d, clase="dato"):
    return f'<path class="{clase}" d="{d}"/>'


def capa(x, nombre, color, lineas, nota, icono):
    # Tarjeta de una capa del medallón (220 x 270)
    cx = x + 110
    p = [caja(x, 470, 220, 275),
         f'<circle cx="{cx}" cy="505" r="17" fill="{color}" stroke="#FFFFFF" stroke-width="3"/>',
         texto(cx, 556, nombre, tam=29, color=NARANJA, ancla="middle", peso="bold")]
    p.append(icono)
    for i, linea in enumerate(lineas):
        p.append(texto(cx, 640 + 26 * i, linea, tam=18, ancla="middle"))
    p.append(texto(cx, 728, nota, tam=16, color=NARANJA, ancla="middle", estilo="italic"))
    return p


def construir():
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
         """font-family="'Times New Roman', 'Liberation Serif', Times, serif">
<defs>
  <filter id="sombra" x="-10%" y="-10%" width="125%" height="135%">
    <feDropShadow dx="2" dy="3" stdDeviation="3" flood-color="#000" flood-opacity="0.30"/>
  </filter>
  <marker id="f" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
    <path d="M0,0 L10,5 L0,10 z" fill="#555555"/>
  </marker>
  <marker id="fn" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
    <path d="M0,0 L10,5 L0,10 z" fill="#FF9900"/>
  </marker>
  <style>
    .dato { stroke:#555555; stroke-width:2.2; fill:none; marker-end:url(#f); }
    .ctrl { stroke:#FF9900; stroke-width:2.6; fill:none; stroke-dasharray:9 6; marker-end:url(#fn); }
    .meta { stroke:#999999; stroke-width:2.2; fill:none; stroke-dasharray:2 5; marker-end:url(#f); }
  </style>
</defs>""",
         f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>']

    # Encabezado y pie (mismo formato que los diagramas de FyH para Big Data)
    p += [f'<rect x="0" y="0" width="{W}" height="222" fill="#EEEEEE" filter="url(#sombra)"/>',
          texto(16, 40, "Inteligencia Artificial - 2S", tam=28, color=TEXTO, peso="bold"),
          f'<rect x="0" y="50" width="{W}" height="32" fill="#999999"/>',
          '<path d="M24,54 L24,70 L72,70" stroke="#000" stroke-width="2" fill="none"/>',
          texto(82, 74, "ARQUITECTURA DEL DESPLIEGUE", tam=22, color=TEXTO, peso="bold", estilo="italic"),
          texto(16, 180, "Alerta temprana de oferente único · SECOP II", tam=62, color=TEXTO, peso="bold"),
          f'<rect x="0" y="{H - 62}" width="{W // 2}" height="62" fill="#999999"/>',
          f'<rect x="{W // 2}" y="{H - 62}" width="{W - W // 2}" height="62" fill="#EEEEEE"/>',
          texto(16, H - 22, "J. E. Viera-Cano &amp; D. M. Madroñero-Ortega", tam=26, color=TEXTO,
                peso="bold", estilo="italic"),
          texto(W - 16, H - 22, "Inteligencia Artificial — Proyecto final", tam=26, color=TEXTO,
                ancla="end", estilo="italic")]

    # Contenedor del pipeline semanal
    p += ['<rect x="28" y="250" width="1290" height="520" rx="24" fill="none" stroke="#999999" '
          'stroke-width="2.2" stroke-dasharray="12 9"/>',
          '<rect x="44" y="236" width="370" height="30" fill="#FFFFFF"/>',
          logo("githubactions.svg", 52, 237, 30, 30),
          texto(92, 260, "Pipeline semanal · GitHub Actions", tam=23, estilo="italic", peso="bold")]

    # Fila superior: orquestación y procesamiento
    p += [caja(300, 285, 470, 105), logo("githubactions.svg", 322, 300, 76, 76),
          titulo(420, 323, "Orquesta el pipeline"),
          texto(420, 352, "cron semanal · lunes 06:00 (Colombia)", tam=18),
          texto(420, 376, "ingesta ▶ silver ▶ gold ▶ validación ▶ pytest", tam=18)]
    p += [caja(830, 285, 450, 105), logo("spark.svg", 845, 297, 160, 80),
          titulo(1025, 323, "Procesa"),
          texto(1025, 352, "PySpark 4.0.1: consolida silver", tam=18),
          texto(1025, 376, "pandas + LightGBM: puntúa gold", tam=18)]

    # Fuente e ingesta
    p += [caja(55, 470, 200, 200),
          '<g transform="translate(125,490)">'
          '<ellipse cx="30" cy="10" rx="30" ry="10" fill="#FCD116"/>'
          '<path d="M0,10 v22 a30,10 0 0 0 60,0 v-22" fill="#FCD116"/>'
          '<path d="M0,32 v20 a30,10 0 0 0 60,0 v-20 a30,10 0 0 1 -60,0" fill="#003893"/>'
          '<path d="M0,52 v14 a30,10 0 0 0 60,0 v-14 a30,10 0 0 1 -60,0" fill="#CE1126"/></g>',
          titulo(155, 600, "Fuente", ancla="middle"),
          texto(155, 626, "datos.gov.co", tam=19, ancla="middle"),
          texto(155, 650, "SECOP II · API Socrata", tam=16, ancla="middle")]
    p += [caja(300, 470, 180, 150), logo("python.svg", 358, 484, 64, 64),
          titulo(390, 580, "Ingesta", ancla="middle"),
          texto(390, 605, "publicados y adjudicados", tam=16, ancla="middle")]
    p += [caja(300, 655, 180, 90, punteada=True), logo("airflow.svg", 318, 662, 144, 50),
          texto(390, 733, "alternativa: DAG local", tam=16, ancla="middle", estilo="italic")]

    # Lakehouse en Hugging Face (papel de MinIO/S3)
    p += ['<rect x="520" y="420" width="790" height="345" rx="14" fill="#FAFAFA" stroke="#FFD21E" stroke-width="3"/>',
          logo("huggingface.svg", 538, 428, 36, 36),
          texto(582, 454, "Hugging Face · lakehouse", tam=22, color=TEXTO, peso="bold")]
    p += capa(545, "Bronze", "#B87333", ["respuesta cruda", "de la API, Parquet"], "partición fecha_ingesta",
              logo("parquet.svg", 625, 572, 40, 40, color="#50ABF1"))
    p += capa(805, "Silver", "#A8A8A8", ["un registro por proceso", "variables del EDA"], "partición por año",
              logo("spark.svg", 860, 568, 110, 50))
    p += capa(1065, "Gold", "#D4AF37", ["riesgo · pares · SHAP", "historial de entidades"], "alertas_vigentes",
              logo("lightgbm.svg", 1105, 578, 140, 32))

    # Servicio y usuarios
    p += [caja(1340, 420, 165, 215), logo("render.svg", 1352, 434, 44, 44, color="#000000"),
          logo("docker.svg", 1400, 437, 50, 38), logo("fastapi.svg", 1454, 434, 44, 44),
          titulo(1422, 520, "Render", ancla="middle"),
          texto(1422, 546, "FastAPI + web", tam=18, ancla="middle"),
          texto(1422, 570, "contenedor Docker", tam=18, ancla="middle"),
          texto(1422, 612, "lee gold cada hora", tam=16, color=NARANJA, ancla="middle", estilo="italic")]
    p += [caja(1340, 670, 165, 150),
          '<g transform="translate(1400,682)" fill="#555555"><circle cx="22" cy="14" r="12"/>'
          '<path d="M0,52 a22,22 0 0 1 44,0 z"/></g>',
          titulo(1422, 762, "Usuarios", ancla="middle", tam=25),
          texto(1422, 786, "analistas · veedurías", tam=16, ancla="middle"),
          texto(1422, 806, "lista · ficha · simulador", tam=16, ancla="middle")]

    # Fila inferior: entrenamiento, artefactos y código
    p += [caja(55, 800, 200, 120),
          '<path d="M75,834 h60" class="dato"/>', texto(145, 840, "datos", tam=17),
          '<path d="M75,864 h60" class="ctrl"/>', texto(145, 870, "control", tam=17),
          '<path d="M75,894 h60" class="meta"/>', texto(145, 900, "lectura", tam=17)]
    p += [caja(300, 800, 470, 120), logo("colab.png", 318, 815, 90, 90),
          titulo(425, 838, "Entrenamiento (una vez)"),
          texto(425, 866, "Colab T4 · E4 TF-IDF frente a E9 BETO", tam=18),
          logo("scikitlearn.svg", 425, 878, 34, 34), logo("pytorch.svg", 466, 878, 30, 30),
          texto(505, 902, "scikit-learn · PyTorch", tam=16, estilo="italic")]
    p += [caja(805, 800, 480, 120), logo("lightgbm.svg", 822, 838, 160, 36),
          titulo(1000, 838, "Artefactos del modelo"),
          texto(1000, 866, "modelo · TF-IDF+SVD · isotónica", tam=18),
          texto(1000, 890, "pares · historial inicial", tam=18)]
    p += [caja(1340, 850, 165, 130), logo("github.svg", 1395, 860, 54, 54),
          titulo(1422, 940, "GitHub", ancla="middle", tam=25),
          texto(1422, 964, "código + pruebas", tam=16, ancla="middle")]

    # Flechas de datos
    p += [flecha("M255,545 L298,545"), flecha("M480,545 L543,545"),
          flecha("M765,605 L803,605"), flecha("M1025,605 L1063,605"),
          flecha("M1422,635 L1422,668"),
          flecha("M770,860 L803,860")]
    # Control (orquestación)
    p += [flecha("M390,390 L390,468", "ctrl"), flecha("M770,337 L828,337", "ctrl"),
          flecha("M915,390 L915,468", "ctrl"), flecha("M1175,390 L1175,468", "ctrl"),
          flecha("M1505,915 L1545,915 L1545,525 L1509,525", "ctrl")]
    # Lectura / sincronización
    p += [flecha("M1175,798 L1175,747", "meta"), flecha("M1310,560 L1338,560", "meta"),
          texto(1250, 790, "carga", tam=15, estilo="italic"),
          texto(1566, 720, "despliegue automático", tam=19, ancla="middle", estilo="italic")
          .replace("<text ", '<text transform="rotate(90 1566 720)" ')]
    p.append("</svg>")
    return "\n".join(p)


def chrome():
    if os.environ.get("CHROME"):
        return os.environ["CHROME"]
    candidatos = glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome"))
    return sorted(candidatos)[-1]


if __name__ == "__main__":
    svg = construir()
    (DOCS / "arquitectura.svg").write_text(svg, encoding="utf-8")
    html = DOCS / "_tmp_diagrama.html"
    html.write_text(f'<html><body style="margin:0">{svg}</body></html>', encoding="utf-8")
    subprocess.run([chrome(), "--headless=new", "--no-sandbox", "--hide-scrollbars", "--disable-gpu",
                    f"--window-size={W},{H}", f"--screenshot={DOCS / 'arquitectura.png'}", html.as_uri()],
                   check=True, capture_output=True)
    html.unlink()
    print("arquitectura.svg y arquitectura.png generados en", DOCS)
    assert not re.search(r"§", svg)
