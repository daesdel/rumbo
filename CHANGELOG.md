# Changelog

Todas las versiones de Rumbo, con su fecha y un resumen de lo que cambia.

## Cómo se versiona

- Formato **`V<mayor>.<menor>`**, con **dos dígitos** en la menor: `V1.00`, `V1.01`, …, `V1.99`, `V2.00`.
- **Cambio grande** → sube la mayor (`V1.xx` → `V2.00`).
- **Cambio pequeño** → sube la menor (`V1.00` → `V1.01`).
- El número vive **solo** en [`app/VERSION`](app/VERSION) (una línea, p. ej. `1.00`). El backend lo
  expone ya formateado como `V1.00` y el navegador solo lo pinta: no hay que
  cambiarlo en dos sitios.
- Para publicar una versión: editar `app/VERSION`, añadir aquí la entrada y hacer
  commit + push + despliegue.

---

## V1.04 — 22 de octubre de 2026

**Cargar movimientos desde un CSV para UN producto concreto.** Para cuando el bróker
te da un extracto de un fondo suelto y no quieres pasar por el importador global de
Portfolio Performance.

- **Botón «Importar movimientos (CSV)»** en la ficha del producto (pestaña **Productos**),
  junto a «+ Anotar movimiento». Abre un modal con la estética de los demás.
- **Formato**: `fecha,tipo,unidades,importe,comision,impuestos,nota`, con la fecha en
  AAAA-MM-DD, los números con **punto o coma** decimal, y **cabecera obligatoria**.
  Los tipos son los de siempre y se aceptan con tildes o con su etiqueta
  («Interés», «Dividendo o cupón»).
- **Botón «Descargar plantilla CSV»** con la cabecera y dos filas de ejemplo.
- **Previsualización antes de tocar nada**: «X movimientos válidos · Y con error», la
  tabla de los que entrarán y, por cada fila mala, su número de línea y el motivo
  (fecha inválida, tipo desconocido, importe ilegible…). El ensayo se hace sobre una
  **copia** de la cartera, así que las reglas son exactamente las de la importación real.
- **Dos modos** (radios):
  - **Añadir a los movimientos existentes** (por defecto).
  - **Sustituir los movimientos existentes**, con confirmación que dice cuántos va a
    borrar: «Esto borrará N movimientos del producto «X» y los reemplazará por los del
    CSV. ¿Continuar?».
- **Solo se toca ESE producto**: los movimientos de los demás no se leen ni se escriben.
  El aislamiento está verificado con un producto testigo.
- El tratamiento del dinero es **el mismo que al anotar a mano**: compra → resta de su
  cuenta de efectivo, dividendo → suma, etc. (se reutiliza `guarda_movimiento` +
  `refresca_efectivo`, sin tocar el importador de PP). Al sustituir, los días que se
  quedan sin movimientos pierden su saldo automático, y los que cambian se rehacen.
- **Todo o nada**: la operación va dentro de `cambia()`, que **no guarda si algo falla**;
  y si en modo «Sustituir» ninguna fila es válida, se deja la cartera como estaba.
  `almacen.guarda` escribe atómico y con copia de seguridad.
- Si el producto **no tiene cuenta de efectivo** o la que apunta ya no existe, se avisa
  y **no se crea nada automáticamente**.

### Detalle

- Nuevo `app/movcsv.py`: solo lee y valida texto (no conoce la app ni toca la cartera).
  La aplicación vive en `servidor._aplica_movs_csv()`, junto a `refresca_efectivo`.
- Rutas nuevas: `GET /api/movimientos/plantilla.csv`,
  `POST /api/productos/<id>/movimientos/csv/previsualizar` y `.../importar`.
- La previsualización contesta **200 con `ok:false`** cuando el CSV tiene problemas:
  es un informe, no una orden, así el navegador no lo apunta como error de red.

### Nota sobre los «errores» de consola

Al cargar la pestaña Patrimonio, la consola del navegador muestra **dos errores CORS de
`api.coingecko.com`** (el precio «en vivo» del Bitcoin). Son **preexistentes** a esta
versión: están en `app/web/app.js` desde antes y **no** los introduce esta función. En la
pestaña Productos, y usando la importación de CSV, la consola queda **limpia**.

---

## V1.03 — 15 de octubre de 2026

**Buscador en la pestaña superior «Productos»** (la de los **chips de colores**, junto a
Patrimonio / El mes / Periodo). En V1.02 el buscador se añadió a la tabla de
**Mis datos → Productos**; esta es la otra vista, que aún no lo tenía.

- **Campo encima de la fila de chips**, en el flujo normal (`position:static`): empuja
  los chips hacia abajo, no flota.
- **Filtra en vivo** al escribir, sin repintar: solo oculta chips, así no se pierde el
  foco ni la selección.
- Busca por **nombre, nombre corto, código/ticker, ISIN y entidad**. En local:
  «Trade Republic» → 5 de 50 · «500.PA» → 1 de 50 · «amundi» → 4 de 50.
- **Sin mayúsculas ni tildes** y espacios colapsados.
- **Contador «X de Y productos»** solo con filtro activo.
- **Limpiar** con la **×** o con **Escape**. **Reset al salir de la pestaña.**
- **La selección se mantiene al filtrar**: si el chip elegido sigue visible, sigue
  marcado; si el filtro lo oculta, **sigue seleccionado internamente** (su ficha se
  mantiene abajo) y **no se auto-selecciona** el único resultado visible.

> El contador cuenta los **chips** visibles («de 50»), no los productos de
> `cartera.json` (60): los chips salen de `TODOS()` = `D.productos` + `otrosActivos` +
> `pasivos`, y el panel no incluye los productos de efectivo de cada cuenta —esos se
> ven como *cuentas*—. Es el comportamiento previo del panel.

### Arreglos internos

- **Alineado el `norm` de `editor.js` con el de `app.js`**: eran la misma función escrita
  de dos formas, y la de `editor.js` empezaba por el arranque del escapador. No fallaba
  hoy (en `editor.js` no hay ningún `&amp;`), pero era una mina latente para
  `test_web_escape.py`, que usa `re.S` y busca ese arranque seguido de cualquier `&amp;`
  del fichero. Ahora las dos son idénticas y ninguna dispara la guarda.

---

## V1.02 — 15 de octubre de 2026

**Buscador en la pestaña Productos**: encontrar un producto sin recorrer la lista
entera (60 productos hoy).

- **Campo de búsqueda encima de la tabla**, en el flujo normal: empuja las filas hacia
  abajo, no flota por encima.
- **Filtra en vivo mientras se escribe**, sin pulsar Enter. No vuelve a pintar la tabla
  (solo oculta filas), así no se pierde el foco ni el cursor.
- Busca **a la vez** por **nombre, nombre corto, código/ticker, ISIN (identificador) y
  entidad (banco o bróker)**, sin selector de campo. Buscar «Trade Republic» encuentra
  sus 5 productos; «MyInvestor», sus 12.
- **Sin distinguir mayúsculas ni tildes** («AMUNDI» = «amundi»; «dolar» encuentra
  «DÓLAR»), y con los espacios de más colapsados.
- **Contador «X de Y productos»** cuando hay filtro activo; sin filtro no se muestra nada.
- **Limpiar** con la **×** del campo o con **Escape**.
- **Reset al salir de Productos**: al volver, la lista completa.
- **Sin auto-selección**: si el filtro deja un solo producto, no se selecciona solo.
- **Etiqueta de entidad** visible bajo cada nombre (junto al ISIN, cuando lo tiene).
- La búsqueda es **ortogonal al filtro de propietario** (David/Gina/Compartido): ese es
  un filtro del panel de Patrimonio y sigue igual.

### Detalle interno

- `buscaDe(p)` construye el texto indexado con `p.nombre` **y** `p.corto` por separado:
  `nombre(p)` devuelve el corto cuando existe, así que el nombre largo —donde suele estar
  la tilde— se perdía y la búsqueda sin tildes no lo encontraba.
- `tr[hidden]{display:none}`: en las filas de una tabla, el atributo `hidden` no basta
  porque `display:table-row` lo pisa.

---

## V1.01 — 14 de octubre de 2026

**Fase 3**: vincular un producto a Yahoo/Morningstar **desde la propia vista previa**
de la importación de Portfolio Performance, antes de confirmar.

### Importación PP — vincular precios en la vista previa

- Cada producto de «Productos nuevos que se crean» tiene un botón **«Buscar precio»**.
- Al pulsarlo se abre **el mismo buscador** que usa el modal de producto (mismo campo
  «IE00BYX5NX33, AAPL, bitcoin, oro…», mismo botón «Buscar», mismas tarjetas de
  resultado y mismos mensajes).
- **El panel flota** sobre las filas de abajo, así no descuadra la tabla de la vista previa.
- Al elegir un resultado, ese producto queda **vinculado** en la vista previa (la fila
  muestra `✓ Yahoo Finance · 500.PA`), con un botón **«Quitar vínculo»** para deshacerlo.
- Al confirmar, los productos vinculados **nacen ya con ese código y esa fuente**, y se
  les **descarga el precio** con la lógica que ya existía (`recalcula(descargar="faltan")`).
- Se toma el **nombre canónico** del resultado, y el nombre original del CSV **no se
  pierde**: queda en la descripción (`papel`) del producto, que es editable.
- El nombre canónico pasa por el **deduplicado por familia**, así que si en la cartera ya
  hay un producto con ese nombre se reutiliza en vez de crear un duplicado.
- Los productos que no se vinculan **conservan el comportamiento anterior**: el código del
  CSV si lo trae, o el del catálogo (el plan Naranja 2040 sigue con `0P00008571.F`).
- Los vínculos se envían tanto al **recálculo de la vista previa** (para que los totales
  reflejen que ese producto ya cotiza) como a la **confirmación**.
- Los vínculos, los tipos de cuenta y las exclusiones llegan como parámetros: `aplicar()`
  **sigue sin modificar el plan**, así que recalcular la vista previa da siempre el mismo
  resultado.

### Refactor interno

- El buscador, que estaba incrustado en `formProducto()`, se extrae a **`montaBuscador()`**,
  reutilizable desde el modal y desde la vista previa. Dentro del contenedor se busca por
  **clases** (`.bq`, `.bBuscar`, `.bRes`) en vez de por ids: el modal y la vista previa
  pueden estar a la vez en el DOM y los ids chocarían. **El modal se comporta igual**
  (mismos mensajes, mismas tarjetas, mismo relleno del formulario y misma ficha de
  Morningstar).

---

## V1.00 — 13 de octubre de 2026

Primera versión con control de versiones. Recoge todo lo construido hasta aquí.

### Base del proyecto

- Panel de patrimonio (Flask + JavaScript sin frameworks) con cuentas, productos,
  movimientos, valoraciones, panel de rendimiento, editor de datos y modo demo.
- **Blindaje del servidor local**: validación de `Host` (anti DNS rebinding) y de
  `Origin`/`Referer` en las escrituras (anti CSRF).
- **Escapado HTML unificado** en el navegador: un solo `escapar` y ~20 puntos de
  riesgo corregidos (XSS).
- **Suite de tests** de Python (`pytest`), aislada de `mis_datos`.
- **Docker + despliegue** en LXC detrás de Pangolin, con volumen de datos propio.

### Cartera y cálculos

- Modelo **cuentas vs. productos**: la cuenta guarda el dinero, el producto el activo.
- INVARIANTE: cada cuenta tiene su producto de efectivo 1:1.
- **Saldos frente a movimientos**: las cuentas de efectivo y deuda se siguen por
  saldos anotados; el resto, por movimientos.
- Métricas de **rentabilidad, TIR, plusvalía latente y realizado**, dividendos,
  intereses, impuestos y comisiones.
- **Rendimiento en dólares**: comparación con el S&P 500 y el MSCI World en su divisa.

### Importación

- **Importación de MyInvestor** (plantilla y pegado de texto).
- **Importación de Portfolio Performance**: cuentas, compras, ventas, dividendos,
  intereses, impuestos, comisiones, depósitos, retiradas y transferencias.
  - Tipos de PP que antes se descartaban en silencio, incluidos los **traspasos** y
    la **entrega entrante** (escisión).
  - **Catálogo de códigos** de los ETF y acciones que sí cotizan, más el código
    **Morningstar** cuando viene en el nombre del activo.
  - **Deduplicado de cuentas y productos** al reimportar.

### Importación: Fase 1 — una cuenta del CSV que en realidad es un producto

- En la vista previa se puede **cambiar el tipo** de cada cuenta detectada.
- Si se marca como `pensión`, `fondo`, `ETF`, `acción`, `cripto`, `bono` o
  `inmueble`, esa cuenta se convierte en **producto** y la cuenta pasa a ser su
  **monedero** de efectivo.
- El **plan de pensiones** se enlaza solo con Yahoo Finance (**`0P00008571.F`**) y
  se descarga su valor liquidativo desde la primera importación.
- **Emparejado de aportaciones**: cada compra que dejaría la cuenta en negativo
  recibe el ingreso que faltaba (PP a veces apunta el depósito días después), así
  que la cuenta no queda nunca en negativo y cierra en **0 €**. Se avisa en la
  vista previa de cuántos ingresos se han añadido.
- El plan de pensiones solo acumula **compras de participaciones**; no se le cuelan
  ingresos sueltos.

### Importación: Fase 2 — excluir cuentas y productos

- **Casilla «Importar»** en cada cuenta y cada producto de la vista previa, marcada
  por defecto, con un contador («X de Y cuentas se importarán»).
- Al desmarcar, **ni la entidad ni sus movimientos se importan**. La vista previa se
  **recalcula en el servidor** para ver el impacto real en los totales.
- **Cascada**: los productos que dependen de una cuenta excluida se excluyen solos
  (y se vuelven a marcar si se recupera la cuenta).
- ⚠️ **Excluir es «no lo importes ahora», nunca «bórralo»**: al reimportar con
  entidades excluidas se **conservan** sus movimientos ya importados, en vez de
  borrarlos con el barrido de la importación.

### Versionado y créditos

- **Versión visible** en la cabecera (bajo «Rumbo») y en la pestaña Ayuda.
- `CHANGELOG.md` (este fichero) y sistema de versiones descrito arriba.
- **Limpieza de las menciones comerciales** al creador original: fuera el crédito
  del pie, la tarjeta flotante de suscripción y el botón «Suscribirme».
- En la pestaña Ayuda queda una **mención de origen**: Rumbo es una adaptación de
  la herramienta original creada por **Dani Dominguez Quant**, con enlace a su
  canal como agradecimiento (sin llamada a la acción).
- Los enlaces de GitHub apuntan ya al **repositorio propio**
  ([daesdel/rumbo](https://github.com/daesdel/rumbo)), y se mantiene el enlace al
  **proyecto original** ([danidm98/rumbo](https://github.com/danidm98/rumbo)).
