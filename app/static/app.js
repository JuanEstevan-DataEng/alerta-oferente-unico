// Interfaz de la alerta temprana de oferente único (sin dependencias externas)
const estado = { vista: "vigentes", pagina: 1, tamano: 25, total: 0, resumen: null };
const $ = (sel) => document.querySelector(sel);
const fmt = new Intl.NumberFormat("es-CO");
const pct = (v, d = 1) => (v == null ? "—" : `${Number(v).toFixed(d).replace(".", ",")} %`);
const dec = (v, d = 3) => (v == null ? "—" : Number(v).toFixed(d).replace(".", ","));
const dinero = (v) => (v == null ? "sin dato" : `$${fmt.format(Math.round(v / 1e6))} M`);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(ruta, opciones) {
  const r = await fetch(ruta, opciones);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

function parametros() {
  const p = new URLSearchParams({ conjunto: estado.vista, pagina: estado.pagina, tamano: estado.tamano });
  const dep = $("#f-departamento").value, mod = $("#f-modalidad").value, q = $("#f-buscar").value.trim();
  const mun = $("#f-municipio").value.trim();
  if (dep) p.set("departamento", dep);
  if (mun) p.set("municipio", mun);
  if (mod) p.set("modalidad", mod);
  if (q) p.set("buscar", q);
  if ($("#f-alertas").checked) p.set("solo_alertas", "true");
  if (estado.vista === "vigentes" && $("#f-nuevos").checked) p.set("solo_nuevos", "true");
  const orden = $("#f-orden").value;
  if (orden !== "prioridad") p.set("orden", orden);
  return p;
}

// ------------------------------------------------------------------ pestañas
document.querySelectorAll(".pestanas button").forEach((b) =>
  b.addEventListener("click", () => cambiarVista(b.dataset.vista)));

function cambiarVista(vista) {
  document.querySelectorAll(".pestanas button").forEach((b) => b.setAttribute("aria-selected", b.dataset.vista === vista));
  const lista = vista === "vigentes" || vista === "2026";
  $("#vista-lista").hidden = !lista;
  $("#vista-simulador").hidden = vista !== "simulador";
  $("#vista-como").hidden = vista !== "como";
  $("#casilla-nuevos").hidden = vista !== "vigentes";
  if (lista) {
    estado.vista = vista;
    estado.pagina = 1;
    cargarFiltros().then(cargarLista);
  }
  if (vista === "como") pintarComo();
}

// ------------------------------------------------------------------ lista
async function cargarFiltros() {
  const f = await api(`/api/filtros?conjunto=${estado.vista}`);
  for (const [id, valores, todos] of [["#f-departamento", f.departamentos, "Todos"], ["#f-modalidad", f.modalidades, "Todas"]]) {
    const sel = $(id), actual = sel.value;
    sel.innerHTML = `<option value="">${todos}</option>` + valores.map((v) => `<option>${esc(v)}</option>`).join("");
    sel.value = valores.includes(actual) ? actual : "";
  }
  await cargarMunicipios();
}

// Sugerencias de municipio según el departamento elegido (también se puede escribir libremente)
async function cargarMunicipios() {
  const p = new URLSearchParams({ conjunto: estado.vista });
  if ($("#f-departamento").value) p.set("departamento", $("#f-departamento").value);
  const f = await api(`/api/filtros?${p}`);
  $("#municipios").innerHTML = (f.municipios || []).map((m) => `<option value="${esc(m)}"></option>`).join("");
}

const umbralAlerta = () => (estado.resumen?.vigentes?.umbral_alerta_riesgo_pct ?? null);

function pintarKpis(datos) {
  const r = estado.resumen;
  let tarjetas;
  if (estado.vista === "vigentes") {
    const e = r.ejecucion || {};
    tarjetas = [
      [fmt.format(r.vigentes.procesos), "procesos que siguen recibiendo ofertas"],
      [fmt.format(r.vigentes.alertas), `alertas (riesgo de ${pct(umbralAlerta())} o más)`],
      [r.vigentes.nuevos == null ? "—" : fmt.format(r.vigentes.nuevos),
       r.vigentes.alertas_nuevas == null ? "nuevos hoy" : `nuevos hoy · ${fmt.format(r.vigentes.alertas_nuevas)} con alerta`],
      [fmt.format(datos.total), "procesos con los filtros actuales"],
    ];
    $("#explicacion-lista").textContent = `Procesos competitivos sin adjudicar cuyo plazo para ofertar sigue abierto (actualizado el ${e.fecha_ejecucion || "—"}). ` +
      TEXTO_ORDEN[$("#f-orden").value] + " La rayita de cada barra marca lo normal en procesos similares.";
  } else {
    const m = r.modelo.metricas_prueba_2026 || {};
    tarjetas = [
      [dec(m["PR-AUC"]).replace(".", ","), "PR-AUC en 2026 (azar 0,456)"],
      [pct((r.modelo.precision_100_primeros_2026 || 0) * 100, 0), "de las 100 primeras alertas tuvo 1 oferta"],
      [fmt.format(datos.total), "procesos con los filtros actuales"],
      [datos.precision_observada == null ? "—" : pct(datos.precision_observada * 100), "con oferente único en esta selección"],
    ];
    $("#explicacion-lista").textContent = "Procesos de 2026, un año que el modelo no vio al entrenarse. " +
      "La columna «Resultado» muestra cuántas ofertas recibió realmente cada proceso.";
  }
  $("#kpis").innerHTML = tarjetas.map(([v, t]) => `<div class="kpi"><div class="valor">${esc(v)}</div><div class="etiqueta">${esc(t)}</div></div>`).join("");
}

// Qué significa cada orden (la columna # conserva la prioridad frente a pares)
const TEXTO_ORDEN = {
  prioridad: "Primero los procesos cuyo riesgo más se sale de lo normal en procesos similares (mismo tipo de compra, modalidad, monto y tamaño del municipio).",
  riesgo: "Ordenados por la probabilidad calibrada de recibir una sola oferta.",
  precio: "Ordenados por precio base, de mayor a menor.",
  monto: "Ordenados por monto en juego: probabilidad de una sola oferta × precio base. Favorece a las entidades grandes.",
};

function barra(riesgo, pares) {
  return `<span class="cifra">${pct(riesgo)}</span>
    <div class="barra" title="Riesgo ${pct(riesgo)} · lo normal en procesos similares: ${pct(pares)}">
      <div class="valor" style="width:${riesgo}%"></div><div class="marca-pares" style="left:${pares}%"></div></div>`;
}

async function cargarLista() {
  const datos = await api(`/api/alertas?${parametros()}`);
  estado.total = datos.total;
  pintarKpis(datos);
  const conResultado = estado.vista === "2026";
  const verMonto = $("#f-orden").value === "monto";
  $("#encabezado").innerHTML = ["#", "Entidad y lugar", "Objeto", "Modalidad", verMonto ? "Monto en juego" : "Precio base", "Riesgo", "Lo normal en similares",
                                conResultado ? "Resultado" : "Estado"]
    .map((t) => `<th>${t}</th>`).join("");
  $("#filas").innerHTML = datos.registros.map((r) => `
    <tr data-id="${esc(r.id_del_proceso)}" tabindex="0">
      <td class="num">${r.prioridad}</td>
      <td><div class="entidad">${esc(r.entidad)}${r.alerta ? '<span class="etiqueta-alerta">alerta</span>' : ""}${r.nuevo ? '<span class="etiqueta-nuevo">nuevo</span>' : ""}</div>
          <div class="lugar">${esc(r.municipio)} · ${esc(r.departamento)}</div></td>
      <td><div class="objeto-corto">${esc((r.objeto || "").slice(0, 110))}${(r.objeto || "").length > 110 ? "…" : ""}</div></td>
      <td class="lugar">${esc(r.modalidad)}</td>
      <td class="cifra">${dinero(verMonto ? r.monto_en_juego : r.precio_base)}</td>
      <td>${barra(r.riesgo_pct, r.riesgo_pares_pct)}</td>
      <td class="cifra">${pct(r.riesgo_pares_pct)}</td>
      <td>${conResultado ? `<span class="${r.resultado_observado === "1 oferta" ? "resultado-1" : "resultado-2"}">${esc(r.resultado_observado)}</span>`
                         : `<span class="lugar">${esc(r.estado || "")}</span>`}</td>
    </tr>`).join("") || `<tr><td colspan="8" class="tenue">No hay procesos con estos filtros.</td></tr>`;
  const paginas = Math.max(1, Math.ceil(datos.total / estado.tamano));
  $("#pagina-info").textContent = `Página ${estado.pagina} de ${fmt.format(paginas)}`;
  $("#anterior").disabled = estado.pagina <= 1;
  $("#siguiente").disabled = estado.pagina >= paginas;
  const p = parametros(); p.delete("pagina"); p.delete("tamano");
  $("#descargar").href = `/api/descargar?${p}`;
}

let espera;
["#f-modalidad", "#f-orden", "#f-alertas", "#f-nuevos"].forEach((id) => $(id).addEventListener("change", () => { estado.pagina = 1; cargarLista(); }));
$("#f-departamento").addEventListener("change", () => { estado.pagina = 1; cargarMunicipios(); cargarLista(); });
for (const id of ["#f-buscar", "#f-municipio"]) {
  $(id).addEventListener("input", () => { clearTimeout(espera); espera = setTimeout(() => { estado.pagina = 1; cargarLista(); }, 300); });
}
$("#anterior").addEventListener("click", () => { estado.pagina--; cargarLista(); });
$("#siguiente").addEventListener("click", () => { estado.pagina++; cargarLista(); });
$("#filas").addEventListener("click", (e) => { const tr = e.target.closest("tr[data-id]"); if (tr) abrirFicha(tr.dataset.id); });
$("#filas").addEventListener("keydown", (e) => { const tr = e.target.closest("tr[data-id]"); if (tr && e.key === "Enter") abrirFicha(tr.dataset.id); });

// ------------------------------------------------------------------ ficha
function htmlFicha(p) {
  const factores = (p.factores || "").split(" | ").filter(Boolean);
  const terminos = (p.terminos_clave || "").split(", ").filter(Boolean);
  const diferencia = p.riesgo_pct - p.riesgo_pares_pct;
  const umbral = p.umbral_alerta_pct ?? umbralAlerta();
  return `
    <p class="tenue">${p.prioridad ? `Prioridad #${p.prioridad} · ` : ""}${esc(p.id_del_proceso)}</p>
    <h2>${esc(p.entidad)}</h2>
    <p class="lugar">${esc(p.municipio)} · ${esc(p.departamento)} · ${esc(p.modalidad)}</p>
    <div class="comparacion">
      <div class="riesgo"><div class="tenue">Riesgo de oferente único</div><div class="grande">${pct(p.riesgo_pct, 0)}</div></div>
      <div><div class="tenue">Lo normal en procesos similares</div><div class="grande">${pct(p.riesgo_pares_pct, 0)}</div></div>
    </div>
    <p>${diferencia > 15 ? `Su riesgo es <b>mucho mayor</b> que lo normal en procesos similares (mismo tipo de compra, modalidad, monto y tamaño del municipio).`
       : diferencia > 0 ? "Su riesgo es un poco mayor que lo normal en procesos similares."
       : "Su riesgo es igual o menor que lo normal en procesos similares."}
       ${p.alerta ? ` Tiene alerta porque su riesgo alcanza el umbral de ${pct(umbral)}.` : ""}</p>
    <p class="tenue">El riesgo se calcula con lo que se sabía al publicarse el proceso y con el historial de la entidad. No es una cuenta regresiva: no sube con el paso de los días.</p>
    ${p.resultado_observado ? `<p>Resultado real: <b class="${p.resultado_observado === "1 oferta" ? "resultado-1" : "resultado-2"}">${esc(p.resultado_observado)}</b></p>` : ""}
    <h3>Factores que elevan el riesgo</h3>
    <ul class="factores">${factores.map((f) => `<li>${esc(f)}</li>`).join("") || "<li>Ningún factor eleva el riesgo sobre el promedio.</li>"}</ul>
    <h3>Términos distintivos del objeto</h3>
    <div class="chips">${terminos.map((t) => `<span class="chip">${esc(t)}</span>`).join("")}</div>
    <h3>Objeto</h3><p>${esc(p.objeto)}</p>
    <dl class="datos">
      <dt>Precio base</dt><dd>${dinero(p.precio_base)}</dd>
      <dt>Monto en juego</dt><dd>${dinero(p.monto_en_juego)} <span class="tenue">(riesgo × precio base)</span></dd>
      <dt>Días para ofertar</dt><dd>${p.dias_para_ofertar ?? "sin dato"}</dd>
      <dt>Publicación</dt><dd>${esc(p.fecha_publicacion)}</dd>
      ${p.fecha_cierre_ofertas ? `<dt>Cierre de ofertas</dt><dd>${esc(p.fecha_cierre_ofertas)}</dd>` : ""}
      ${p.fecha_ingreso_lista ? `<dt>En la lista desde</dt><dd>${esc(p.fecha_ingreso_lista)}${p.nuevo ? " (nuevo hoy)" : ""}</dd>` : ""}
      ${p.tipo_contrato ? `<dt>Tipo de contrato</dt><dd>${esc(p.tipo_contrato)}</dd>` : ""}
    </dl>
    ${p.url ? `<a class="boton" href="${esc(p.url)}" target="_blank" rel="noopener">Ver el proceso en SECOP II</a>` : ""}
    <p class="tenue" style="margin-top:16px">Los factores son asociaciones aprendidas de procesos anteriores (valores SHAP), no evidencia de una conducta.</p>`;
}

async function abrirFicha(id) {
  const p = await api(`/api/proceso/${encodeURIComponent(id)}?conjunto=${estado.vista}`);
  $("#ficha-contenido").innerHTML = htmlFicha(p);
  $("#ficha").hidden = false; $("#velo").hidden = false;
  $("#cerrar-ficha").focus();
}
const cerrarFicha = () => { $("#ficha").hidden = true; $("#velo").hidden = true; };
$("#cerrar-ficha").addEventListener("click", cerrarFicha);
$("#velo").addEventListener("click", cerrarFicha);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") cerrarFicha(); });

// ------------------------------------------------------------------ simulador
$("#form-simulador").addEventListener("submit", async (e) => {
  e.preventDefault();
  const datos = Object.fromEntries(new FormData(e.target));
  for (const c of ["precio_base", "dias_para_ofertar", "duracion_dias"]) datos[c] = Number(datos[c]);
  datos.numero_de_lotes = 0;
  if (!datos.codigo_principal_de_categoria) delete datos.codigo_principal_de_categoria;
  const caja = $("#resultado-simulador");
  caja.classList.remove("vacio");
  caja.innerHTML = '<p class="tenue">Calculando…</p>';
  try {
    const p = await api("/api/puntuar", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(datos) });
    caja.innerHTML = htmlFicha({ ...p, prioridad: null, id_del_proceso: "Proceso simulado" }) +
      `<p class="tenue">Umbral de alerta: riesgo de ${pct(p.umbral_alerta_pct)} o más.</p>`;
  } catch (err) {
    caja.innerHTML = `<p>No fue posible puntuar el proceso: ${esc(err.message)}</p>`;
  }
});

// ------------------------------------------------------------------ cómo funciona
function pintarComo() {
  const r = estado.resumen, m = r.modelo.metricas_prueba_2026 || {}, op = r.modelo.puntos_operacion || {};
  const ap = op["alta precisión (P ≥ 0,80)"] || {}, pr = r.validacion_prospectiva || {};
  const fila = (t, v) => `<tr><td>${t}</td><td>${v}</td></tr>`;
  $("#metricas").innerHTML = `
    <div class="tarjeta"><h3>Modelo (${esc(r.modelo.nombre)}): prueba en 2026</h3><table>
      ${fila("PR-AUC (azar 0,456)", dec(m["PR-AUC"]))}${fila("ROC-AUC", dec(m["ROC-AUC"]))}
      ${fila("Precisión en el 1 % superior", pct(m["P@1%"] * 100))}${fila("Precisión de las alertas", pct(ap["precisión"] * 100))}
      ${fila("Recall de las alertas", pct(ap["recall"] * 100))}</table>
      <p class="tenue">LightGBM con historial de la entidad y texto del objeto (TF-IDF). Entrenado con 2017–2024, umbral y calibración en 2025.</p></div>
    <div class="tarjeta"><h3>Sistema desplegado: validación prospectiva</h3><table>
      ${fila("Procesos evaluados", fmt.format(pr.procesos_evaluados || 0))}${fila("Tasa real de oferente único", pct((pr.tasa_real || 0) * 100))}
      ${fila("PR-AUC", dec(pr["PR-AUC"]))}${fila("Precisión de las alertas", pct((pr.precision_alertas || 0) * 100))}
      ${fila("Recall de las alertas", pct((pr.recall_alertas || 0) * 100))}</table>
      <p class="tenue">Semanas posteriores al corte de los datos de entrenamiento (${esc(r.modelo.fecha_corte_datos)}).</p></div>`;
  graficoSemanas(r.validacion_por_semana || []);
}

function graficoSemanas(s) {
  if (!s.length) { $("#grafico-semanas").innerHTML = '<p class="tenue">Sin datos de validación prospectiva.</p>'; return; }
  const W = 720, H = 220, m = { i: 44, d: 16, s: 16, f: 34 };
  const x = (i) => m.i + (i + 0.5) * (W - m.i - m.d) / s.length, y = (v) => H - m.f - v * (H - m.s - m.f);
  const series = [["PR-AUC", "var(--acento)"], ["P@50", "var(--riesgo)"], ["tasa_real", "var(--pares)"]];
  const nombres = { "PR-AUC": "PR-AUC", "P@50": "Precisión de las 50 primeras", tasa_real: "Tasa real (azar)" };
  let svg = `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Métricas por semana">`;
  for (const t of [0, 0.25, 0.5, 0.75, 1]) svg += `<line x1="${m.i}" x2="${W - m.d}" y1="${y(t)}" y2="${y(t)}" stroke="var(--borde)"/><text x="${m.i - 8}" y="${y(t) + 4}" text-anchor="end">${t.toFixed(2).replace(".", ",")}</text>`;
  s.forEach((f, i) => { svg += `<text x="${x(i)}" y="${H - 12}" text-anchor="middle">${f.ejecucion.slice(5)}</text>`; });
  for (const [c, color] of series) {
    svg += `<polyline fill="none" stroke="${color}" stroke-width="2.5" points="${s.map((f, i) => `${x(i)},${y(f[c])}`).join(" ")}"/>`;
    s.forEach((f, i) => { svg += `<circle cx="${x(i)}" cy="${y(f[c])}" r="3.5" fill="${color}"><title>${nombres[c]}: ${Number(f[c]).toFixed(3)}</title></circle>`; });
  }
  svg += "</svg>";
  const leyenda = series.map(([c, color]) => `<span style="margin-right:14px"><span style="display:inline-block;width:12px;height:3px;background:${color};vertical-align:middle"></span> ${nombres[c]}</span>`).join("");
  $("#grafico-semanas").innerHTML = svg + `<div class="tenue" style="font-size:.85rem">${leyenda} · eje x: fecha de ejecución simulada</div>`;
}

// ------------------------------------------------------------------ inicio
(async () => {
  estado.resumen = await api("/api/resumen");
  await cargarFiltros();
  await cargarLista();
  // ?guia=0 no abre la guía (capturas, demostraciones); ?guia=N la abre en el paso N
  const pedida = new URLSearchParams(location.search).get("guia");
  if (window.guia && pedida !== "0" && (pedida || !window.guia.vista())) window.guia.iniciar(Math.max(0, Number(pedida || 1) - 1));
})();
