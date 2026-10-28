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

## V1.08 — 28 de octubre de 2026

**La importación de movimientos por CSV deja de ser un callejón sin salida.** Cinco cosas,
todas alrededor del mismo botón «Importar movimientos (CSV)».

### a) Se llega desde más sitios

- **Al crear un producto**: interruptor «Cargar sus movimientos desde un CSV». Al guardar,
  el producto se crea y **se abre la importación ya apuntando a él** (era el paso natural:
  el alta ya encadenaba al primer movimiento; ahora también al CSV). Si marcas el CSV y no
  has elegido cuenta, se avisa **antes** de crear nada.
- **En Mis datos → Productos**, cada fila tiene **«Importar CSV»** junto a Editar. Abre el
  **mismo modal** (no hay dos): el de la ficha del producto.

### b) El parser de fechas deja de ser rígido

Antes solo valía `AAAA-MM-DD`. Ahora:

- **ISO con hora** (`2026-10-05 00:00:00`, `2026-10-05T00:00:00`), **DD/MM/AAAA**,
  **MM/DD/AAAA**, **DD-MM-AAAA**, con barras, guiones o puntos, y año primero o al final.
- **El propio fichero delata el orden** cuando puede: una fila con el día (o el mes) por
  encima de 12 decide por todas. Solo si no lo delata se resuelve fila a fila.
- **Si queda ambiguo** (`10/05/2026`) se lee como **DD/MM** y sale un **aviso ámbar** en la
  previsualización diciendo cuántas filas y en qué líneas, sugiriendo el selector.
- El error de una fila ahora dice **qué formatos valen**, no solo que está mal.
- En modo **«Sustituir»** con una fila inválida se enseña **el motivo real de la fila** (antes
  salía el mensaje genérico del guard).

### c) Selector de formato de fecha, y el CSV de Portfolio Performance tal cual

- Desplegable **«Formato de fecha»**: `Auto (detectar)` · `DD/MM/AAAA` · `MM/DD/AAAA` ·
  `AAAA-MM-DD (ISO)`. Si eliges uno, **manda sobre la inferencia** del fichero y la
  previsualización se recalcula. Con «ISO» se rechazan las fechas a la española.
- **Se acepta el export de Portfolio Performance sin adaptarlo**: separador `;`, trece
  columnas, `Fecha`/`Tipo`/`Activo`/`Títulos`/`Comisiones`/`Impuestos`/`Valor neto de
  transacción`/`Nota`. Se **reutiliza el importador global** (`importar.leer_portfolio` y su
  tabla de **26 tipos**), sin duplicar el mapeo y **sin tocar `app/importar.py`**.
- **Filtra por producto**: de un export con varios activos entran solo las filas del
  producto abierto. Si no hay ninguna, lo dice **y enumera qué trae el fichero**.

### d) FIX: las fechas del CSV de PP ya no se adivinan

El flujo de PP **no consultaba** el selector (delegaba en `importar.lee_fecha`, que ante una
fecha no ISO **suponía día primero**). Así, un `3/12/2026` reescrito por Excel se volvía el
3 de diciembre y daba un **falso «fecha futura»**, y cambiar el selector no lo arreglaba
porque no se leía nunca.

- En un CSV de PP las fechas **tienen que ser ISO**: si alguna no lo es, esa fila se reporta
  con su motivo y **no se adivina el orden**.
- Con un CSV de PP el selector de formato aparece **deshabilitado** (con explicación) y
  cambiarlo **no re-lee** el fichero.
- El aviso de «fecha futura» **solo sale si la fecha es futura de verdad**.

### e) FIX: el selector de destino ya no esconde el producto actual

Al elegir a qué producto corresponden los movimientos de un CSV de PP, la lista **excluía el
producto abierto** — justo el caso normal, porque PP y la app suelen llamar distinto al
mismo fondo.

- El selector muestra **todos los productos**, **incluido el actual**.
- Si el producto elegido **no tiene cuenta de efectivo**, se pide en el mismo modal con un
  selector de cuentas, y **la asignación se guarda junto con los movimientos** en la misma
  operación (atómica). Sin cuenta **no se importa nada**.
- Al forzar un destino se pide **doble confirmación**: «Vas a importar los movimientos de
  «PLAN 2050 ING» en «Naranja 2040 PP». ¿Continuar?».

### Detalle

- `app/movcsv.py` sigue sin conocer la app: solo lee y valida. La aplicación de los
  movimientos sigue en `servidor._aplica_movs_csv()`.
- Rutas: las mismas de V1.04, con `formato`, `productoDestino` y `cuentaDestino` nuevos en el
  cuerpo de la petición.
- `app/importar.py` **sin tocar**: se importa y se llama, nunca se modifica.

---

## V1.06 — 23 de octubre de 2026

**Cuatro recuadros de variación del patrimonio en la vista Patrimonio, con su gráfica
vinculada.** Arriba a la derecha, al lado de la cifra grande y debajo de los filtros.

- **Cuatro ventanas**: **Última sesión** (no «24h»: un lunes serían 72 horas), **7 días**,
  **30 días** y **Mes actual** (desde el día 1; el día 1 marca 0).
- Cada recuadro enseña **variación en euros y en porcentaje**, con signo, en verde si
  sube, rojo si baja y **gris con `0,00 €`** si no cambia. El porcentaje sale `—` cuando
  la base es 0 y no se puede dividir.
- **Gráfica debajo**, con la evolución del periodo del recuadro elegido. **Activo por
  defecto: 30 días**, que es la ventana más equilibrada.
- El recuadro activo se distingue con **borde y fondo** (y `aria-pressed`).
- **Respeta los filtros**: propietario (Total / David / Gina / Compartido) y los **dos**
  selectores de moneda — el que **filtra** productos (Global / EUR / USD) y el que
  **convierte** la visualización (€ / $).
- **Sin datos suficientes** (por ejemplo una cartera de tres días con «30 días»
  seleccionado): el recuadro enseña **`—`** y la gráfica «Sin datos suficientes para este
  periodo». No se inventa un cero.
- **Responsive**: en fila en escritorio, **2×2 en móvil** (375 px); si la columna derecha
  no cabe (menos de 1180 px) el bloque baja debajo de la cifra grande.

### Detalle

- Los recuadros **no calculan patrimonio**: leen `m.serie`, la misma serie que dibuja el
  gráfico grande, que ya viene filtrada por propietario y convertida a la divisa de
  visualización **con el cambio de cada día** (`convSerie` → `fxEn(i)` desde `D.fxSerie`).
  Solo se restan dos puntos, indexando **por fecha natural** en `D.fechas`.
- **Gráfica pequeña nueva, no reutilizada**: acoplar el zoom del gráfico grande al
  recuadro habría cambiado su comportamiento. Cada uno tiene su estado (`estado.varRango`
  frente a `estado.rango`), así que tocar uno no toca el otro.
- Se dibuja con el motor del proyecto (`graficos.js`, `G.lineaConEventos`), sin
  dependencias nuevas.
- **Cero desplazamiento** de lo que ya había: el bloque va en la columna derecha del hero,
  en espacio que estaba vacío, y la gráfica se ajustó a **110 px** para no hacer crecer
  esa fila (medido: los KPIs quedan en la misma `y` con el bloque y sin él).
- **Ojo con los dos selectores de moneda**: `Global/EUR/USD` **filtra qué productos
  entran**; `€/$` **convierte la visualización**. Los recuadros obedecen a los dos.

### Por qué en dólares el signo puede cambiar (comprobado, no es un fallo)

En la ventana de 30 días del 23-sep al 23-oct-2026: la cartera ganó **+1.000,36 €
(+1,42 %)**, pero el euro cayó **−2,17 %** frente al dólar, así que en dólares el
resultado es **−636,17 $ (−0,79 %)**: `(1 + 0,0142) × (1 − 0,0217) ≈ 0,992`. La serie se
convierte **punto a punto con el cambio de su día**, no con el de hoy; si se convirtiera
con el de hoy saldría +1.120,35 $, con el mismo signo que en euros. Un movimiento
concreto (un dividendo, una compra) sí lleva el cambio de su fecha.

---

## V1.05 — 23 de octubre de 2026

**Selector de moneda al importar movimientos de un producto desde CSV.** Hasta ahora
esos importes entraban siempre como euros, así que un extracto en dólares se anotaba mal.

- **Desplegable «Moneda de los movimientos»** en el modal de importación, junto al
  selector de archivo. Trae las mismas monedas que el formulario de movimientos
  (EUR, USD, GBP, CHF, JPY, SEK, NOK, DKK, PLN, CZK, CAD, AUD).
- **Por defecto propone la moneda de la cuenta del producto** (si el producto está en una
  cuenta en dólares, USD; si es en euros, EUR), y si no, la del producto o EUR.
- Cada movimiento se guarda con **`monedaOriginal`, `importeOriginal` y `tipoCambio`**,
  igual que al anotarlo a mano o al importar de Portfolio Performance; el `importe` en
  euros se calcula **con el cambio del día del movimiento**.
- **La previsualización enseña los importes en la moneda elegida** —la columna pasa a
  «Importe (USD)» y el resumen avisa de que son dólares— y **se vuelve a calcular si
  cambias la moneda** después de subir el archivo.
- **Si no hay cambio del día, no se importa a ciegas**: esa fila se reporta con
  «No encuentro el cambio de USD a euros del …» y en «Sustituir» no se borra nada.
- Una moneda con un código que no son tres letras da un **error claro** y no entra nada.
- **Sin regresión con EUR**: con euros seleccionados los movimientos quedan exactamente
  como en V1.04 (sin campos de moneda original), y los movimientos que ya existieran no
  se tocan.
- Al **sustituir cambiando de moneda** no hay mezcla: los anteriores se borran y los
  nuevos entran en la moneda nueva. Sigue afectando **solo a ese producto**.

### Detalle

- No hay matemáticas nuevas: se reutiliza `_importe_en_eur()` (y su `_tc_eur()`), que es
  la misma ruta que usa el formulario manual y la importación de PP. La moneda viaja en
  la petición y `_aplica_movs_csv()` la pasa a cada movimiento.
- `app/movcsv.py` **no cambia**: el formato del CSV sigue sin columna de moneda; la elige
  el usuario en el modal.
- El modal pasa a usar el ancho grande (860 px): la tabla de la previsualización lleva
  seis columnas y la de «Nota» se cortaba.
- `guarda_movimiento()` redondea los campos extra a 4 decimales (comportamiento previo),
  así que `tipoCambio` se guarda como `0,8828`; el `importe` en euros se calcula con la
  precisión completa del cambio.

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
