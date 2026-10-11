/* ============================================================
   editor.js  ·  Pestaña «Mis datos»: productos, movimientos y
   saldos. Todo se guarda en mis_datos a través del servidor.
   ============================================================ */
(function () {
  "use strict";

  const $ = s => document.querySelector(s);
  const D = window.DATOS;
  const SOLO_SALDO = ["efectivo", "deuda"];
  const E = { cfg: null, modo: "demo", tipos: {}, fuentes: {}, tiposMov: {}, tiposCuenta: {}, vista: "productos",
              filtro: "todos", filtroCuenta: "todos", cuenta: null };

  /* ---------------------------------------------- utilidades */
  const esc = window.escapar;   // escapado unificado (una sola copia, en graficos.js)
  const eur = v => v == null ? "—" : Number(v).toLocaleString("es-ES", { style: "currency", currency: "EUR" });
  const num = (v, d = 4) => v == null ? "—" : Number(v).toLocaleString("es-ES", { maximumFractionDigits: d });
  const fecha = iso => iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}` : "—";
  const hoy = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); };
  const leeNum = t => {
    t = String(t || "").replace(/[€\s]/g, "");
    // "1.234,56" y "1.000" (mil) en castellano; "1234.5" también vale.
    if (t.includes(",") || /^-?\d{1,3}(\.\d{3})+$/.test(t)) t = t.replace(/\./g, "").replace(",", ".");
    return parseFloat(t);
  };
  const nombre = p => p ? (p.corto || p.nombre) : "¿?";
  const prod = id => E.cfg.productos.find(p => p.id === id);
  const cuentaDe = id => (E.cfg.cuentas || []).find(c => c.id === id);
  const opCuentas = () => (E.cfg.cuentas || []).map(c =>
    `<option value="${esc(c.id)}">${esc(c.nombre)}${c.moneda && c.moneda !== "EUR" ? " · " + esc(c.moneda) : ""}</option>`).join("");
  const propDe = id => (E.cfg.propietarios || []).find(p => p.id === id);
  const soloSaldo = p => SOLO_SALDO.includes(p.tipo);
  const manual = p => p.fuente === "manual" || soloSaldo(p);
  // Se le puede pedir el precio a la fuente: cotiza en internet o tiene URL de donde leerlo.
  const actualizable = p => !manual(p) || !!p.urlFuente;
  const opciones = (obj, sel) => Object.entries(obj)
    .map(([k, v]) => `<option value="${esc(k)}"${k === sel ? " selected" : ""}>${esc(v)}</option>`).join("");
  const recuerda = {
    lee(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    guarda(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* da igual */ } },
  };
  const Q = new URLSearchParams(location.search);
  E.vista = Q.get("vista") || recuerda.lee("patrimonio.editor") || "productos";
  E.cuenta = Q.get("cuenta") || null;    // ficha de cuenta abierta (enlace desde el panel)

  async function api(metodo, url, cuerpo) {
    const r = await fetch(url, {
      method: metodo, headers: { "Content-Type": "application/json" },
      body: cuerpo ? JSON.stringify(cuerpo) : undefined,
    });
    let j = {};
    try { j = await r.json(); } catch (e) { /* respuesta vacía */ }
    if (!r.ok || j.ok === false) throw new Error((j.errores || [j.error || "Algo ha fallado. ¿Sigue abierta la ventana negra de la app?"]).join("\n"));
    return j;
  }
  async function carga() {
    const j = await api("GET", "api/cartera");
    Object.assign(E, { cfg: j.cartera, modo: j.modo, tipos: j.tipos, fuentes: j.fuentes,
                       tiposMov: j.tiposMovimiento, tiposCuenta: j.tiposCuenta || {} });
  }
  async function guarda(coleccion, datos) {
    const j = await api("POST", "api/" + coleccion, datos);
    E.cfg = j.cartera;
    COP.lista = null;   // hay una copia automática nueva
    window.EDITOR_SUCIO = true;
    avisa(j.avisos);
    return j.item;
  }
  async function borra(coleccion, id) {
    const j = await api("DELETE", `api/${coleccion}/${encodeURIComponent(id)}`);
    E.cfg = j.cartera;
    COP.lista = null;
    window.EDITOR_SUCIO = true;
    avisa(j.avisos);
  }
  /** Avisos que llegan del servidor al guardar o borrar. Se quedan pendientes
      cuando aún no hay sitio para ellos: `pinta()` regenera la barra de avisos y
      los re-pinta al terminar, que es justo cuando se ven (si no, se escribían
      antes de repintar y `pinta()` los borraba sin que el usuario llegara a
      verlos). */
  /** Los avisos son PERSISTENTES: se quedan en pantalla hasta que el usuario los
      cierra con su «×» o cambia de pestaña dentro de «Mis datos». Antes se perdían
      al repintar (el guardado los escribía y `pinta()` los volvía a borrar), y
      avisos como «tu saldo de hoy no recoge estos 5 €» son justo los que tienen
      que estar a la vista sin prisa. */
  let AVISOS = [];
  function avisa(avisos) {
    // Los avisos GLOBALES del motor («REVOLUT_EUR: todavía no tiene ningún saldo
    // anotado», precios sin conexión…) ya están a la vista en el pie del panel: aquí
    // solo se quedan los que ha producido lo que acabas de hacer (p. ej. «ese día hay
    // un saldo a mano y no lo he tocado»), que son los que hacen falta mientras
    // decides qué hacer con ellos.
    const globales = (D && D.avisos) || [];
    for (const a of (avisos || [])) {
      if (a && !AVISOS.includes(a) && !globales.includes(a)) AVISOS.push(a);
    }
    pintaAvisos();
  }
  function cierraAviso(i) { AVISOS.splice(Number(i), 1); pintaAvisos(); }
  function limpiaAvisos() { AVISOS = []; pintaAvisos(); }
  function pintaAvisos() {
    const el = $("#edAvisos");
    if (!el) return;                     // la vista aún no está montada: al repintar
    el.innerHTML = AVISOS.map((a, i) => `<div class="av"><span>⚠</span><span>${esc(a)}</span>
      <button class="cierra" data-acc="cierraAviso" data-id="${i}" aria-label="Cerrar aviso">×</button></div>`).join("")
      + (AVISOS.length > 1 ? `<div style="text-align:right"><button class="btn" data-acc="cierraTodosAvisos">
          Cerrar los ${AVISOS.length} avisos</button></div>` : "");
  }

  /* ---------------------------------------------- ventana modal */
  function abreModal(titulo, cuerpo, alGuardar, textoBoton = "Guardar") {
    const dlg = $("#modal");
    dlg.classList.remove("ancho");      // la ficha de anotaciones es la única más ancha
    if (dlg.open) dlg.close();          // si venía de otra ventana abierta (p. ej. el historial)
    dlg.innerHTML = `<form class="mForm" novalidate>
      <header><h2>${titulo}</h2><button type="button" class="x" data-cerrar aria-label="Cerrar">×</button></header>
      <div class="mCuerpo">${cuerpo}</div>
      <div class="mErr" hidden></div>
      <footer><button type="button" class="btn" data-cerrar>Cancelar</button>
        <button type="submit" class="btn prim">${textoBoton}</button></footer></form>`;
    const f = dlg.querySelector("form");
    dlg.querySelectorAll("[data-cerrar]").forEach(b => { b.onclick = () => dlg.close(); });
    f.onsubmit = async e => {
      e.preventDefault();
      const btn = f.querySelector("[type=submit]"), err = f.querySelector(".mErr");
      btn.disabled = true;
      err.hidden = true;
      try {
        const siguiente = await alGuardar(f);
        dlg.close();
        pinta();
        if (typeof siguiente === "function") siguiente();
      } catch (x) {
        err.textContent = x.message;
        err.hidden = false;
      } finally { btn.disabled = false; }
    };
    dlg.showModal();
    return f;
  }
  const campos = f => Object.fromEntries(new FormData(f).entries());
  function rellena(f, obj) {
    Object.entries(obj).forEach(([k, v]) => {
      const el = f.elements[k];
      if (!el || v == null) return;
      if (el.type === "checkbox") el.checked = !!v;
      else if (el instanceof RadioNodeList) el.value = String(v);
      else el.value = v;
    });
  }

  /* ---------------------------------------------- empezar con mis datos */
  function empezar() {
    const f = abreModal("Empezar con mis datos", `
      <p>Ahora estás viendo una cartera de ejemplo. ¿Cómo quieres empezar la tuya?</p>
      <label class="opcion"><input type="radio" name="desde" value="vacia" checked>
        <span><b>Empezar de cero</b><br>Una cartera vacía para meter lo tuyo.</span></label>
      <label class="opcion"><input type="radio" name="desde" value="ejemplo">
        <span><b>Copiar el ejemplo para practicar</b><br>Puedes tocar, añadir y borrar sin miedo.
        Cuando quieras empezar de verdad, borra sus productos.</span></label>
      <p class="ayuda">Tus datos se guardan solo en tu ordenador, en la carpeta <code>mis_datos</code>.</p>`,
    async f => {
      await api("POST", "api/empezar", { desde: campos(f).desde });
      recuerda.guarda("patrimonio.tab", "datos");
      location.reload();
    }, "Empezar");
    return f;
  }
  function reiniciar() {
    abreModal("Empezar de nuevo", `
      <p>¿Qué quieres hacer con la cartera que tienes ahora?</p>
      <label class="opcion"><input type="radio" name="a" value="vacia" checked>
        <span><b>Empezar de cero</b><br>Una cartera vacía para meter lo tuyo.</span></label>
      <label class="opcion"><input type="radio" name="a" value="demo">
        <span><b>Volver a ver la cartera de ejemplo</b><br>Luego podrás empezar otra vez con «Empezar con mis datos».</span></label>
      <p class="ayuda">No se pierde nada: tu cartera actual se guarda en <code>mis_datos/copias</code> por si quieres recuperarla.</p>`,
    async f => {
      await api("POST", "api/reiniciar", { a: campos(f).a });
      recuerda.guarda("patrimonio.tab", "datos");
      location.reload();
    }, "Continuar");
  }
  function soloPropio(fn) {
    return (...a) => (E.modo === "demo" ? empezar() : fn(...a));
  }

  /* ---------------------------------------------- pintado general */
  function pinta() {
    const cont = $("#editor");
    if (!cont) return;
    if (!E.cfg) { cont.innerHTML = '<p class="subt" style="margin-top:24px">Cargando tus datos…</p>'; return; }
    let html = "";
    // En la demo ya se ve arriba el aviso con el botón «Empezar con mis datos».
    if (E.modo !== "demo" && !E.cfg.productos.length) {
      html += `<section class="tarjeta bienvenida"><h2>Tu cartera está vacía</h2><ol>
        <li><b>Añade tus productos</b>: fondos, acciones, cripto, tu cuenta del banco, tu plan de pensiones…
          Usa el buscador para encontrarlos por ISIN o ticker.</li>
        <li><b>Anota tus compras</b> en «Movimientos», o <b>los saldos</b> de tus cuentas en «Saldos y valores».
          ¿Tienes muchas? Tráelas de golpe desde <b>«Importar»</b>: MyInvestor, una hoja de Excel o con ayuda de una IA.</li>
        <li>Vuelve a la pestaña <b>Patrimonio</b> y mira tu panel.</li></ol>
        <button class="btn prim" data-acc="nuevoProducto">+ Añadir mi primer producto</button></section>`;
    }
    html += `<div class="edBarra"><div class="segm" id="edVistas"></div><span class="sp"></span>
      ${!D && E.cfg.productos.length ? '<button class="btn" data-acc="verPanel">Ver mi panel →</button>' : ""}
      ${E.modo === "propio" ? '<button class="btn" data-acc="reiniciar">Empezar de nuevo…</button>' : ""}</div>
      <div id="edAvisos" class="avisos"></div><div id="edCuerpo"></div>`;
    cont.innerHTML = html;

    const vistas = [["productos", "Productos"], ["cuentas", "Cuentas"], ["movimientos", "Movimientos"],
                    ["saldos", "Saldos y valores"], ["importar", "Importar"], ["copias", "Copias y web"]];
    const seg = $("#edVistas");
    vistas.forEach(([id, et]) => {
      const b = document.createElement("button");
      b.textContent = et;
      b.setAttribute("aria-pressed", String(id === E.vista));
      // Cambiar de pantalla cierra la ficha de cuenta y descarta los avisos.
      b.onclick = () => { E.vista = id; E.cuenta = null; limpiaAvisos();
                          recuerda.guarda("patrimonio.editor", id); pinta(); };
      seg.appendChild(b);
    });
    $("#edCuerpo").innerHTML = ({ productos: vistaProductos, cuentas: vistaCuentas,
      movimientos: vistaMovimientos, saldos: vistaSaldos,
      importar: vistaImportar, copias: vistaCopias }[E.vista] || vistaProductos)();
    if (E.vista === "importar" || E.vista === "copias") conectaImportar();
    if (E.vista === "saldos") conectaSaldos();
    ["#edFiltro", "#edFiltroCuenta"].forEach(sel => {
      const el = $(sel);
      if (!el) return;
      el.onchange = e => {
        if (sel === "#edFiltro") E.filtro = e.target.value; else E.filtroCuenta = e.target.value;
        pinta();
      };
    });
    // Los avisos se repintan aquí: `pinta()` regenera la barra entera.
    pintaAvisos();
  }

  /* ---------------------------------------------- productos */
  function precioDe(p) {
    if (manual(p)) {
      const v = E.cfg.valoraciones.filter(x => x.producto === p.id).sort((a, b) => a.fecha < b.fecha ? 1 : -1)[0];
      return v ? `${eur(v.valor)} <small>${fecha(v.fecha)}</small>` : '<span class="neg">sin valor anotado</span>';
    }
    const c = D && (D.productos || []).find(x => x.id === p.id);
    return c && c.nav ? `${num(c.nav)} € <small>${fecha(c.navFecha)}</small>` : '<small>tras guardar</small>';
  }
  function vistaProductos() {
    const filas = E.cfg.productos.map(p => {
      const n = soloSaldo(p) || manual(p)
        ? E.cfg.valoraciones.filter(v => v.producto === p.id).length + " valores"
        : E.cfg.movimientos.filter(m => m.producto === p.id).length + " movs.";
      return `<tr><td><i class="pt" style="background:var(--s${p.slot || 1})"></i>${esc(nombre(p))}
          ${p.identificador ? `<small class="idp">${esc(p.identificador)}</small>` : ""}</td>
        <td>${esc(E.tipos[p.tipo] || p.tipo)}</td><td>${precioDe(p)}</td>
        <td>${esc(E.fuentes[p.fuente] || "")}${p.codigo ? ` <small>${esc(p.codigo)}</small>` : ""}</td>
        <td>${n}</td>
        <td class="acc">${actualizable(p) ? `<button data-acc="actPrecio" data-id="${esc(p.id)}" title="Baja solo el precio de este producto">Actualizar</button>` : ""}
          <button data-acc="editarProducto" data-id="${esc(p.id)}">Editar</button>
          <button data-acc="borrarProducto" data-id="${esc(p.id)}">Borrar</button></td></tr>`;
    }).join("");
    return `<section class="tarjeta"><header><h2>Productos</h2>
        <span class="subt">Todo lo que tienes: fondos, acciones, cripto, cuentas, planes, inmuebles…</span>
        <span class="sp"></span>${E.cfg.productos.length > 1 ? '<button class="btn" data-acc="repartirColores" title="Da a cada producto un color distinto">Repartir colores</button>' : ""}
        <button class="btn prim" data-acc="nuevoProducto">+ Añadir producto</button></header>
      ${filas ? `<div class="tablaEnv"><table class="dt"><thead><tr><th>Producto</th><th>Tipo</th><th>Último precio</th>
        <th>Fuente del precio</th><th>Datos</th><th></th></tr></thead><tbody>${filas}</tbody></table></div>`
        : '<p class="subt">Todavía no has añadido ningún producto.</p>'}</section>`;
  }

  function siguienteColor() {
    const usos = Array(13).fill(0);
    E.cfg.productos.forEach(p => { usos[p.slot || 1]++; });
    let mejor = 1;
    for (let i = 1; i <= 12; i++) if (usos[i] < usos[mejor]) mejor = i;
    return mejor;
  }

  /* Piezas de formulario: todas las cajas iguales, con su etiqueta encima. */
  const campo = (et, control, pista = "", clase = "") =>
    `<label class="campo ${clase}"><span class="et">${et}${pista ? ` <em>${pista}</em>` : ""}</span>${control}</label>`;
  const seccion = t => `<div class="secc">${t}</div>`;
  const LUPA = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>';
  const COLOR_FUENTE = { morningstar: "var(--s3)", yahoo: "var(--s7)", coingecko: "var(--s4)" };
  const decimal = v => v == null || v === "" ? "" : String(v).replace(".", ",");

  function formProducto(p) {
    const nuevo = !p;
    p = p || { tipo: "fondo", fuente: "morningstar", moneda: "EUR", largoPlazo: true, slot: siguienteColor() };
    const props = E.cfg.propietarios || [];
    const clases = [...new Set(E.cfg.productos.map(x => x.clase).filter(Boolean))];
    const colores = Array.from({ length: 12 }, (_, i) =>
      `<label class="color" style="--c:var(--s${i + 1})" title="Color ${i + 1}"><input type="radio" name="slot" value="${i + 1}"><i></i></label>`).join("");
    const f = abreModal(nuevo ? "Añadir producto" : "Editar " + esc(nombre(p)), `
      <div class="buscador">
        <div class="tit">Busca tu producto</div>
        <div class="sub">Por ISIN, ticker o nombre. Comprobamos que tiene precio antes de proponerlo.</div>
        <div class="fila"><div class="caja">${LUPA}<input id="bq" placeholder="IE00BYX5NX33, AAPL, bitcoin, oro…" autocomplete="off"></div>
          <button type="button" class="btn prim" id="bBuscar">Buscar</button></div>
        <div id="bRes" class="bRes"></div>
        <p class="ayuda">¿No aparece o no tiene precio en internet (un piso, oro físico, un plan de pensiones)?
          Rellénalo abajo y elige <b>«Valor anotado a mano»</b> como fuente del precio.</p>
      </div>

      ${seccion("El producto")}
      <div class="rejilla">
        ${campo("Nombre", '<input name="nombre" required>', "", "ancho")}
        ${campo("Nombre corto", '<input name="corto" maxlength="24">', "para los gráficos")}
        ${campo("Tipo", `<select name="tipo">${opciones(E.tipos, p.tipo)}</select>`)}
        ${campo("ISIN o ticker", '<input name="identificador">', "opcional")}
        ${campo("Banco o bróker", '<input name="entidad">', "opcional")}
        ${campo("Cuenta", `<select name="cuenta"><option value="">— ninguna todavía —</option>${opCuentas()}</select>`, "de sus compras, ventas y dividendos")}
        ${campo("Propietario", `<select name="propietario">${props.map(x =>
          `<option value="${esc(x.id)}"${x.id === p.propietario ? " selected" : ""}>${esc(x.nombre)}</option>`).join("")}</select>`,
          "para los filtros David / Gina / Compartido")}
      </div>

      <div class="siCotiza">${seccion("De dónde sale el precio")}
      <div class="rejilla tres">
        ${campo("Fuente", `<select name="fuente">${opciones(E.fuentes, p.fuente)}</select>`)}
        ${campo("Código", '<input name="codigo">', "", "siOnline")}
        ${campo("Moneda", '<input name="moneda" maxlength="3">', "", "siOnline")}
      </div></div>

      ${seccion("Cómo se muestra")}
      <div class="rejilla">
        ${campo("Clase de activo", `<input name="clase" list="edClases" placeholder="Renta variable global">
          <datalist id="edClases">${clases.map(c => `<option value="${esc(c)}">`).join("")}</datalist>`, "opcional")}
        ${campo("Color en los gráficos", `<div class="colores">${colores}</div>`)}
        <label class="interruptor ancho"><input type="checkbox" name="largoPlazo"><span class="pista"></span>
          <span><b>Inversión a largo plazo</b><small>El botón «Solo largo plazo» del panel quita lo que no lo es: colchón, cuentas…</small></span></label>
      </div>
      <p class="relleno" id="bRelleno" hidden></p>

      <details class="avanzado"><summary>Ficha y opciones avanzadas</summary>
        <div class="rejilla tres">
          ${campo("Comisión anual", '<input name="ter" inputmode="decimal" placeholder="0,12">', "TER, %")}
          ${campo("Riesgo", '<input name="riesgo" inputmode="numeric" placeholder="1 a 7">', "de 1 a 7")}
          ${campo("Gestora", '<input name="gestora">')}
          ${campo("Línea de respaldo", '<input name="respaldo" placeholder="BTCW.SW">', "Yahoo")}
          ${campo("Moneda respaldo", '<input name="respaldoMoneda" maxlength="3" placeholder="CHF">')}
          ${campo("Precio en vivo", '<input name="vivo" placeholder="bitcoin">', "id CoinGecko")}
          ${campo("Descripción", '<textarea name="papel" rows="2" placeholder="Para qué tienes este producto"></textarea>', "opcional", "ancho")}
        </div>
        <p class="ayuda">El <b>respaldo</b> contrasta cada día el precio con otra línea del mismo producto y usa esa
          cuando no coinciden. El <b>precio en vivo</b> mueve el valor minuto a minuto con una criptomoneda.</p>
      </details>`,
    async f => {
      const eraManual = manual(p);
      const d = campos(f);
      d.largoPlazo = f.elements.largoPlazo.checked;
      if (!nuevo) d.id = p.id;
      const item = await guarda("productos", d);
      // Si el producto era manual y ahora tiene código + fuente no manual,
      // intentamos descargar su precio automáticamente.
      const ahoraManual = manual(item);
      if (!nuevo && eraManual && !ahoraManual && item.codigo) {
        try {
          const j = await api("POST", `api/productos/${encodeURIComponent(item.id)}/actualizar`);
          if (j.nav != null) {
            avisa([`Precio de «${nombre(item)}» descargado: ${num(j.nav)} € (${fecha(j.navFecha)}).`]
              .concat(j.avisos || []));
          } else if (j.errores && j.errores.length) {
            avisa([`No se pudo descargar el precio de «${nombre(item)}»: ${j.errores[0]}`]);
          } else {
            avisa([`Código guardado para «${nombre(item)}». Se intentará descargar el precio en la próxima actualización.`]);
          }
        } catch (x) {
          avisa([`No se pudo descargar el precio de «${nombre(item)}»: ${x.message}`]);
        }
      }
      if (!nuevo) return null;
      // Siguiente paso natural: su primer dato.
      return manual(item) ? () => formValor(null, item.id) : () => formMovimiento(null, item.id);
    }, nuevo ? "Guardar producto" : "Guardar cambios");

    rellena(f, { ...p, ter: p.ter != null ? decimal(+(p.ter * 100).toFixed(4)) : "" });
    const ajusta = () => {
      const saldo = SOLO_SALDO.includes(f.elements.tipo.value);
      const online = !saldo && f.elements.fuente.value !== "manual";
      f.querySelector(".siCotiza").hidden = saldo;
      f.querySelectorAll(".siOnline").forEach(el => { el.hidden = !online; });
      f.querySelector(".rejilla.tres").classList.toggle("una", !online);
      f.querySelector(".buscador").hidden = saldo;
    };
    f.elements.tipo.onchange = ajusta;
    f.elements.fuente.onchange = ajusta;
    ajusta();

    const buscar = async () => {
      const q = $("#bq").value.trim();
      const res = $("#bRes");
      if (!q) return;
      res.innerHTML = '<p class="cargando">Buscando y comprobando precios…</p>';
      try {
        const j = await api("GET", "api/buscar?q=" + encodeURIComponent(q));
        if (!j.resultados.length && j.sinConexion) {
          res.innerHTML = `<p class="neg">No he podido conectar con internet (o Yahoo/Morningstar no han
            respondido). Comprueba tu conexión e inténtalo otra vez.</p>`;
          return;
        }
        if (!j.resultados.length) {
          res.innerHTML = `<p class="neg">No encuentro «${esc(q)}» con precio en internet. Prueba con el ISIN
            (viene en la ficha del producto en tu banco) o elige «Valor anotado a mano».</p>`;
          return;
        }
        res.innerHTML = j.resultados.map((r, i) => `<button type="button" class="bItem" data-i="${i}" style="--c:${COLOR_FUENTE[r.fuente]}">
          <span class="franja"></span>
          <span><span class="nm">${esc(r.nombre || r.codigo)}</span>
            <span class="meta"><span>${esc(r.codigo)}</span>${r.mercado && r.mercado !== E.fuentes[r.fuente] ? `<span>${esc(r.mercado)}</span>` : ""}<span>${esc(E.fuentes[r.fuente])}</span></span></span>
          <span class="pre">${num(r.precio)} ${esc(r.moneda)}<small>${fecha(r.fecha)}</small></span></button>`).join("");
        res.querySelectorAll(".bItem").forEach(b => {
          b.onclick = () => {
            const r = j.resultados[+b.dataset.i];
            const n = r.nombre || r.codigo;
            const fi = r.ficha || {};
            rellena(f, {
              nombre: n, corto: n.slice(0, 24).trim(), tipo: r.tipo, identificador: r.identificador,
              fuente: r.fuente, codigo: r.codigo, moneda: r.moneda || "EUR", vivo: r.vivo || "",
              ter: decimal(fi.ter), riesgo: fi.riesgo || "", gestora: fi.gestora || "",
            });
            if (fi.clase) f.elements.clase.value = fi.clase;
            const rell = [fi.ter != null && `comisión ${decimal(fi.ter)} %`, fi.riesgo && `riesgo ${fi.riesgo}/7`,
              fi.clase && "categoría", fi.gestora && "gestora"].filter(Boolean);
            const aviso = $("#bRelleno");
            aviso.hidden = !rell.length;
            aviso.textContent = rell.length ? `✓ Ficha rellenada desde Morningstar: ${rell.join(", ")}.` : "";
            res.querySelectorAll(".bItem").forEach(x => x.classList.toggle("sel", x === b));
            ajusta();
          };
        });
      } catch (x) { res.innerHTML = `<p class="neg">${esc(x.message)}</p>`; }
    };
    $("#bBuscar").onclick = buscar;
    $("#bq").onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); buscar(); } };
    if (nuevo) $("#bq").focus();
  }

  async function borrarProducto(id) {
    const p = prod(id);
    const nm = E.cfg.movimientos.filter(m => m.producto === id).length;
    const nv = E.cfg.valoraciones.filter(v => v.producto === id).length;
    const extra = nm || nv ? `\n\nSe borrarán también sus ${nm} movimientos y ${nv} valores anotados.` : "";
    if (!confirm(`¿Borrar «${nombre(p)}»?${extra}\n\nSi te equivocas, hay copias automáticas en mis_datos/copias.`)) return;
    try { await borra("productos", id); pinta(); } catch (x) { alert(x.message); }
  }

  /* ---------------------------------------------- cuentas (efectivo) */
  // Una CUENTA es un contenedor de dinero: nombre, entidad, moneda y propietario.
  // Su dinero vive en SU producto de efectivo vinculado (1:1), que es donde se
  // anotan los saldos y donde sube o baja con cada movimiento. Esta vista es la
  // casa de las cuentas: aquí se encuentran, se mira su saldo, su último ancla y
  // sus últimos movimientos, y se anota algo en ellas. Antes solo estaban la tabla
  // del panel y el desplegable del formulario, y localizar REVOLUT_EUR era casi
  // imposible.
  const efectivoDe = cid => E.cfg.productos.find(p => p.tipo === "efectivo" && p.cuenta === cid);
  const valsDe = pid => E.cfg.valoraciones
    .filter(v => v.producto === pid).sort((a, b) => a.fecha < b.fecha ? 1 : -1);
  const movsDe = cid => E.cfg.movimientos
    .filter(m => m.cuenta === cid || m.contrapartida === cid)
    .sort((a, b) => a.fecha < b.fecha ? 1 : a.fecha > b.fecha ? -1 : 0);
  const tiposCuenta = () => Object.keys(E.tiposCuenta || {}).length ? E.tiposCuenta
    : { efectivo: "Efectivo", banco: "Banco", broker: "Bróker", fondo: "Fondo / gestión",
        pension: "Plan de pensiones", cripto: "Cripto", otro: "Otro" };
  const etqTipoCuenta = c => tiposCuenta()[c.tipo] || c.tipo || "Efectivo";
  const enCuenta = (m, cid, mon) => {           // el dinero que este movimiento mueve
    const s = efectoDe(m, cid);
    const x = s ? importeEn(m, mon) : null;
    return x == null ? null : Math.round(s * x * 100) / 100;
  };
  /** Lo anotado el mismo día de un saldo A MANO: ese dinero no está sumado en el
      saldo (manda el banco), así que no puede quedarse sin verse. */
  function pendienteDe(p, v) {
    if (!v || v.auto || !p || !p.cuenta) return null;
    const mon = (p.moneda || "EUR").toUpperCase();
    let total = 0, n = 0;
    for (const m of E.cfg.movimientos || []) {
      if (m.fecha !== v.fecha) continue;
      const x = enCuenta(m, p.cuenta, mon);
      if (x == null) continue;
      total += x;
      n++;
    }
    if (!n || Math.abs(total) < 0.005) return null;
    return { fecha: v.fecha, importe: Math.round(total * 100) / 100, n, mon,
             saldo: v.valor, sugerido: Math.round((v.valor + total) * 100) / 100 };
  }

  function vistaCuentas() {
    const cuentas = E.cfg.cuentas || [];
    if (E.cuenta && cuentas.some(c => c.id === E.cuenta)) return fichaCuenta(cuentaDe(E.cuenta));
    const filas = cuentas.map(c => {
      const mon = (c.moneda || "EUR").toUpperCase();
      const p = efectivoDe(c.id);
      const u = p ? valsDe(p.id)[0] : null;
      const ms = movsDe(c.id);
      const pr = propDe(c.propietario);
      const saldo = u
        ? `<b class="${u.valor < 0 ? "neg" : ""}"${u.valor < 0
            ? ' title="Saldo negativo: en esta cuenta has apuntado más dinero del que tiene. Mira si te falta anotar un saldo o si algún movimiento salió en realidad de otra cuenta."'
            : ""}>${num(u.valor, 2)} ${esc(mon)}</b><div class="subt">${fecha(u.fecha)}${
            u.auto ? " · calculado" : " · anotado a mano"}${anotadoEseDia(p, u, true)}</div>`
        : `<span class="neg" title="Todavía no has anotado el saldo de esta cuenta. Anótalo tú aquí o apunta un movimiento de dinero: a partir de ahí sube y baja solo.">sin saldo anotado</span>`;
      const ult = ms.slice(0, 3).map(m => {
        const x = enCuenta(m, c.id, mon);
        return `<div class="subt">${fecha(m.fecha)} · ${esc(E.tiposMov[m.tipo] || m.tipo)}${
          x == null ? "" : ` ${x > 0 ? "+" : "−"}${num(Math.abs(x), 2)} ${esc(mon)}`}</div>`;
      }).join("") + (ms.length > 3 ? `<div class="subt">… y ${ms.length - 3} más</div>` : "");
      return `<tr><td style="text-align:left"><b>${esc(c.nombre)}</b>
          <div class="subt">${esc(c.entidad || "")}${pr ? " · " + esc(pr.nombre) : ""}</div></td>
        <td class="subt">${esc(etqTipoCuenta(c))}</td>
        <td class="subt">${esc(mon)}</td>
        <td>${saldo}</td>
        <td style="text-align:left">${ult || '<span class="subt">—</span>'}</td>
        <td class="acc"><button data-acc="verCuenta" data-id="${esc(c.id)}">Abrir ficha</button>
          <button data-acc="movsCuenta" data-id="${esc(c.id)}" title="Ver solo sus movimientos">Movimientos</button>
          <button data-acc="editarCuenta" data-id="${esc(c.id)}">Editar</button></td></tr>`;
    }).join("");
    return `<section class="tarjeta"><header><h2>Cuentas</h2>
        <span class="subt">Dónde está tu dinero: el saldo de cada cuenta, de quién es y lo último que ha hecho.</span>
        <span class="sp"></span>
        <button class="btn prim" data-acc="nuevaCuenta">+ Añadir cuenta</button></header>
      ${filas ? `<div class="tablaEnv"><table class="dt"><thead><tr>
        <th style="text-align:left">Cuenta</th><th>Tipo</th><th>Moneda</th><th>Saldo</th>
        <th style="text-align:left">Últimos movimientos</th><th></th></tr></thead><tbody>${filas}</tbody></table></div>`
        : '<p class="subt">Todavía no tienes ninguna cuenta. Añádela para anotar ahí sus saldos y sus movimientos.</p>'}
      <p class="ayuda" style="margin-top:12px">Pulsa «Abrir ficha» para ver la serie de saldos y todos los
      movimientos de una cuenta, y para anotar algo en ella.</p></section>`;
  }

  function fichaCuenta(c) {
    const mon = (c.moneda || "EUR").toUpperCase();
    const p = efectivoDe(c.id);
    const vals = p ? valsDe(p.id) : [];
    const u = vals[0];
    const ms = movsDe(c.id);
    const pr = propDe(c.propietario);
    const pend = pendienteDe(p, u);
    const filasVals = vals.map((v, i) => `<tr><td>${fecha(v.fecha)}${
        v.auto ? `<span class="subt" title="Saldo calculado: el último anotado a mano más lo que entró y salió ese día. Puedes corregirlo o borrarlo si tu banco dice otra cosa."> · calculado</span>`
               : anotadoEseDia(p, v, i === 0)}</td>
        <td class="${v.valor < 0 ? "neg" : ""}">${num(v.valor, 2)} ${esc(mon)}</td>
        <td class="acc"><button data-acc="editarValor" data-id="${esc(v.id)}">Editar</button>
          <button data-acc="replicarValor" data-id="${esc(v.id)}">Replicar</button>
          <button data-acc="borrarValor" data-id="${esc(v.id)}">Borrar</button></td></tr>`).join("");
    const filasMovs = ms.map(m => {
      const x = enCuenta(m, c.id, mon);
      const otro = m.cuenta === c.id ? m.contrapartida : m.cuenta;
      const o = otro ? cuentaDe(otro) : null;
      return `<tr><td>${fecha(m.fecha)}</td>
        <td style="text-align:left">${esc(E.tiposMov[m.tipo] || m.tipo)}</td>
        <td style="text-align:left">${m.producto ? esc(nombre(prod(m.producto))) : "—"}</td>
        <td style="text-align:left" class="subt">${o ? esc(o.nombre) : "—"}</td>
        <td class="${x == null ? "" : x > 0 ? "pos" : "neg"}">${x == null
          ? "—" : `${x > 0 ? "+" : "−"}${num(Math.abs(x), 2)} ${esc(mon)}`}</td>
        <td class="acc"><button data-acc="editarMov" data-id="${esc(m.id)}">Editar</button>
          <button data-acc="borrarMov" data-id="${esc(m.id)}">Borrar</button></td></tr>`;
    }).join("");
    return `<section class="tarjeta"><header>
        <button class="btn" data-acc="volverCuentas">← Todas</button>
        <h2>${esc(c.nombre)}</h2>
        <span class="subt">${esc(etqTipoCuenta(c))}${c.entidad ? " · " + esc(c.entidad) : ""} · ${esc(mon)}${
          pr ? " · " + esc(pr.nombre) : ""}</span><span class="sp"></span>
        <button class="btn" data-acc="movsCuenta" data-id="${esc(c.id)}">Ver en Movimientos</button>
        <button class="btn" data-acc="nuevoMovCuenta" data-id="${esc(c.id)}">+ Movimiento</button>
        <button class="btn prim" data-acc="nuevoValorCuenta" data-id="${esc(p ? p.id : "")}"
          ${p ? "" : "disabled title=\"Falta su producto de efectivo\""}>+ Anotar saldo</button></header>
      <p class="ayuda"><b>Saldo:</b> ${u ? `<span class="${u.valor < 0 ? "neg" : ""}">${num(u.valor, 2)} ${esc(mon)}</span> (anotado el ${fecha(u.fecha)}${u.auto ? ", calculado" : ""})`
        : 'ninguno anotado todavía: pulsa «+ Anotar saldo» o apunta un movimiento de dinero.'}
        · ${ms.length} ${ms.length === 1 ? "movimiento" : "movimientos"}</p>
      ${pend ? `<div class="av"><span>⚠</span><span>${esc(
        `Tu saldo del ${fecha(pend.fecha)} está anotado a mano y es el real de ese día, así que no lo he tocado: ` +
        `${pend.n === 1 ? "este movimiento" : `estos ${pend.n} movimientos`} de ese día (${pend.importe > 0 ? "+" : "−"}${num(Math.abs(pend.importe), 2)} ${pend.mon}) ` +
        `${pend.n === 1 ? "no está" : "no están"} sumado${pend.n === 1 ? "" : "s"} en él. Si tu saldo ya lo incluye, no hagas nada; ` +
        `si lo anotaste antes, edítalo y pónlo a ${num(pend.sugerido, 2)} ${pend.mon}.`)}</span></div>` : ""}
      ${u && u.valor < -0.005 ? `<div class="av"><span>⚠</span><span>${esc(
        `El saldo de esta cuenta está en negativo (${num(u.valor, 2)} ${mon}): mira si te falta anotar un saldo ` +
        "o si algún movimiento salió en realidad de otra cuenta.")}</span></div>` : ""}
      </section>
      <div class="saldos">
        <section class="tarjeta saldo"><header><h2>Serie de saldos</h2>
            <span class="subt">Lo anotado a mano manda; lo calculado se rehace con los movimientos.</span>
            <span class="sp"></span>${p ? `<button class="btn" data-acc="nuevoValorCuenta" data-id="${esc(p.id)}">+ Anotar</button>` : ""}</header>
          ${filasVals ? `<div class="tablaEnv"><table class="dt"><thead><tr><th>Fecha</th><th>Saldo</th><th></th></tr></thead>
            <tbody>${filasVals}</tbody></table></div>`
            : '<p class="neg">Todavía no tiene ningún saldo anotado.</p>'}</section>
        <section class="tarjeta saldo"><header><h2>Movimientos de esta cuenta</h2>
            <span class="subt">Cada movimiento de dinero sube o baja su saldo ese día.</span></header>
          ${filasMovs ? `<div class="tablaEnv alto"><table class="dt"><thead><tr><th>Fecha</th>
            <th style="text-align:left">Tipo</th><th style="text-align:left">Producto</th>
            <th style="text-align:left">Otra cuenta</th>
            <th title="Lo que este movimiento mueve en ESTA cuenta: con «+» entra, con «−» sale; «—» es que no toca su dinero (por ejemplo, una compra pagada desde otra cuenta).">Dinero</th><th></th></tr></thead>
            <tbody>${filasMovs}</tbody></table></div>`
            : '<p class="subt">Ningún movimiento anotado todavía en esta cuenta.</p>'}</section>
      </div>`;
  }

  /** Crear o editar una cuenta (identidad: nombre, tipo, moneda, entidad,
      propietario). Su saldo no vive aquí: vive en su producto de efectivo, que se
      le crea al guardar (invariante 1:1 del modelo cuentas/valores). */
  function formCuenta(c) {
    const nuevo = !c;
    const props = E.cfg.propietarios || [];
    const tipos = tiposCuenta();
    const f = abreModal(nuevo ? "Añadir cuenta" : `Editar cuenta · ${c.nombre}`, `
      <div class="rejilla">
        ${campo("Nombre", '<input name="nombre" maxlength="60" placeholder="REVOLUT_EUR">', "como la llamas tú", "ancho")}
        ${campo("Tipo", `<select name="tipo">${Object.entries(tipos)
          .map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join("")}</select>`, "qué clase de cuenta es")}
        ${campo("Moneda", '<input name="moneda" maxlength="3" placeholder="EUR">', "código de tres letras")}
        ${campo("Entidad", '<input name="entidad" maxlength="60" placeholder="Revolut">', "opcional")}
        ${campo("Propietario", `<select name="propietario"><option value="">${nuevo ? "— sin propietario —" : "— sin cambiar —"}</option>${
          props.map(p => `<option value="${esc(p.id)}">${esc(p.nombre)}</option>`).join("")}</select>`, "de quién es")}
      </div>
      <div class="resumen"><span>Al guardar se le crea su <b>saldo de efectivo</b>, donde se anota su dinero y
      que sube o baja con sus movimientos. El dinero ya anotado no se toca.</span></div>`,
    async f2 => {
      const d = campos(f2);
      if (!nuevo) d.id = c.id;
      if (!d.propietario) delete d.propietario;      // vacío: no se cambia
      const guardada = await guarda("cuentas", d);
      E.cuenta = guardada.id;                        // la abrimos: la cuenta es localizable
      return null;
    }, nuevo ? "Crear cuenta" : "Guardar cambios");
    rellena(f, c ? { ...c, moneda: c.moneda || "EUR" }
                 : { nombre: "", tipo: "efectivo", moneda: "EUR", entidad: "", propietario: "" });
    f.elements.nombre.focus();
  }

  /* ---------------------------------------------- movimientos */
  function vistaMovimientos() {
    const cotizables = E.cfg.productos.filter(p => !soloSaldo(p));
    const movs = E.cfg.movimientos
      .filter(m => E.filtro === "todos" || m.producto === E.filtro)
      .filter(m => E.filtroCuenta === "todos" || m.cuenta === E.filtroCuenta || m.contrapartida === E.filtroCuenta)
      .sort((a, b) => a.fecha < b.fecha ? 1 : a.fecha > b.fecha ? -1 : 0);
    const filas = movs.map(m => {
      const p = prod(m.producto);
      const c = cuentaDe(m.cuenta);
      const cp = cuentaDe(m.contrapartida);
      const pr = propDe(m.propietario);
      const precio = m.unidades ? (m.importe - (m.comision || 0)) / m.unidades : null;
      const original = m.monedaOriginal && m.monedaOriginal !== "EUR" && m.importeOriginal != null
        ? `${num(m.importeOriginal, 2)} ${esc(m.monedaOriginal)}` : "—";
      const etqCuenta = `${c ? c.nombre : "—"}${cp ? ` ⇄ ${cp.nombre}` : ""}`;
      // Lo retenido y lo cobrado aparte, para poder consultarlo sin abrir el movimiento.
      const aparte = [m.impuestos ? `Impuestos ${eur(m.impuestos)}` : "",
                      m.comision ? `Comisión ${eur(m.comision)}` : ""].filter(Boolean).join(" · ");
      return `<tr><td>${fecha(m.fecha)}</td><td style="text-align:left">${p ? `<i class="pt" style="background:var(--s${p.slot || 1})"></i>` : ""}${esc(nombre(p))}</td>
        <td style="text-align:left">${esc(E.tiposMov[m.tipo] || m.tipo)}</td>
        <td style="text-align:left" class="subt" title="${esc(etqCuenta)}">${esc(etqCuenta)}</td>
        <td style="text-align:left">${esc(pr ? pr.nombre : (m.propietario || "—"))}</td>
        <td>${m.unidades ? num(m.unidades) : "—"}</td>
        <td class="${m.tipo === "compra" || m.tipo === "comision" ? "" : "pos"}"${aparte ? ` title="${esc(aparte)}"` : ""}>${eur(m.importe)}</td>
        <td class="subt">${original}</td>
        <td>${precio ? num(precio) + " €" : "—"}</td>
        <td class="nota" title="${esc(m.nota)}">${esc(m.nota || "")}</td>
        <td class="acc"><button data-acc="editarMov" data-id="${esc(m.id)}" title="Cambiar este movimiento">Editar</button>
          <button data-acc="replicarMov" data-id="${esc(m.id)}" title="Anotar otro igual, sin tocar este">Replicar</button>
          <button data-acc="borrarMov" data-id="${esc(m.id)}" title="Borrar este movimiento">Borrar</button></td></tr>`;
    }).join("");
    return `<section class="tarjeta"><header><h2>Movimientos</h2>
        <span class="subt">Compras, ventas, dividendos y comisiones</span><span class="sp"></span>
        <select id="edFiltroCuenta" aria-label="Filtrar por cuenta"><option value="todos">Todas las cuentas</option>
          ${(E.cfg.cuentas || []).map(c => `<option value="${esc(c.id)}"${c.id === E.filtroCuenta ? " selected" : ""}>${esc(c.nombre)}</option>`).join("")}</select>
        <select id="edFiltro" aria-label="Filtrar por producto"><option value="todos">Todos los productos</option>
          ${cotizables.map(p => `<option value="${esc(p.id)}"${p.id === E.filtro ? " selected" : ""}>${esc(nombre(p))}</option>`).join("")}</select>
        <button class="btn prim" data-acc="nuevoMov">+ Añadir movimiento</button></header>
      ${filas ? `<div class="tablaEnv alto"><table class="dt"><thead><tr><th>Fecha</th><th style="text-align:left">Producto</th>
        <th style="text-align:left">Tipo</th><th style="text-align:left">Cuenta</th><th style="text-align:left">Propietario</th>
        <th>Unidades</th><th>Importe (EUR)</th><th>Importe original</th><th>Precio por unidad</th>
        <th style="text-align:left">Nota</th><th></th></tr></thead><tbody>${filas}</tbody></table></div>
        <p class="subt" style="margin-top:10px">${movs.length} movimientos · el importe original es el de la moneda en la que se hizo la operación (si fue en dólares, verás los dólares); el resto está convertido a euros con el cambio de ese día.</p>`
        : '<p class="subt">No hay movimientos todavía.</p>'}</section>`;
  }

  // Sufijo que se enseña junto al importe según la moneda elegida.
  const SUFIJO_MON = { EUR: "€", USD: "$", GBP: "£", JPY: "¥", CHF: "CHF", CAD: "CA$",
                       AUD: "A$", SEK: "kr", NOK: "kr", DKK: "kr", PLN: "zł", CZK: "Kč" };
  const AYUDA_IMPORTE = {
    compra: "Lo que salió de tu cuenta, con las comisiones incluidas.",
    venta: "Lo que te ingresaron, ya descontadas las comisiones.",
    entrega: "Coste asignado a los títulos que entran (escisión o entrega). Si ha sido gratis, déjalo en 0.",
    dividendo: "Lo que te ingresaron por el dividendo o el cupón, con la retención y las comisiones ya descontadas: es lo que llega a tu cuenta.",
    interes: "Lo que te ingresaron por el interés, con la retención (si la hubo) ya descontada: es lo que llega a tu cuenta.",
    comision: "Comisiones sueltas, como la de custodia. Las de compra y venta ya van dentro de su importe.",
  };
  // Movimientos de una cuenta: pueden llevar contrapartida (la otra cuenta).
  const MOV_CONTRAPARTIDA = ["deposito", "retirada", "transferencia", "traspaso", "saldo",
                             "cambio_divisa", "apertura", "interes", "impuesto", "comision"];
  // Qué significa la cuenta elegida según el tipo: la primera opción (vacía) se titula así.
  const ETQ_CUENTA = {
    compra: "— Externa: aportación de dinero nuevo —",
    venta: "— Fuera de la app: bolsillo o gasto —",
    dividendo: "— Sin cuenta —",
    deposito: "— Cuenta que recibe el dinero —",
    retirada: "— Cuenta de la que sale el dinero —",
    transferencia: "— Cuenta de la que sale —",
    traspaso: "— Cuenta de la que sale —",
    cambio_divisa: "— Cuenta que cambia de divisa —",
    apertura: "— Cuenta que se abre —",
    saldo: "— Elige la cuenta —",
    interes: "— Elige la cuenta —", impuesto: "— Sin cuenta —", comision: "— Sin cuenta —",
  };
  const PISTA_CUENTA = {
    compra: "de qué cuenta sale el dinero",
    venta: "a qué cuenta entra el dinero",
    dividendo: "a qué cuenta va el dinero",
    deposito: "cuenta que lo recibe",
    retirada: "cuenta de la que sale",
    transferencia: "de dónde sale", traspaso: "de dónde sale",
    cambio_divisa: "la cuenta en su moneda",
    interes: "en qué cuenta has cobrado el interés",
  };

  /** Replicar: el mismo formulario con los datos copiados, pero como movimiento
      NUEVO (el original no se toca). La fecha viene con la de hoy y no con la del
      original: una copia con la fecha vieja sería un duplicado silencioso de un
      apunte que ya existe, y se anotaría sin querer. */
  function replicarMov(id) {
    const m = E.cfg.movimientos.find(x => x.id === id);
    if (!m) return;
    formMovimiento(m, null, true);
  }

  /** `trasGuardar`, si viene, sustituye al final de siempre (dejar la vista en
      «Movimientos»): así la ficha del producto puede recargar el panel en vez de
      cambiar de pestaña. */
  function formMovimiento(m, productoId, copia, trasGuardar, opcs) {
    const cotizables = E.cfg.productos.filter(p => !soloSaldo(p));
    if (!cotizables.length) { alert("Primero añade un producto en «Productos»."); return; }
    const nuevo = !m || !!copia;
    // Con la copia se trabaja sobre una copia del original: rellenar no lo toca.
    m = m ? (copia ? Object.assign({}, m) : m)
          : { fecha: hoy(), tipo: "compra",
              producto: productoId || (E.filtro !== "todos" ? E.filtro : cotizables[0].id),
              // Cuenta ya elegida al abrirlo desde la ficha de una cuenta.
              ...(opcs && opcs.cuenta ? { cuenta: opcs.cuenta } : {}) };
    const props = E.cfg.propietarios || [];
    // Cuenta y propietario por defecto: los del producto, y si no, los de la cuenta.
    const cuentaPorDef = m.cuenta || (prod(m.producto) || {}).cuenta || "";
    const propPorDef = m.propietario || (cuentaDe(cuentaPorDef) || {}).propietario
      || (props[0] || {}).id || "";
    // Moneda del importe: la original si el movimiento ya existe; si no, la de la
    // cuenta por la que circula el dinero y, en su defecto, la del producto.
    const monedas = ["EUR", "USD", "GBP", "CHF", "JPY", "SEK", "NOK", "DKK", "PLN", "CZK", "CAD", "AUD"];
    [(cuentaDe(cuentaPorDef) || {}).moneda, (prod(m.producto) || {}).moneda, m.monedaOriginal]
      .forEach(x => { const u = (x || "").toUpperCase(); if (u && !monedas.includes(u)) monedas.push(u); });
    const monPorDef = m.monedaOriginal || (cuentaDe(cuentaPorDef) || {}).moneda
      || (prod(m.producto) || {}).moneda || "EUR";
    // Importe y comisión están guardados en euros: al editar se devuelven en su moneda.
    const tcMov = m.monedaOriginal && m.monedaOriginal !== "EUR" && m.tipoCambio ? m.tipoCambio : 1;
    const pildoras = Object.entries(E.tiposMov).map(([k, v]) =>
      `<label><input type="radio" name="tipo" value="${esc(k)}"><span>${esc(k === "dividendo" ? "Dividendo" : v)}</span></label>`).join("");
    const f = abreModal(copia ? "Replicar movimiento" : nuevo ? "Añadir movimiento" : "Editar movimiento", `
      ${copia ? `<p class="subt" style="margin:0 0 14px">Copia del movimiento del
        ${fecha(m.fecha)}. Le he puesto la fecha de hoy: cámbiala si lo quieres anotar en otro día.
        Hasta que pulses «Guardar movimiento» no se guarda nada, y el original no se toca.</p>` : ""}
      <div class="pildoras">${pildoras}</div>
      <div class="rejilla" style="margin-top:18px">
        ${campo("Producto", `<select name="producto"><option value="">— Ninguno: es un movimiento de cuenta —</option>${cotizables.map(p =>
          `<option value="${esc(p.id)}">${esc(nombre(p))}</option>`).join("")}</select>`, "", "ancho")}
        ${campo("Cuenta", `<select name="cuenta"><option value="">— sin cuenta —</option>${opCuentas()}</select>`, "de qué cuenta sale o entra", "ancho cuentaCampo")}
        ${campo("Cuenta contrapartida", `<select name="contrapartida"><option value="">— ninguna —</option>${opCuentas()}</select>`, "la otra cuenta, si la hay", "ancho siContra")}
        ${campo("Propietario", `<select name="propietario">${props.map(p =>
          `<option value="${esc(p.id)}">${esc(p.nombre)}</option>`).join("")}</select>`, "de quién es")}
        ${campo("Fecha", `<input type="date" name="fecha" max="${hoy()}">`)}
        ${campo("Unidades", '<input name="unidades" inputmode="decimal" placeholder="0">', "participaciones, acciones…", "siUnid")}
        ${campo("Moneda", `<select name="moneda">${monedas.map(k => `<option value="${k}">${k}</option>`).join("")}</select>`, "del importe")}
        ${campo("Importe total", '<div class="conSufijo"><input name="importe" inputmode="decimal" placeholder="0,00"><span>€</span></div>', "en la moneda elegida")}
        ${campo("Impuestos retenidos", '<div class="conSufijo"><input name="impuestos" inputmode="decimal" placeholder="0,00"><span>€</span></div>', "lo que retuvieron: el importe ya es lo que llega", "siImp")}
        ${campo("Coste salido de", `<select name="productoOrigen"><option value="">— Ninguno: es coste nuevo —</option>${cotizables.map(p =>
          `<option value="${esc(p.id)}">${esc(nombre(p))}</option>`).join("")}</select>`,
          "escisión: de qué activo se resta el coste", "ancho siEntrega")}
        ${campo("Comisión", '<div class="conSufijo"><input name="comision" inputmode="decimal" placeholder="0,00"><span>€</span></div>', "ya incluida en el importe", "siCom")}
        ${campo("Nota", '<input name="nota" maxlength="200" placeholder="Por ejemplo: aportación mensual">', "opcional", "ancho")}
      </div>
      <label class="interruptor siVincula" hidden><input type="checkbox" name="vincular"><span class="pista"></span>
        <span><b>Vincular «<span id="mVincNombre"></span>» a esta cuenta</b>
          <small>Sus próximas compras, ventas y dividendos usarán esta cuenta automáticamente.</small></span></label>
      <div class="resumen"><div><div id="mCuentaMov" class="movCta"></div><span id="mAyuda"></span></div><b id="mPrecio"></b></div>`,
    async f => {
      const d = campos(f);
      if (!nuevo) d.id = m.id;
      const hayVinculo = !f.querySelector(".siVincula").hidden && f.elements.vincular.checked;
      d.vincular = hayVinculo ? "1" : "";
      // Una entrega entrante no toca dinero: ni cuenta, ni comisión. La contrapartida
      // no se borra, solo se deja de mandar: el servidor conserva la que estuviera.
      if (d.tipo === "entrega") { d.cuenta = ""; d.comision = ""; delete d.contrapartida; }
      else d.productoOrigen = "";
      const pv = prod(d.producto);
      const avisoVinc = hayVinculo && pv && d.cuenta
        ? `«${nombre(pv)}» queda vinculado a la cuenta «${(cuentaDe(d.cuenta) || {}).nombre}»: ` +
          "sus próximos movimientos la usarán solos."
        : null;
      await guarda("movimientos", d);
      if (trasGuardar) return trasGuardar;
      // Vista a la que volver: la que tenía el formulario abierto (p. ej. la ficha
      // de una cuenta), para que guardar no te saque de donde estabas.
      E.vista = (opcs && opcs.vista) || E.vista || "movimientos";
      recuerda.guarda("patrimonio.editor", E.vista);
      return avisoVinc ? () => avisa([avisoVinc]) : null;
    }, nuevo ? "Guardar movimiento" : "Guardar cambios");
    rellena(f, { ...m, producto: m.producto || "", cuenta: cuentaPorDef, propietario: propPorDef,
      contrapartida: m.contrapartida || "", productoOrigen: m.productoOrigen || "",
      moneda: monPorDef,
      fecha: copia ? hoy() : m.fecha,
      impuestos: m.impuestos != null ? decimal(m.impuestos) : "",
      unidades: decimal(m.unidades || ""),
      importe: decimal(tcMov !== 1 && m.importeOriginal != null ? m.importeOriginal : m.importe),
      comision: decimal(m.comision != null && m.comision !== ""
        ? (tcMov !== 1 ? Math.round((m.comision / tcMov) * 100) / 100 : m.comision) : m.comision) });
    // La moneda sigue a la cuenta/producto salvo que el usuario la cambie (o salvo
    // que estemos editando o copiando un movimiento que ya trae la suya anotada).
    let monToque = !nuevo || !!copia;
    f.elements.moneda.addEventListener("change", () => { monToque = true; });
    let vinMostrado = false;
    const ajusta = () => {
      const t = f.elements.tipo.value;
      const p = prod(f.elements.producto.value);
      // Moneda del importe: la de la cuenta o del producto, mientras no se cambie a mano.
      const selMon = f.elements.moneda;
      if (selMon && !monToque) {
        const mon = (cuentaDe(f.elements.cuenta.value) || {}).moneda
          || (prod(f.elements.producto.value) || {}).moneda || "EUR";
        if ([...selMon.options].some(o => o.value === mon)) selMon.value = mon;
      }
      const suf = SUFIJO_MON[(selMon || {}).value] || (selMon ? selMon.value : "€");
      f.querySelectorAll(".conSufijo span").forEach(s => { s.textContent = suf; });
      const conUnid = t === "compra" || t === "venta" || t === "entrega";
      f.querySelector(".siUnid").hidden = !conUnid;
      // Impuestos y comisión en lo que los puede traer: compras, ventas,
      // dividendos e intereses (en un dividendo o un interés, si los hay).
      const esRenta = t === "dividendo" || t === "interes";
      f.querySelector(".siImp").hidden = !esRenta;
      f.querySelector(".siCom").hidden = !(t === "compra" || t === "venta" || esRenta);
      // Una entrega entrante (escisión) no mueve dinero de ninguna cuenta.
      f.querySelector(".cuentaCampo").hidden = t === "entrega";
      f.querySelector(".siEntrega").hidden = t !== "entrega";
      // Qué significa «cuenta» según el tipo: de dónde sale el dinero, quién la recibe…
      f.elements.cuenta.options[0].textContent = ETQ_CUENTA[t] || "— Sin cuenta —";
      const emC = f.querySelector(".cuentaCampo .et em");
      if (emC) emC.textContent = PISTA_CUENTA[t] || "de qué cuenta sale o entra";
      // La contrapartida solo tiene sentido en los movimientos de una cuenta…
      // …pero si el movimiento ya trae una guardada (la trae la importación) se
      // enseña igual: el usuario tiene que verla, y guardar nunca la puede perder.
      // En una entrega no se enseña: no mueve dinero (y no se manda al guardar).
      const hayCp = MOV_CONTRAPARTIDA.includes(t)
        || (t !== "entrega" && !!f.elements.contrapartida.value);
      f.querySelector(".siContra").hidden = !hayCp;
      // Vincular producto ↔ cuenta al anotar una compra, venta o dividendo.
      const cid = f.elements.cuenta.value;
      const conVin = ["compra", "venta", "dividendo"].includes(t) && p && cid && p.cuenta !== cid;
      const caja = f.querySelector(".siVincula");
      if (conVin && !vinMostrado) {
        f.elements.vincular.checked = !p.cuenta;   // sugerido solo si aún no está vinculado
        $("#mVincNombre").textContent = nombre(p);
      }
      caja.hidden = !conVin;
      vinMostrado = !!conVin;
      // Con la caja de unidades oculta, la del importe ocupa su hueco sin descuadrar la rejilla.
      $("#mAyuda").textContent = AYUDA_IMPORTE[t] + (p && manual(p) && t === "compra"
        ? " Como este producto se valora a mano, las unidades son opcionales." : "")
        + (esRenta && cid ? ` El dinero entra en «${nombre(cuentaDe(cid))}»: su saldo sube en ese importe.` : "");
      // De qué cuenta sale o entra el dinero, en texto y no solo en el desplegable: en
      // una compra o una venta ese campo decide a quién se le cobra, y era fácil no
      // verlo (una compra se anotó en REVOLUT_EUR creyendo que era TRADE REPUBLIC).
      const mCta = $("#mCuentaMov");
      if (mCta) {
        const nomCta = cid ? nombre(cuentaDe(cid)) : "";
        if (t === "compra") {
          mCta.textContent = nomCta
            ? `El dinero sale de «${nomCta}».`
            : "Sin cuenta: es una aportación de dinero nuevo, no sale de ninguna cuenta.";
        } else if (t === "venta") {
          mCta.textContent = nomCta
            ? `El dinero entra en «${nomCta}».`
            : "Sin cuenta: el dinero sale de la app, no entra en ninguna cuenta.";
        } else {
          mCta.textContent = "";
        }
      }
      const u = leeNum(f.elements.unidades.value), imp = leeNum(f.elements.importe.value);
      const com = leeNum(f.elements.comision.value) || 0;
      $("#mPrecio").textContent = t === "entrega" && u > 0
        ? `${num(imp / u)} ${suf} / unidad asignado`
        : conUnid && u > 0 && imp > 0 ? `${num((imp - com) / u)} ${suf} / unidad` : "";
    };
    f.oninput = ajusta;
    f.onchange = ajusta;
    ajusta();
  }

  async function borrarMov(id) {
    const m = E.cfg.movimientos.find(x => x.id === id);
    if (!confirm(`¿Borrar ${(E.tiposMov[m.tipo] || "").toLowerCase()} de ${eur(m.importe)} del ${fecha(m.fecha)} en «${nombre(prod(m.producto))}»?`)) return;
    try { await borra("movimientos", id); pinta(); } catch (x) { alert(x.message); }
  }

  /* ---------------------------------------------- saldos y valores anotados */
  const etiquetaValor = p => p.tipo === "efectivo" ? "Saldo" : p.tipo === "deuda" ? "Lo que queda por pagar" : "Valor";

  // Mismo criterio que el servidor para refrescar el efectivo de una cuenta:
  // qué movimientos entran (+1) y cuáles salen (−1) según la cuenta que se mire.
  const EFECTO = { dividendo: [1, 0], interes: [1, 0], deposito: [1, -1],
                   retirada: [-1, 1], transferencia: [-1, 1], traspaso: [-1, 1],
                   comision: [-1, 0], impuesto: [-1, 0] };
  // Una compra o una venta mueve UNA sola cuenta: la contrapartida si la hay (es
  // la que desembolsa o cobra), si no, la propia cuenta.
  const EFECTO_CV = { compra: -1, venta: 1 };
  const efectoDe = (m, cid) => {
    if (!cid) return 0;
    if (EFECTO_CV[m.tipo]) return (m.contrapartida || m.cuenta) === cid ? EFECTO_CV[m.tipo] : 0;
    if (!EFECTO[m.tipo]) return 0;
    if (m.cuenta === cid) return EFECTO[m.tipo][0];
    return m.contrapartida === cid ? EFECTO[m.tipo][1] : 0;
  };
  /** El importe del movimiento en la moneda de la cuenta; null si haría falta un
      cambio de divisa que no tenemos (no se inventa ninguna cifra). */
  const importeEn = (m, mon) => {
    if ((m.monedaOriginal || "EUR").toUpperCase() === mon && m.importeOriginal != null) {
      return +m.importeOriginal;
    }
    return mon === "EUR" && m.importe != null ? +m.importe : null;
  };
  /** Lo anotado el mismo día del ÚLTIMO saldo A MANO de la cuenta: es el saldo que
      enseña el panel, y ese dinero no está sumado en él, así que no puede quedarse
      sin verse. Solo esa fila, o quedaría marcado medio histórico. */
  function anotadoEseDia(p, v, ultimo) {
    const q = ultimo ? pendienteDe(p, v) : null;
    if (!q) return "";
    const ayuda = "Tu saldo de este día está anotado a mano y es el real de tu banco: estos " +
      "movimientos NO están sumados en él. Si tu saldo ya los incluye (lo normal), no hagas " +
      "nada; si lo anotaste antes de que entraran, edítalo y súbelo.";
    const que = q.n === 1 ? "ese día" : `ese día (${q.n})`;
    return `<span class="subt" title="${esc(ayuda)}">· ${que} ${q.importe > 0 ? "+" : ""}${eur(q.importe)}</span>`;
  }

  function vistaSaldos() {
    const lista = E.cfg.productos.filter(manual);
    if (!lista.length) {
      return `<section class="tarjeta"><header><h2>Saldos y valores</h2></header>
        <p class="subt">Aquí aparecen tus cuentas, deudas, planes de pensiones y todo lo que no tiene precio en
        internet. Añádelos en «Productos» (tipo «Cuenta / efectivo», o fuente del precio «Valor anotado a mano»).</p></section>`;
    }
    // Una fila por valor con lo básico y sus anotaciones en un popup: con el historial
    // entero a la vista la página se hacía larguísima y había que bajar y subir.
    const hayAportado = lista.some(p => !soloSaldo(p));
    const filas = lista.map(p => {
      const vals = valsDe(p.id);
      const u = vals[0];
      const conAportado = !soloSaldo(p);
      const desde = vals.length ? vals[vals.length - 1].fecha : null;
      return `<tr>
        <td style="text-align:left"><i class="pt" style="background:var(--s${p.slot || 1})"></i> ${esc(nombre(p))}
          <small class="subt">${esc(E.tipos[p.tipo] || "")}${p.entidad ? " · " + esc(p.entidad) : ""}${
            p.moneda && p.moneda !== "EUR" ? " · " + esc(p.moneda) : ""}</small></td>
        <td>${u ? fecha(u.fecha) : '<span class="neg">sin datos</span>'}</td>
        <td>${u ? eur(u.valor) : "—"}${u && u.auto
          ? '<span class="subt" title="Saldo calculado con sus movimientos"> · calculado</span>' : ""}</td>
        ${hayAportado ? `<td>${conAportado ? (u && u.aportado != null ? eur(u.aportado) : "—") : ""}</td>` : ""}
        <td class="subt">${vals.length ? `${vals.length}${desde ? ` · desde ${fecha(desde)}` : ""}` : "—"}</td>
        <td class="acc">
          <button data-acc="verAnotaciones" data-id="${esc(p.id)}"${vals.length ? "" : " disabled"}
            title="Ver su historial completo en una ventana">Ver anotaciones${vals.length ? ` (${vals.length})` : ""}</button>
          <button data-acc="editarProducto" data-id="${esc(p.id)}" title="Editar este producto">Editar</button>
          <button data-acc="nuevoValor" data-id="${esc(p.id)}">+ Anotar</button></td></tr>`;
    }).join("");
    return `<section class="tarjeta"><header><h2>Saldos y valores</h2>
        <span class="subt">Lo que no tiene precio en internet. Cuanto más a menudo lo anotes (una vez al mes basta),
        mejor sale su curva.</span><span class="sp"></span>
        <button class="btn prim" data-acc="todosValores">Anotar todos de una vez</button>
        <a class="btn" href="api/valores/plantilla" download>Descargar plantilla CSV</a>
        <button class="btn" data-acc="cargarPlantilla">Cargar plantilla</button></header>
      <input type="file" id="plantArchivo" accept=".csv,text/csv" hidden>
      <div class="imErr" id="plantErr" hidden></div>
      <div class="tablaEnv" style="margin-top:16px"><table class="dt"><thead><tr>
        <th style="text-align:left">Valor</th><th>Último dato</th><th>Valor</th>${
          hayAportado ? "<th>Aportado</th>" : ""}<th>Anotaciones</th><th></th></tr></thead>
        <tbody>${filas}</tbody></table></div>
      <p class="ayuda" style="margin-top:12px">Pulsa <b>«Ver anotaciones»</b> y su historial se abre en una ventana,
      sin salir de aquí; desde ella puedes editarlas, replicarlas o borrarlas.</p></section>
      ${vistaSinCotizacion()}`;
  }

  /** El historial completo de un valor, en la misma ventana modal: se abre desde su
      fila de «Saldos y valores» y trae los botones de siempre para no salir de aquí. */
  function abreAnotaciones(p) {
    const vals = valsDe(p.id);
    const conAportado = !soloSaldo(p);
    const filas = vals.map((v, i) => `<tr><td>${fecha(v.fecha)}${v.auto ? `<span class="subt"
        title="Saldo calculado: el último anotado a mano más lo cobrado ese día en dividendos, intereses, depósitos y retiradas. Cámbialo o bórralo si tu banco dice otra cosa."> · calculado</span>` : anotadoEseDia(p, v, i === 0)}</td>
      <td>${eur(v.valor)}</td>
      ${conAportado ? `<td>${v.aportado != null ? eur(v.aportado) : "—"}</td>` : ""}
      <td class="acc"><button data-acc="editarValor" data-id="${esc(v.id)}">Editar</button>
        <button data-acc="replicarValor" data-id="${esc(v.id)}">Replicar</button>
        <button data-acc="borrarValor" data-id="${esc(v.id)}">Borrar</button></td></tr>`).join("");
    const dlg = $("#modal");
    dlg.classList.add("ancho");
    dlg.innerHTML = `<div class="mForm">
      <header><h2>Anotaciones · ${esc(nombre(p))}</h2>
        <button type="button" class="x" data-cerrar aria-label="Cerrar">×</button></header>
      <div class="mCuerpo">
        <p class="subt">${esc(E.tipos[p.tipo] || "")}${p.entidad ? " · " + esc(p.entidad) : ""} ·
          ${vals.length} ${vals.length === 1 ? "anotación" : "anotaciones"}${
            vals.length > 1 ? ` · de ${fecha(vals[vals.length - 1].fecha)} a ${fecha(vals[0].fecha)}` : ""}</p>
        ${filas ? `<div class="tablaEnv alto"><table class="dt"><thead><tr><th>Fecha</th>
          <th>${esc(etiquetaValor(p))}</th>${conAportado ? "<th>Aportado</th>" : ""}<th></th></tr></thead>
          <tbody>${filas}</tbody></table></div>`
          : '<p class="neg">Todavía no tiene ninguna anotación.</p>'}
      </div>
      <footer><button type="button" class="btn" data-cerrar>Cerrar</button>
        <button type="button" class="btn prim" data-acc="nuevoValor" data-id="${esc(p.id)}">+ Anotar</button></footer>
    </div>`;
    dlg.querySelectorAll("[data-cerrar]").forEach(b => { b.onclick = () => dlg.close(); });
    if (!dlg.open) dlg.showModal();
  }

  /* --- valores que no se pueden bajar de internet: edición y fuente de precio --- */
  function sinCotizacion() {
    return E.cfg.productos.filter(p => p.fuente === "manual" && !soloSaldo(p));
  }
  const ultimoValor = id => E.cfg.valoraciones
    .filter(v => v.producto === id).sort((a, b) => a.fecha < b.fecha ? 1 : -1)[0];

  /* La fuente de precio, como en Portfolio Performance: la URL y CÓMO leerla
     (automático, JSON con rutas, tabla web o el precio marcado en la página). */
  const MODOS_FUENTE = [["auto", "Automático"], ["json", "JSON con rutas"],
                        ["tabla", "Tabla en la web"], ["web", "Precio marcado en la web"]];
  const CAMPOS_FUENTE_UI = [
    ["json", "urlRutaPrecio", "Ruta para la cotización", "$[*].kurs", true],
    ["json", "urlRutaFecha", "Ruta para la fecha", "$[*].datum"],
    ["json", "urlFormatoFecha", "Formato de fecha (si no es 2025-01-31)", "%d.%m.%Y"],
    ["tabla", "urlColPrecio", "Columna del precio", "Precio", true],
    ["tabla", "urlColFecha", "Columna de la fecha", "Fecha"],
    ["tabla", "urlFormatoFecha", "Formato de fecha (si no es 2025-01-31)", "%d.%m.%Y"],
    ["web", "urlSelector", "Dónde está el precio", "span#precio o el texto de al lado", true],
    ["json tabla web", "urlFactor", "Factor (multiplica al precio)", "1"]];
  const FUENTE = { estado: {} };   // id → fila de ajustes abierta a mano

  function detalleFuente(p) {
    const campos = CAMPOS_FUENTE_UI.map(([mods, k, etq, ph, nec]) =>
      `<label data-modos="${mods}" hidden><span>${etq}${nec ? "" : " (opcional)"}</span>
        <input data-campo="${k}" data-id="${esc(p.id)}" value="${esc(p[k] || "")}"
          placeholder="${esc(ph)}" spellcheck="false"></label>`).join("");
    return `<tr data-fuente-fila="${esc(p.id)}" hidden><td colspan="5" style="text-align:left">
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:8px 16px;align-items:end">
        ${campos}
        <p class="ayuda" data-modos="auto">Automático busca el precio en la página (JSON-LD, meta o el
          primer número). Si la fuente es un JSON, una tabla o el precio está marcado, elige otro modo y pon aquí las rutas.</p>
      </div>
      <div data-fuente-res="${esc(p.id)}" style="margin-top:8px"></div></td></tr>`;
  }

  function vistaSinCotizacion() {
    const lista = sinCotizacion();
    if (!lista.length) return "";
    const filas = lista.map(p => {
      const u = ultimoValor(p.id);
      const modo = p.urlModo || "auto";
      const sel = `<select data-fuente-modo="${esc(p.id)}" title="Cómo leer la URL"
          style="width:100%;margin-top:4px">${MODOS_FUENTE.map(([v, t]) =>
            `<option value="${v}"${modo === v ? " selected" : ""}>${t}</option>`).join("")}</select>`;
      return `<tr>
        <td style="text-align:left"><i class="pt" style="background:var(--s${p.slot || 1})"></i> ${esc(nombre(p))}
          <small class="subt">${esc(E.tipos[p.tipo] || "")}${p.moneda && p.moneda !== "EUR" ? " · " + esc(p.moneda) : ""}</small></td>
        <td>${u ? fecha(u.fecha) : '<span class="neg">sin valores</span>'}</td>
        <td>${u ? eur(u.valor) : "—"}</td>
        <td style="text-align:left"><input type="url" data-url="${esc(p.id)}" value="${esc(p.urlFuente || "")}"
          placeholder="https://…" style="width:100%" spellcheck="false">${sel}</td>
        <td class="acc">
          <button data-acc="guardarUrl" data-id="${esc(p.id)}">Guardar fuente</button>
          <button data-acc="probarFuente" data-id="${esc(p.id)}">Probar</button>
          <button data-acc="fuenteDet" data-id="${esc(p.id)}">Ajustes</button>
          <a class="btn" href="api/valores/plantilla?producto=${encodeURIComponent(p.id)}" download>Plantilla</a>
          <button data-acc="nuevoValor" data-id="${esc(p.id)}">Anotar fecha y valor</button>
        </td></tr>${detalleFuente(p)}`;
    }).join("");
    return `<section class="tarjeta" style="margin-top:16px">
      <header><h2>Valores sin cotización automática</h2>
        <span class="subt">Planes, oro, fondos sin precio en internet… Anota fecha y valor, o pon una URL
        y la app leerá el precio de ahí cada vez que actualices (JSON, tabla web o precio marcado).</span></header>
      <div class="tablaEnv"><table class="dt"><thead><tr>
        <th style="text-align:left">Producto</th><th>Última fecha</th><th>Último valor</th>
        <th style="text-align:left">Fuente de precio (URL y lectura)</th><th></th></tr></thead>
        <tbody>${filas}</tbody></table></div>
      <p class="ayuda" style="margin-top:12px">La plantilla <code>fecha;valor</code> de cada fila actualiza solo a ese producto;
        la general trae <code>producto;fecha;valor</code> para actualizar varios de una vez.</p>
    </section>`;
  }

  const datosFuente = id => {
    const d = {};
    const url = document.querySelector(`input[data-url="${CSS.escape(id)}"]`);
    if (url) d.urlFuente = url.value.trim();
    const modo = document.querySelector(`select[data-fuente-modo="${CSS.escape(id)}"]`);
    if (modo) d.urlModo = modo.value;
    document.querySelectorAll(`[data-campo][data-id="${CSS.escape(id)}"]`).forEach(i => {
      d[i.dataset.campo] = i.value.trim();
    });
    return d;
  };

  function ajustaFuente(id) {
    const fila = document.querySelector(`tr[data-fuente-fila="${CSS.escape(id)}"]`);
    if (!fila) return;
    const modo = (document.querySelector(`select[data-fuente-modo="${CSS.escape(id)}"]`) || {}).value || "auto";
    fila.querySelectorAll("[data-modos]").forEach(el => {
      el.hidden = !el.dataset.modos.split(" ").includes(modo);
    });
  }

  function alternaFuente(id) {
    const fila = document.querySelector(`tr[data-fuente-fila="${CSS.escape(id)}"]`);
    if (!fila) return;
    fila.hidden = !fila.hidden;
    FUENTE.estado[id] = !fila.hidden;
    if (!fila.hidden) ajustaFuente(id);
  }

  function pintaProbar(id, j) {
    const caja = document.querySelector(`[data-fuente-res="${CSS.escape(id)}"]`);
    if (!caja) return;
    if (!j || !j.ok) {
      caja.innerHTML = `<span class="neg">${esc(((j && j.errores) || ["No he podido leer la fuente."]).join(" "))}</span>`;
      return;
    }
    let h = "";
    if (j.precio != null) h += `<p><strong>Lee ${num(j.precio)} € del ${fecha(j.fecha)}</strong> · ${j.total} fila(s) en total.</p>`;
    if (j.tablas) h += `<p class="ayuda">Tablas en la página: ${j.tablas.map(t =>
      esc((t.cabeceras || []).join(" | "))).join("  ·  ")}${j.filas ? "" : ". Indica la columna de la fecha y la del precio."}</p>`;
    const filas = (j.filas || []).map(f => `<tr><td>${esc(String(f[0]))}</td><td>${num(f[1])}</td></tr>`).join("");
    if (filas) h += `<div class="tablaEnv" style="max-height:220px;overflow:auto"><table class="dt">
      <thead><tr><th>Fecha</th><th>Precio</th></tr></thead><tbody>${filas}</tbody></table></div>`;
    caja.innerHTML = h || '<span class="neg">La fuente no ha devuelto nada legible.</span>';
  }

  async function probarFuente(id) {
    const fila = document.querySelector(`tr[data-fuente-fila="${CSS.escape(id)}"]`);
    if (fila) { fila.hidden = false; FUENTE.estado[id] = true; ajustaFuente(id); }
    const caja = document.querySelector(`[data-fuente-res="${CSS.escape(id)}"]`);
    if (caja) caja.textContent = "Leyendo la fuente…";
    try {
      const j = await api("POST", `api/productos/${encodeURIComponent(id)}/fuente/probar`, datosFuente(id));
      pintaProbar(id, j);
    } catch (x) { pintaProbar(id, { ok: false, errores: [x.message] }); }
  }

  async function guardarUrl(id) {
    try {
      const j = await api("POST", `api/productos/${encodeURIComponent(id)}/url`, datosFuente(id));
      E.cfg = j.cartera;
      window.EDITOR_SUCIO = true;
      avisa([datosFuente(id).urlFuente
                ? "Fuente guardada: el precio se leerá al pulsar «Actualizar precios» del panel."
                : "URL quitada."]);
      pinta();
    } catch (x) { alert(x.message); }
  }

  function conectaFuente() {
    document.querySelectorAll("tr[data-fuente-fila]").forEach(f => {
      const id = f.dataset.fuenteFila;
      const modo = (document.querySelector(`select[data-fuente-modo="${CSS.escape(id)}"]`) || {}).value || "auto";
      f.hidden = FUENTE.estado[id] != null ? FUENTE.estado[id] : modo !== "auto";
      ajustaFuente(id);
    });
    document.querySelectorAll("select[data-fuente-modo]").forEach(sel => {
      sel.onchange = () => {
        ajustaFuente(sel.dataset.fuenteModo);
        const fila = document.querySelector(`tr[data-fuente-fila="${CSS.escape(sel.dataset.fuenteModo)}"]`);
        if (fila && sel.value !== "auto") { fila.hidden = false; ajustaFuente(sel.dataset.fuenteModo); }
      };
    });
  }

  /* Baja el precio de UN producto sin tocar los demás (mucho más rápido que
     «Actualizar precios», que baja los de toda la cartera). */
  async function actPrecio(id) {
    const p = prod(id);
    const b = document.querySelector(`[data-acc="actPrecio"][data-id="${CSS.escape(id)}"]`);
    if (b) { b.disabled = true; b.textContent = "…"; }
    try {
      const j = await api("POST", `api/productos/${encodeURIComponent(id)}/actualizar`);
      if (j.cartera) E.cfg = j.cartera;
      const c = D && (D.productos || []).find(x => x.id === id);
      if (c && j.nav != null) { c.nav = j.nav; c.navFecha = j.navFecha; }
      window.EDITOR_SUCIO = true;
      pinta();
      avisa([`Precio de «${nombre(p)}» actualizado${j.nav != null ? `: ${num(j.nav)} € (${fecha(j.navFecha)})` : ""}.`]
        .concat(j.avisos || []));
    } catch (x) {
      if (b) { b.disabled = false; b.textContent = "Actualizar"; }
      alert(x.message);
    }
  }

  function conectaSaldos() {
    conectaFuente();
    const inp = $("#plantArchivo");
    if (inp) inp.onchange = async () => {
      const fallo = $("#plantErr");
      fallo.hidden = true;
      if (!inp.files.length) return;
      const fd = new FormData();
      fd.append("archivos", inp.files[0]);
      try {
        const r = await fetch("api/valores/plantilla", { method: "POST", body: fd });
        const j = await r.json().catch(() => ({}));
        if (!r.ok || !j.ok) throw new Error((j.errores || ["No he podido leer la plantilla."]).join("\n"));
        E.cfg = j.cartera;
        window.EDITOR_SUCIO = true;
        avisa([`Guardados ${j.guardados} ${j.guardados === 1 ? "valor" : "valores"}.`]
          .concat(j.avisos || []));
        pinta();
      } catch (x) {
        fallo.textContent = x.message;
        fallo.hidden = false;
      }
      inp.value = "";
    };
  }

  /** Replicar una anotación: el mismo formulario con los datos copiados, pero como
      valor NUEVO (el original no se toca). La fecha viene con la de hoy y no con la
      del original, para no sustituir sin querer el valor ya anotado en esa fecha. */
  function replicarValor(id) {
    const v = E.cfg.valoraciones.find(x => x.id === id);
    if (v) formValor(v, null, true);
  }

  function formValor(v, productoId, copia, vistaTras) {
    const nuevo = !v || !!copia;
    // Con la copia se trabaja sobre una copia del original: rellenar no lo toca.
    if (v && copia) v = Object.assign({}, v);
    const p = prod(v ? v.producto : productoId);
    const conAportado = !soloSaldo(p);
    const f = abreModal(`${copia ? "Replicar" : nuevo ? "Anotar" : "Editar"} ${etiquetaValor(p).toLowerCase()} · ${esc(nombre(p))}`, `
      ${copia ? `<p class="subt" style="margin:0 0 14px">Copia del valor del
        ${fecha(v.fecha)}. Le he puesto la fecha de hoy: cámbiala si lo quieres anotar en otro día.
        ${conAportado && v.aportado != null ? "El «aportado» es el de esa fecha: ajústalo si desde entonces has metido dinero. " : ""}
        Hasta que pulses «Guardar valor» no se guarda nada, y el original no se toca.</p>` : ""}
      <div class="rejilla">
        ${campo("Fecha", `<input type="date" name="fecha" max="${hoy()}">`)}
        ${campo(etiquetaValor(p), '<div class="conSufijo"><input name="valor" inputmode="decimal" placeholder="0,00"><span>€</span></div>')}
        ${conAportado ? campo("Aportado hasta esa fecha", '<div class="conSufijo"><input name="aportado" inputmode="decimal" placeholder="0,00"><span>€</span></div>', "opcional", "ancho") : ""}
      </div>
      <div class="resumen"><span>${conAportado
        ? "Lo aportado es el dinero que llevas metido en total. Si lo anotas, el panel calcula su rentabilidad."
        : "Copia el saldo que ves hoy en tu banco."} Si ya había un valor ese mismo día, se sustituye.</span></div>`,
    async f => {
      const d = { ...campos(f), producto: p.id };
      if (!nuevo) d.id = v.id;
      await guarda("valoraciones", d);
      E.vista = vistaTras || E.vista || "saldos";      // la vista desde la que se abrió
      recuerda.guarda("patrimonio.editor", E.vista);
      return null;
    }, copia ? "Guardar valor" : "Guardar");
    rellena(f, v
      ? { ...v, valor: decimal(v.valor), aportado: decimal(v.aportado),
          fecha: copia ? hoy() : v.fecha }
      : { fecha: hoy() });
    f.elements.valor.focus();
  }

  function todosValores() {
    const lista = E.cfg.productos.filter(manual);
    const ultimo = id => E.cfg.valoraciones.filter(v => v.producto === id).sort((a, b) => a.fecha < b.fecha ? 1 : -1)[0];
    abreModal("Anotar todos los saldos", `
      <div class="rejilla">${campo("Fecha", `<input type="date" name="fecha" max="${hoy()}" value="${hoy()}">`)}</div>
      <div class="listaValores">${lista.map(p => {
        const u = ultimo(p.id);
        return `<label class="filaValor"><span><span class="nm"><i class="pt" style="background:var(--s${p.slot || 1})"></i>${esc(nombre(p))}</span>
          <small>${u ? `Último: ${eur(u.valor)} el ${fecha(u.fecha)}` : "Sin valores todavía"}</small></span>
          <span class="conSufijo"><input name="v_${esc(p.id)}" inputmode="decimal" placeholder="${u ? decimal(u.valor) : "0,00"}"><span>€</span></span></label>`;
      }).join("")}</div>
      <div class="resumen"><span>Deja en blanco los que no quieras tocar. Es el gesto de cada mes: abre tu banco y copia los saldos.</span></div>`,
    async f => {
      const d = campos(f);
      const pendientes = lista.filter(p => String(d["v_" + p.id] || "").trim());
      if (!pendientes.length) throw new Error("No has escrito ningún valor.");
      for (const p of pendientes) {
        try { await guarda("valoraciones", { producto: p.id, fecha: d.fecha, valor: d["v_" + p.id] }); }
        catch (x) { throw new Error(`${nombre(p)}: ${x.message}`); }
      }
      E.vista = "saldos";
      return null;
    }, "Guardar todos");
  }

  async function borrarValor(id) {
    const v = E.cfg.valoraciones.find(x => x.id === id);
    if (!confirm(`¿Borrar el valor de ${eur(v.valor)} del ${fecha(v.fecha)} de «${nombre(prod(v.producto))}»?`)) return;
    try {
      await borra("valoraciones", id);
      const dlg = $("#modal");
      if (dlg && dlg.open) dlg.close();      // si el borrado venía del historial abierto
      pinta();
    } catch (x) { alert(x.message); }
  }

  /* ---------------------------------------------- importar */
  const IMP = { origen: "myinvestor", informe: null, token: null, hecho: null, prompt: null, archivos: [] };
  const ICONOS = {
    portfolio: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h16v16H4z"/><path d="M4 9h16M9 9v11M14 9v11"/></svg>',
    myinvestor: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21h18M5 21V10l7-5 7 5v11M9 21v-6h6v6"/></svg>',
    plantilla: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M9 3v18"/></svg>',
    ia: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 17l.8 2.2L22 20l-2.2.8L19 23l-.8-2.2L16 20l2.2-.8z"/></svg>',
  };

  function zona(acepta, varios, texto) {
    return `<label class="zona" id="imZona"><input type="file" id="imArchivos" accept="${acepta}"${varios ? " multiple" : ""}>
      <span class="zIc">↥</span><b>${texto}</b><small>o pulsa aquí para elegir${varios ? "los" : "lo"}</small>
      <span class="zNom" id="imNombres"></span></label>`;
  }

  function vistaImportar() {
    if (IMP.informe) return vistaPrevia();
    const exito = IMP.hecho ? `<div class="exito"><b>✓ ${esc(IMP.hecho)}</b>
      <button class="btn" data-acc="verPanelDatos">Ver mi panel →</button></div>` : "";
    const op = (id, titulo, texto) => `<button class="imOp${IMP.origen === id ? " sel" : ""}" data-acc="imOrigen" data-id="${id}">
      <span class="ic">${ICONOS[id]}</span><b>${titulo}</b><small>${texto}</small></button>`;
    let paso;
    if (IMP.origen === "portfolio") {
      paso = `<ol class="pasos">
          <li>Abre <b>Portfolio Performance</b> en el ordenador.</li>
          <li>Ve a <b>Archivo → Exportar → Todas las transacciones…</b> (o «Export all transactions»)
            y guarda el archivo <b>CSV</b>.</li>
          <li>Arrástralo aquí. Trae cuentas, compras, ventas, dividendos, intereses, impuestos,
            comisiones, depósitos, transferencias y el efectivo de cada cuenta.</li></ol>
        ${zona(".csv", false, "Arrastra aquí el CSV de Portfolio Performance")}
        <p class="ayuda">Sustituye lo que hubiera importado antes con esta misma opción, así que puedes repetirlo
          cada mes sin duplicar nada. El separador es «;» y los números van con coma decimal.</p>`;
    } else if (IMP.origen === "myinvestor") {
      paso = `<ol class="pasos">
          <li>Entra en MyInvestor desde el ordenador y abre <b>cada uno de tus fondos</b>.</li>
          <li>Pulsa <b>«Plusvalías y minusvalías»</b> y descarga el <b>CSV</b>. No le cambies el nombre: lleva el ISIN del fondo.</li>
          <li>Arrastra aquí todos los archivos a la vez.</li></ol>
        ${zona(".csv", true, "Arrastra aquí los CSV de MyInvestor")}
        <p class="ayuda">Cada importación sustituye lo que importaste antes de ese mismo fondo: repítela cada mes sin miedo a duplicar.
          MyInvestor no permite descargar las órdenes de ETF o acciones: haz capturas y usa la opción «Con ayuda de una IA».</p>`;
    } else if (IMP.origen === "plantilla") {
      paso = `<ol class="pasos">
          <li>Descarga la plantilla: <a class="btn" href="api/plantilla.xlsx" download>Excel</a>
            <a class="btn" href="api/plantilla.csv" download>CSV</a></li>
          <li>Rellena una fila por operación. En la hoja «Ejemplo» tienes cinco filas de muestra.</li>
          <li>Guárdala y arrástrala aquí.</li></ol>
        ${zona(".xlsx,.csv,.txt", false, "Arrastra aquí tu plantilla")}`;
    } else {
      paso = `<ol class="pasos">
          <li><b>Copia el prompt</b>: <button class="btn" data-acc="imCopiar" id="imCopiarBtn">Copiar prompt</button>
            <details class="verPrompt"><summary>Ver el prompt</summary><pre id="imPrompt">${esc(IMP.prompt || "Cargando…")}</pre></details></li>
          <li>Abre ChatGPT, Gemini o la IA que uses. Pega el prompt y, debajo, tu extracto, o adjunta el PDF o
            <b>capturas de pantalla</b> de tus órdenes (así se importan, por ejemplo, las compras de ETF o acciones de MyInvestor).
            <span class="alerta">Antes, borra (o tapa en las capturas) tu nombre, DNI, IBAN, números de cuenta y cualquier dato personal.</span></li>
          <li>Copia su respuesta y pégala aquí:</li></ol>
        <textarea id="imTexto" class="imTexto" rows="8" spellcheck="false"
          placeholder="fecha;identificador;nombre;tipo_producto;tipo_movimiento;unidades;importe;moneda;comision;nota"></textarea>`;
    }
    return `${exito}<section class="tarjeta"><header><h2>Importar datos</h2>
        <span class="subt">Trae tus movimientos de golpe. Antes de guardar nada verás una vista previa.</span></header>
      <div class="imOps">
        ${op("portfolio", "Portfolio Performance", "El CSV «Todas las transacciones»")}
        ${op("myinvestor", "MyInvestor", "El CSV de cada fondo")}
        ${op("plantilla", "Plantilla", "Excel o CSV, para cualquier banco")}
        ${op("ia", "Con ayuda de una IA", "Convierte el extracto de tu banco")}
      </div>
      <div class="imPaso">${paso}
        <div class="imErr" id="imFallo" hidden></div>
        <div class="imAcc"><span class="sp"></span>
          <button class="btn prim" data-acc="imRevisar" id="imRevisarBtn">Revisar antes de importar</button></div>
      </div></section>`;
  }

  function conectaImportar() {
    const inp = $("#imArchivos"), z = $("#imZona");
    if (inp) {
      const muestra = () => {
        IMP.archivos = [...inp.files];
        $("#imNombres").textContent = IMP.archivos.map(f => f.name).join(" · ");
        z.classList.toggle("lleno", IMP.archivos.length > 0);
      };
      inp.onchange = muestra;
      z.ondragover = e => { e.preventDefault(); z.classList.add("encima"); };
      z.ondragleave = () => z.classList.remove("encima");
      z.ondrop = e => {
        e.preventDefault();
        z.classList.remove("encima");
        inp.files = e.dataTransfer.files;
        muestra();
      };
    }
    if (IMP.origen === "ia" && !IMP.prompt) {
      api("GET", "api/prompt").then(j => { IMP.prompt = j.texto; const pre = $("#imPrompt"); if (pre) pre.textContent = j.texto; });
    }
  }

  async function imRevisar() {
    const fd = new FormData();
    fd.append("origen", IMP.origen);
    const inp = $("#imArchivos");
    if (inp) [...inp.files].forEach(f => fd.append("archivos", f));
    const txt = $("#imTexto");
    if (txt) fd.append("texto", txt.value);
    const b = $("#imRevisarBtn"), fallo = $("#imFallo");
    fallo.hidden = true;
    b.disabled = true;
    b.textContent = "Revisando y buscando precios…";
    try {
      const r = await fetch("api/importar/previsualizar", { method: "POST", body: fd });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || !j.ok) throw new Error((j.errores || ["Algo ha fallado al leerlo."]).join("\n"));
      IMP.informe = j.informe;
      IMP.token = j.token;
      IMP.hecho = null;
      pinta();
    } catch (x) {
      fallo.textContent = x.message;
      fallo.hidden = false;
      b.disabled = false;
      b.textContent = "Revisar antes de importar";
    }
  }

  /** Opciones del desplegable de tipo de una cuenta: los tipos de cuenta que ya
      usa la app (banco, bróker…) y los de producto (ETF, fondo, pensión…), porque
      aquí se decide justo si la cuenta es una cuenta o un producto. */
  function opcionesTipoCuenta(sel) {
    const deCuenta = E.tiposCuenta || {}, deProducto = E.tipos || {};
    const claves = [];
    Object.keys(deCuenta).forEach(k => { if (!(k in deProducto)) claves.push(k); });
    Object.keys(deProducto).forEach(k => claves.push(k));
    if (sel && !claves.includes(sel)) claves.unshift(sel);
    return claves.map(k => `<option value="${esc(k)}"${k === sel ? " selected" : ""}>${
      esc(deProducto[k] || deCuenta[k] || k)}</option>`).join("");
  }

  /** Una fila de la tabla de cuentas detectadas, con su tipo editable. */
  function filaCuentaDetectada(c, i) {
    return `<tr><td style="text-align:left"><b>${esc(c.datos.nombre)}</b>${
      c.existente ? ' <span class="subt">(ya existe)</span>' : ""}</td>` +
      `<td><select data-cuentatipo="${i}" data-tipo-orig="${esc(c.datos.tipo || "")}" style="width:170px">${
        opcionesTipoCuenta(c.datos.tipo)}</select></td>` +
      `<td>${esc(c.datos.moneda || "EUR")}</td><td>${esc(c.datos.entidad || "—")}</td></tr>`;
  }

  /** «Cuentas detectadas»: si alguna no es una cuenta sino un plan, un fondo…,
      aquí se cambia su tipo antes de importar. */
  function bloqueCuentas(inf) {
    const lista = inf.cuentasNuevas || [];
    if (!lista.length) return "";
    return `<div class="imNuevos"><div class="secc">Cuentas detectadas: cambia el tipo si alguna no es una cuenta</div>
      <div class="tablaEnv"><table class="dt"><thead><tr><th style="text-align:left">Cuenta</th>
      <th style="text-align:left">Tipo</th><th>Moneda</th><th>Entidad</th></tr></thead>
      <tbody>${lista.map(filaCuentaDetectada).join("")}</tbody></table></div></div>`;
  }

  function vistaPrevia() {
    const inf = IMP.informe, t = inf.totales;
    const n = inf.añadidos + inf.saldos;
    const cifra = (et, v, extra = "") => `<div class="cifra"><span>${et}</span><b>${v}</b>${extra ? `<small>${extra}</small>` : ""}</div>`;
    const errores = inf.errores.length ? `<div class="imErr"><b>${inf.errores.length} ${inf.errores.length === 1 ? "fila tiene" : "filas tienen"} problemas y no se importará${inf.errores.length === 1 ? "" : "n"}:</b>
      <ul>${inf.errores.map(e => `<li><span class="fila">${typeof e.fila === "number" ? "Fila " + e.fila : esc(e.fila)}</span>${esc(e.mensaje)}</li>`).join("")}</ul></div>` : "";
    const avisos = inf.avisos.map(a => `<div class="av"><span>⚠</span><span>${esc(a)}</span></div>`).join("");
    const nuevos = inf.productosNuevos.length ? `<div class="imNuevos"><div class="secc">Productos nuevos que se crearán</div>
      ${inf.productosNuevos.map(p => `<div class="imProd"><b>${esc(p.nombre)}</b>
        <span class="meta"><span>${esc(E.tipos[p.tipo] || p.tipo)}</span><span>${esc(p.codigo || "valor a mano")}</span>
        <span>${esc(E.fuentes[p.fuente])}</span>${p.precio ? `<span>${num(p.precio)} ${esc(p.monedaPrecio)} · ${fecha(p.fechaPrecio)}</span>` : ""}</span></div>`).join("")}</div>` : "";
    const ESTADO = { nuevo: "Nuevo", repetido: "Ya estaba", error: "Con error" };
    const filas = inf.filas.map(f => `<tr class="est-${f.estado}"><td>${fecha(f.fecha)}</td>
      <td style="text-align:left">${esc(f.productoNombre)}</td><td style="text-align:left">${esc(E.tiposMov[f.tipo] || "Saldo")}</td>
      <td>${f.unidades ? num(f.unidades) : "—"}</td><td>${eur(f.importe)}</td>
      <td style="text-align:left">${f.marcas.map(m => `<span class="etqImp">${esc(m)}</span>`).join("")}</td>
      <td><span class="estado">${ESTADO[f.estado]}</span></td></tr>`).join("");
    return `<section class="tarjeta"><header><h2>Vista previa</h2>
        <span class="subt">Todavía no se ha guardado nada.</span></header>
      <div class="cifras">
        ${cifra("Movimientos nuevos", inf.añadidos, t.numCompras ? `${t.numCompras} compras` : "")}
        ${cifra("Invertido en compras", eur(t.compras))}
        ${cifra("Ventas y dividendos", eur(t.ventas + t.dividendos))}
        ${inf.saldos ? cifra("Saldos anotados", inf.saldos) : ""}
        ${inf.repetidos ? cifra("Ya estaban", inf.repetidos, "se omiten") : ""}
        ${inf.sustituidos ? cifra("Sustituyen a", inf.sustituidos, "importados antes") : ""}
      </div>
      <div class="comprueba"><b>Compara estas cifras con tu banco antes de confirmar.</b>
        ${IMP.origen === "ia" ? "Una IA puede equivocarse al copiar números o saltarse alguna fila: revisa sobre todo el total invertido." : ""}</div>
      ${avisos}${errores}${bloqueCuentas(inf)}${nuevos}
      ${filas ? `<div class="tablaEnv alto" style="margin-top:16px"><table class="dt"><thead><tr><th>Fecha</th>
        <th style="text-align:left">Producto</th><th style="text-align:left">Tipo</th><th>Unidades</th><th>Importe</th>
        <th style="text-align:left"></th><th>Estado</th></tr></thead><tbody>${filas}</tbody></table></div>` : ""}
      <div class="imAcc"><button class="btn" data-acc="imCancelar">Cancelar</button><span class="sp"></span>
        <button class="btn prim" data-acc="imConfirmar" id="imConfirmarBtn"${n ? "" : " disabled"}>
          ${n ? `Importar ${n} ${n === 1 ? "dato" : "datos"}` : "No hay nada nuevo que importar"}</button></div></section>`;
  }

  async function imConfirmar() {
    const b = $("#imConfirmarBtn");
    b.disabled = true;
    b.textContent = "Importando…";
    // Solo se envían las cuentas cuyo tipo haya cambiado el usuario.
    const cuentas = [];
    document.querySelectorAll("[data-cuentatipo]").forEach(sel => {
      if (sel.value && sel.value !== sel.dataset.tipoOrig) {
        cuentas.push({ idx: Number(sel.dataset.cuentatipo), tipo: sel.value });
      }
    });
    try {
      const j = await api("POST", "api/importar/confirmar", { token: IMP.token, cuentas });
      E.cfg = j.cartera;
      window.EDITOR_SUCIO = true;
      const i = j.informe;
      const pl = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;
      IMP.hecho = "Importado: " + [i.añadidos && pl(i.añadidos, "movimiento", "movimientos"),
        i.saldos && pl(i.saldos, "saldo", "saldos")].filter(Boolean).join(" y ") +
        (i.repetidos ? `. ${pl(i.repetidos, "ya estaba y se ha omitido", "ya estaban y se han omitido")}` : "") + ".";
      IMP.informe = null;
      IMP.token = null;
      pinta();
      avisa(j.avisos);
    } catch (x) {
      alert(x.message);
      b.disabled = false;
    }
  }

  /* ---------------------------------------------- copias y web */
  const COP = { lista: null };

  function vistaCopias() {
    if (COP.lista === null) {
      api("GET", "api/copias").then(j => { COP.lista = j.copias; if (E.vista === "copias") pinta(); });
    }
    const propio = E.modo === "propio";
    const filas = (COP.lista || []).map(c => `<tr><td>${fecha(c.fecha.slice(0, 10))} <small>${c.fecha.slice(11, 16)}</small></td>
      <td style="text-align:left">${esc(c.motivo)}</td><td>${c.productos}</td><td>${c.movimientos}</td>
      <td class="acc"><button data-acc="recuperarCopia" data-id="${esc(c.archivo)}">Recuperar</button></td></tr>`).join("");
    return `<section class="tarjeta"><header><h2>Copia de seguridad</h2>
        <span class="subt">Un archivo con toda tu cartera, para guardarlo donde quieras o pasarlo a otro ordenador.</span></header>
      <div class="dosCol">
        <div class="bloque"><b>Guardar una copia</b>
          <p class="ayuda">Descarga un archivo <code>.json</code> con todos tus productos, movimientos y saldos.
            Guárdalo en tu nube o en un USB de vez en cuando.</p>
          ${propio ? `<input type="password" id="copClave" placeholder="Frase de paso (opcional)" autocomplete="new-password"
              title="Si pones frase de paso, el archivo se guarda cifrado: sin ella no se puede leer.">
            <p class="ayuda">Con frase de paso el archivo sale <b>cifrado</b> y sin ella no se puede abrir:
              apúntala en tu gestor de contraseñas. Déjala vacía para una copia normal.</p>
            <button class="btn prim" data-acc="descargarCopia">Descargar copia</button>`
            : '<span class="subt">Disponible cuando empieces tu propia cartera.</span>'}</div>
        <div class="bloque"><b>Recuperar desde un archivo</b>
          <p class="ayuda">Sube una copia que descargaste antes. Sustituye la cartera actual (que se guarda antes, por si acaso).</p>
          ${zona(".json", false, "Arrastra aquí tu copia")}
          <input type="password" id="copClaveSubir" placeholder="Frase de paso (si la copia está cifrada)" autocomplete="current-password">
          <div class="imErr" id="copFallo" hidden></div>
          <div class="imAcc"><span class="sp"></span><button class="btn prim" data-acc="subirCopia" id="copSubirBtn">Recuperar esta copia</button></div></div>
      </div></section>

      <section class="tarjeta"><header><h2>Copias automáticas</h2>
        <span class="subt">Antes de cada cambio se guarda una copia (las últimas 20). Si te equivocas, vuelve a una anterior.</span></header>
      ${COP.lista === null ? '<p class="cargando">Cargando…</p>' : filas
        ? `<div class="tablaEnv alto"><table class="dt"><thead><tr><th>Fecha</th><th style="text-align:left">Motivo</th>
          <th>Productos</th><th>Movimientos</th><th></th></tr></thead><tbody>${filas}</tbody></table></div>`
        : '<p class="subt">Todavía no hay copias: se crean solas en cuanto cambias algo.</p>'}</section>

      <section class="tarjeta"><header><h2>Publicar como web</h2>
        <span class="subt">Tu panel en un solo archivo, de solo lectura, para enseñarlo o subirlo a internet.</span></header>
      <label class="interruptor"><input type="checkbox" id="webOcultar"><span class="pista"></span>
        <span><b>Ocultar importes</b><small>Solo se ven porcentajes y la forma de las gráficas. Las cantidades reales no
          van dentro del archivo, ni siquiera escondidas.</small></span></label>
      <ol class="pasos" style="margin-top:18px">
        <li><button class="btn prim" data-acc="exportarWeb">Descargar la web</button>
          Puedes abrirla con doble clic o mandarla por correo.</li>
        <li>Para tener un enlace: crea una carpeta, mete dentro el archivo, cámbiale el nombre a <code>index.html</code>
          y arrastra la carpeta a <a href="https://app.netlify.com/drop" target="_blank" rel="noopener">app.netlify.com/drop</a>.
          En unos segundos te da una dirección para compartir.</li>
      </ol>
      <p class="ayuda">La web lleva la fecha de hoy: cuando actualices tus datos, vuelve a descargarla y súbela otra vez.</p></section>`;
  }

  async function descargarCopia() {
    const clave = $("#copClave") ? $("#copClave").value : "";
    const r = await fetch("api/copia/descargar", { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ clave }) });
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      alert((j.errores || ["No he podido generar la copia."]).join("\n"));
      return;
    }
    const cd = r.headers.get("Content-Disposition") || "";
    const nombre = (/filename="([^"]+)"/.exec(cd) || [])[1] || "copia_patrimonio.json";
    const enlace = document.createElement("a");
    enlace.href = URL.createObjectURL(await r.blob());
    enlace.download = nombre;
    document.body.appendChild(enlace);
    enlace.click();
    enlace.remove();
    setTimeout(() => URL.revokeObjectURL(enlace.href), 4000);
  }

  async function subirCopia() {
    const inp = $("#imArchivos"), fallo = $("#copFallo");
    fallo.hidden = true;
    if (!inp.files.length) { fallo.textContent = "Elige primero el archivo de la copia."; fallo.hidden = false; return; }
    if (E.modo === "propio" && !confirm("Esto sustituye tu cartera actual por la de la copia. Tu cartera actual se guarda antes en «Copias automáticas». ¿Seguir?")) return;
    const fd = new FormData();
    fd.append("archivo", inp.files[0]);
    fd.append("clave", $("#copClaveSubir") ? $("#copClaveSubir").value : "");
    const r = await fetch("api/copia/subir", { method: "POST", body: fd });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || !j.ok) { fallo.textContent = (j.errores || ["No he podido leer la copia."]).join("\n"); fallo.hidden = false; return; }
    recuerda.guarda("patrimonio.tab", "datos");
    recuerda.guarda("patrimonio.editor", "productos");
    location.reload();
  }

  async function recuperarCopia(archivo) {
    const c = COP.lista.find(x => x.archivo === archivo);
    if (!confirm(`¿Volver a la copia del ${fecha(c.fecha.slice(0, 10))} a las ${c.fecha.slice(11, 16)} (${c.productos} productos, ${c.movimientos} movimientos)?\n\nTu cartera actual se guarda antes, así que puedes deshacerlo.`)) return;
    try {
      await api("POST", "api/copia/recuperar", { archivo });
      recuerda.guarda("patrimonio.tab", "datos");
      location.reload();
    } catch (x) { alert(x.message); }
  }

  /* ---------------------------------------------- aviso de versión nueva */
  api("GET", "api/version").then(v => {
    const pie = $("#ayudaVersion");
    if (pie) pie.innerHTML = `Versión ${esc(v.actual)}. ¿Otra duda o un fallo? Cuéntalo en la
      <a href="${esc(v.repo)}" target="_blank" rel="noopener">página del proyecto en GitHub</a>.`;
    if (!v.hayNueva) return;
    $("#bannerVersionTexto").innerHTML = `<b>Hay una versión nueva (${esc(v.ultima)}).</b> Descárgala en
      <a href="${esc(v.repo)}" target="_blank" rel="noopener">GitHub</a> y copia tu carpeta <code>mis_datos</code> a la
      nueva: así no pierdes nada. Los pasos están en la pestaña Ayuda.`;
    $("#bannerVersion").hidden = false;
  }).catch(() => { /* sin internet: no pasa nada */ });

  /* ---------------------------------------------- acciones */
  const ACC = {
    empezar,
    reiniciar,
    verPanel() { recuerda.guarda("patrimonio.tab", "patrimonio"); location.reload(); },
    nuevoProducto: soloPropio(() => formProducto(null)),
    editarProducto: soloPropio(id => formProducto(prod(id))),
    borrarProducto: soloPropio(borrarProducto),
    nuevoMov: soloPropio(() => formMovimiento(null)),
    nuevoMovCuenta: soloPropio(id => formMovimiento(null, null, false, null, { cuenta: id, vista: "cuentas" })),
    nuevoValorCuenta: soloPropio(id => formValor(null, id, false, "cuentas")),
    verCuenta(id) { E.cuenta = id; E.vista = "cuentas"; recuerda.guarda("patrimonio.editor", "cuentas"); pinta(); },
    volverCuentas() { E.cuenta = null; pinta(); },
    movsCuenta(id) { E.filtroCuenta = id; E.filtro = "todos"; E.vista = "movimientos";
                     recuerda.guarda("patrimonio.editor", "movimientos"); pinta(); },
    nuevaCuenta: soloPropio(() => formCuenta(null)),
    editarCuenta: soloPropio(id => formCuenta(cuentaDe(id))),
    cierraAviso,
    cierraTodosAvisos: limpiaAvisos,
    editarMov: soloPropio(id => formMovimiento(E.cfg.movimientos.find(m => m.id === id))),
    replicarMov: soloPropio(replicarMov),
    borrarMov: soloPropio(borrarMov),
    nuevoValor: soloPropio(id => formValor(null, id)),
    verAnotaciones: soloPropio(id => abreAnotaciones(prod(id))),
    editarValor: soloPropio(id => formValor(E.cfg.valoraciones.find(v => v.id === id))),
    replicarValor: soloPropio(replicarValor),
    borrarValor: soloPropio(borrarValor),
    todosValores: soloPropio(todosValores),
    cargarPlantilla: soloPropio(() => { const i = $("#plantArchivo"); if (i) i.click(); }),
    guardarUrl: soloPropio(guardarUrl),
    probarFuente: soloPropio(probarFuente),
    fuenteDet: alternaFuente,
    actPrecio: soloPropio(actPrecio),
    repartirColores: soloPropio(async () => {
      try {
        const j = await api("POST", "api/repartir-colores");
        E.cfg = j.cartera;
        window.EDITOR_SUCIO = true;
        pinta();
      } catch (x) { alert(x.message); }
    }),
    imOrigen(id) { IMP.origen = id; IMP.hecho = null; pinta(); },
    imRevisar: soloPropio(imRevisar),
    imCancelar() { IMP.informe = null; IMP.token = null; pinta(); },
    imConfirmar,
    descargarCopia,
    subirCopia,
    recuperarCopia,
    exportarWeb() { location.href = "api/exportar-web?ocultar=" + ($("#webOcultar").checked ? "1" : "0"); },
    verPanelDatos() { recuerda.guarda("patrimonio.tab", "patrimonio"); location.reload(); },
    async imCopiar() {
      const txt = IMP.prompt || (await api("GET", "api/prompt")).texto;
      IMP.prompt = txt;
      try { await navigator.clipboard.writeText(txt); } catch (e) {
        const ta = document.createElement("textarea"); ta.value = txt; document.body.appendChild(ta); ta.select();
        document.execCommand("copy"); ta.remove();
      }
      const b = $("#imCopiarBtn");
      if (b) { b.textContent = "✓ Copiado"; setTimeout(() => { b.textContent = "Copiar prompt"; }, 2000); }
    },
  };
  document.addEventListener("click", e => {
    const b = e.target.closest("[data-acc]");
    if (b && ACC[b.dataset.acc]) ACC[b.dataset.acc](b.dataset.id);
  });
  const btnEmpezar = $("#btnEmpezar");
  if (btnEmpezar) btnEmpezar.onclick = empezar;

  /* ---------------------------------------------- el canal del autor */
  // Una tarjeta pequeña, la primera vez que ves tu propio panel con datos. Si pulsas
  // «Ahora no», vuelve como mucho una vez más al cabo de un mes; luego, nunca.
  (function canal() {
    const K = window.CANAL;
    if (!K) return;
    document.querySelectorAll(".autorCanal").forEach(el => { el.textContent = K.autor; });
    document.querySelectorAll(".enlaceCanal").forEach(el => { el.href = K.canal; });
    document.querySelectorAll(".enlaceSuscribir").forEach(el => { el.href = K.suscribir; });
    const tut = $("#ayudaTutorial");
    if (tut) tut.href = K.tutorial || K.canal + "/videos";

    if (!D || D.modo !== "propio" || !(D.productos || []).length) return;
    let est = {};
    try { est = JSON.parse(recuerda.lee("patrimonio.canal") || "{}"); } catch (e) { est = {}; }
    const MES = 30 * 24 * 3600 * 1000;
    if (est.hecho || (est.veces || 0) >= 2 || (est.veces === 1 && Date.now() - (est.ultima || 0) < MES)) return;
    const guarda = cambios => recuerda.guarda("patrimonio.canal", JSON.stringify({ ...est, ...cambios }));

    setTimeout(() => {
      if (document.body.classList.contains("video") || $("#modal").open) return;
      const t = document.createElement("div");
      t.className = "tarjetaCanal";
      t.setAttribute("role", "dialog");
      t.innerHTML = `<button class="x" aria-label="Cerrar">×</button>
        <b>¿Te está siendo útil?</b>
        <p>Esta herramienta es gratis. La hago para mi canal de YouTube, donde cuento cómo invierto:
          suscribirte es la mejor forma de apoyarla. — ${esc(K.autor)}</p>
        <div class="botones"><a class="btn prim" href="${esc(K.suscribir)}" target="_blank" rel="noopener">▶ Suscribirme</a>
          <button class="ahoraNo">Ahora no</button></div>`;
      const cierra = () => { t.remove(); guarda({ veces: (est.veces || 0) + 1, ultima: Date.now() }); };
      t.querySelector(".x").onclick = cierra;
      t.querySelector(".ahoraNo").onclick = cierra;
      t.querySelector("a").onclick = () => { guarda({ hecho: true }); setTimeout(() => t.remove(), 300); };
      document.body.appendChild(t);
    }, 6000);
  })();

  window.Editor = {
    mostrar: pinta,
    /** Abre la ficha de una cuenta en «Mis datos → Cuentas». Lo usa cada fila de la
        tabla Cuentas del panel, para que una cuenta como REVOLUT_EUR sea
        localizable: antes no había ninguna parte de la app donde verla. */
    verCuenta(id) { E.cuenta = id; E.vista = "cuentas"; recuerda.guarda("patrimonio.editor", "cuentas"); pinta(); },
    /** Abre el formulario de movimiento con este producto ya elegido. Lo usa el
        botón de la ficha del producto (pestaña Productos): al guardar recarga el
        panel, porque las cifras de esa pestaña ya no son las mismas. */
    movimiento: soloPropio(id => formMovimiento(null, id, false, () => location.reload())),
  };
  carga().then(pinta).catch(x => {
    const cont = $("#editor");
    if (cont) cont.innerHTML = `<div class="av"><span>⚠</span><span>${esc(x.message)}</span></div>`;
  });
})();
