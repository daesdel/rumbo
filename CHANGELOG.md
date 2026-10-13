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
