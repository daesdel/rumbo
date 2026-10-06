/* ============================================================
   app.js  ·  Dashboard de patrimonio
   ============================================================ */
(function () {
  "use strict";

  let D = window.DATOS;
  const $ = s => document.querySelector(s);
  const raiz = document.documentElement;
  const esc = window.escapar;   // escapado unificado (está en graficos.js)

  const recuerda = {
    lee(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    guarda(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* da igual */ } },
  };

  // ?tab=rendimiento&tema=claro abre directamente esa pestaña con ese tema.
  const qs = new URLSearchParams(location.search);
  if (qs.get("tab")) recuerda.guarda("patrimonio.tab", qs.get("tab"));
  if (qs.get("tema")) recuerda.guarda("patrimonio.tema", qs.get("tema"));

  // El tema (claro u oscuro) se aplica siempre, también con la cartera vacía.
  const temaGuardado = recuerda.lee("patrimonio.tema");
  if (temaGuardado) raiz.dataset.tema = temaGuardado;
  const cambiaTema = () => {
    raiz.dataset.tema = raiz.dataset.tema === "claro" ? "oscuro" : "claro";
    recuerda.guarda("patrimonio.tema", raiz.dataset.tema);
  };

  if (!D) {
    $("#btnTema").onclick = cambiaTema;
    // Cartera vacía: solo se enseña «Mis datos», para empezar a meter productos.
    document.body.classList.add("sinDatos");
    document.querySelectorAll("#tabs button").forEach(b =>
      b.setAttribute("aria-selected", String(b.dataset.tab === "datos")));
    document.querySelectorAll(".panel").forEach(p => { p.hidden = p.id !== "tab-datos"; });
    document.querySelectorAll(".aviso-legal, #bannerDemo").forEach(el => { el.hidden = true; });
    document.querySelectorAll("#tabs button").forEach(b => {
      b.onclick = () => {
        document.querySelectorAll("#tabs button").forEach(x => x.setAttribute("aria-selected", String(x === b)));
        document.querySelectorAll(".panel").forEach(p => { p.hidden = p.id !== "tab-" + b.dataset.tab; });
      };
    });
    return;
  }

  const estado = {
    tab: "patrimonio",
    rango: "todo",
    vista: "apilado",
    dist: "clase",
    fondo: null,
    serieDetalle: "posicion",
    mes: (D.resumenMensual || []).length - 1,
    anual: "mia",
    tablaFiltro: "todos",
    ordenTabla: { col: "fecha", desc: true },
    btcVivo: null,
    compRef: recuerda.lee("patrimonio.compRef") || "mundo",
    ocultos: new Set(),
    // Filtros globales del panel: [Total · David · Gina · Compartido] × [Global · EUR · USD]
    prop: recuerda.lee("patrimonio.prop") || "total",
    mon: recuerda.lee("patrimonio.mon") || "global",
    // Moneda en la que se MUESTRAN las cifras (los datos se convierten al pintar).
    vis: recuerda.lee("patrimonio.vis") === "USD" ? "USD" : "EUR",
    // Periodo de la pestaña «Periodo»: últimos X días, año Y o dos fechas.
    periodo: recuerda.lee("patrimonio.periodo") || "u30",
    perDesde: recuerda.lee("patrimonio.perDesde") || "",
    perHasta: recuerda.lee("patrimonio.perHasta") || "",
  };
  G.setMoneda(estado.vis);

  /* ----------------------------------------------------------------
     Moneda de visualización: todo se puede ver en euros (por defecto)
     o en dólares. Las series se convierten con el cambio de CADA DÍA
     (por eso una inversión comprada en dólares rinde distinto en una
     moneda que en la otra) y las cifras puntuales con el cambio de hoy.
     ---------------------------------------------------------------- */
  const enUSD = () => estado.vis === "USD";
  const red2 = v => Math.round(v * 100) / 100;
  let convUSD = new WeakMap();          // conversión cacheada por producto
  let mapaIdx = null, mapaMeses = null; // fecha -> índice, mes -> último índice
  const reiniciaConv = () => { convUSD = new WeakMap(); mapaIdx = null; mapaMeses = null; };
  function idxFecha(f) {
    if (!mapaIdx) { mapaIdx = new Map(); D.fechas.forEach((x, i) => mapaIdx.set(x, i)); }
    const i = mapaIdx.get(f);
    return i === undefined ? -1 : i;
  }
  function ultimoIdxMes(ym) {
    if (!mapaMeses) { mapaMeses = new Map(); D.fechas.forEach((x, i) => mapaMeses.set(x.slice(0, 7), i)); }
    const i = mapaMeses.get(ym);
    return i === undefined ? D.fechas.length - 1 : i;
  }
  /** Dólares por euro en el día i, con el cambio actual de respaldo.
      (El motor guarda en fx.USDEUR lo que su nombre no dice: dólares por euro.) */
  function fxEn(i) {
    if (!enUSD()) return 1;
    const s = D.fxSerie || [];
    let t = null;
    if (i >= 0) for (let k = Math.min(i, s.length - 1); k >= 0; k--) { if (s[k] != null) { t = s[k]; break; } }
    if (t == null) for (let k = 0; k < s.length; k++) { if (s[k] != null) { t = s[k]; break; } }
    if (t == null) t = (D.fx && D.fx.USDEUR) || null;
    return t || 1;
  }
  const fxHoy = () => fxEn(D.fechas.length - 1);
  const convAhora = v => (v == null || !enUSD()) ? v : red2(v * fxHoy());
  /** Ver la cartera en otra divisa es SIEMPRE una traducción al cambio de hoy:
      cada cifra en euros se multiplica por el cambio actual, ni más ni menos.
      Así «en euros» y «en dólares» dan el mismo signo, el mismo porcentaje y la
      misma rentabilidad. Si cada día se convirtiera con su cambio de ese día, el
      movimiento del EUR/USD del periodo se colaría en la cifra y un +170 € de hoy
      podía salir como −24 $: la ganancia no cambia de signo por mirarla en dólares. */
  function convSerie(arr) {
    if (!arr || !enUSD()) return arr;
    const k = fxHoy();
    return arr.map(v => v == null ? null : red2(v * k));
  }
  function convApSerie(arr) {
    if (!arr || !enUSD()) return arr;
    const k = fxHoy();
    return arr.map(v => v == null ? null : red2(v * k));
  }
  /** Copia del producto con sus cifras en la moneda de visualización (cacheada). */
  function baseConv(p) {
    if (!enUSD() || p._conv) return p;      // idempotente: no convertir dos veces
    let c = convUSD.get(p);
    if (c) return c;
    c = Object.assign({}, p, { _conv: true });
    c.valor = convAhora(p.valor);
    ["aportado", "realizado", "dividendos", "intereses", "impuestosPagados",
      "precioMedio", "precioActual", "nav"].forEach(k => { if (p[k] != null) c[k] = convAhora(p[k]); });
    if (p.serie) c.serie = convSerie(p.serie);
    if (p.serieAportado) c.serieAportado = convApSerie(p.serieAportado);
    // El aportado total se toma de su curva ya convertida: así cada aporte va
    // con el cambio del día en que se hizo (un depósito en dólares sigue siendo
    // los dólares que metiste) y la rentabilidad en USD difiere de la de EUR.
    if (p.aportado != null && c.serieAportado) {
      const ap = c.serieAportado.reduce((a, v) => (v == null ? a : v), null);
      if (ap != null) c.aportado = ap;
    }
    if (p.flujos) c.flujos = p.flujos.map(([f, v]) => [f, red2(v * (enUSD() ? fxHoy() : 1))]);
    if (p.aportaciones) c.aportaciones = p.aportaciones.map(a => Object.assign({}, a, {
      importe: a.importe != null ? convAhora(a.importe) : null,
      valor: a.valor != null ? convAhora(a.valor) : null,
    }));
    if (p.tramos) {
      const t = Object.assign({}, p.tramos);
      ["p33", "p67", "min", "max", "mediana"].forEach(k => { if (t[k] != null) t[k] = convAhora(t[k]); });
      c.tramos = t;
    }
    convUSD.set(p, c);
    return c;
  }

  /* ----------------------------------------------------------------
     Secciones que el motor calcula con TODA la cartera (rentabilidad anual,
     comparador de riesgo, «¿y si lo hubieras metido en un indexado?» y
     comisiones). Aquí se vuelven a montar con los filtros puestos, para que
     al elegir propietario, divisa u ocultar componentes cambien también ellas.
     Sin filtros se usan los datos tal cual los mandó el motor.
     ---------------------------------------------------------------- */
  /** Los datos en crudo (sin convertir a la divisa de vista) ya filtrados. */
  function crudos(lista) {
    const out = [];
    lista.forEach(p => {
      if (!pasaMoneda(p)) return;
      const f = factorDe(p);
      if (f <= 1e-9) return;
      if (estado.ocultos.has(p.id)) return;
      out.push(f === 1 ? p : escala(p, f));
    });
    return out;
  }
  const r4 = v => (v == null ? null : Math.round(v * 10000) / 10000);
  const r2 = v => (v == null ? null : Math.round(v * 100) / 100);

  /** Índice encadenado (base 100), limpio del efecto de cuándo entra el dinero.
      Espejo exacto de motor.indice_twr(). */
  function indiceTWR(valores, flujos) {
    const out = [];
    let ant = null, nivel = 100;
    for (let i = 0; i < valores.length; i++) {
      const v = valores[i];
      const f = i < flujos.length ? flujos[i] : 0;
      if (v == null) { out.push(nivel); continue; }
      if (ant == null || ant <= 1) { if (f > 0) nivel *= Math.max(v / f, 0.05); }
      else nivel *= 1 + Math.max((v - f) / ant - 1, -0.95);
      out.push(nivel);
      ant = v;
    }
    return out;
  }

  /** Índice de TU cartera con los filtros puestos (sin filtros, el del motor). */
  function idxCartera() {
    if (!filtrando()) {
      const real = (D.comparador || []).find(x => x.real);
      return real && real.indice ? real.indice : null;
    }
    const n = D.fechas.length;
    const lista = crudos(D.productos).filter(p => p.origen === "csv" || p.origen === "ordenes");
    if (!lista.length) return null;
    const serie = new Array(n).fill(0), fl = new Array(n).fill(0);
    let hay = false;
    lista.forEach(p => {
      const s = p.serie || [];
      for (let i = 0; i < n; i++) if (s[i] != null) { serie[i] += s[i]; hay = true; }
      (p.flujos || []).forEach(([f, v]) => { const i = idxFecha(f); if (i >= 0) fl[i] -= v; });
    });
    return hay ? indiceTWR(serie, fl) : null;
  }

  /** Rentabilidad por año natural de un índice (espejo de rentabilidadAnual.cartera). */
  function rentAnualDe(idx, anos) {
    if (!idx) return null;
    const f = D.fechas;
    return anos.map(ano => {
      let ini = -1, fin = -1;
      for (let i = 0; i < f.length; i++) if (f[i].slice(0, 4) === ano) { if (ini < 0) ini = i; fin = i; }
      if (fin < 0) return null;
      const b = ini > 0 ? idx[ini - 1] : 100;
      return b ? r4(idx[fin] / b - 1) : null;
    });
  }

  /** Riesgo y rentabilidad de un índice (espejo de motor.metricas_indice). */
  function metricasIndice(idx, rf) {
    if (!idx) return null;
    const pts = [];
    idx.forEach((v, i) => { if (v) pts.push(i); });
    if (pts.length < 30) return null;
    const i0 = pts[0], i1 = pts[pts.length - 1];
    const dias = (Date.parse(D.fechas[i1]) - Date.parse(D.fechas[i0])) / 864e5;
    const anos = dias / 365.25;
    const rent = idx[i1] / idx[i0] - 1;
    const cagr = anos > 0.15 ? Math.pow(idx[i1] / idx[i0], 1 / anos) - 1 : null;
    const rs = [];
    let ant = null;
    for (let i = i0; i <= i1; i++) {
      const wd = new Date(D.fechas[i] + "T00:00:00Z").getUTCDay();
      if (wd === 0 || wd === 6 || !idx[i]) continue;
      if (ant) rs.push(idx[i] / ant - 1);
      ant = idx[i];
    }
    let vol = null;
    if (rs.length > 20) {
      const mu = rs.reduce((a, b) => a + b, 0) / rs.length;
      vol = Math.sqrt(rs.reduce((a, b) => a + (b - mu) * (b - mu), 0) / (rs.length - 1)) * Math.sqrt(252);
    }
    let pico = 0, dd = 0;
    for (let i = i0; i <= i1; i++) {
      if (!idx[i]) continue;
      pico = Math.max(pico, idx[i]);
      dd = Math.min(dd, idx[i] / pico - 1);
    }
    return {
      rentTotal: r4(rent), cagr: r4(cagr), vol: r4(vol),
      sharpe: cagr != null && vol && rf != null ? r4((cagr - rf) / vol) : null,
      maxDD: r4(dd), desde: D.fechas[i0], hasta: D.fechas[i1],
    };
  }

  /* ---------------------------------------------- ¿y si lo hubieras metido en un indexado? */
  /** El comparador del motor, recalculado con los filtros puestos. */
  function comparacionFiltrada() {
    const base = D.comparacion;
    if (!base || !base.referencias || !base.referencias.length) return base;
    if (!filtrando()) return base;
    const n = D.fechas.length;
    // Igual que el motor: TODO lo visible (productos, cuentas y valores a mano)
    // y las entradas y salidas de dinero (los cambios de la curva de aportado).
    const conAp = crudos(D.productos).concat(crudos(D.otrosActivos || []));
    const tuya = new Array(n).fill(0), ap = new Array(n).fill(0);
    conAp.concat(crudos(D.pasivos || [])).forEach(p => {
      const s = p.serie || [];
      for (let i = 0; i < n; i++) if (s[i] != null) tuya[i] += s[i];
    });
    conAp.forEach(p => {
      const a = p.serieAportado || [];
      for (let i = 0; i < n; i++) if (a[i] != null) ap[i] += a[i];
    });
    const flujo = new Array(n).fill(0);
    let hayFlujo = false;
    for (let i = 1; i < n; i++) {
      const dif = (ap[i] || 0) - (ap[i - 1] || 0);
      if (Math.abs(dif) >= 0.005) { flujo[i] = dif; hayFlujo = true; }
    }
    if (!hayFlujo) return null;
    let i0 = -1;
    for (let i = 0; i < n; i++) {
      tuya[i] = r2(tuya[i]);
      if (i0 < 0 && (tuya[i] || flujo[i])) i0 = i;
    }
    if (i0 < 0) return null;
    const aportado = [];
    for (let i = 0; i < n; i++) aportado.push(i >= i0 ? r2(ap[i]) : null);
    const flujosC = [];
    for (let i = 0; i < n; i++) if (flujo[i]) flujosC.push({ t: Date.parse(D.fechas[i]), v: -flujo[i] });
    const cierre = Date.parse(D.fechaExtracto);
    const refs = [];
    base.referencias.forEach(r => {
      const piezas = r.piezas;
      if (!piezas) { refs.push(r); return; }       // cálculo viejo guardado: nos quedamos con el suyo
      const primeros = piezas.map(p => p.precios.find(v => v) || null);
      if (primeros.some(v => v == null)) return;
      const unidades = piezas.map(() => 0);
      const serie = [];
      let antes = false;
      for (let i = 0; i < n; i++) {
        const prHoy = piezas.map((p, k) => p.precios[i] || primeros[k]);
        if (flujo[i]) {
          antes = antes || piezas.some((p, k) => p.precios[i] == null);
          for (let k = 0; k < piezas.length; k++) unidades[k] += flujo[i] * piezas[k].peso / prHoy[k];
        }
        const val = piezas.reduce((a, p, k) => a + unidades[k] * prHoy[k], 0);
        serie.push(i >= i0 ? r2(val) : null);
      }
      const final = serie[n - 1];
      refs.push({
        id: r.id, nombre: r.nombre, detalle: r.detalle, serie, valor: final,
        tir: xirr(flujosC.concat([{ t: cierre, v: final }])),
        aviso: antes ? "Tienes aportaciones anteriores a los precios de esta referencia: " +
                       "para esas se usa su primer precio conocido." : null,
      });
    });
    if (!refs.length) return null;
    return {
      desde: D.fechas[i0], tuya: tuya.map((v, i) => i >= i0 ? v : null), aportado,
      tuValor: tuya[n - 1],
      tuTir: xirr(flujosC.concat([{ t: cierre, v: tuya[n - 1] }])),
      referencias: refs,
    };
  }

  function pintaComparacion() {
    const sec = $("#seccionComparar");
    const C = comparacionFiltrada();
    if (!sec) return;
    if (!C || !C.referencias.length) {
      // Sin el campo, los datos los calculó una versión anterior de la app (que sigue abierta).
      $("#compTitular").innerHTML = !C && filtrando()
        ? '<p class="vacio">Con estos filtros no queda ninguna compra anotada, así que no hay nada que comparar. Quita el filtro de arriba para ver la comparación completa.</p>'
        : "comparacion" in D
        ? '<p class="vacio">Aparecerá cuando tengas compras anotadas.</p>'
        : '<p class="vacio">Cierra la ventana negra de la app y vuelve a abrirla para calcular esta sección.</p>';
      $("#compRef").innerHTML = "";
      $("#grafComparacion").innerHTML = "";
      return;
    }
    if (!C.referencias.some(r => r.id === estado.compRef)) estado.compRef = C.referencias[0].id;
    const r = C.referencias.find(x => x.id === estado.compRef);
    const segm = $("#compRef");
    segm.innerHTML = "";
    C.referencias.forEach(x => {
      const b = document.createElement("button");
      b.textContent = x.nombre;
      b.setAttribute("aria-pressed", String(x.id === r.id));
      b.onclick = () => { estado.compRef = x.id; recuerda.guarda("patrimonio.compRef", x.id); pintaComparacion(); };
      segm.appendChild(b);
    });
    const dif = C.tuValor - r.valor;
    const pct = r.valor ? dif / r.valor : 0;
    const igual = Math.abs(pct) < 0.005;
    const nom = esc(r.nombre);   // nombre de la referencia (puede ser tuyo)
    // Las tres series y las cajas se pasan a la moneda de visualización.
    const apConv = convApSerie(C.aportado);
    const apHoy = apConv[apConv.length - 1];
    const tuV = convAhora(C.tuValor), refV = convAhora(r.valor);
    const difM = tuV - refV;
    const veredicto = igual ? `Vas prácticamente igual que el ${nom}.`
      : dif > 0 ? `Vas ${G.fmtEur(Math.abs(difM))} por delante del ${nom} (${G.fmtPctSigno(pct, 1)}).`
      : `Con el ${nom} tendrías ${G.fmtEur(Math.abs(difM))} más (${G.fmtPctSigno(-dif / C.tuValor, 1)}).`;
    const caja = (et, v, extra, cls = "") => `<div class="compCaja ${cls}"><span>${et}</span><b>${v}</b>${extra ? `<small>${extra}</small>` : ""}</div>`;
    $("#compTitular").innerHTML =
      caja("Tú tienes hoy", G.fmtEur(tuV), `TIR ${G.fmtPctSigno(C.tuTir, 1)}`) +
      caja(`Con el ${nom} tendrías`, G.fmtEur(refV), `TIR ${G.fmtPctSigno(r.tir, 1)}`) +
      caja("Has puesto de tu bolsillo", G.fmtEur(apHoy), "compras menos ventas") +
      caja("Veredicto", veredicto, "", "veredicto");
    G.multiLinea($("#grafComparacion"), {
      fechas: D.fechas, alto: 300,
      series: [
        { nombre: "Tu cartera", valores: convSerie(C.tuya), color: G.css("--s1"), destacado: true },
        { nombre: "Con el " + r.nombre, valores: convSerie(r.serie), color: G.css("--s2") },
        { nombre: "Tu dinero puesto", valores: apConv, color: G.css("--tinta3") },
      ],
      formatoY: v => G.fmtEurCorto(v),
      formatoValor: v => G.fmtEur(v, 0),
      desdeCero: true,
    });
    const ley = (c, t) => `<span class="leyItem"><i style="background:${G.css(c)}"></i>${esc(t)}</span>`;
    $("#compNota").innerHTML = `<span class="leyComp">${ley("--s1", "Tu cartera")}${ley("--s2", "Con el " + r.nombre)}${ley("--tinta3", "Tu dinero puesto")}</span>
      ${esc(r.detalle)} Se compara con <b>todo tu patrimonio</b> (productos, cuentas de efectivo y lo que
      valoras a mano), con las entradas y salidas de dinero que has anotado, desde el ${G.fmtFecha(C.desde)}:
      las cifras cuadran con las de la pestaña Patrimonio. Sin impuestos ni comisiones de compra.
      ${filtrando() ? "<br><b>Con los filtros de arriba aplicados</b>: solo entran los componentes que estás viendo." : ""}
      ${r.aviso ? "<br>" + esc(r.aviso) : ""}`;
  }

  /* ---------------------------------------------- tema y colores */
  function temaOscuro() { return raiz.dataset.tema !== "claro"; }
  function color(p) {
    const c = p.slotColor || p.color || ["#2a78d6", "#3987e5"];
    const v = temaOscuro() ? c[1] : c[0];
    // Solo se admite un color hex: lo que venga de datos a mano no se cuela en el CSS.
    return typeof v === "string" && /^#[0-9a-fA-F]{3,8}$/.test(v)
      ? v : (temaOscuro() ? "#3987e5" : "#2a78d6");
  }
  function hex2rgb(h) {
    h = String(h).replace("#", "");
    if (h.length === 3) h = h.split("").map(c => c + c).join("");
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
  }
  function mezcla(a, b, t) {
    const A = hex2rgb(a), B = hex2rgb(b);
    return "#" + A.map((v, i) => Math.round(v + (B[i] - v) * t).toString(16).padStart(2, "0")).join("");
  }
  /** Tres tonos del propio color del producto: pequeña, habitual, extraordinaria. */
  function tonos(base) {
    return temaOscuro()
      ? [mezcla(base, "#1a1a19", 0.52), base, mezcla(base, "#ffffff", 0.42)]
      : [mezcla(base, "#fcfcfb", 0.58), base, mezcla(base, "#000000", 0.32)];
  }

  const TODOS_CRUDOS = () => D.productos.concat(D.otrosActivos || [], D.pasivos || []).map(baseConv);

  /* ----------------------------------------------------------------
     Filtros globales: propietario (Total/David/Gina/Compartido) y
     divisa (Global/EUR/USD). TODOS() es la única puerta de entrada a los
     datos del panel: lo que salga de aquí es lo que ve cada widget, así que
     al pulsar un botón cambian KPIs, gráficos y tablas de golpe.
     Si un producto es de dos personas, se muestra la parte que toca.
     ---------------------------------------------------------------- */
  const filtrosActivos = () => estado.prop !== "total" || estado.mon !== "global";
  function factorDe(p) {
    if (estado.prop === "total") return 1;
    const d = p.duenos || {};
    if (d[estado.prop]) return d[estado.prop];
    return p.propietario === estado.prop ? 1 : 0;
  }
  function pasaMoneda(p) {
    if (estado.mon === "global") return true;
    return (p.moneda || "EUR").toUpperCase() === estado.mon;
  }
  function escala(p, f) {
    const c = Object.assign({}, p, { _f: f });
    const m = v => (v == null ? null : v * f);
    c.valor = m(p.valor || 0);
    ["aportado", "realizado", "dividendos", "intereses", "impuestosPagados",
      "participaciones", "titulos"].forEach(k => { if (p[k] != null) c[k] = m(p[k]); });
    if (p.serie) c.serie = p.serie.map(m);
    if (p.serieAportado) c.serieAportado = p.serieAportado.map(m);
    if (p.flujos) c.flujos = p.flujos.map(([f1, v]) => [f1, m(v)]);
    if (p.aportaciones) c.aportaciones = p.aportaciones.map(a =>
      Object.assign({}, a, { importe: m(a.importe), valor: m(a.valor) }));
    if (p.tramos) {
      const t = Object.assign({}, p.tramos);
      ["p33", "p67", "min", "max", "mediana"].forEach(k => { if (t[k] != null) t[k] = m(t[k]); });
      c.tramos = t;
    }
    return c;
  }
  const TODOS = () => {
    const out = [];
    TODOS_CRUDOS().forEach(p => {
      if (!pasaMoneda(p)) return;
      const f = factorDe(p);
      if (f <= 1e-9) return;
      const b = baseConv(p);
      out.push(f === 1 ? Object.assign({}, b, { _f: 1 }) : escala(b, f));
    });
    const peso = out.reduce((a, p) => a + (p.valor || 0), 0);
    out.forEach(p => { p.peso = peso ? (p.valor || 0) / peso : 0; });   // reparto dentro del filtro
    return out;
  };
  const visibles = () => TODOS().filter(p => !estado.ocultos.has(p.id));
  const filtrando = () => estado.ocultos.size > 0 || filtrosActivos();
  const buscaProd = id => TODOS().find(p => p.id === id);
  const cuentasFiltradas = () => (D.cuentas || []).filter(c =>
    (estado.mon === "global" || String(c.moneda || "EUR").toUpperCase() === estado.mon) &&
    (estado.prop === "total" || c.propietario === estado.prop));

  /* ---------------------------------------------- precio en vivo */
  function precioVivo() {
    const v = D.vivo;
    if (!v || !estado.btcVivo) return null;
    return { id: v.productoId, titulos: v.titulos, precio: v.precioRef * (estado.btcVivo / v.btcRef) };
  }
  function valorDe(p) {
    const pv = precioVivo();
    if (pv && p.id === pv.id) return convAhora(pv.titulos * pv.precio);
    return p.valor || 0;
  }

  /** Plusvalía calculada con el mismo valor que se enseña (en vivo si lo hay),
      para que valor, plusvalía y porcentaje siempre sumen entre sí. */
  function plusvaliaDe(p) {
    if (p.aportado == null || !(p.aportado > 0)) return null;
    const eur = valorDe(p) - p.aportado;
    return { eur, pct: eur / p.aportado };
  }

  /* ---------------------------------------------- TIR (XIRR) */
  function xirr(flujos) {
    const f = flujos.filter(x => x.v);
    if (f.length < 2) return null;
    if (!(f.some(x => x.v < 0) && f.some(x => x.v > 0))) return null;
    const t0 = Math.min.apply(null, f.map(x => x.t));
    const ANO = 365 * 24 * 3600 * 1000;
    const van = tasa => {
      let s = 0;
      const base = 1 + tasa;
      if (base <= 1e-9) return Infinity;
      for (const x of f) s += x.v / Math.pow(base, (x.t - t0) / ANO);
      return s;
    };
    let lo = -0.9999, hi = 10, vlo = van(lo), vhi = van(hi);
    if (!isFinite(vlo) || !isFinite(vhi) || vlo * vhi > 0) return null;
    for (let i = 0; i < 200; i++) {
      const mid = (lo + hi) / 2, vm = van(mid);
      if (Math.abs(vm) < 1e-7) return mid;
      if (vlo * vm <= 0) hi = mid; else { lo = mid; vlo = vm; }
    }
    return (lo + hi) / 2;
  }

  /* ----------------------------------------------------------------
     Métricas de un conjunto de componentes. Se recalcula todo aquí
     para que, al apagar series, cada cifra del panel siga cuadrando.
     ---------------------------------------------------------------- */
  function metricas(lista) {
    const n = D.fechas.length;
    const serie = new Array(n).fill(0);
    const serieAp = new Array(n).fill(0);
    let valor = 0, aportado = 0, valorConCoste = 0, valorTir = 0, nAp = 0;
    const flujos = [];

    lista.forEach(p => {
      const s = p.serie || [], sa = p.serieAportado || [];
      for (let i = 0; i < n; i++) {
        if (s[i] != null) serie[i] += s[i];
        if (sa[i] != null) serieAp[i] += sa[i];
      }
      valor += valorDe(p);
      // Puede ser negativo (una cuenta cuyo saldo procede de dividendos ya
      // reinvertidos): el efectivo tiene que contar aunque sea así, o el
      // patrimonio no cuadra con aportado + ganancia.
      if (p.aportado != null) {
        aportado += p.aportado;
        valorConCoste += valorDe(p);
        nAp += (p.aportaciones || []).filter(a => a.importe).length;
      }
      // La TIR usa todo el dinero que entró y salió (compras, ventas, dividendos y
      // comisiones), y solo el valor de los productos que tienen esos movimientos.
      if (p.flujos && p.flujos.length) {
        p.flujos.forEach(([f, v]) => flujos.push({ t: Date.parse(f), v }));
        valorTir += valorDe(p);
      }
    });

    const plusvalia = aportado ? valorConCoste - aportado : null;
    const tir = flujos.length
      ? xirr(flujos.concat([{ t: Date.parse(D.fechaExtracto), v: valorTir }]))
      : null;

    const am = D.aportacionesMensuales;
    const ids = new Set(lista.map(p => p.id));
    const porMes = am.meses.map((_, i) => Object.keys(am.porProducto)
      .reduce((a, id) => a + (ids.has(id) ? (am.porProducto[id][i] || 0) : 0), 0))
      .map(v => convAhora(v));                              // en la divisa de vista
    const mesesConAp = am.meses.filter((m, i) => porMes[i] > 0);
    const ult12 = porMes.slice(-12);
    const ritmo = ult12.length ? ult12.reduce((a, b) => a + b, 0) / ult12.length : 0;

    let racha = 0;
    if (mesesConAp.length) {
      const set = new Set(mesesConAp);
      const ult = mesesConAp[mesesConAp.length - 1].split("-");
      let y = +ult[0], mo = +ult[1];
      while (set.has(y + "-" + String(mo).padStart(2, "0"))) {
        racha++; mo--; if (mo === 0) { mo = 12; y--; }
      }
    }

    let pico = 0, caida = 0, caidaFecha = null;
    for (let i = 0; i < n; i++) {
      pico = Math.max(pico, serie[i]);
      if (pico > 0) {
        const c = serie[i] / pico - 1;
        if (c < caida) { caida = c; caidaFecha = D.fechas[i]; }
      }
    }

    return {
      valor, aportado, valorConCoste, plusvalia,
      rentabilidad: aportado ? plusvalia / aportado : null,
      tir, numAportaciones: nAp, ritmo, racha, caida, caidaFecha,
      serie, serieAportado: serieAp,
    };
  }

  function agrupa(lista, campo) {
    const acc = new Map();
    lista.forEach(p => {
      const k = p[campo] || "Otros";
      const g = acc.get(k) || { nombre: k, valor: 0, color: color(p) };
      g.valor += valorDe(p);
      acc.set(k, g);
    });
    return [...acc.values()].filter(g => g.valor > 0).sort((a, b) => b.valor - a.valor);
  }

  /* ---------------------------------------------- rango temporal */
  const RANGOS = [
    { id: "1m", et: "1M", dias: 30 }, { id: "3m", et: "3M", dias: 91 },
    { id: "6m", et: "6M", dias: 182 }, { id: "ytd", et: "YTD", dias: null },
    { id: "1a", et: "1A", dias: 365 }, { id: "todo", et: "Todo", dias: null },
  ];
  function desdeIdx() {
    const n = D.fechas.length;
    const r = RANGOS.find(x => x.id === estado.rango);
    if (!r || r.id === "todo") return 0;
    if (r.id === "ytd") {
      const ini = D.fechaExtracto.slice(0, 4) + "-01-01";
      const i = D.fechas.findIndex(f => f >= ini);
      return i < 0 ? 0 : i;
    }
    return Math.max(0, n - 1 - r.dias);
  }
  const corta = arr => (arr || []).slice(desdeIdx());

  function pintaSegm(cont, opciones, activo, alPulsar) {
    if (!cont) return;
    cont.innerHTML = "";
    opciones.forEach(o => {
      const b = document.createElement("button");
      b.textContent = o.et;
      b.setAttribute("aria-pressed", String(o.id === activo));
      b.onclick = () => alPulsar(o.id);
      cont.appendChild(b);
    });
  }

  /* ---------------------------------------------- filtros globales del panel */
  const MONEDAS = [{ id: "global", et: "Global" }, { id: "EUR", et: "EUR" }, { id: "USD", et: "USD" }];
  function cambiaFiltro(campo, valor) {
    estado[campo] = valor;
    recuerda.guarda("patrimonio." + (campo === "prop" ? "prop" : "mon"), valor);
    estado.ocultos = new Set();       // un filtro nuevo empieza con todo incluido
    estado.tablaFiltro = "todos";
    pintar();
  }
  function pintaFiltrosGlobal() {
    const cont = $("#filtrosGlobal");
    if (!cont) return;
    cont.hidden = !D || estado.tab === "datos" || estado.tab === "ayuda";
    if (cont.hidden) return;
    const props = [{ id: "total", et: "Total" }]
      .concat((D.propietarios || []).map(p => ({ id: p.id, et: p.nombre })));
    if (!props.some(p => p.id === estado.prop)) estado.prop = "total";
    pintaSegm($("#segProp"), props, estado.prop, id => cambiaFiltro("prop", id));
    pintaSegm($("#segMon"), MONEDAS, estado.mon, id => cambiaFiltro("mon", id));
    pintaSegm($("#segVis"), [{ id: "EUR", et: "€ Euros" }, { id: "USD", et: "$ Dólares" }], estado.vis, id => {
      if (id === estado.vis) return;
      estado.vis = id;
      recuerda.guarda("patrimonio.vis", id);
      G.setMoneda(id);
      reiniciaConv();
      pintar();
    });
    const n = TODOS().length;
    const et = (props.find(p => p.id === estado.prop) || {}).et || "Total";
    const mo = (MONEDAS.find(m => m.id === estado.mon) || {}).et || "Global";
    $("#filtrosGlobalNota").textContent = filtrosActivos()
      ? `${et} · ${mo}: ${n} ${n === 1 ? "componente" : "componentes"}` : "";
  }

  /* ================================================================
     PESTAÑA 1 · PATRIMONIO
     ================================================================ */
  const idsCorto = () => TODOS().filter(p => p.largoPlazo === false).map(p => p.id);

  function pintaFiltros() {
    const cont = $("#filtros");
    cont.innerHTML = "";
    TODOS().forEach(p => {
      const on = !estado.ocultos.has(p.id);
      const b = document.createElement("button");
      b.className = "filtro";
      b.style.setProperty("--c", color(p));
      b.setAttribute("aria-pressed", String(on));
      b.title = on ? "Quitar del gráfico y de las métricas" : "Volver a incluirlo";
      b.innerHTML = `<i></i>${esc(p.corto || p.nombre)}<span class="im">${G.fmtEurCorto(valorDe(p))}</span>`;
      b.onclick = () => {
        if (on) { if (visibles().length <= 1) return; estado.ocultos.add(p.id); }
        else estado.ocultos.delete(p.id);
        pintaPatrimonio();
      };
      cont.appendChild(b);
    });
    const sep = document.createElement("span");
    sep.className = "filtroSep";
    cont.appendChild(sep);

    const cortos = idsCorto();
    const esLargo = cortos.length > 0 && cortos.length === estado.ocultos.size &&
      cortos.every(id => estado.ocultos.has(id));
    [
      { id: "todo", et: "Ver todo", act: estado.ocultos.size === 0, fn: () => estado.ocultos.clear() },
      { id: "largo", et: "Solo largo plazo", act: esLargo, fn: () => { estado.ocultos = new Set(cortos); } },
    ].forEach(pr => {
      if (pr.id === "largo" && !cortos.length) return;
      const b = document.createElement("button");
      b.className = "filtro preset";
      b.setAttribute("aria-pressed", String(pr.act));
      b.textContent = pr.et;
      b.title = pr.id === "largo"
        ? "Deja fuera el colchón y el efectivo: solo lo que tienes invertido a largo plazo"
        : "Vuelve a mostrar todos los componentes";
      b.onclick = () => { pr.fn(); pintaPatrimonio(); };
      cont.appendChild(b);
    });
  }

  /** Cambio del día de un producto (datos en crudo): el último valorado contra
      el cierre anterior de la última sesión que cambió. La serie rellena los
      días sin cotización repitiendo el último precio, así que el "cierre
      anterior" es el último valor distinto del actual; si todo el tramo es
      igual, no hay cambio. Con precio en vivo (bitcoin) se mide desde ese
      mismo cierre. El importe sale en la divisa de vista y escalado al
      propietario. */
  function cambioDia(p, valorActual) {
    const n = D.fechas.length;
    const s = p.serie || [];
    if (s.length < n || n < 2) return null;
    const act = valorActual != null ? valorActual : s[n - 1];
    if (act == null) return null;
    let base = null;
    for (let i = n - 2; i >= 0 && i >= n - 90; i--) {
      if (s[i] == null) continue;
      if (base == null) base = s[i];
      if (s[i] !== act) { base = s[i]; break; }
    }
    const f = factorDe(p);
    if (base == null || f <= 1e-9) return null;
    return { eur: convAhora((act - base) * f), pct: base ? (act - base) / base : null };
  }

  /** Los componentes visibles con cambio de día que puede enseñar el ticker. */
  function candidatosTicker() {
    const out = [];
    (D.productos || []).forEach(p => {
      if (!pasaMoneda(p) || estado.ocultos.has(p.id)) return;
      const c = cambioDia(p);
      if (c && c.pct != null) out.push({ p, c });
    });
    return out;
  }

  /** El activo que toca del ticker rotatorio (uno cada X segundos). */
  function pintaTicker() {
    const cont = $("#tickerActivo");
    if (!cont) return;
    const lista = candidatosTicker();
    if (!lista.length) { cont.innerHTML = ""; cont.hidden = true; return; }
    cont.hidden = false;
    const { p, c } = lista[((estado.tick || 0) % lista.length + lista.length) % lista.length];
    const cl = c.eur >= 0 ? "pos" : "neg";
    const nm = p.corto || p.nombre;
    cont.innerHTML = `<span class="latido"></span>${esc(nm)}
      <span class="${cl}">${G.fmtEurSigno(c.eur)} · ${G.fmtPctSigno(c.pct, 2)}</span>`;
    cont.title = `Última sesión de ${nm}: ${G.fmtEurSigno(c.eur)} (${G.fmtPctSigno(c.pct, 2)})`;
  }

  function pintaHero(mVis, mTodo) {
    const filtro = filtrando();
    const m = filtro ? mVis : mTodo;
    $("#heroEtq").textContent = filtro ? "Vista filtrada" : "Patrimonio neto";
    $("#heroCifra").textContent = G.fmtEur(m.valor);

    const partes = [];
    if (m.plusvalia !== null) {
      const cl = m.plusvalia >= 0 ? "pos" : "neg";
      partes.push(`<span class="${cl} fuerte">${G.fmtEurSigno(m.plusvalia)}</span>
        <span class="${cl}">(${G.fmtPctSigno(m.rentabilidad)})</span> sobre lo aportado`);
    }
    if (m.tir !== null) partes.push(`TIR anualizada <span class="fuerte">${G.fmtPctSigno(m.tir)}</span>`);

    const pv = precioVivo();
    if (pv) {
      const p = D.productos.find(x => x.id === pv.id);
      const c = p && !estado.ocultos.has(p.id) && pasaMoneda(p)
        ? cambioDia(p, pv.titulos * pv.precio) : null;
      if (c && c.pct != null) {
        partes.push(`<span class="pill vivo" id="pillBtc"><span class="latido"></span>Bitcoin en vivo
          <span class="${c.eur >= 0 ? "pos" : "neg"}">${G.fmtEurSigno(c.eur)} · ${G.fmtPctSigno(c.pct, 2)}</span></span>`);
      }
    } else if (D.vivo) {
      partes.push(`<span class="pill">Cotización a cierre del ${G.fmtFechaCorta(D.fechaExtracto)}</span>`);
    }
    // El ticker que va recorriendo todos los activos, junto al bitcoin.
    if (candidatosTicker().length)
      partes.push('<span class="pill vivo" id="tickerActivo"></span>');
    if (filtro) {
      partes.push(`<button class="pill reset" id="btnReset" title="Volver a mostrarlo todo">
        de ${G.fmtEur(mTodo.valor)} totales · ver todo</button>`);
    }
    $("#heroSub").innerHTML = partes.join('<span style="color:var(--tinta3)">·</span>');
    pintaTicker();
    const reset = $("#btnReset");
    if (reset) reset.onclick = () => { estado.ocultos.clear(); pintaPatrimonio(); };

    if (filtro) { $("#progEnv").hidden = true; return; }

    // Progreso medido desde cero, que es como se lee de forma natural.
    const propio = (D.objetivo && D.objetivo.activo) ? D.objetivo.importe : null;
    const siguienteHito = (D.total.hitos.find(h => h.importe > m.valor) || {}).importe;
    const sig = (propio && propio > m.valor) ? propio : siguienteHito;
    if (!sig) { $("#progEnv").hidden = true; return; }
    const pct = Math.max(0, Math.min(1, m.valor / sig));
    $("#progEnv").hidden = false;
    $("#progRelleno").style.width = (pct * 100).toFixed(1) + "%";
    $("#progIzq").innerHTML =
      `<b style="color:var(--tinta)">${G.fmtPct(pct, 1)}</b> del camino hacia ${G.fmtEurCorto(sig)}`;
    $("#progDer").textContent = "Faltan " + G.fmtEur(sig - m.valor, 0);
  }

  function pintaKPIs(m) {
    const kpis = [
      { e: "Aportado", v: G.fmtEur(m.aportado), n: `${m.numAportaciones} aportaciones` },
      {
        e: "Ganancia total", v: G.fmtEurSigno(m.plusvalia),
        n: m.rentabilidad != null ? G.fmtPctSigno(m.rentabilidad) + " sobre lo aportado" : "sin coste registrado",
        cl: m.plusvalia >= 0 ? "pos" : "neg"
      },
      { e: "TIR anualizada", v: G.fmtPctSigno(m.tir), n: "rentabilidad real del dinero", cl: m.tir >= 0 ? "pos" : "neg" },
      { e: "Ritmo mensual", v: G.fmtEur(m.ritmo), n: "media de los últimos 12 meses" },
      { e: "Racha", v: m.racha + (m.racha === 1 ? " mes" : " meses"), n: "aportando sin fallar" },
      { e: "Peor caída", v: G.fmtPctSigno(m.caida), n: m.caidaFecha ? "del patrimonio, el " + G.fmtFecha(m.caidaFecha) : "", cl: "neg" },
    ];
    $("#kpis").innerHTML = kpis.map(k =>
      `<div class="kpi"><div class="e">${k.e}</div>
       <div class="v ${k.cl || ""}">${k.v}</div><div class="n">${k.n}</div></div>`).join("");
    $("#kpisNota").textContent = filtrando()
      ? `Métricas de los ${visibles().length} componentes activos, no del patrimonio completo.` : "";
  }

  function pintaPrincipal(m) {
    const fechas = corta(D.fechas);
    const prods = visibles().filter(p => (p.serie || []).some(v => v));
    const cont = $("#grafPrincipal");
    let nota = "";

    if (estado.vista === "total") {
      G.lineaConEventos(cont, {
        fechas, valores: corta(m.serie), color: G.css("--s1"), alto: 330,
        overlay: { nombre: "Aportado", valores: corta(m.serieAportado) },
      });
    } else if (estado.vista === "dinero") {
      // Lo que pusiste tú contra lo que ha puesto el mercado.
      const tuyo = m.serie.map((v, i) => Math.min(m.serieAportado[i], v));
      const mercado = m.serie.map((v, i) => Math.max(0, v - m.serieAportado[i]));
      const bajoCoste = m.serie.some((v, i) => v > 0 && v < m.serieAportado[i] - 0.01);
      G.areaApilada(cont, {
        fechas, alto: 330,
        series: [
          { nombre: "Lo que pusiste tú", color: G.css("--tinta3"), valores: corta(tuyo) },
          { nombre: "Lo que puso el mercado", color: G.css("--s3"), valores: corta(mercado) },
        ],
      });
      nota = bajoCoste
        ? "Hubo días por debajo de lo aportado: ahí la banda verde desaparece."
        : "La banda verde es rentabilidad, no dinero tuyo.";
    } else if (estado.vista === "reparto") {
      const series = prods.map(p => ({ id: p.id, nombre: p.corto || p.nombre, color: color(p), valores: corta(p.serie) }));
      const tot = fechas.map((_, i) => series.reduce((a, s) => a + (s.valores[i] || 0), 0));
      series.forEach(s => { s.valores = s.valores.map((v, i) => tot[i] ? (v || 0) / tot[i] * 100 : 0); });
      G.areaApilada(cont, {
        fechas, series, alto: 330, maxForzado: 100,
        formatoY: v => Math.round(v) + " %",
        formatoValor: v => v.toFixed(1) + " %",
      });
    } else {
      G.areaApilada(cont, {
        fechas, alto: 330,
        series: prods.map(p => ({ id: p.id, nombre: p.corto || p.nombre, color: color(p), valores: corta(p.serie) })),
        overlay: { nombre: "Aportado", valores: corta(m.serieAportado) },
      });
      const tardios = visibles().filter(p => p.desde && p.desde > D.fechas[0] && p.aportado == null);
      if (tardios.length) {
        nota = tardios.map(p => p.corto).join(", ") + (tardios.length > 1 ? " entran" : " entra") +
          " en el seguimiento el " + G.fmtFecha(tardios[0].desde);
      }
    }
    $("#evolNota").textContent = nota;
  }

  function pintaChips() {
    const cont = $("#chips");
    cont.innerHTML = "";
    TODOS().forEach(p => {
      const oculto = estado.ocultos.has(p.id);
      const b = document.createElement("button");
      b.className = "chip" + (oculto ? " apagado" : "");
      b.style.setProperty("--c", color(p));
      const plTarjeta = plusvaliaDe(p);
      const rent = plTarjeta ? plTarjeta.pct : null;
      b.innerHTML = `<span class="barra"></span>
        <div class="nm"><i></i>${esc(p.corto || p.nombre)}</div>
        <div class="vl">${G.fmtEur(valorDe(p))}</div>
        <div class="pi"><span>${oculto ? "fuera del gráfico" : G.fmtPct(p.peso, 1) + " del total"}</span>
          <span class="${rent == null ? "" : rent >= 0 ? "pos" : "neg"}">${rent == null ? "—" : G.fmtPctSigno(rent, 1)}</span></div>
        <div class="sp"></div>`;
      b.onclick = () => { estado.fondo = p.id; irA("fondos"); };
      cont.appendChild(b);
      G.mini(b.querySelector(".sp"), corta(p.serie), color(p));
    });
  }

  function pintaCuentas() {
    const sec = $("#seccionCuentas");
    if (!sec) return;
    const cuentas = cuentasFiltradas();
    sec.hidden = !cuentas.length;
    if (!cuentas.length) return;
    const filas = cuentas.slice().sort((a, b) => (b.saldoEur || 0) - (a.saldoEur || 0));
    const props = {};
    (D.propietarios || []).forEach(p => { props[p.id] = p.nombre; });
    const nom = c => props[c.propietario] || c.propietario || "Compartido";
    const enEur = c => (c.saldoEur == null ? null : convAhora(c.saldoEur));
    const suma = filas.reduce((a, c) => a + (enEur(c) || 0), 0);
    const nat = estado.mon !== "global";
    const nato = v => Number(v == null ? 0 : v).toLocaleString("es-ES",
      { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    $("#tablaCuentas").innerHTML =
      `<thead><tr><th>Cuenta</th><th>Entidad</th><th>Propietario</th><th>Moneda</th>
        <th>Saldo</th>${nat ? "" : `<th>En ${enUSD() ? "dólares" : "euros"}</th>`}</tr></thead>
       <tbody>${filas.map(c => `<tr>
        <td>${esc(c.nombre)}</td>
        <td class="subt">${esc(c.entidad || "")}</td>
        <td>${esc(nom(c))}</td>
        <td class="subt">${esc(c.moneda)}</td>
        <td>${nato(c.saldo)} ${esc(c.moneda)}</td>
        ${nat ? "" : `<td>${enEur(c) == null ? "—" : G.fmtEur(enEur(c))}</td>`}
      </tr>`).join("")}</tbody>
       <tfoot><tr><td colspan="4">${filas.length} ${filas.length === 1 ? "cuenta" : "cuentas"}</td>
        <td></td>${nat ? "" : `<td>${G.fmtEur(suma)}</td>`}</tr></tfoot>`;
  }

  function pintaDistribucion() {
    const lista = visibles();
    const datos = estado.dist === "producto"
      ? lista.filter(p => valorDe(p) > 0)
        .map(p => ({ nombre: p.corto || p.nombre, valor: valorDe(p), color: color(p), id: p.id }))
        .sort((a, b) => b.valor - a.valor)
      : agrupa(lista, estado.dist);
    const total = datos.reduce((a, x) => a + x.valor, 0);
    G.donut($("#grafDonut"), {
      datos, alto: 236, tituloCentro: filtrando() ? "Filtrado" : "Total",
      valorCentro: G.fmtEurCorto(total),
      onClick: d => { if (d.id) { estado.fondo = d.id; irA("fondos"); } }
    });
    $("#leyendaDist").innerHTML = datos.map(d =>
      `<tr><td><i style="background:${d.color}"></i>${esc(d.nombre)}</td>
       <td>${G.fmtEur(d.valor)}</td><td>${G.fmtPct(d.valor / total, 1)}</td></tr>`).join("");
  }

  function pintaBarras() {
    const am = D.aportacionesMensuales;
    const desde = D.fechas[desdeIdx()].slice(0, 7);
    const idx = am.meses.findIndex(m => m >= desde);
    const i0 = idx < 0 ? am.meses.length : idx;
    const meses = am.meses.slice(i0);
    const series = visibles()
      .filter(p => (am.porProducto[p.id] || []).some(v => v))
      .map(p => ({ nombre: p.corto || p.nombre, color: color(p),
                   valores: am.porProducto[p.id].slice(i0)
                     .map(v => convAhora(v * (p._f || 1))) }));
    G.barrasApiladas($("#grafBarras"), { categorias: meses, alto: 236, series });
    const suma = meses.reduce((a, _, i) => a + series.reduce((b, s) => b + (s.valores[i] || 0), 0), 0);
    $("#notaAport").textContent = meses.length
      ? `${G.fmtEur(suma)} en ${meses.length} ${meses.length === 1 ? "mes" : "meses"}` : "";
  }

  function pintaHitos(mVista) {
    // En la web con importes ocultos no hay hitos (delatarían cifras).
    $("#hitos").closest("section").hidden = !D.total.hitos.length;
    const serie = mVista.serie || [];
    $("#hitos").innerHTML = D.total.hitos.map(h => {
      const imp = convAhora(h.importe);          // hitos en la moneda de visualización
      const i = serie.findIndex(v => v != null && v >= imp);
      const fecha = i >= 0 ? D.fechas[i] : null;
      const hecho = !!fecha;
      return `<div class="hito ${hecho ? "hecho" : ""}">
        <div class="im">${G.fmtEurCorto(imp)}</div>
        <div class="fe">${hecho ? "✓ " + G.fmtFecha(fecha) : "faltan " + G.fmtEurCorto(imp - mVista.valor)}</div>
      </div>`;
    }).join("");
  }

  function pintaProyeccion() {
    const anos = +$("#rAnos").value, rent = +$("#rRent").value / 100;
    const apor = convAhora(+$("#rApor").value);
    $("#vAnos").textContent = anos;
    $("#vRent").textContent = $("#rRent").value.replace(".", ",") + " %";
    $("#vApor").textContent = G.fmtEur(apor);

    const m = metricas(visibles());
    const rm = rent / 12, n = anos * 12;
    const fechas = [], valores = [], aportado = [];
    const base = new Date(D.fechaExtracto);
    let v = m.valor, ap = m.aportado;
    for (let i = 0; i <= n; i++) {
      const f = new Date(base.getFullYear(), base.getMonth() + i, 1);
      fechas.push(f.toISOString().slice(0, 10));
      valores.push(Math.round(v));
      aportado.push(Math.round(ap));
      v = v * (1 + rm) + apor;
      ap += apor;
    }
    G.lineaConEventos($("#grafProy"), {
      fechas, valores, color: G.css("--s3"), alto: 250,
      overlay: { nombre: "Habré aportado", valores: aportado },
    });
    const fin = valores[valores.length - 1], apFin = aportado[aportado.length - 1];
    $("#proyResumen").innerHTML =
      `Partiendo de ${G.fmtEur(m.valor, 0)}${filtrando() ? " (vista filtrada)" : ""},
       en <b class="fuerte">${anos} años</b> tendrías <b class="fuerte">${G.fmtEur(fin, 0)}</b>
       <span style="color:var(--tinta3)">·</span> habrías aportado ${G.fmtEur(apFin, 0)}
       <span style="color:var(--tinta3)">·</span> el mercado pondría
       <span class="pos fuerte">${G.fmtEur(fin - apFin, 0)}</span>`;
  }

  function pintaTabla() {
    if (estado.tablaFiltro !== "todos" &&
        !visibles().some(p => p.id === estado.tablaFiltro)) estado.tablaFiltro = "todos";
    const filas = [];
    visibles().forEach(p => (p.aportaciones || []).forEach(a => {
      if (!a.importe) return;
      filas.push({
        fecha: a.fecha, producto: p.corto || p.nombre, color: color(p), id: p.id,
        importe: a.importe, valor: a.valor,
        pl: a.valor != null ? a.valor - a.importe : null,
        rent: a.valor != null && a.importe ? (a.valor - a.importe) / a.importe : null,
      });
    }));
    const f = estado.tablaFiltro === "todos" ? filas : filas.filter(x => x.id === estado.tablaFiltro);
    const o = estado.ordenTabla;
    f.sort((a, b) => {
      const va = a[o.col], vb = b[o.col];
      const c = va == null ? -1 : vb == null ? 1 : va > vb ? 1 : va < vb ? -1 : 0;
      return o.desc ? -c : c;
    });
    const cols = [["fecha", "Fecha"], ["producto", "Producto"], ["importe", "Aportado"],
    ["valor", "Vale hoy"], ["pl", "Plusvalía"], ["rent", "Rentabilidad"]];
    $("#tablaMov").innerHTML =
      `<thead><tr>${cols.map(c => `<th class="orden" data-c="${c[0]}">${c[1]}${o.col === c[0] ? (o.desc ? " ↓" : " ↑") : ""}</th>`).join("")}</tr></thead>
       <tbody>${f.map(r => `<tr>
        <td>${G.fmtFecha(r.fecha)}</td>
        <td><i class="pt" style="background:${r.color}"></i>${esc(r.producto)}</td>
        <td>${G.fmtEur(r.importe)}</td>
        <td>${r.valor != null ? G.fmtEur(r.valor) : "—"}</td>
        <td class="${r.pl >= 0 ? "pos" : "neg"}">${r.pl != null ? G.fmtEurSigno(r.pl) : "—"}</td>
        <td class="${r.rent >= 0 ? "pos" : "neg"}">${r.rent != null ? G.fmtPctSigno(r.rent, 1) : "—"}</td>
      </tr>`).join("")}</tbody>`;
    $("#tablaMov").querySelectorAll("th.orden").forEach(th => {
      th.onclick = () => {
        const c = th.dataset.c;
        estado.ordenTabla = { col: c, desc: o.col === c ? !o.desc : true };
        pintaTabla();
      };
    });
    $("#notaTabla").textContent =
      `${f.length} movimientos · ${G.fmtEur(f.reduce((a, r) => a + r.importe, 0))}`;
  }

  function pintaPatrimonio() {
    const mTodo = metricas(TODOS_CRUDOS());          // todo, sin ningún filtro
    const mVis = filtrando() ? metricas(visibles()) : metricas(TODOS());
    pintaFiltros();
    pintaHero(mVis, mTodo);
    pintaKPIs(mVis);
    pintaPrincipal(mVis);
    pintaChips();
    pintaCuentas();
    pintaDistribucion();
    pintaBarras();
    pintaHitos(mVis);
    pintaProyeccion();
    pintaTabla();
    pintaSegm($("#segRango"), RANGOS, estado.rango, id => { estado.rango = id; pintaPatrimonio(); });
    pintaSegm($("#segVista"), [
      { id: "apilado", et: "Por producto" }, { id: "total", et: "Total" },
      { id: "dinero", et: "Tu dinero vs mercado" }, { id: "reparto", et: "Reparto %" }
    ], estado.vista, id => { estado.vista = id; pintaPatrimonio(); });
    pintaSegm($("#segDist"), [
      { id: "clase", et: "Activo" }, { id: "producto", et: "Producto" },
      { id: "entidad", et: "Entidad" }, { id: "tipo", et: "Tipo" }
    ], estado.dist, id => { estado.dist = id; pintaDistribucion(); });
    pintaSegm($("#segTabla"), [{ id: "todos", et: "Todos" }].concat(
      visibles().filter(p => (p.aportaciones || []).some(a => a.importe))
        .map(p => ({ id: p.id, et: p.corto || p.nombre }))),
      estado.tablaFiltro, id => { estado.tablaFiltro = id; pintaTabla(); });
  }

  /* ================================================================
     PESTAÑA 2 · EL MES
     ================================================================ */
  function pintaMes() {
    const rm = D.resumenMensual || [];
    if (!rm.length) { $("#mesCifra").textContent = "—"; return; }
    if (estado.mes == null || estado.mes < 0 || estado.mes >= rm.length) estado.mes = rm.length - 1;
    const r = rm[estado.mes];
    // Cifras del mes en la moneda de visualización (cambio de hoy, como todo).
    const cv = v => convAhora(v);

    // Con los filtros globales encima, las cifras de este mes se vuelven a sumar.
    const filas = visibles().map(p => {
      const d = r.porProducto[p.id];
      if (!d) return null;
      const f = p._f || 1;
      const esc = v => (v == null ? v : cv(v * f));
      return { p, d: { inicio: esc(d.inicio), aportado: esc(d.aportado),
                       mercado: esc(d.mercado), fin: esc(d.fin), nuevo: esc(d.nuevo) } };
    }).filter(Boolean);
    const T = filtrando()
      ? filas.reduce((a, x) => ({ inicio: a.inicio + x.d.inicio, aportado: a.aportado + x.d.aportado,
          mercado: a.mercado + x.d.mercado, fin: a.fin + x.d.fin, nuevo: a.nuevo + (x.d.nuevo || 0) }),
          { inicio: 0, aportado: 0, mercado: 0, fin: 0, nuevo: 0 })
      : r;
    const rentMes = T === r ? r.rentabilidad
      : (T.inicio > 0 ? T.mercado / T.inicio : null);
    // Para pintar: en modo filtrado las filas ya están convertidas arriba;
    // sin filtros se convierte el resumen del mes tal cual.
    const Tm = filtrando() ? T
      : { inicio: cv(T.inicio), fin: cv(T.fin), aportado: cv(T.aportado),
          mercado: cv(T.mercado), nuevo: cv(T.nuevo) };

    const sel = $("#mesSel");
    if (sel.options.length !== rm.length) {
      sel.innerHTML = rm.map((x, i) => `<option value="${i}">${G.fmtMes(x.mes)}</option>`).join("");
    }
    sel.value = String(estado.mes);
    $("#mesPrev").disabled = estado.mes === 0;
    $("#mesNext").disabled = estado.mes === rm.length - 1;

    const cambio = Tm.fin - Tm.inicio;
    // El titular es el cambio REAL: lo que aportaste mas lo que hizo el mercado.
    // Incorporar una cuenta al panel mueve el saldo pero no es dinero ganado,
    // asi que va aparte y no infla la cifra grande.
    const real = Tm.aportado + Tm.mercado;
    const ultimo = estado.mes === rm.length - 1;
    $("#mesEtq").textContent = ultimo ? "Cambio en lo que va de mes" : "Cambio del mes";
    $("#mesCifra").textContent = G.fmtEurSigno(real);
    $("#mesCifra").className = "hCifra " + (real >= 0 ? "pos" : "neg");
    $("#mesNota").textContent = ultimo
      ? "Mes en curso, con datos hasta el " + G.fmtFecha(D.fechaExtracto) : "";
    const trozos = [`De <span class="fuerte">${G.fmtEur(Tm.inicio)}</span> a <span class="fuerte">${G.fmtEur(Tm.fin)}</span>`];
    if (rentMes != null) {
      trozos.push(`rentabilidad de la cartera
        <span class="${rentMes >= 0 ? "pos" : "neg"} fuerte">${G.fmtPctSigno(rentMes)}</span>`);
    }
    if (T.nuevo) {
      trozos.push(`<span class="pill">de la diferencia, ${G.fmtEur(Tm.nuevo)} son cuentas que entran al panel</span>`);
    }
    $("#mesSub").innerHTML = trozos.join('<span style="color:var(--tinta3)">·</span>');

    const tarjetas = [
      { e: "Lo pusiste tú", v: G.fmtEur(Tm.aportado), n: "aportaciones del mes", c: G.css("--s1") },
      {
        e: "Lo puso el mercado", v: G.fmtEurSigno(Tm.mercado), n: "revalorización, sin tocar nada",
        c: G.css("--s3"), cl: Tm.mercado >= 0 ? "pos" : "neg"
      },
    ];
    if (Tm.nuevo) tarjetas.push({
      e: "Nuevo en el panel", v: G.fmtEur(Tm.nuevo),
      n: "no es dinero nuevo: es que empiezas a seguirlo", c: G.css("--s7")
    });
    $("#mesTarjetas").innerHTML = tarjetas.map(t =>
      `<div class="mesT" style="--c:${t.c}"><span class="barra"></span>
        <div class="e">${t.e}</div><div class="v ${t.cl || ""}">${t.v}</div><div class="n">${t.n}</div></div>`).join("");

    // tabla por componente (filas ya calculadas arriba, con los filtros aplicados)
    const hayNuevo = filas.some(x => x.d.nuevo);
    const colNuevo = hayNuevo ? "<th>Entra al panel</th>" : "";
    $("#mesTabla").innerHTML =
      `<thead><tr><th>Componente</th><th>Al empezar</th><th>Aportaste</th>
        <th>Mercado</th>${colNuevo}<th>Al cerrar</th><th>Variación</th></tr></thead>
       <tbody>${filas.map(({ p, d }) => {
        const var_ = d.fin - d.inicio;
        return `<tr>
          <td><i class="pt" style="background:${color(p)}"></i>${esc(p.corto || p.nombre)}</td>
          <td>${G.fmtEur(d.inicio)}</td>
          <td>${d.aportado ? G.fmtEur(d.aportado) : "—"}</td>
          <td class="${d.mercado >= 0 ? "pos" : "neg"}">${G.fmtEurSigno(d.mercado)}</td>
          ${hayNuevo ? `<td>${d.nuevo ? G.fmtEur(d.nuevo) : "—"}</td>` : ""}
          <td>${G.fmtEur(d.fin)}</td>
          <td class="${var_ >= 0 ? "pos" : "neg"}">${G.fmtEurSigno(var_)}</td></tr>`;
      }).join("")}</tbody>
       <tfoot><tr><td>Total</td><td>${G.fmtEur(Tm.inicio)}</td><td>${G.fmtEur(Tm.aportado)}</td>
        <td class="${Tm.mercado >= 0 ? "pos" : "neg"}">${G.fmtEurSigno(Tm.mercado)}</td>
        ${hayNuevo ? `<td>${G.fmtEur(Tm.nuevo)}</td>` : ""}
        <td>${G.fmtEur(Tm.fin)}</td>
        <td class="${cambio >= 0 ? "pos" : "neg"}">${G.fmtEurSigno(cambio)}</td></tr></tfoot>`;
    $("#mesTablaNota").textContent = Tm.nuevo
      ? `Incluye ${G.fmtEur(Tm.nuevo)} que entran al seguimiento este mes.` : "";

    // histórico de esfuerzo vs mercado (con los filtros, mes a mes)
    const mesDe = x => {
      if (!filtrando()) return x;
      let a = 0, m = 0;
      visibles().forEach(p => {
        const d = (x.porProducto || {})[p.id];
        if (d) { const f = p._f || 1; a += d.aportado * f; m += d.mercado * f; }
      });
      return { mes: x.mes, aportado: convAhora(a), mercado: convAhora(m) };
    };
    const ult = rm.slice(-18).map(mesDe);
    G.barrasAgrupadas($("#grafMesHist"), {
      categorias: ult.map(x => x.mes), alto: 250,
      formatoCat: G.fmtMes,
      series: [
        { nombre: "Lo pusiste tú", color: G.css("--s1"), valores: ult.map(x => x.aportado) },
        { nombre: "Lo puso el mercado", color: G.css("--s3"), valores: ult.map(x => x.mercado) },
      ],
    });
  }

  /* ================================================================
     PESTAÑA 2b · PERIODO — rango libre (últimos X, año Y o dos fechas)
     ================================================================ */
  const UDIAS = { u7: 7, u15: 15, u30: 30, u90: 90, u180: 180, u365: 365 };
  const sumaISO = (iso, dias) => {
    // En UTC: así «hoy menos 14 días» no se desfasa un día con toISOString.
    const t = new Date(iso + "T00:00:00Z");
    t.setUTCDate(t.getUTCDate() + dias);
    return t.toISOString().slice(0, 10);
  };
  /** Fechas (desde/hasta) del periodo elegido. */
  function rangoPeriodo() {
    const hoy = D.fechaExtracto;
    const v = estado.periodo;
    if (v === "pers") return { desde: estado.perDesde || D.fechas[0], hasta: estado.perHasta || hoy };
    if (v === "ytd") return { desde: hoy.slice(0, 4) + "-01-01", hasta: hoy };
    if (v[0] === "a" && v.length === 5) return { desde: v.slice(1) + "-01-01", hasta: v.slice(1) + "-12-31" };
    const dias = UDIAS[v] || 30;
    return { desde: sumaISO(hoy, -(dias - 1)), hasta: hoy };
  }
  /** iAntes = último día ANTES del periodo (−1 si empieza desde el principio),
      iFin = último día dentro del periodo. */
  function indicesPeriodo() {
    const f = D.fechas;
    const { desde, hasta } = rangoPeriodo();
    const h = hasta < D.fechaExtracto ? hasta : D.fechaExtracto;
    let iFin = -1;
    for (let i = f.length - 1; i >= 0; i--) { if (f[i] <= h) { iFin = i; break; } }
    let iAntes = -1;
    for (let i = f.length - 1; i >= 0; i--) { if (f[i] < desde) { iAntes = i; break; } }
    return { desde, hasta: h, iAntes, iFin };
  }
  /** Aportado de un componente dentro del rango (iAntes, iFin]. Espejo exacto
      del resumen_mensual del motor: el efectivo por su curva de aportado (saldo
      menos rendimiento); el resto por sus flujos (compras suman, ventas y
      dividendos cobrados restan). En dólares cada flujo va con el cambio de su día. */
  function aportadoRango(p, iAntes, iFin) {
    if (p.tipoClave === "efectivo") {
      const sa = p.serieAportado || [];
      const a1 = sa[iFin], a0 = iAntes >= 0 ? sa[iAntes] : null;
      if (a1 == null) return 0;
      return a1 - (a0 == null ? 0 : a0);
    }
    let ap = 0;
    (p.flujos || []).forEach(([f, v]) => {
      const i = idxFecha(f);
      if (i > iAntes && i <= iFin) ap += -v;
    });
    return ap;
  }
  /** Resumen de un rango para una lista de componentes. */
  function resumenRango(lista, iAntes, iFin) {
    const filas = [];
    let inicio = 0, fin = 0, aportado = 0, nuevo = 0;
    lista.forEach(p => {
      const s = p.serie || [];
      const pv0 = iAntes >= 0 ? (s[iAntes] || 0) : 0;
      const pv1 = s[iFin] || 0;
      const ap = aportadoRango(p, iAntes, iFin);
      const estrena = (iAntes < 0 || s[iAntes] == null) && s[iFin] != null;
      const pnuevo = (estrena && p.aportado == null) ? pv1 : 0;
      if (!(pv1 || pv0 || ap)) return;
      inicio += pv0; fin += pv1; aportado += ap; nuevo += pnuevo;
      filas.push({ p, inicio: pv0, fin: pv1, aportado: ap, nuevo: pnuevo,
                   mercado: pv1 - pv0 - ap - pnuevo });
    });
    return { filas, inicio, fin, aportado, nuevo, mercado: fin - inicio - aportado - nuevo };
  }

  function pintaPeriodo() {
    const sel = $("#perSel");
    if (!sel) return;
    if (!sel.options.length) {          // opciones: se construyen una vez
      const anos = [];
      for (let y = +D.fechaExtracto.slice(0, 4); y >= +D.fechas[0].slice(0, 4); y--) anos.push(y);
      sel.innerHTML = [
        '<optgroup label="Últimos días, semanas o meses">',
        '<option value="u7">Últimos 7 días (1 semana)</option>',
        '<option value="u15">Últimos 15 días</option>',
        '<option value="u30">Últimos 30 días (1 mes)</option>',
        '<option value="u90">Últimos 3 meses</option>',
        '<option value="u180">Últimos 6 meses</option>',
        '<option value="u365">Últimos 12 meses</option>',
        '</optgroup><optgroup label="Años completos">',
        '<option value="ytd">Lo que va del año</option>',
        ...anos.map(y => `<option value="a${y}">Año ${y} completo</option>`),
        '</optgroup><optgroup label="Dos fechas">',
        '<option value="pers">Del… al… (elegir fechas)</option>',
        '</optgroup>',
      ].join("");
    }
    if (![...sel.options].some(o => o.value === estado.periodo)) estado.periodo = "u30";
    sel.value = estado.periodo;
    sel.onchange = () => {
      estado.periodo = sel.value;
      recuerda.guarda("patrimonio.periodo", sel.value);
      if (sel.value === "pers" && !estado.perDesde) {
        estado.perDesde = sumaISO(D.fechaExtracto, -29);
        estado.perHasta = D.fechaExtracto;
      }
      pintaPeriodo();
    };
    const pers = estado.periodo === "pers";
    $("#perFechas").hidden = !pers;
    const dEl = $("#perDesde"), hEl = $("#perHasta");
    dEl.min = hEl.min = D.fechas[0];
    dEl.max = hEl.max = D.fechaExtracto;
    if (pers) {
      if (estado.perDesde > estado.perHasta) estado.perHasta = estado.perDesde;
      dEl.value = estado.perDesde;
      hEl.value = estado.perHasta;
      dEl.onchange = () => {
        estado.perDesde = dEl.value || D.fechas[0];
        if (estado.perDesde > estado.perHasta) { estado.perHasta = estado.perDesde; hEl.value = estado.perHasta; }
        recuerda.guarda("patrimonio.perDesde", estado.perDesde);
        recuerda.guarda("patrimonio.perHasta", estado.perHasta);
        pintaPeriodo();
      };
      hEl.onchange = () => {
        estado.perHasta = hEl.value || D.fechaExtracto;
        if (estado.perHasta < estado.perDesde) { estado.perDesde = estado.perHasta; dEl.value = estado.perDesde; }
        recuerda.guarda("patrimonio.perDesde", estado.perDesde);
        recuerda.guarda("patrimonio.perHasta", estado.perHasta);
        pintaPeriodo();
      };
    }
    pintaPeriodoCifras();
  }

  function pintaPeriodoCifras() {
    const { desde, hasta, iAntes, iFin } = indicesPeriodo();
    const vacio = iFin < 0 || iFin <= iAntes;
    $("#perNota").textContent = vacio ? "" : `${G.fmtFecha(desde)} – ${G.fmtFecha(hasta)}`;
    if (vacio) {
      $("#perCifra").textContent = "—";
      $("#perCifra").className = "hCifra";
      $("#perEtq").textContent = "Cambio del periodo";
      $("#perSub").textContent = desde > hasta
        ? "La fecha de inicio es posterior a la de fin."
        : "No hay datos en ese periodo.";
      $("#perTarjetas").innerHTML = "";
      $("#perTabla").innerHTML = "";
      $("#perTablaNota").textContent = "";
      $("#grafPeriodo").innerHTML = "";
      return;
    }
    const lista = visibles();
    const T = resumenRango(lista, iAntes, iFin);
    const cambio = T.fin - T.inicio;
    const rent = T.inicio > 0 ? T.mercado / T.inicio : null;
    // El titular es el cambio REAL (lo aportado más lo que hizo el mercado),
    // igual que en «El mes»: lo que entra al panel no infla la cifra.
    const real = T.aportado + T.mercado;
    const enCurso = hasta >= D.fechaExtracto;
    $("#perEtq").textContent = enCurso ? "Cambio desde el inicio hasta hoy" : "Cambio del periodo";
    $("#perCifra").textContent = G.fmtEurSigno(real);
    $("#perCifra").className = "hCifra " + (real >= 0 ? "pos" : "neg");

    const trozos = [`De <span class="fuerte">${G.fmtEur(T.inicio)}</span> a <span class="fuerte">${G.fmtEur(T.fin)}</span>`];
    if (rent != null) trozos.push(`rentabilidad de la cartera
      <span class="${rent >= 0 ? "pos" : "neg"} fuerte">${G.fmtPctSigno(rent)}</span>`);
    if (T.nuevo) trozos.push(`<span class="pill">de la diferencia, ${G.fmtEur(T.nuevo)} son cuentas que entran al panel</span>`);
    $("#perSub").innerHTML = trozos.join('<span style="color:var(--tinta3)">·</span>');

    const tarjetas = [
      { e: "Lo pusiste tú", v: G.fmtEur(T.aportado), n: "aportaciones en el periodo", c: G.css("--s1") },
      { e: "Lo puso el mercado", v: G.fmtEurSigno(T.mercado), n: "revalorización, sin tocar nada",
        c: G.css("--s3"), cl: T.mercado >= 0 ? "pos" : "neg" },
    ];
    if (T.nuevo) tarjetas.push({
      e: "Nuevo en el panel", v: G.fmtEur(T.nuevo),
      n: "no es dinero nuevo: es que empiezas a seguirlo", c: G.css("--s7"),
    });
    $("#perTarjetas").innerHTML = tarjetas.map(t =>
      `<div class="mesT" style="--c:${t.c}"><span class="barra"></span>
       <div class="e">${t.e}</div><div class="v ${t.cl || ""}">${t.v}</div><div class="n">${t.n}</div></div>`).join("");

    const hayNuevo = T.filas.some(x => x.nuevo);
    const colNuevo = hayNuevo ? "<th>Entra al panel</th>" : "";
    $("#perTabla").innerHTML =
      `<thead><tr><th>Componente</th><th>Al empezar</th><th>Aportaste</th>
        <th>Mercado</th>${colNuevo}<th>Al cerrar</th><th>Variación</th></tr></thead>
       <tbody>${T.filas.map(f => {
        const var_ = f.fin - f.inicio;
        return `<tr>
          <td><i class="pt" style="background:${color(f.p)}"></i>${esc(f.p.corto || f.p.nombre)}</td>
          <td>${G.fmtEur(f.inicio)}</td>
          <td>${f.aportado ? G.fmtEur(f.aportado) : "—"}</td>
          <td class="${f.mercado >= 0 ? "pos" : "neg"}">${G.fmtEurSigno(f.mercado)}</td>
          ${hayNuevo ? `<td>${f.nuevo ? G.fmtEur(f.nuevo) : "—"}</td>` : ""}
          <td>${G.fmtEur(f.fin)}</td>
          <td class="${var_ >= 0 ? "pos" : "neg"}">${G.fmtEurSigno(var_)}</td></tr>`;
       }).join("")}</tbody>
       <tfoot><tr><td>Total</td><td>${G.fmtEur(T.inicio)}</td><td>${G.fmtEur(T.aportado)}</td>
        <td class="${T.mercado >= 0 ? "pos" : "neg"}">${G.fmtEurSigno(T.mercado)}</td>
        ${hayNuevo ? `<td>${G.fmtEur(T.nuevo)}</td>` : ""}
        <td>${G.fmtEur(T.fin)}</td>
        <td class="${cambio >= 0 ? "pos" : "neg"}">${G.fmtEurSigno(cambio)}</td></tr></tfoot>`;
    $("#perTablaNota").textContent = T.nuevo
      ? `Incluye ${G.fmtEur(T.nuevo)} que entran al seguimiento en este periodo.` : "";

    const i0 = iAntes + 1;
    const m = metricas(lista);
    G.lineaConEventos($("#grafPeriodo"), {
      fechas: D.fechas.slice(i0, iFin + 1),
      valores: m.serie.slice(i0, iFin + 1),
      color: G.css("--s1"), alto: 260,
      overlay: { nombre: "Aportado", valores: m.serieAportado.slice(i0, iFin + 1) },
    });
  }

  /* ================================================================
     PESTAÑA 3 · FONDOS
     ================================================================ */
  function pintaFondos() {
    const lista = TODOS();
    if (!lista.length) {
      $("#selFondo").innerHTML = "";
      $("#fondoFicha").innerHTML = `<header><h2>Nada bajo estos filtros</h2></header>
        <p class="vacio">Ningún componente coincide con el propietario o la divisa elegidos.
        Cambia el filtro de arriba para verlos.</p>`;
      $("#fondoExpo").hidden = true;
      $("#fondoTabla").innerHTML = "";
      return;
    }
    if (!estado.fondo || !buscaProd(estado.fondo)) estado.fondo = lista[0].id;
    const p = buscaProd(estado.fondo);

    $("#selFondo").innerHTML = "";
    lista.forEach(x => {
      const b = document.createElement("button");
      b.style.setProperty("--c", color(x));
      b.setAttribute("aria-pressed", String(x.id === estado.fondo));
      b.innerHTML = `<i></i>${esc(x.corto || x.nombre)}`;
      b.onclick = () => { estado.fondo = x.id; pintaFondos(); };
      $("#selFondo").appendChild(b);
    });

    pintaFichaFondo(p);
    pintaExposicion(p);
    pintaTablaFondo(p);
  }

  function pintaFichaFondo(p) {
    const sec = $("#fondoFicha");
    sec.style.setProperty("--c", color(p));
    const campos = [
      ["Tipo", p.tipo], ["ISIN", p.isin], ["Índice que replica", p.indice],
      ["Comisión anual (TER)", p.ter != null ? G.fmtPct(p.ter, 2) : null],
      ["Entidad", p.entidad], ["Gestora", p.gestora],
      ["Política", p.politica], ["Mercado", p.mercado],
      [p.origen ? "Primera aportación" : "Primer dato anotado", p.desde ? G.fmtFecha(p.desde) : null],
      [p.etqUnidades || "Participaciones",
        p.titulos != null ? G.nfNum.format(p.titulos)
          : p.participaciones != null ? G.nfNum.format(p.participaciones) : null],
      ["Precio medio de compra", p.precioMedio != null ? G.fmtEur(p.precioMedio) : null],
      [p.etqPrecio || "Valor liquidativo",
        p.nav != null ? G.fmtEur(p.nav) + (p.navFecha ? " · cierre del " + G.fmtFechaCorta(p.navFecha) : "") : null],
      ["Fuente del precio", p.fuenteTexto || p.fuentePrecio],
      ["Plusvalía ya materializada", p.realizado ? G.fmtEur(p.realizado) : null],
      ["Peso en el patrimonio", p.peso != null ? G.fmtPct(p.peso, 1) : null],
    ].filter(c => c[0] && c[1]);

    const hayVL = !!(p.navSerie && p.navSerie.some(v => v));
    const etqVL = p.etqPrecio || "Valor liquidativo";
    const pocos = (p.serie || []).filter(v => v != null).length < 5;
    const puedeAct = p.fuente !== "manual" || !!p.urlFuente;

    sec.innerHTML = `
      <header>
        <h2><span style="display:inline-block;width:10px;height:10px;border-radius:3px;background:${color(p)};margin-right:9px"></span>${esc(p.nombre)}</h2>
        <div class="sep"></div>
        ${hayVL ? '<div class="segm" id="segSerie"></div>' : ""}
        ${puedeAct ? '<button class="btn" id="btnActPrecio" title="Baja solo el precio de este producto, sin tocar los demás">↻ Actualizar precio</button>' : ""}
      </header>
      ${p.papel ? `<div class="papel">${esc(p.papel)}</div>` : ""}
      ${p.indiceDetalle ? `<p style="color:var(--tinta2);font-size:13.5px;margin:0 0 16px">${esc(p.indiceDetalle)}</p>` : ""}
      <div class="ficha">${campos.map(c => `<div><dt>${esc(c[0])}</dt><dd>${esc(c[1])}</dd></div>`).join("")}</div>
      <div id="ventanas"></div>
      ${pocos ? '<p class="subt" style="margin:0 0 12px">Solo hay un valor anotado, así que aún no hay curva. Anota más en «Mis datos → Saldos y valores».</p>' : ""}
      <div class="envGraf" id="grafFondo"></div>
      <div class="tramos" id="tramosLey"></div>`;

    // Precio de UN solo producto: lo baja y repinta el panel sin tocar los demás.
    const bAct = $("#btnActPrecio");
    if (bAct) bAct.onclick = async () => {
      bAct.disabled = true;
      bAct.textContent = "↻ Actualizando…";
      try {
        const r = await fetch(`api/productos/${encodeURIComponent(p.id)}/actualizar`, { method: "POST" });
        const j = await r.json().catch(() => ({}));
        if (!r.ok || j.ok === false)
          throw new Error((j.errores || []).join("\n") || "No he podido bajar el precio.");
        bAct.textContent = "✓ Precio actualizado";
        if (!(await window.__refrescaDatos())) pintaFondos();
      } catch (e) {
        bAct.disabled = false;
        bAct.textContent = "↻ Actualizar precio";
        alert(e.message || "No he podido bajar el precio de este producto. ¿Tienes conexión a internet?");
      }
    };

    // "Al cierre" es la cifra comparable con MyInvestor, que fuera de horario
    // se queda en el último cierre. "En vivo" sigue al bitcoin a cualquier hora.
    const vivoAqui = !!(precioVivo() && precioVivo().id === p.id);
    const plCierre = p.aportado > 0 ? { eur: p.valor - p.aportado, pct: (p.valor - p.aportado) / p.aportado } : null;
    const res = [
      ["Aportado", p.aportado != null ? G.fmtEur(p.aportado) : "—"],
      [vivoAqui ? "Valor al cierre" : "Valor hoy", G.fmtEur(p.valor)],
      [vivoAqui ? "Plusvalía al cierre" : "Plusvalía",
        plCierre ? `${G.fmtEurSigno(plCierre.eur)} · ${G.fmtPctSigno(plCierre.pct, 2)}` : "—"],
    ];
    if (vivoAqui) {
      const plv = plusvaliaDe(p);
      res.push(["En vivo ahora", `${G.fmtEur(valorDe(p))} · ${G.fmtPctSigno(plv.pct, 2)}`]);
    }
    res.push(["TIR", p.tir != null ? G.fmtPctSigno(p.tir) : "—"]);
    // Una escisión deja dos activos que nacieron del mismo dinero: aquí se ven
    // juntos, para que la caída mecánica del original no parezca una pérdida.
    const rel = (p.relacionados || []).map(id => D.productos.find(x => x.id === id)).filter(Boolean);
    if (rel.length) {
      const crudo = D.productos.find(x => x.id === p.id);
      const juntos = [crudo].concat(rel).filter(Boolean);
      let val = 0, ap = 0, hayAp = false;
      juntos.forEach(x => {
        const f = factorDe(x);
        if (f <= 1e-9) return;
        val += convAhora((x.valor || 0) * f);
        if (x.aportado != null) { ap += x.aportado * f; hayAp = true; }
      });
      const rent = hayAp && ap > 0 ? (val - convAhora(ap)) / convAhora(ap) : null;
      const nmRel = rel.map(x => x.corto || x.nombre).join(" y ");
      res.push([`Juntos con ${nmRel}`,
        `${G.fmtEur(val)} · ${rent == null ? "sin coste registrado" : G.fmtPctSigno(rent, 1)}`]);
    }
    // Tu posición y el comportamiento del producto van en filas separadas:
    // el "1 año" del bitcoin es del precio, no de tu dinero.
    let html = `<div class="ventanas"><span class="grupoEtq">Tu posición</span>` +
      res.map(r => `<div class="ventana"><div class="e">${r[0]}</div><div class="v">${r[1]}</div></div>`).join("") +
      `</div>`;
    if (p.ventanas) {
      const et = { "1m": "1 mes", "3m": "3 meses", "6m": "6 meses", ytd: "En el año", "1a": "1 año" };
      const celdas = ["1m", "3m", "6m", "ytd", "1a"].filter(k => p.ventanas[k] != null)
        .map(k => `<div class="ventana"><div class="e">${et[k]}</div>
          <div class="v ${p.ventanas[k] >= 0 ? "pos" : "neg"}">${G.fmtPctSigno(p.ventanas[k], 1)}</div></div>`).join("");
      if (celdas) {
        html += `<div class="ventanas"><span class="grupoEtq">${p.etqVentanas || "El precio"}, lo tuvieras o no</span>${celdas}</div>`;
      }
    }
    $("#ventanas").innerHTML = html;

    if (hayVL) {
      pintaSegm($("#segSerie"),
        [{ id: "posicion", et: "Mi posición" }, { id: "vl", et: etqVL }],
        estado.serieDetalle, id => { estado.serieDetalle = id; pintaFichaFondo(p); });
    }

    const verVL = hayVL && estado.serieDetalle === "vl";
    const paleta = tonos(color(p));
    const fechas = corta(D.fechas);
    const eventos = (p.aportaciones || []).filter(a => a.importe).map(a => {
      const niv = a.nivel == null ? 1 : a.nivel;
      return {
        fecha: a.fecha, color: paleta[niv], aro: niv === 2, r: 5,
        texto: `${["Aportación pequeña", "Aportación habitual", "Aportación extraordinaria"][niv]}: ${G.fmtEur(a.importe)}`,
      };
    });
    G.lineaConEventos($("#grafFondo"), {
      fechas,
      valores: corta(verVL ? p.navSerie : p.serie),
      color: color(p), alto: 280, eventos, desdeCero: !verVL,
      overlay: verVL ? null : ((p.serieAportado || []).some(v => v)
        ? { nombre: "Aportado", valores: corta(p.serieAportado) } : null),
      formatoY: verVL ? (v => G.fmtEur(v, v > 500 ? 0 : 2)) : null,
      referencia: (verVL && p.precioMedio)
        ? { valor: p.precioMedio, etiqueta: "tu precio medio · " + G.fmtEur(p.precioMedio) } : null,
    });

    // leyenda de los tramos, con los importes reales de este producto
    const t = p.tramos;
    if (t && eventos.length) {
      const cuenta = [0, 0, 0];
      (p.aportaciones || []).forEach(a => { if (a.nivel != null) cuenta[a.nivel]++; });
      const medio = t.p33 != null && t.p67 != null
        ? (t.p33 === t.p67 ? G.fmtEur(t.p33, 0) : `${G.fmtEur(t.p33, 0)} – ${G.fmtEur(t.p67, 0)}`)
        : "";
      const et = t.p33 == null
        ? [["Aportaciones", ""]]
        : [["Pequeña", "menos de " + G.fmtEur(t.p33, 0)],
           ["Habitual", medio],
           ["Extraordinaria", "más de " + G.fmtEur(t.p67, 0)]];
      $("#tramosLey").innerHTML =
        `<span style="color:var(--tinta3)">Tamaño de cada aportación, medido con tu propio historial en este producto:</span>` +
        et.map((e, i) => `<span><i class="${i === 2 ? "aro" : ""}" style="background:${paleta[i]};color:${paleta[i]}"></i>
          ${e[0]} <span style="color:var(--tinta3)">${e[1]}${cuenta[i] ? " · " + cuenta[i] : ""}</span></span>`).join("");
    } else $("#tramosLey").innerHTML = "";
  }

  function pintaExposicion(p) {
    const sec = $("#fondoExpo");
    const e = p.exposicion;
    if (!e) { sec.hidden = true; return; }
    sec.hidden = false;
    const meses = (Date.parse(D.fechaExtracto) - Date.parse(e.actualizado)) / (30.44 * 864e5);
    const viejo = meses > 6;
    sec.innerHTML = `
      <header>
        <h2>Qué hay dentro</h2>
        <div class="sep"></div>
        <span class="expoNota ${viejo ? "viejo" : ""}">${viejo ? "⚠ " : ""}Datos a ${G.fmtFecha(e.actualizado)}${viejo ? " · conviene refrescarlos" : ""}</span>
      </header>
      <p class="subt" style="margin:0 0 18px">${e.constituyentes ? e.constituyentes.toLocaleString("es-ES") + " empresas. " : ""}${esc(e.fuente)}. Datos del índice a la fecha indicada.</p>
      <div class="expo">
        <div><h3>Por país</h3><div class="envGraf" id="expoPaises"></div></div>
        <div><h3>Por sector</h3><div class="envGraf" id="expoSectores"></div></div>
      </div>
      ${e.top10 ? `<h3 style="font-size:12px;text-transform:uppercase;letter-spacing:.07em;color:var(--tinta3);margin:24px 0 10px">
        Las 10 mayores posiciones · ${e.top10.reduce((a, x) => a + x[1], 0).toFixed(1)} % del fondo</h3>
        <div class="tablaEnv"><table class="dt"><tbody>${e.top10.map(x =>
          `<tr><td>${esc(x[0])}</td><td>${x[1].toLocaleString("es-ES", { minimumFractionDigits: 2 })} %</td></tr>`).join("")}</tbody></table></div>` : ""}`;
    G.barrasHorizontales($("#expoPaises"), { datos: e.paises, color: color(p) });
    G.barrasHorizontales($("#expoSectores"), { datos: e.sectores, color: color(p) });
  }

  function pintaTablaFondo(p) {
    const sec = $("#fondoTabla");
    const filas = (p.aportaciones || []).filter(a => a.importe).slice().reverse();
    if (!filas.length) {
      sec.innerHTML = `<header><h2>Aportaciones</h2></header>
        <p class="vacio">Este componente no tiene aportaciones registradas: solo anotas su valor.</p>`;
      return;
    }
    const esFondo = p.tipoClave === "fondo" || p.tipoClave === "pension";
    const paleta = tonos(color(p));
    const hoy = new Date(D.fechaExtracto);
    const cab = ["Fecha", "Aportado", p.etqUnidades || "Participaciones",
      esFondo ? "VL de compra" : "Precio de compra", "Vale hoy", "Plusvalía", "Rent.", "Días"];
    sec.innerHTML = `<header><h2>Aportaciones a este producto</h2>
        <span class="subt">${filas.length} en total · ${G.fmtEur(p.aportado, 0)}</span></header>
      <div class="tablaEnv alto"><table class="dt">
        <thead><tr>${cab.map(c => `<th>${c}</th>`).join("")}</tr></thead>
        <tbody>${filas.map(a => {
          const pl = a.valor != null ? a.valor - a.importe : null;
          const rt = pl != null && a.importe ? pl / a.importe : null;
          const dias = Math.round((hoy - new Date(a.fecha)) / 864e5);
          const niv = a.nivel == null ? 1 : a.nivel;
          return `<tr><td>${G.fmtFecha(a.fecha)}</td>
            <td><i class="pt" style="background:${paleta[niv]}"></i>${G.fmtEur(a.importe)}</td>
            <td>${G.nfNum.format(a.participaciones || 0)}</td>
            <td>${a.precio != null ? G.fmtEur(a.precio) : "—"}</td>
            <td>${a.valor != null ? G.fmtEur(a.valor) : "—"}</td>
            <td class="${pl >= 0 ? "pos" : "neg"}">${pl != null ? G.fmtEurSigno(pl) : "—"}</td>
            <td class="${rt >= 0 ? "pos" : "neg"}">${rt != null ? G.fmtPctSigno(rt, 1) : "—"}</td>
            <td>${dias}</td></tr>`;
        }).join("")}</tbody></table></div>`;
  }

  /* ================================================================
     PESTAÑA 4 · RENDIMIENTO
     ================================================================ */
  function pintaRendimiento() {
    const ra = D.rentabilidadAnual;
    if (ra && ra.anos.length) {
      // Con filtros encima, la rentabilidad de TU cartera se recalcula aquí.
      const idx = idxCartera();
      const cartera = filtrando() ? rentAnualDe(idx, ra.anos) : ra.cartera;
      if (cartera) {
        G.barrasSimples($("#grafAnual"), {
          categorias: ra.anos.map((a, i) => a + (ra.parcial[i] ? " *" : "")),
          valores: cartera, alto: 240,
          color: G.css("--s1"),
          colores: cartera.map(v => v >= 0 ? G.css("--s1") : G.css("--s2")),
        });
        $("#notaAnual").textContent = `${filtrando() ? "Tu cartera con los filtros puestos" : "Tu cartera completa"},
          limpia del efecto de cuándo metiste el dinero. * año incompleto.`.replace(/\s+/g, " ");
      } else {
        $("#grafAnual").innerHTML = "";
        $("#notaAnual").textContent =
          "Con estos filtros no queda ningún producto con cotización, así que no hay rentabilidad anual que calcular.";
      }

      // Solo TU rentabilidad, por producto y año.
      $("#notaTablaAnual").textContent =
        "Tu rentabilidad en cada producto y año, desde el precio real al que compraste y con comisiones. "
        + "En un año completo coincide con la rentabilidad publicada del producto; el primer año cuenta desde tu primera compra.";
      const verProducto = false;
      const tabla = ra.porProducto;
      const desde = ra.desde || {};
      const MES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
      const corto = iso => { const q = iso.split("-"); return `${+q[2]} ${MES[+q[1] - 1]}`; };
      const celda = (v, d) => v == null
        ? `<td class="subt">${verProducto ? "—" : "aún no lo tenías"}</td>`
        : `<td class="${v >= 0 ? "pos" : "neg"}">${G.fmtPctSigno(v, 1)}` +
          `${d ? `<span class="subt" style="font-weight:400"> · desde ${corto(d)}</span>` : ""}</td>`;
      const prods = visibles().filter(p => tabla[p.id]);
      $("#tablaAnual").innerHTML =
        `<thead><tr><th>Producto</th>${ra.anos.map((a, i) =>
          `<th>${a}${ra.parcial[i] ? " *" : ""}</th>`).join("")}</tr></thead>
         <tbody>${prods.map(p => `<tr>
           <td><i class="pt" style="background:${color(p)}"></i>${esc(p.corto)}</td>
           ${tabla[p.id].map((v, i) => celda(v, (desde[p.id] || [])[i])).join("")}
         </tr>`).join("")}</tbody>` +
        (verProducto || !cartera ? "" : `<tfoot><tr><td>${filtrando() ? "Tu cartera (filtro)" : "Tu cartera"}</td>${cartera.map(v =>
          `<td class="${v == null ? "" : v >= 0 ? "pos" : "neg"}">${G.fmtPctSigno(v, 1)}</td>`).join("")}</tr></tfoot>`);
    }

    pintaComparacion();

    const comp = (() => {
      const base = D.comparador || [];
      const real = base.find(x => x.real);
      if (!filtrando() || !real) return base;
      // El tipo sin riesgo del motor (para el Sharpe): si no viene, se deduce
      // de cualquier alternativa que lo tenga calculado.
      let rf = real.rf != null ? real.rf : null;
      if (rf == null) {
        const conS = base.find(x => x.metricas && x.metricas.sharpe != null && x.metricas.vol);
        if (conS) rf = conS.metricas.cagr - conS.metricas.sharpe * conS.metricas.vol;
      }
      const idx = idxCartera();
      const met = metricasIndice(idx, rf);
      if (!met) return base.filter(x => !x.real);   // sin datos: la cartera real se queda fuera
      return base.map(x => x.real
        ? Object.assign({}, x, { indice: idx.map(v => v == null ? null : Math.round(v * 100) / 100),
                                  metricas: met })
        : x);
    })();
    const detalles = $("#compDetalles");
    // Los detalles solo se dibujan al abrirlos: un SVG dentro de algo cerrado no tiene ancho.
    if (detalles && !detalles.dataset.conectado) {
      detalles.dataset.conectado = "1";
      detalles.addEventListener("toggle", () => { if (detalles.open) pintaRendimiento(); });
    }
    if (comp.length && (!detalles || detalles.open)) {
      const met0 = comp[0].metricas;
      const paleta = [G.css("--s1"), G.css("--s2"), G.css("--s3"), G.css("--s4"), G.css("--s5"), G.css("--s7"), G.css("--s6")];
      const series = comp.map((c, i) => ({
        nombre: c.nombre, valores: c.indice, destacado: c.real,
        color: c.real ? G.css("--tinta") : paleta[(i + 1) % paleta.length],
      }));
      G.multiLinea($("#grafComparador"), {
        fechas: D.fechas, series, alto: 320,
        formatoY: v => Math.round(v),
        formatoValor: v => v.toFixed(1),
      });
      $("#notaComparador").textContent =
        `Base 100 desde el ${G.fmtFecha(met0.desde)}. Las alternativas son comprar y mantener con pesos fijos.`;
      $("#tablaComparador").innerHTML =
        `<thead><tr><th>Cartera</th><th>Rentabilidad</th><th>Anualizada</th>
          <th>Volatilidad</th><th>Sharpe</th><th>Máx. caída</th></tr></thead>
         <tbody>${comp.map((c, i) => {
          const m = c.metricas;
          return `<tr class="${c.real ? "destacada" : ""}">
            <td><i class="pt" style="background:${series[i].color}"></i>${esc(c.nombre)}</td>
            <td class="${m.rentTotal >= 0 ? "pos" : "neg"}">${G.fmtPctSigno(m.rentTotal, 1)}</td>
            <td class="${m.cagr >= 0 ? "pos" : "neg"}">${G.fmtPctSigno(m.cagr, 1)}</td>
            <td>${G.fmtPct(m.vol, 1)}</td>
            <td>${m.sharpe == null ? "—" : m.sharpe.toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
            <td class="neg">${G.fmtPct(m.maxDD, 1)}</td></tr>`;
        }).join("")}</tbody>`;
      $("#notaRiesgo").innerHTML =
        `<b>Cómo leerlo.</b> La volatilidad mide cuánto se mueve la cartera; el Sharpe, cuánta rentabilidad
         sacas por cada unidad de ese meneo (más alto, mejor). El tipo sin riesgo sale de tu fondo
         monetario, si tienes uno. Ojo: son solo
         ${((Date.parse(met0.hasta) - Date.parse(met0.desde)) / 3.1536e10).toFixed(1)} años de datos,
         así que valen para comparar entre ellas, no como pronóstico. Tu cartera real cambia de pesos
         con el tiempo y cada producto solo cuenta desde que lo compraste; las alternativas son
         hipotéticas y llevan sus pesos fijos desde el primer día.`;
    } else if (!detalles || detalles.open) {
      $("#grafComparador").innerHTML = "";
      $("#tablaComparador").innerHTML = "";
      $("#notaComparador").textContent = "";
      $("#notaRiesgo").innerHTML = "";
    }

    const c = D.comisiones;
    const lineas = !c ? [] : (filtrando()
      ? crudos(D.productos).filter(p => p.ter && p.valor).map(p => ({
          id: p.id, nombre: p.corto, ter: p.ter, valor: p.valor,
          anual: Math.round(p.valor * p.ter * 100) / 100, color: p.slotColor }))
      : c.lineas);
    if (lineas.length) {
      // Importes en la moneda de visualización (convAhora es 1× en euros).
      const anualNat = lineas.reduce((a, l) => a + l.anual, 0);
      const baseNat = lineas.reduce((a, l) => a + l.valor, 0);
      const anual = convAhora(anualNat), base = convAhora(baseNat);
      const ponderado = baseNat ? anualNat / baseNat : 0;
      $("#notaComisiones").textContent =
        `${G.fmtEur(anual)} al año · ${G.fmtPct(ponderado, 3)} de lo invertido${filtrando() ? " (vista filtrada)" : ""}`;
      $("#tablaComisiones").innerHTML =
        `<thead><tr><th>Producto</th><th>Comisión</th><th>Sobre</th><th>Al año</th><th>Al mes</th></tr></thead>
         <tbody>${lineas.map(l => `<tr>
            <td><i class="pt" style="background:${temaOscuro() ? l.color[1] : l.color[0]}"></i>${esc(l.nombre)}</td>
            <td>${G.fmtPct(l.ter, 2)}</td><td>${G.fmtEur(convAhora(l.valor))}</td>
            <td>${G.fmtEur(convAhora(l.anual))}</td><td>${G.fmtEur(convAhora(l.anual / 12))}</td></tr>`).join("")}</tbody>
         <tfoot><tr><td>Total</td><td>${G.fmtPct(ponderado, 3)}</td>
           <td>${G.fmtEur(base)}</td><td>${G.fmtEur(anual)}</td>
           <td>${G.fmtEur(convAhora(anualNat / 12))}</td></tr></tfoot>`;
    } else if (c && c.lineas.length) {
      $("#tablaComisiones").innerHTML = "";
      $("#notaComisiones").textContent = "Con estos filtros no queda ningún producto con comisión.";
    }
  }

  /* ---------------------------------------------- avisos y pie */
  function pintaComun() {
    $("#avisos").innerHTML = (D.avisos || [])
      .map(a => `<div class="av"><span>⚠</span><span>${esc(a)}</span></div>`).join("");
    const pa = D.preciosActualizados;
    const fuentes = [...new Set(D.productos.map(p => p.fuentePrecio).filter(Boolean))];
    $("#pie").innerHTML =
      `${pa ? `Precios actualizados el ${G.fmtFecha(pa.slice(0, 10))} a las ${pa.slice(11, 16)}` : "Precios sin actualizar"} ·
       datos valorados a ${G.fmtFecha(D.fechaExtracto)} ·
       ${D.total.diasInvertido} días invertido.<br>
       Fuentes de precios: ${esc(fuentes.join(", ") || "ninguna")}. En la pestaña Productos verás la de cada uno.<br>
       <b>Aviso:</b> herramienta informativa. No es asesoramiento financiero ni una recomendación de compra o venta.
       Los precios vienen de servicios públicos gratuitos y pueden tener errores o retrasos: no se garantiza su exactitud.`;
    if ($("#bannerDemo")) $("#bannerDemo").hidden = D.modo !== "demo";
    const K = window.CANAL;
    if (K) {
      $("#pie").insertAdjacentHTML("beforeend", `<span class="creditoCanal">Herramienta gratuita hecha por
        ${K.autor} · ¿Te resulta útil? <a href="${K.suscribir}" target="_blank" rel="noopener">Suscríbete al canal ▶</a></span>`);
      document.querySelectorAll(".autorCanal").forEach(el => { el.textContent = K.autor; });
      document.querySelectorAll(".enlaceCanal").forEach(el => { el.href = K.canal; });
      document.querySelectorAll(".enlaceSuscribir").forEach(el => { el.href = K.suscribir; });
    }
  }

  /* ---------------------------------------------- bitcoin en vivo */
  async function traeBtc() {
    const coin = D.vivo.coin || "bitcoin";
    const fuentes = [
      [`https://api.coingecko.com/api/v3/simple/price?ids=${encodeURIComponent(coin)}&vs_currencies=eur`, j => j[coin] && j[coin].eur],
    ];
    if (coin === "bitcoin") fuentes.push(["https://api.binance.com/api/v3/ticker/price?symbol=BTCEUR", j => parseFloat(j.price)]);
    for (const [url, extrae] of fuentes) {
      try {
        const r = await fetch(url, { cache: "no-store" });
        if (!r.ok) continue;
        const v = extrae(await r.json());
        if (v && isFinite(v)) return v;
      } catch (e) { /* probamos la siguiente */ }
    }
    return null;
  }
  async function actualizaVivo() {
    if (!D.vivo) return;
    const v = await traeBtc();
    if (!v) return;
    estado.btcVivo = v;
    pintarTab();
  }

  /* ---------------------------------------------- pestañas */
  function irA(tab) {
    // Si has cambiado datos en «Mis datos», el panel se recarga con las cifras nuevas.
    if (window.EDITOR_SUCIO && tab !== "datos") {
      recuerda.guarda("patrimonio.tab", tab);
      location.reload();
      return;
    }
    estado.tab = tab;
    document.querySelectorAll("#tabs button").forEach(b =>
      b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
    document.querySelectorAll(".panel").forEach(p => { p.hidden = p.id !== "tab-" + tab; });
    recuerda.guarda("patrimonio.tab", tab);
    pintarTab();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function pintarTab() {
    // Cada pestaña se dibuja al mostrarse: un SVG dentro de un panel oculto
    // no tiene ancho, y saldria del tamano equivocado.
    pintaFiltrosGlobal();
    if (estado.tab === "patrimonio") pintaPatrimonio();
    else if (estado.tab === "mes") pintaMes();
    else if (estado.tab === "periodo") pintaPeriodo();
    else if (estado.tab === "fondos") pintaFondos();
    else if (estado.tab === "rendimiento") pintaRendimiento();
    else if (estado.tab === "datos" && window.Editor) window.Editor.mostrar();
  }
  function pintar() { pintaComun(); pintarTab(); }

  /** Vuelve a leer datos.js y repinta el panel sin recargar la página: así el
      panel va saliendo mientras aún se están descargando los precios. */
  window.__refrescaDatos = async () => {
    try {
      const txt = await (await fetch("datos.js?_=" + Date.now())).text();
      const i = txt.indexOf("{"), j = txt.lastIndexOf("}");
      if (i < 0 || j < i) return null;
      const nuevo = JSON.parse(txt.slice(i, j + 1));
      if (!nuevo || !nuevo.fechas || !nuevo.fechas.length) return null;
      D = nuevo;
      window.DATOS = nuevo;
      reiniciaConv();
      pintar();
      return nuevo.generado || null;
    } catch (e) {
      console.warn("No he podido refrescar el panel en vivo:", e);
      return null;
    }
  };

  /* ---------------------------------------------- arranque */
  document.title = "Rumbo · " + (D.titular || "Mi patrimonio");
  $("#marcaTexto").textContent = D.titular || "Mi patrimonio";
  $("#metaFecha").textContent = "Datos a " + G.fmtFecha(D.fechaExtracto);

  $("#btnTema").onclick = () => { cambiaTema(); pintar(); };
  if ($("#btnPrecios")) $("#btnPrecios").onclick = async () => {
    const b = $("#btnPrecios");
    b.disabled = true;
    const pinta = pct => {
      const p = Math.max(0, Math.min(100, Math.round(pct)));
      b.classList.add("actualizando");
      b.style.setProperty("--pct", p + "%");
      b.textContent = `↻ Actualizando… ${p} %`;
    };
    const vuelve = () => {
      b.classList.remove("actualizando");
      b.style.removeProperty("--pct");
      b.disabled = false;
      b.textContent = "↻ Actualizar precios";
    };
    pinta(0);
    try {
      const j = await (await fetch("api/actualizar", { method: "POST" })).json();
      if (!j.ok) throw new Error((j.errores || []).join(" ") || j.error || "No he podido empezar.");
    } catch (e) {
      vuelve();
      alert(e.message || "No he podido actualizar los precios. ¿Tienes conexión a internet?");
      return;
    }
    // Barra verde de 0 a 100 % y panel que se va actualizando al llegar los datos.
    let visto = null, parado = 0, reiniciado = false;
    const tic = setInterval(async () => {
      let j = null;
      try {
        j = await (await fetch("api/actualizar/progreso?_=" + Date.now())).json();
      } catch (e) { return; }
      const pr = j.progreso || {};
      pinta(pr.pct || 0);
      if (pr.error) {
        clearInterval(tic); vuelve();
        alert("No he podido actualizar los precios: " + pr.error);
        return;
      }
      if (pr.errores && pr.errores.length) b.title = pr.errores.join("\n");
      if (j.generado && j.generado !== visto) {
        visto = j.generado;
        await window.__refrescaDatos();       // el panel sale en vivo, sin esperar
      }
      parado = pr.activa ? 0 : parado + 1;
      if (parado >= 2 && !reiniciado) {
        reiniciado = true;
        clearInterval(tic);
        pinta(100);
        b.textContent = "✓ Precios actualizados";
        // Última recarga: así las secciones pesadas (histórico, comparador) quedan al día.
        setTimeout(() => location.reload(), 700);
      }
    }, 1000);
  };
  if (location.protocol === "file:" && $("#btnPrecios")) $("#btnPrecios").hidden = true;
  $("#btnVideo").onclick = () => {
    document.body.classList.toggle("video");
    $("#btnVideo").classList.toggle("act");
    setTimeout(pintarTab, 60);
  };
  document.querySelectorAll("#tabs button").forEach(b => { b.onclick = () => irA(b.dataset.tab); });
  $("#mesSel").onchange = e => { estado.mes = +e.target.value; pintaMes(); };
  $("#mesPrev").onclick = () => { estado.mes = Math.max(0, estado.mes - 1); pintaMes(); };
  $("#mesNext").onclick = () => { estado.mes = Math.min(D.resumenMensual.length - 1, estado.mes + 1); pintaMes(); };
  ["rAnos", "rRent", "rApor"].forEach(id => $("#" + id).addEventListener("input", pintaProyeccion));
  $("#rApor").value = Math.min(3000, Math.max(0, Math.round((D.total.ritmoMensual || 500) / 50) * 50));

  document.addEventListener("keydown", e => {
    // Solo se ignoran los atajos mientras escribes en un campo. Si el guardia
    // fuese "el foco esta en el body", dejarian de funcionar en cuanto pulsas
    // cualquier boton, que es justo cuando los quieres.
    const t = e.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
    if (e.key === "Escape" && filtrando()) {
      estado.ocultos.clear(); estado.prop = "total"; estado.mon = "global";
      recuerda.guarda("patrimonio.prop", "total"); recuerda.guarda("patrimonio.mon", "global");
      pintar();
    }
    if (e.key === "v" && !e.metaKey && !e.ctrlKey) $("#btnVideo").click();
    if (e.key === "l" && !e.metaKey && !e.ctrlKey && estado.tab === "patrimonio") {
      estado.ocultos = estado.ocultos.size ? new Set() : new Set(idsCorto());
      pintaPatrimonio();
    }
    const n = "123456".indexOf(e.key);
    const tab = ["patrimonio", "mes", "fondos", "rendimiento", "datos", "ayuda"][n];
    if (n >= 0 && document.getElementById("tab-" + tab)) irA(tab);
  });

  let t = null;
  window.addEventListener("resize", () => { clearTimeout(t); t = setTimeout(pintarTab, 140); });

  const tabGuardada = recuerda.lee("patrimonio.tab");
  if (tabGuardada && document.getElementById("tab-" + tabGuardada)) {
    estado.tab = tabGuardada;
    document.querySelectorAll("#tabs button").forEach(b =>
      b.setAttribute("aria-selected", String(b.dataset.tab === estado.tab)));
    document.querySelectorAll(".panel").forEach(p => { p.hidden = p.id !== "tab-" + estado.tab; });
  }

  try {
    pintar();
  } catch (e) {
    console.error(e);
    document.querySelector(".env").insertAdjacentHTML("afterbegin",
      '<div class="av" style="margin:20px 0"><span>⚠</span><span><b>Algo ha fallado al pintar el panel.</b> ' +
      esc(String(e && e.message || e)) + '<br>Cierra la app y vuelve a abrirla con «Iniciar»; si sigue igual, pulsa F12 y mira la consola del navegador.</span></div>');
  }
  // ?ir=seccionComparar pone esa sección la primera de su pestaña (para capturas y enlaces).
  const irA_ = qs.get("ir") && document.getElementById(qs.get("ir"));
  if (irA_) {
    irA_.parentNode.prepend(irA_);
    irA_.style.marginTop = "24px";
    pintarTab();
  }
  actualizaVivo();
  setInterval(actualizaVivo, 60000);          // el precio en vivo, cada minuto
  setInterval(() => {                          // el ticker pasa a otro activo cada 7 s
    estado.tick = (estado.tick || 0) + 1;
    pintaTicker();
  }, 7000);
  // Si los precios cambian detrás (una actualización en marcha, o desde otra
  // pestaña), el panel se refresca solo. Nunca mientras escribes en «Mis datos».
  let vigente = null;
  setInterval(async () => {
    if (location.protocol === "file:" || window.EDITOR_SUCIO || estado.tab === "datos") return;
    try {
      const j = await (await fetch("api/datos/vigente?_=" + Date.now())).json();
      if (!j || !j.vigente) return;
      if (vigente === null) { vigente = j.vigente; return; }
      if (j.vigente !== vigente) { vigente = j.vigente; await window.__refrescaDatos(); }
    } catch (e) { /* sin servidor detrás (archivo suelto): no pasa nada */ }
  }, 120000);
})();
