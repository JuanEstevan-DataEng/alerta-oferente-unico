// Guía rápida: oscurece la página, ilumina una herramienta a la vez y la explica en un globo con contador (1/8, 2/8…).
// Se abre sola la primera vez y después con el botón «Guía rápida».
(() => {
  const CLAVE = "guia-oferente-unico-v1";
  const umbral = () => {
    const u = estado.resumen?.vigentes?.umbral_alerta_riesgo_pct;
    return u == null ? "el umbral" : `${String(u).replace(".", ",")} %`;
  };

  // Cada paso: elementos a iluminar (vacío = globo centrado), título y texto
  const PASOS = [
    { sel: [], titulo: "Te damos la bienvenida",
      texto: () => "Esta página ayuda a veedurías, personerías y ciudadanía a decidir <b>por dónde empezar a revisar</b> la " +
        "contratación pública. Cada día ordena los procesos de SECOP II que todavía reciben ofertas según qué tan probable " +
        "es que llegue <b>una sola oferta</b>, es decir, que no haya competencia." },
    { sel: [".aviso"], titulo: "Priorizar, no señalar",
      texto: () => "Una alerta no es una acusación: indica que vale la pena mirar con más atención. " +
        "El riesgo tampoco es una cuenta regresiva: <b>no sube con el paso de los días</b>." },
    { sel: ["#campo-departamento", "#campo-municipio", "#campo-buscar"], titulo: "Busca tu territorio",
      texto: () => "Elige el departamento y escribe o elige tu municipio. El buscador encuentra <b>palabras completas</b> " +
        "en la entidad o en el objeto del contrato: «Cali» no trae «Calima» ni «calidad»." },
    { sel: ["#campo-orden"], titulo: "Decide qué revisar primero",
      texto: () => "Por defecto salen primero los procesos que <b>más se salen de lo normal</b> para procesos similares. " +
        "Si te importa más la plata, elige <b>«Monto en juego»</b> (riesgo × precio base)." },
    { sel: ["#casilla-alertas", "#casilla-nuevos"], titulo: "Filtra lo urgente",
      texto: () => `«Solo alertas» deja los procesos con riesgo de <b>${umbral()} o más</b>. ` +
        "«Solo nuevos de hoy» muestra los que entraron a la lista desde ayer." },
    { sel: ["#filas tr[data-id] td:nth-child(6)", "#filas tr[data-id] td:nth-child(7)", "#encabezado th:nth-child(6)", "#encabezado th:nth-child(7)"],
      titulo: "Lee el riesgo",
      texto: () => "La barra es la probabilidad de que llegue una sola oferta. La <b>rayita</b> marca lo normal en procesos " +
        "similares (mismo tipo de compra, modalidad, monto y tamaño del municipio). Entre más lejos esté la barra de la rayita, " +
        "más arriba sale el proceso." },
    { sel: ["#filas tr[data-id]"], titulo: "Abre un proceso",
      texto: () => "Haz clic en una fila para ver <b>por qué</b> salió con riesgo alto, hasta cuándo recibe ofertas y el enlace " +
        "para revisarlo en SECOP II." },
    { sel: ["#descargar"], titulo: "Llévate la lista",
      texto: () => "Descarga en CSV la lista con los filtros que elegiste. Puedes volver a ver esta guía cuando quieras con el " +
        "botón <b>«Guía rápida»</b> de la parte de arriba." },
  ];

  let paso = 0, bloqueo, capa, foco, globo, activa = false, temporizador;

  function guardarVista() { try { localStorage.setItem(CLAVE, "1"); } catch { /* sin almacenamiento: se mostrará de nuevo */ } }
  function vista() { try { return localStorage.getItem(CLAVE) === "1"; } catch { return false; } }

  function elementos(p) {
    // Para selectores de filas se toma solo la primera coincidencia; se descartan los ocultos
    return p.sel.map((s) => document.querySelector(s))
      .filter((el) => el && el.getClientRects().length && getComputedStyle(el).visibility !== "hidden");
  }

  function union(els) {
    const r = els.map((el) => el.getBoundingClientRect());
    const izq = Math.min(...r.map((x) => x.left)), arr = Math.min(...r.map((x) => x.top));
    return { left: izq, top: arr, width: Math.max(...r.map((x) => x.right)) - izq, height: Math.max(...r.map((x) => x.bottom)) - arr };
  }

  function crear() {
    // bloqueo: impide usar la página durante la guía; capa: fondo oscuro con un hueco sobre la herramienta
    bloqueo = Object.assign(document.createElement("div"), { className: "guia-bloqueo" });
    capa = Object.assign(document.createElement("div"), { className: "guia-capa" });
    foco = Object.assign(document.createElement("div"), { className: "guia-foco" });
    globo = Object.assign(document.createElement("div"), { className: "guia-globo" });
    globo.setAttribute("role", "dialog");
    globo.setAttribute("aria-modal", "true");
    globo.setAttribute("aria-labelledby", "guia-titulo");
    globo.addEventListener("click", (e) => {
      const accion = e.target.closest("[data-accion]")?.dataset.accion;
      if (accion === "siguiente") ir(paso + 1);
      if (accion === "anterior") ir(paso - 1);
      if (accion === "saltar") cerrar();
    });
    document.body.append(bloqueo, capa, foco, globo);
  }

  function pintar() {
    const p = PASOS[paso], n = PASOS.length, ultimo = paso === n - 1;
    globo.innerHTML = `
      <div class="guia-cabeza"><span class="guia-contador">${paso + 1}/${n}</span>
        <span class="guia-puntos" aria-hidden="true">${PASOS.map((_, k) => `<i class="${k === paso ? "activo" : ""}"></i>`).join("")}</span></div>
      <h2 id="guia-titulo">${p.titulo}</h2>
      <p>${p.texto()}</p>
      <div class="guia-acciones">
        ${ultimo ? "<span></span>" : '<button type="button" class="guia-saltar" data-accion="saltar">Saltar guía</button>'}
        <span class="guia-botones">
          ${paso > 0 ? '<button type="button" class="boton secundario" data-accion="anterior">Anterior</button>' : ""}
          <button type="button" class="boton" data-accion="${ultimo ? "saltar" : "siguiente"}">${ultimo ? "Terminar" : "Siguiente"}</button>
        </span>
      </div>`;
    globo.querySelector(".boton:last-child").focus({ preventScroll: true });
  }

  function posicionar() {
    if (!activa) return;
    const els = elementos(PASOS[paso]);
    const margen = 8, ancho = innerWidth, alto = innerHeight;
    const g = globo.getBoundingClientRect();
    globo.classList.remove("arriba", "abajo", "centro");
    if (!els.length) {
      // Sin herramienta: todo oscuro y el globo al centro
      capa.style.clipPath = "none";
      foco.classList.add("oculto");
      Object.assign(globo.style, { left: `${(ancho - g.width) / 2}px`, top: `${(alto - g.height) / 2}px` });
      globo.classList.add("centro");
      return;
    }
    const r = union(els);
    const f = { left: r.left - margen, top: r.top - margen, width: r.width + 2 * margen, height: r.height + 2 * margen };
    Object.assign(foco.style, { left: `${f.left}px`, top: `${f.top}px`, width: `${f.width}px`, height: `${f.height}px` });
    foco.classList.remove("oculto");
    const [x1, y1, x2, y2] = [f.left, f.top, f.left + f.width, f.top + f.height].map((v) => `${Math.round(v)}px`);
    capa.style.clipPath = `polygon(evenodd, 0 0, 100% 0, 100% 100%, 0 100%, 0 0, ${x1} ${y1}, ${x2} ${y1}, ${x2} ${y2}, ${x1} ${y2}, ${x1} ${y1})`;
    const espacio = 14;
    const debajo = f.top + f.height + espacio + g.height <= alto - 8 || f.top < g.height + espacio + 8;
    const top = debajo ? f.top + f.height + espacio : f.top - espacio - g.height;
    const left = Math.min(Math.max(16, f.left + f.width / 2 - g.width / 2), ancho - g.width - 16);
    globo.classList.add(debajo ? "abajo" : "arriba");
    globo.style.setProperty("--flecha", `${Math.min(Math.max(20, f.left + f.width / 2 - left), g.width - 20)}px`);
    Object.assign(globo.style, { left: `${left}px`, top: `${Math.max(8, Math.min(top, alto - g.height - 8))}px` });
  }

  function ir(n) {
    if (n < 0 || n >= PASOS.length) return;
    paso = n;
    pintar();
    const els = elementos(PASOS[paso]);
    // Desplazamiento inmediato: el foco y el globo ya se animan al moverse
    if (els.length) els[0].scrollIntoView({ block: "center", behavior: "auto" });
    posicionar();
    clearTimeout(temporizador);
    temporizador = setTimeout(posicionar, 60);  // por si la página termina de acomodarse
  }

  function teclas(e) {
    if (!activa) return;
    if (e.key === "Escape") { e.stopPropagation(); cerrar(); }
    if (e.key === "ArrowRight") ir(paso + 1);
    if (e.key === "ArrowLeft") ir(paso - 1);
  }

  function cerrar() {
    activa = false;
    guardarVista();
    for (const el of [bloqueo, capa, foco, globo]) el?.remove();
    removeEventListener("resize", posicionar);
    removeEventListener("scroll", posicionar, true);
    document.removeEventListener("keydown", teclas, true);
    document.getElementById("abrir-guia")?.focus();
  }

  async function iniciar(desde = 0) {
    if (activa) return;
    if (typeof desde !== "number" || !Number.isFinite(desde)) desde = 0;  // clic en el botón: desde el inicio
    // La guía recorre la lista vigente: se abre esa pestaña y se espera a que la tabla tenga filas
    if (estado.vista !== "vigentes" || document.getElementById("vista-lista").hidden) cambiarVista("vigentes");
    if (typeof cerrarFicha === "function") cerrarFicha();
    for (let t = 0; t < 30 && !document.querySelector("#filas tr[data-id]"); t++) await new Promise((r) => setTimeout(r, 100));
    activa = true;
    crear();
    addEventListener("resize", posicionar);
    addEventListener("scroll", posicionar, true);
    document.addEventListener("keydown", teclas, true);
    ir(Math.min(desde, PASOS.length - 1));
  }

  document.getElementById("abrir-guia").addEventListener("click", iniciar);
  window.guia = { iniciar, vista };
})();
