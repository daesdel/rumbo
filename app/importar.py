# -*- coding: utf-8 -*-
"""
importar.py  ·  Trae movimientos de golpe
=========================================
Tres caminos, todos con vista previa antes de guardar nada:
  1. El CSV «Plusvalías y minusvalías» de cada fondo de MyInvestor.
  2. La plantilla genérica (Excel o CSV), rellena a mano o por una IA.
  3. El texto que devuelve la IA, pegado tal cual.

El proceso tiene dos pasos: preparar() lo lee, reconoce los productos y deja un
plan; aplicar() ejecuta ese plan sobre la cartera. La vista previa es aplicar()
sobre una copia, así que lo que ves es exactamente lo que se guardará.
"""

import copy
import csv
import datetime as dt
import io
import re
import unicodedata

from . import almacen, buscar, motor
from .motor import num_es, valor_en

COLUMNAS = ["fecha", "identificador", "nombre", "tipo_producto", "tipo_movimiento",
            "unidades", "importe", "moneda", "comision", "nota"]

# Nombres alternativos que se aceptan en la cabecera.
SINONIMOS = {
    "fecha": ["fecha", "date", "fecha operacion", "fecha valor", "fecha ejecucion"],
    "identificador": ["identificador", "isin", "ticker", "simbolo", "codigo", "id"],
    "nombre": ["nombre", "producto", "descripcion", "name"],
    "tipo_producto": ["tipo producto", "tipo_producto", "clase", "tipo de producto"],
    "tipo_movimiento": ["tipo movimiento", "tipo_movimiento", "movimiento", "operacion", "tipo"],
    "unidades": ["unidades", "participaciones", "titulos", "acciones", "cantidad", "units"],
    "importe": ["importe", "importe eur", "total", "amount", "importe total"],
    "moneda": ["moneda", "divisa", "currency"],
    "comision": ["comision", "comisiones", "fee", "gastos"],
    "nota": ["nota", "notas", "comentario", "observaciones"],
}
TIPO_MOV = {
    "compra": "compra", "suscripcion": "compra", "buy": "compra", "aportacion": "compra",
    "venta": "venta", "reembolso": "venta", "sell": "venta",
    "dividendo": "dividendo", "cupon": "dividendo", "dividend": "dividendo", "interes": "dividendo",
    "comision": "comision", "fee": "comision", "custodia": "comision",
    "saldo": "saldo", "valor": "saldo", "valoracion": "saldo",
}
TIPO_PROD = {
    "fondo": "fondo", "fondo de inversion": "fondo", "etf": "etf", "etp": "etf",
    "accion": "accion", "acciones": "accion", "cripto": "cripto", "criptomoneda": "cripto",
    "commodity": "commodity", "materia prima": "commodity", "oro": "commodity",
    "bono": "bono", "renta fija": "bono", "pension": "pension", "plan de pensiones": "pension",
    "efectivo": "efectivo", "cuenta": "efectivo", "cuenta corriente": "efectivo",
    "inmueble": "inmueble", "piso": "inmueble", "vivienda": "inmueble",
    "deuda": "deuda", "prestamo": "deuda", "hipoteca": "deuda", "otro": "otro",
}


def sin_tildes(t):
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t.replace("_", " ")).strip().lower()


def _normaliza(t):
    """Nombre para comparar: sin tildes ni signos («Tesla, Inc.» -> "tesla inc")."""
    return re.sub(r"[^a-z0-9]+", " ", sin_tildes(t)).strip()


def decodifica(crudo):
    """Bytes de un archivo de texto -> str, probando las codificaciones habituales."""
    if isinstance(crudo, str):
        return crudo
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return crudo.decode(enc)
        except UnicodeDecodeError:
            continue
    return crudo.decode("utf-8", "replace")


# ---------------------------------------------------------------- MyInvestor

CAB_MYINVESTOR = {"fecha": ["fecha fiscal", "fecha"],
                  "coste": ["inversion", "inversión", "coste"],
                  "valor": ["valor de mercado", "valor mercado", "valor"]}


def leer_csv_myinvestor(texto):
    """
    Lee el CSV "Plusvalías y minusvalías" de un fondo de MyInvestor.
    Devuelve (lotes, reembolsos): lotes = [[fecha, coste, valor]] de lo que sigues
    teniendo; reembolsos = [[fecha, resultado]] de lo ya vendido, del que el extracto
    solo da la plusvalía.
    """
    texto = decodifica(texto)
    delim = ";" if texto.count(";") >= texto.count(",") else ","
    filas = [f for f in csv.reader(io.StringIO(texto), delimiter=delim)
             if any((c or "").strip() for c in f)]
    if not filas:
        return [], []

    cab = [(c or "").strip().lower() for c in filas[0]]

    def col(clave, defecto):
        for i, c in enumerate(cab):
            if any(a in c for a in CAB_MYINVESTOR[clave]):
                return i
        return defecto

    ic, ico, iv = col("fecha", 0), col("coste", 1), col("valor", 2)
    lotes, reembolsos = [], []
    for fila in filas[1:]:
        if len(fila) <= max(ic, ico, iv):
            continue
        m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", fila[ic])
        if not m:
            continue
        fecha = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
        coste, valor = num_es(fila[ico]), num_es(fila[iv])
        if coste <= 0 and valor <= 0:
            # Participaciones ya reembolsadas: solo queda el resultado fiscal.
            if len(fila) > 3 and num_es(fila[3]):
                reembolsos.append([fecha, round(num_es(fila[3]), 2)])
            continue
        lotes.append([fecha, round(coste, 2), round(valor, 2)])
    lotes.sort(key=lambda x: x[0])
    return lotes, reembolsos


def myinvestor_a_movimientos(producto_id, lotes, reembolsos, serie_vl):
    """
    Convierte los lotes en compras. El extracto no trae participaciones, así que
    se calculan como coste / valor liquidativo del día de compra. No se usa el
    valor de mercado del extracto porque MyInvestor lo calcula con un VL de uno o
    dos días antes y saldrían participaciones erróneas.
    """
    # VL con el que MyInvestor valoró el extracto, para los lotes sin VL de compra.
    estimados = sorted(serie_vl[f] * v / c for f, c, v in lotes if serie_vl.get(f) and c > 0)
    vl_extracto = estimados[len(estimados) // 2] if estimados else None
    movs, sin_vl = [], 0
    for fecha, coste, valor in lotes:
        vc = serie_vl.get(fecha)
        if vc:
            unidades = coste / vc
        elif vl_extracto:
            unidades, sin_vl = valor / vl_extracto, sin_vl + 1
        else:
            unidades, sin_vl = 0.0, sin_vl + 1
        movs.append({"fecha": fecha, "producto": producto_id, "tipo": "compra",
                     "unidades": round(unidades, 6), "importe": coste, "nota": "MyInvestor"})
    for fecha, resultado in reembolsos:
        # Del reembolso solo se conoce la plusvalía: se anota como una venta de 0
        # participaciones que cobra ese resultado.
        movs.append({"fecha": fecha, "producto": producto_id, "tipo": "venta",
                     "unidades": 0, "importe": resultado,
                     "nota": "Plusvalía de un reembolso (MyInvestor no da la fecha de venta)"})
    return movs, sin_vl


# ---------------------------------------------------------------- lectura de tablas

def leer_tabla(nombre, contenido):
    """Excel (.xlsx), CSV o texto pegado -> [(número de fila, {columna: valor})]."""
    if nombre and nombre.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        libro = load_workbook(io.BytesIO(contenido), data_only=True, read_only=True)
        hoja = libro["Movimientos"] if "Movimientos" in libro.sheetnames else libro.worksheets[0]
        filas = [list(f) for f in hoja.iter_rows(values_only=True)]
    else:
        texto = decodifica(contenido)
        # Lo que devuelve una IA suele venir dentro de un bloque ``` ... ```.
        texto = re.sub(r"^\s*```[a-zA-Z]*\s*$", "", texto, flags=re.M).strip()
        lineas = [l for l in texto.splitlines() if l.strip()]
        if not lineas:
            return [], "El texto está vacío."
        cab = lineas[0]
        delim = max([";", "\t", ","], key=cab.count)
        filas = list(csv.reader(io.StringIO("\n".join(lineas)), delimiter=delim))
    # Se guarda el número de fila real (el que ves en Excel) aunque haya filas en blanco.
    filas = [(n, f) for n, f in enumerate(filas, start=1)
             if f and any(c not in (None, "") and str(c).strip() for c in f)]
    if not filas:
        return [], "No hay ninguna fila con datos."

    cab = [sin_tildes(c) for c in filas[0][1]]
    idx = {}
    for col, alias in SINONIMOS.items():
        for i, c in enumerate(cab):
            if c in alias and i not in idx.values():
                idx[col] = i
                break
    faltan = [c for c in ("fecha", "tipo_movimiento", "importe") if c not in idx]
    if faltan:
        return [], ("No encuentro las columnas " + ", ".join(faltan) + ". La primera fila tiene que ser la "
                    "cabecera de la plantilla: " + ";".join(COLUMNAS))
    if len(filas) < 2:
        if nombre and nombre.lower().endswith((".xlsx", ".xlsm")):
            return [], ("La hoja «Movimientos» está vacía: solo tiene la cabecera. Las filas de la hoja "
                        "«Ejemplo» son de muestra y no se importan; escribe tus operaciones en «Movimientos», "
                        "debajo de la cabecera, guarda el archivo y vuelve a subirlo.")
        return [], "Solo hay cabecera: escribe tus operaciones debajo, una por fila."
    salida = []
    for n, f in filas[1:]:
        salida.append((n, {col: (f[i] if i < len(f) else None) for col, i in idx.items()}))
    return salida, None


def lee_fecha(v):
    if isinstance(v, dt.datetime):
        return v.date().isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    t = str(v or "").strip()
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", t)
    if m:
        a, me, di = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})", t)
        if not m:
            return None
        a = int(m.group(3)) + (2000 if len(m.group(3)) == 2 else 0)
        me, di = int(m.group(2)), int(m.group(1))
    try:
        return dt.date(a, me, di).isoformat()
    except ValueError:   # un 31 de febrero, un mes 13...
        return None


def lee_numero(v):
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, (int, float)):
        return abs(float(v))
    t = str(v).strip().replace("€", "").replace("$", "").replace(" ", "")
    if not re.fullmatch(r"[-+]?[\d.,]+", t):
        return "error"
    return abs(num_es(t))


# ---------------------------------------------------------------- preparar el plan

class Plan:
    """Lo que se va a importar: productos nuevos, movimientos, saldos y errores."""

    def __init__(self):
        self.productos_nuevos = []   # [{"ref": "nuevo:1", "datos": {...}, "precio": ..., "fecha": ...}]
        self.movimientos = []        # [{"fila", "producto" (id o ref), campos del movimiento, "marcas"}]
        self.valoraciones = []
        self.cuentas = []            # [{"ref": "cuenta:1", "cuenta": id si ya existía, "datos": {...}}]
        self.reemplazar = []         # [(producto id o ref, origen)]: se borran sus importados previos
        self.reemplazarTodo = None   # origen: se borran todos los movimientos con ese origen
        self.errores = []            # [{"fila", "mensaje"}]
        self.avisos = []

    def error(self, fila, mensaje):
        self.errores.append({"fila": fila, "mensaje": mensaje})


def _producto_existente(cfg, identificador, nombre):
    ident = (identificador or "").strip().upper()
    for p in cfg.get("productos", []):
        if ident and ident in ((p.get("identificador") or "").upper(), (p.get("codigo") or "").upper()):
            return p
    nom = sin_tildes(nombre)
    if nom and not ident:
        for p in cfg.get("productos", []):
            if nom in (sin_tildes(p.get("nombre")), sin_tildes(p.get("corto"))):
                return p
    return None


def _producto_existente_de(cfg, nombre, es_saldo):
    """El producto que ya existe con ese nombre Y de la misma familia: `es_saldo`
    para el dinero (efectivo/deuda) y lo contrario para un activo. Hace falta
    porque una cuenta y su activo pueden llamarse igual («REVOLUT FONDO
    MONETARIO DÓLAR»), y no son lo mismo: sin esto se crea un duplicado con _2."""
    nom = sin_tildes(nombre)
    if not nom:
        return None
    for p in cfg.get("productos", []):
        if nom in (sin_tildes(p.get("nombre")), sin_tildes(p.get("corto"))):
            if (p.get("tipo") in almacen.SOLO_SALDO) == bool(es_saldo):
                return p
    return None


class Resolutor:
    """Encuentra (o propone crear) el producto de cada fila, una sola vez por producto."""

    def __init__(self, cfg, plan, carpeta):
        self.cfg, self.plan, self.carpeta = cfg, plan, carpeta
        self.cache, self.series, self.frescas = {}, {}, set()
        self.fallos = {}   # clave de producto -> mensaje, para avisar también en las filas siguientes

    @staticmethod
    def _datos_fila(nombre, identificador, r):
        fi = r.get("ficha") or {}
        return {"nombre": nombre or r.get("nombre") or r["codigo"], "tipo": r["tipo"],
                "identificador": identificador.strip(), "fuente": r["fuente"], "codigo": r["codigo"],
                "moneda": r.get("moneda") or "EUR", "vivo": r.get("vivo") or "",
                "ter": fi.get("ter"), "riesgo": fi.get("riesgo"), "clase": fi.get("clase") or "",
                "gestora": fi.get("gestora") or "", "largoPlazo": True}

    @staticmethod
    def _mejor_si_coincide(nombre, res):
        """Mejor candidato cuyo nombre coincida con el de la fila («NVIDIA» ->
        NVDA, «Tesla Inc.» -> TSLA). Solo se aceptan coincidencias, y de esas se
        queda con la cotización principal: valores, ETF o fondos antes que
        tokenizadas, el nombre que empieza por lo que has escrito y la línea
        original (NVDA) antes que una secundaria (NVD.DE en Xetra)."""
        nom = _normaliza(nombre)
        if len(nom) < 3:
            return None
        mejores = []
        for i, r in enumerate(res or []):
            otro = _normaliza(r.get("nombre") or "")
            if len(otro) >= 3 and (nom in otro or otro in nom):
                clave = (r.get("tipo") not in ("accion", "etf", "fondo"),
                         not otro.startswith(nom), "." in (r.get("codigo") or ""), i)
                mejores.append((clave, r))
        return min(mejores, key=lambda x: x[0])[1] if mejores else None

    @classmethod
    def _nombre_cercano(cls, nombre):
        """Busca por nombre y devuelve el mejor candidato que coincida, o None."""
        try:
            res = buscar.buscar(nombre)
        except Exception:
            return None
        return cls._mejor_si_coincide(nombre, res)

    def producto(self, fila, identificador, nombre, tipo_prod):
        clave = ((identificador or "").strip().upper(), sin_tildes(nombre) if not identificador else "")
        if clave in self.cache:
            ref = self.cache[clave]
            if not ref:   # ya falló antes: se avisa también en esta fila, no se descarta en silencio
                self.plan.error(fila, self.fallos.get(clave, f"No encuentro «{identificador}»."))
            return ref
        ref = None
        existente = _producto_existente(self.cfg, identificador, nombre)
        if existente:
            ref = existente["id"]
        elif identificador:
            n_fallos = len(buscar.FALLOS)
            res = buscar.buscar(identificador)
            if not res and buscar.hubo_fallos_desde(n_fallos):
                self.fallos[clave] = (f"No he podido consultar «{identificador}» en internet ahora mismo "
                                      "(la conexión ha fallado o Yahoo/Morningstar no han respondido). "
                                      "Comprueba tu conexión y vuelve a pulsar «Previsualizar»: suele bastar "
                                      "con intentarlo otra vez.")
                self.plan.error(fila, self.fallos[clave])
                ref = None
            elif res:
                ref = self._nuevo(self._datos_fila(nombre, identificador, res[0]), res[0])
            else:
                # Algunos ISIN no están indexados por los buscadores (p. ej. US6706661040,
                # el de NVIDIA): se reintenta con el nombre de la fila.
                otro = self._nombre_cercano(nombre)
                if otro:
                    ref = self._nuevo(self._datos_fila(nombre, identificador, otro), otro)
                else:
                    self.fallos[clave] = (f"No encuentro «{identificador}» con precio en internet. Si no cotiza, "
                                          "créalo en Productos con «Valor anotado a mano» y ese mismo "
                                          "identificador, y vuelve a importar.")
                    self.plan.error(fila, self.fallos[clave])
                    ref = None
        elif nombre:
            tipo = tipo_prod if tipo_prod in motor.TIPOS else "otro"
            # Solo el nombre (extractos sin ISIN): antes se creaba manual a ciegas y,
            # sin valores anotados, ni siquiera salía en el panel. Ahora se busca en
            # internet con el mismo criterio de coincidencia; si no, manual como antes.
            r = None
            fallo_red = False
            if tipo not in almacen.SOLO_SALDO:   # una cuenta no se busca: es un saldo
                n_fallos = len(buscar.FALLOS)
                res = buscar.buscar(nombre)
                if not res and buscar.hubo_fallos_desde(n_fallos):
                    fallo_red = True
                    self.fallos[clave] = (f"No he podido consultar «{nombre}» en internet ahora mismo "
                                          "(la conexión ha fallado o Yahoo/Morningstar no han respondido). "
                                          "Comprueba tu conexión y vuelve a pulsar «Previsualizar»: suele bastar "
                                          "con intentarlo otra vez.")
                    self.plan.error(fila, self.fallos[clave])
                else:
                    r = self._mejor_si_coincide(nombre, res)
            if fallo_red:
                ref = None
            elif r:
                ident = (identificador or "").strip() or (r.get("identificador") or "")
                ref = self._nuevo(self._datos_fila(nombre, ident, r), r)
            else:
                ref = self._nuevo({"nombre": nombre, "tipo": tipo, "fuente": "manual",
                                   "largoPlazo": tipo not in ("efectivo", "deuda")}, None)
        else:
            self.fallos[clave] = "No tiene identificador ni nombre: no sé de qué producto es."
            self.plan.error(fila, self.fallos[clave])
        self.cache[clave] = ref
        return ref

    def _nuevo(self, datos, resultado):
        ref = f"nuevo:{len(self.plan.productos_nuevos) + 1}"
        self.plan.productos_nuevos.append({
            "ref": ref, "datos": datos,
            "precio": resultado and resultado.get("precio"), "monedaPrecio": resultado and resultado.get("moneda"),
            "fecha": resultado and resultado.get("fecha"), "mercado": resultado and resultado.get("mercado")})
        return ref

    def datos(self, ref):
        if ref and ref.startswith("nuevo:"):
            return next(n["datos"] for n in self.plan.productos_nuevos if n["ref"] == ref)
        return almacen.producto(self.cfg, ref)

    def serie(self, ref, fecha=None):
        """Precios en euros del producto; si no llegan a 'fecha', se bajan de nuevo."""
        if ref not in self.series:
            p = self.datos(ref)
            self.series[ref] = motor.serie_producto(p, self.carpeta) if p and p.get("fuente") != "manual" else {}
        s = self.series[ref]
        if fecha and s and max(s) < fecha and ref not in self.frescas:
            self.frescas.add(ref)
            self.series[ref] = s = motor.serie_producto(self.datos(ref), self.carpeta, fresca=True)
        return s


def preparar_tabla(cfg, filas, carpeta):
    """Plantilla o texto de la IA -> Plan."""
    plan = Plan()
    res = Resolutor(cfg, plan, carpeta)
    cambios = {}
    for n, f in filas:
        fecha = lee_fecha(f.get("fecha"))
        tipo = TIPO_MOV.get(sin_tildes(f.get("tipo_movimiento")))
        ident = str(f.get("identificador") or "").strip()
        nombre = str(f.get("nombre") or "").strip()
        tprod = TIPO_PROD.get(sin_tildes(f.get("tipo_producto")), "")
        importe, unidades, comision = (lee_numero(f.get(k)) for k in ("importe", "unidades", "comision"))
        moneda = (str(f.get("moneda") or "").strip() or "EUR").upper()
        nota = str(f.get("nota") or "").strip()

        if not fecha:
            plan.error(n, f"La fecha «{f.get('fecha') or ''}» no es válida. Usa el formato 2025-03-10 o 10/03/2025.")
            continue
        if not tipo:
            plan.error(n, f"El tipo de movimiento «{f.get('tipo_movimiento') or ''}» no es válido: "
                          "usa compra, venta, dividendo, comision o saldo.")
            continue
        if "error" in (importe, unidades, comision):
            plan.error(n, "Algún número no se entiende (importe, unidades o comisión).")
            continue
        if not importe and tipo != "saldo":
            plan.error(n, "No tiene importe.")
            continue
        if not ident and not nombre:
            plan.error(n, "No tiene identificador: pon el ISIN o el ticker (o, si es una cuenta, su nombre).")
            continue
        if tipo == "saldo" and not ident:
            tprod = tprod or "efectivo"
        ref = res.producto(n, ident, nombre, tprod)
        if not ref:
            continue
        marcas = []

        # Importes en otra moneda: se pasan a euros con el cambio de ese día.
        if moneda != "EUR" and importe is not None:
            if moneda not in cambios:
                cambios[moneda] = motor.serie_cambio(moneda, carpeta)
            fx = valor_en(cambios[moneda], fecha, margen=6)
            if not fx:
                plan.error(n, f"No encuentro el cambio de {moneda} a euros del {almacen.fmt_fecha(fecha)}.")
                continue
            importe = importe * fx
            comision = comision * fx if comision else comision
            marcas.append(f"convertido de {moneda}")

        if tipo == "saldo":
            plan.valoraciones.append({"fila": n, "producto": ref, "fecha": fecha, "valor": round(importe or 0, 2)})
            continue

        p = res.datos(ref)
        cotiza = p and p.get("fuente") != "manual" and p.get("tipo") not in almacen.SOLO_SALDO
        if tipo in ("compra", "venta") and not unidades and cotiza:
            # Muchos extractos no dan las participaciones: se calculan con el precio de ese día.
            precio = valor_en(res.serie(ref, fecha), fecha, margen=6)
            if not precio:
                plan.error(n, "No trae unidades y no encuentro el precio de ese día para calcularlas.")
                continue
            neto = importe - (comision or 0) if tipo == "compra" else importe + (comision or 0)
            unidades = neto / precio
            marcas.append("unidades calculadas")
        plan.movimientos.append({"fila": n, "producto": ref, "fecha": fecha, "tipo": tipo,
                                 "unidades": unidades, "importe": round(importe, 2),
                                 "comision": round(comision, 2) if comision else None,
                                 "nota": nota, "marcas": marcas, "origen": "importado"})
    return plan


def preparar_myinvestor(cfg, archivos, carpeta):
    """[(nombre de archivo, bytes)] de MyInvestor -> Plan. Cada archivo sustituye lo que se
    importó antes de ese fondo, porque el extracto siempre trae la foto completa."""
    plan = Plan()
    res = Resolutor(cfg, plan, carpeta)
    for nombre, contenido in archivos:
        m = re.search(r"([A-Z]{2}[A-Z0-9]{9}\d)", (nombre or "").upper())
        if not m:
            plan.error(nombre, "No encuentro el ISIN en el nombre del archivo. Descárgalo otra vez de "
                               "MyInvestor sin cambiarle el nombre (lleva el ISIN del fondo).")
            continue
        isin = m.group(1)
        lotes, reembolsos = leer_csv_myinvestor(contenido)
        if not lotes and not reembolsos:
            plan.error(nombre, "No parece un extracto «Plusvalías y minusvalías» de MyInvestor, o está vacío.")
            continue
        ref = res.producto(nombre, isin, "", "fondo")
        if not ref:
            continue
        p = res.datos(ref)
        if p.get("fuente") == "manual":
            plan.error(nombre, f"«{p.get('corto') or p['nombre']}» se valora a mano: el extracto de MyInvestor "
                               "necesita un fondo con precio en internet.")
            continue
        serie = res.serie(ref, lotes[-1][0] if lotes else None)
        movs, sin_vl = myinvestor_a_movimientos(ref, lotes, reembolsos, serie)
        if sin_vl:
            plan.avisos.append(f"{isin}: {sin_vl} compras sin valor liquidativo de ese día; sus "
                               "participaciones se han estimado con el valor del extracto.")
        plan.reemplazar.append((ref, "myinvestor"))
        for mv in movs:
            plan.movimientos.append({**mv, "fila": nombre, "comision": None, "marcas": [],
                                     "origen": "myinvestor"})
    return plan


# ---------------------------------------------------------------- Portfolio Performance

# Export «Todas las transacciones» de Portfolio Performance:
#   Fecha;Tipo;Activo;Títulos;Precio;Cantidad;Comisiones;Impuestos;
#   Valor neto de transacción;Cuenta;Cuenta de contrapartida;Nota;Fuente
# Números con coma decimal y punto de miles, a veces con la moneda delante («USD 2.565,00»).

MONEDAS_PP = ("EUR", "USD", "GBP", "CHF", "JPY", "SEK", "NOK", "DKK", "PLN", "CZK",
              "HUF", "CAD", "AUD", "MXN", "BRL", "TRY", "ZAR")

# tipo_pp -> (tipo de la app, signo del efectivo en la cuenta «Cuenta»)
PP_TIPOS = {
    "compra": ("compra", -1), "venta": ("venta", 1),
    "dividendo": ("dividendo", 1), "cupon": ("dividendo", 1),
    "intereses": ("interes", 1), "interes": ("interes", 1),
    "comisiones": ("comision", -1), "comision": ("comision", -1),
    "impuestos": ("impuesto", -1), "impuesto": ("impuesto", -1),
    "deposito": ("deposito", 1), "depositos": ("deposito", 1),
    "retirada": ("retirada", -1), "retiradas": ("retirada", -1),
    "transferencia": ("transferencia", -1),
    "transferencia (salida)": ("transferencia", -1),
    "transferencia (entrada)": ("transferencia", 1),
    "traspaso": ("traspaso", -1),
    "traspaso (salida)": ("traspaso", -1),
    "traspaso (entrada)": ("traspaso", 1),
    # Escisiones (Corteva -> Vylor): PP las exporta como «Entrega (entrante)». Entran
    # títulos con un coste asignado y NO se mueve dinero de ninguna cuenta.
    "entrega": ("entrega", 1), "entrega (entrante)": ("entrega", 1),
    "apertura": ("apertura", 1), "cambio de divisa": ("cambio_divisa", -1),
    "saldo": ("saldo", 1), "reparto": ("saldo", 1),
}

# Cómo se llama cada columna en el export (en minúsculas y sin tildes).
PP_COLUMNAS = {"fecha": "fecha", "tipo": "tipo", "activo": "activo", "titulos": "titulos",
               "precio": "precio", "cantidad": "cantidad", "comisiones": "comisiones",
               "impuestos": "impuestos", "cuenta": "cuenta", "nota": "nota", "fuente": "fuente"}

# Algunos fondos vienen con su código de Morningstar como nombre («0P0001XF41.F», tal cual
# los exporta PP). Yahoo los sirve con ese mismo código, así que se usan directamente en
# vez de dejarlos «a coste».
CODIGO_MORNINGSTAR = re.compile(r"^0P[0-9A-Z]{6,9}\.[A-Z]{1,2}$", re.I)

# Fichas de los productos que aparecen en el export. Así no se «adivina» nada:
# ACCOR y AIRBUS se negocian en euros (no en los ADR en dólares) y «blackrock» es
# el fondo de MyInvestor, no la acción BLK. Lo que no esté aquí se valora a mano.
CATALOGO_PP = {
    "tesla inc": ("accion", "yahoo", "TSLA", "USD"),
    "nvidia corp": ("accion", "yahoo", "NVDA", "USD"),
    "microsoft corp": ("accion", "yahoo", "MSFT", "USD"),
    "amazon com inc": ("accion", "yahoo", "AMZN", "USD"),
    "costco wholesale corp": ("accion", "yahoo", "COST", "USD"),
    "unitedhealth group inc": ("accion", "yahoo", "UNH", "USD"),
    "qualcomm inc": ("accion", "yahoo", "QCOM", "USD"),
    "lululemon athletica inc": ("accion", "yahoo", "LULU", "USD"),
    "corteva inc": ("accion", "yahoo", "CTVA", "USD"),
    "american tower corp": ("accion", "yahoo", "AMT", "USD"),
    "agnc investment corp": ("accion", "yahoo", "AGNC", "USD"),
    "ses ai corp": ("accion", "yahoo", "SES", "USD"),
    "sirius xm holdings inc": ("accion", "yahoo", "SIRI", "USD"),
    "alphabet inc class c": ("accion", "yahoo", "GOOGL", "USD"),
    "constellation brands inc class a": ("accion", "yahoo", "STZ", "USD"),
    "accor sa": ("accion", "yahoo", "AC.PA", "EUR"),
    "airbus se": ("accion", "yahoo", "AIR.PA", "EUR"),
    "grifols sa": ("accion", "yahoo", "GRF.MC", "EUR"),
    "acm research inc class a": ("accion", "yahoo", "1ACMR.MI", "EUR"),
    "universal music group nv": ("accion", "yahoo", "0VD.HA", "EUR"),
    "cellnex telecom sa": ("accion", "yahoo", "CLNX.MC", "EUR"),
    "vinci s a": ("accion", "yahoo", "DG.PA", "EUR"),
    # Escisión Corteva -> Vylor: PP la entrega con este nombre y cotiza en el NYSE.
    "vylor inc": ("accion", "yahoo", "VYLR", "USD"),
    "bitcoin": ("cripto", "yahoo", "BTC-EUR", "EUR"),
    "xrp eur": ("cripto", "yahoo", "XRP-EUR", "EUR"),
    "invesco s p 500 ucits etf": ("etf", "yahoo", "SPXD.MI", "EUR"),
    "amundi s p 500 swap ucits etf eur acc": ("etf", "yahoo", "500.PA", "EUR"),
    "amundi msci world ex emu ucits": ("etf", "yahoo", "CM9.PA", "EUR"),
    "amundi ibex35 ucits etf acc": ("etf", "yahoo", "AMES.DE", "EUR"),
    "bnp paribas easy ftse epra nareit eurozone capped ucits etf capitalisation": ("etf", "yahoo", "EEA.PA", "EUR"),
    "vanguard s p 500 ucits etf accumulating": ("etf", "yahoo", "VUAA.DE", "EUR"),
    "ishares msci world sri eur a": ("etf", "yahoo", "2B7K.DE", "EUR"),
    "fidelity msci euro in pa eur": ("fondo", "manual", "", "EUR"),
    "fidelity msci jp indx pa eur": ("fondo", "manual", "", "EUR"),
    "fidelity msci pacf exjp pau": ("fondo", "manual", "", "EUR"),
    # El nombre ES el código de Morningstar: Yahoo lo sirve tal cual.
    "0p0001xf41 f": ("fondo", "yahoo", "0P0001XF41.F", "EUR"),
    "ishares emerging metal myinvestor": ("fondo", "manual", "", "EUR"),
    "vanguard us equity metal myinvestor": ("fondo", "manual", "", "EUR"),
    "ishares us equity index fund clase s": ("fondo", "manual", "", "EUR"),
    "amundi index s p 500 myinvestor": ("fondo", "manual", "", "EUR"),
    "gx spx quarter tail hedge uc": ("fondo", "manual", "", "EUR"),
    "blackrock": ("fondo", "manual", "", "EUR"),
    # El plan de pensiones de ING sí tiene valor liquidativo público: se enlaza
    # solo para que traiga el precio desde la primera importación.
    "plan2040 ing": ("pension", "yahoo", "0P00008571.F", "EUR"),
    "plan 2040 ing": ("pension", "yahoo", "0P00008571.F", "EUR"),
    "gold philharmoniker 1oz": ("commodity", "manual", "", "EUR"),
}

# Tipos de inversión: si el usuario los elige para una «cuenta» del CSV, esa
# cuenta es en realidad un producto y el dinero vive en una cuenta de efectivo.
TIPOS_INVERSION = ("pension", "fondo", "etf", "accion", "cripto", "bono", "inmueble")

# Movimientos que meten dinero en la cuenta de efectivo y que lo sacan.
ENTRA_EFECTIVO = ("deposito", "interes", "dividendo", "venta")
SALE_EFECTIVO = ("compra", "comision", "impuesto", "retirada")


def _ficha_catalogo(nombre):
    """Ficha del catálogo para un nombre, tolerando espacios de más
    («PLAN 2040 ING» y «PLAN2040 ING» son el mismo plan)."""
    if not nombre:
        return None
    clave = _normaliza(nombre)
    ficha = CATALOGO_PP.get(clave)
    if ficha:
        return ficha
    sin_espacios = clave.replace(" ", "")
    for k, v in CATALOGO_PP.items():
        if k.replace(" ", "") == sin_espacios:
            return v
    return None


def _fuente_para(nombre, tipo):
    """(fuente, código) del catálogo para ese nombre y tipo, si se conoce."""
    ficha = _ficha_catalogo(nombre)
    if not ficha:
        return None, ""
    tipo_cat, fuente, codigo, _moneda = ficha
    if tipo and tipo_cat != tipo:
        return None, ""
    return fuente, codigo


def _exclusiones(excluir):
    """Lo que ha desmarcado el usuario, como dos juegos de refs del plan."""
    e = excluir or {}
    return set(e.get("cuentas") or ()), set(e.get("productos") or ())


def _se_importa(mv, fuera_cuentas, fuera_prod):
    """Un movimiento se importa si no toca ninguna entidad excluida. Cuentan las
    tres referencias: a qué producto va, de qué cuenta sale y con qué cuenta se
    paga."""
    return not (mv.get("producto") in fuera_prod
                or mv.get("cuenta") in fuera_cuentas
                or mv.get("contrapartida") in fuera_cuentas)


def _aportaciones_que_faltan(plan, ref, nombre, moneda="EUR", movs=None):
    """Cada compra que paga esta cuenta tiene que tener su ingreso: Portfolio
    Performance a veces apunta el depósito días después (o aún no lo ha apuntado),
    y la cuenta quedaría en negativo. Devuelve (movimientos, ajustes de la serie),
    sin tocar el plan (la vista previa se ejecuta dos veces: no puede duplicarlos).

    Usa las mismas reglas de dinero que el motor (motor.efecto_de), así que una
    compra que paga la cuenta contrapartida no cuenta aquí. Todo se calcula en la
    moneda de la cuenta, que es donde vive el saldo. `movs` son los movimientos
    que de verdad se van a importar (los excluidos no piden su ingreso)."""
    if movs is None:
        movs = plan.movimientos
    vivos = []
    for m in movs:
        e = motor.efecto_de(m, ref)
        if not e:
            continue
        imp = motor.importe_en_cuenta(m, moneda, None)
        if imp is None:
            imp = float(m.get("importe") or 0)
        vivos.append((e, m, float(imp)))
    if not vivos:
        return [], []
    extra, ajustes, saldo = [], [], 0.0
    for e, m, imp in sorted(vivos, key=lambda x: (x[1]["fecha"], ORDEN_PP.get(x[1]["tipo"], 9), x[1]["fila"])):
        saldo += e * imp
        if saldo < -0.005:
            falta = round(-saldo, 2)
            tc = float(m.get("tipoCambio") or 1) or 1.0
            extra.append({
                "fila": m["fila"], "fecha": m["fecha"], "tipo": "deposito",
                "producto": None, "unidades": 0.0,
                "importe": round(falta * tc, 2) if moneda != "EUR" else falta,
                "importeOriginal": falta, "monedaOriginal": moneda, "tipoCambio": tc,
                "cuenta": ref, "contrapartida": None,
                "propietario": m.get("propietario"),
                "nota": f"Aportación al plan {nombre}: el CSV no traía el ingreso",
                "marcas": ["ingreso añadido"], "origen": "portfolio", "fuente": "",
            })
            ajustes.append((m["fecha"], falta))     # la serie de saldo sube lo mismo
            saldo = 0.0
    return extra, ajustes


def es_portfolio_performance(cabecera):
    """¿La primera fila es la de un export de Portfolio Performance?"""
    t = sin_tildes(cabecera).lower()
    return "fecha" in t and "valor neto" in t and "cuenta" in t


def _columnas_pp(cab):
    idx = {}
    for i, c in enumerate(cab):
        if c in PP_COLUMNAS and PP_COLUMNAS[c] not in idx:
            idx[PP_COLUMNAS[c]] = i
        elif c.startswith("valor neto") and "neto" not in idx:
            idx["neto"] = i
        elif c.startswith("cuenta de contrapartida") and "contrapartida" not in idx:
            idx["contrapartida"] = i
    return idx, [k for k in ("fecha", "tipo", "neto", "cuenta") if k not in idx]


def _moneda_de(txt, por_defecto=None):
    """«USD 2.565,00» -> (2565.0, 'USD'); «1.400,00» -> (1400.0, None)."""
    t = (txt or "").strip()
    if not t:
        return None, None
    m = re.match(r"^([A-Za-z]{3})\s+(.*)$", t)
    if m and m.group(1).upper() in MONEDAS_PP:
        return m.group(2), m.group(1).upper()
    return t, por_defecto


def _numero_pp(txt, es_coma):
    t = (txt or "").replace("€", "").replace("$", "").replace("%", "")
    t = t.replace("\u00a0", "").replace(" ", "").strip()
    if not t:
        return None
    if not es_coma:
        try:
            return float(t.replace(",", ""))
        except ValueError:
            return None
    if not re.fullmatch(r"[-+]?[\d.,]+", t):
        return None
    return num_es(t)


def leer_portfolio(texto):
    """Lee el CSV de «Todas las transacciones» de Portfolio Performance.

    Devuelve (filas, error): cada fila es un dict con fecha, tipo, activo, unidades,
    importes ya parseados y las dos cuentas. Las fechas salen ordenadas de menor a
    mayor, como pide la regla de importación.
    """
    texto = decodifica(texto).replace("\r\n", "\n").replace("\r", "\n")
    lineas = [l for l in texto.splitlines() if l.strip()]
    if not lineas:
        return [], "El archivo está vacío."
    cab = [sin_tildes(c) for c in next(csv.reader([lineas[0]], delimiter=";"))]
    if not es_portfolio_performance(";".join(cab)):
        return [], ("No parece un CSV de Portfolio Performance: me faltan las columnas «Fecha», "
                    "«Valor neto de transacción» y «Cuenta».")
    idx, faltan = _columnas_pp(cab)
    if faltan:
        return [], "Faltan columnas en la cabecera: " + ", ".join(faltan) + "."

    def celda(f, k, defecto=""):
        i = idx.get(k)
        return (f[i] if i is not None and i < len(f) else defecto) or defecto

    brutas = [next(csv.reader([l], delimiter=";")) for l in lineas[1:]]
    brutas = [f for f in brutas if any((x or "").strip() for x in f)]
    # ¿Los números vienen con coma decimal (español) o con punto (inglés)?
    nums = [celda(f, k) for f in brutas for k in ("cantidad", "comisiones", "impuestos", "neto", "precio")]
    es_coma = any("," in (x or "") for x in nums)

    filas = []
    for n, f in enumerate(brutas, start=2):
        fecha = lee_fecha(celda(f, "fecha"))
        if not fecha:
            return [], f"La fecha «{celda(f, 'fecha')}» de la fila {n} no se entiende."
        bruto, mon_bruto = _moneda_de(celda(f, "cantidad"))
        neto, mon_neto = _moneda_de(celda(f, "neto"))
        comision, mon_com = _moneda_de(celda(f, "comisiones"))
        impuestos, mon_imp = _moneda_de(celda(f, "impuestos"))
        precio, mon_precio = _moneda_de(celda(f, "precio"))
        valores = {"bruto": _numero_pp(bruto, es_coma), "neto": _numero_pp(neto, es_coma),
                   "comision": _numero_pp(comision, es_coma), "impuestos": _numero_pp(impuestos, es_coma),
                   "precio": _numero_pp(precio, es_coma)}
        if valores["neto"] is None:
            return [], f"El importe de la fila {n} («{celda(f, 'neto')}») no se entiende."
        filas.append({
            "fila": n, "fecha": fecha,
            "tipo_pp": sin_tildes(celda(f, "tipo")).lower(),
            "activo": celda(f, "activo").strip(),
            "unidades": _numero_pp(celda(f, "titulos"), es_coma),
            "precio": valores["precio"],
            "bruto": valores["bruto"] or 0.0,
            "neto": abs(valores["neto"]),
            "comision": abs(valores["comision"] or 0.0),
            "impuestos": abs(valores["impuestos"] or 0.0),
            "moneda": mon_neto or mon_bruto or mon_com or mon_imp or mon_precio,
            "cuenta": celda(f, "cuenta").strip(),
            "contrapartida": celda(f, "contrapartida").strip(),
            "nota": celda(f, "nota").strip(),
            "fuente": celda(f, "fuente").strip(),
        })
    filas.sort(key=lambda x: (x["fecha"], x["fila"]))
    return filas, None


def _tipo_cuenta(nombre):
    u = sin_tildes(nombre).upper()
    if "PLAN" in u:
        return "pension"
    if "FONDOS" in u or "CARTERA" in u or "MONETARIO" in u:
        return "fondo"
    if any(k in u for k in ("TRADE REPUBLIC", "MY INVESTOR", "FREEDOM", "REVOLUT")):
        return "broker"
    return "efectivo"


def _entidad_cuenta(nombre):
    u = sin_tildes(nombre).upper()
    for k, e in (("TRADE REPUBLIC", "Trade Republic"), ("MY INVESTOR", "MyInvestor"),
                 ("FREEDOM", "Freedom"), ("REVOLUT", "Revolut"), ("ING", "ING")):
        if k in u:
            return e
    return ""


def _moneda_por_nombre(nombre):
    u = sin_tildes(nombre).upper()
    if "DOLAR" in u or "DOLARES" in u or "USD" in u:
        return "USD"
    if "EUR" in u:
        return "EUR"
    return "EUR"


def _propietario_por_nombre(nombre):
    return "gina" if "GINA" in sin_tildes(nombre).upper() else "david"


def preparar_portfolio(cfg, contenido, carpeta):
    """CSV de Portfolio Performance -> Plan completo: cuentas, productos, movimientos
    y saldos de cada cuenta. No consulta internet: las fichas salen de CATALOGO_PP y,
    si un producto no está, se valora a mano para que tú decidas (aparece en
    «Valores sin cotización automática»)."""
    plan = Plan()
    plan.reemplazarTodo = "portfolio"
    filas, error = leer_portfolio(contenido)
    if error:
        plan.error(1, error)
        return plan
    if not filas:
        plan.error(1, "El archivo no tiene ninguna fila con datos.")
        return plan

    cambios = {}

    def fx(moneda):
        if moneda and moneda != "EUR" and moneda not in cambios:
            cambios[moneda] = motor.serie_cambio(moneda, carpeta)
        return cambios.get(moneda) or {}

    def a_eur(importe, moneda, fecha):
        """Importe en su moneda -> euros con el cambio de ese día."""
        if not importe:
            return 0.0, 1.0
        if not moneda or moneda == "EUR":
            return importe, 1.0
        t = valor_en(fx(moneda), fecha, margen=6)
        if not t:
            return None, None
        return importe * t, t

    def a_moneda(importe, mon_desde, mon_hasta, fecha):
        if not mon_desde or not mon_hasta or mon_desde == mon_hasta:
            return importe
        eur, _ = a_eur(importe, mon_desde, fecha)
        if eur is None:
            return None
        if mon_hasta == "EUR":
            return eur
        t = valor_en(fx(mon_hasta), fecha, margen=6)
        return eur / t if t else None

    # ---------------------------------------------------------------- cuentas
    nombres_cuentas = []
    for f in filas:
        for nombre in (f["cuenta"], f["contrapartida"]):
            if nombre and nombre not in nombres_cuentas:
                nombres_cuentas.append(nombre)
    # La moneda de cada cuenta: lo que diga su nombre y, si aparece, la de sus importes.
    monedas_vistas = {n: set() for n in nombres_cuentas}
    for f in filas:
        # La moneda del importe es la de la cuenta en la que se registra la operación,
        # no la de la contrapartida (una transferencia en USD a una cuenta en euros
        # no convierte la cuenta de euros en una cuenta en dólares).
        if f["cuenta"] and f["moneda"]:
            monedas_vistas[f["cuenta"]].add(f["moneda"])
    ref_cuenta, cuentas_datos = {}, {}
    for nombre in nombres_cuentas:
        vistas = monedas_vistas.get(nombre) or set()
        # Portfolio Performance solo escribe la moneda cuando NO es el euro: si en
        # una cuenta ningún importe lleva prefijo, todos sus movimientos son en euros
        # (pasa en las cuentas de Gina, que se llaman «… USD» pero llevan euros).
        moneda = (sorted(vistas)[0] if len(vistas) == 1
                  else _moneda_por_nombre(nombre) if vistas else "EUR")
        ref = f"cuenta:{len(ref_cuenta) + 1}"
        ref_cuenta[nombre] = ref
        existente = next((c for c in cfg.get("cuentas", []) if c["nombre"] == nombre), None)
        datos = {"nombre": nombre, "tipo": _tipo_cuenta(nombre), "moneda": moneda,
                 "entidad": _entidad_cuenta(nombre), "propietario": _propietario_por_nombre(nombre)}
        cuentas_datos[ref] = datos
        plan.cuentas.append({"ref": ref, "cuenta": existente and existente["id"], "datos": datos})

    def cuenta_moneda(nombre):
        return (cuentas_datos.get(ref_cuenta.get(nombre, "")) or {}).get("moneda") or "EUR"

    def cuenta_propietario(nombre):
        return (cuentas_datos.get(ref_cuenta.get(nombre, "")) or {}).get("propietario") or "david"

    # ---------------------------------------------------------------- saldos por cuenta
    saldos = {n: {"serie": {}, "acum": 0.0} for n in nombres_cuentas}

    def mueve(nombre, importe, moneda, fecha, signo):
        if not nombre or not importe:
            return
        destino = cuenta_moneda(nombre)
        v = a_moneda(importe, moneda, destino, fecha)
        if v is None:
            return
        s = saldos[nombre]
        s["acum"] = round(s["acum"] + signo * v, 2)
        s["serie"][fecha] = s["acum"]

    # ---------------------------------------------------------------- productos
    prod_ref, prod_info = {}, {}

    def producto_de(nombre, fila, moneda_fila):
        if nombre in prod_ref:
            return prod_ref[nombre]
        clave = _normaliza(nombre)
        ficha = CATALOGO_PP.get(clave)
        if not ficha and CODIGO_MORNINGSTAR.match(nombre.strip()):
            # El nombre ya es el código: no hay nada que adivinar.
            ficha = ("fondo", "yahoo", nombre.strip().upper(), None)
        if not ficha and re.fullmatch(r".+ [a-z]", clave):
            # PP le pega la clase al final («VINCI S.A.  A»): se prueba sin ese token,
            # que es como está en el catálogo. Solo se acepta si el nombre recortado
            # existe, así que no hay riesgo de acertar mal.
            ficha = CATALOGO_PP.get(clave.rsplit(" ", 1)[0])
        moneda_cuenta = cuenta_moneda(fila["cuenta"]) if fila.get("cuenta") else "EUR"
        if ficha:
            tipo, fuente, codigo, moneda = ficha
            moneda = moneda or moneda_fila or moneda_cuenta
        else:
            tipo, fuente, codigo = "otro", "manual", ""
            moneda = moneda_fila or moneda_cuenta
        propietario = cuenta_propietario(fila["cuenta"]) if fila.get("cuenta") else "david"
        datos = {"nombre": nombre, "corto": " ".join(nombre.split())[:24], "tipo": tipo,
                 "fuente": fuente, "codigo": codigo, "moneda": moneda, "largoPlazo": True,
                 "propietario": propietario, "cuenta": ref_cuenta.get(fila.get("cuenta") or "", ""),
                 "entidad": _entidad_cuenta(fila.get("cuenta") or "")}
        if fuente == "manual":
            # Sin precio en internet: se le pone su coste para que no falte nada en el
            # panel y aparece en «Valores sin cotización automática» para que ajustes tú.
            datos["revision"] = "valor a coste, pendiente de fijar"
        existente = _producto_existente(cfg, "", nombre)
        if existente:
            datos["id"] = existente["id"]      # se reutiliza y se le actualiza la ficha
            ref = existente["id"]
        else:
            ref = f"nuevo:{len(plan.productos_nuevos) + 1}"
        plan.productos_nuevos.append({"ref": ref, "datos": datos, "precio": None,
                                      "monedaPrecio": None, "fecha": None, "mercado": None})
        prod_ref[nombre] = ref
        prod_info[ref] = {"nombre": nombre, "manual": (fuente == "manual"), "movs": []}
        return ref

    # ---------------------------------------------------------------- filas
    sin_cambio = 0
    ceros = []
    for f in filas:
        tipo, signo = PP_TIPOS.get(f["tipo_pp"], (None, 0))
        if tipo is None:
            plan.error(f["fila"], f"El tipo «{celda_tipo(f)}» no lo sé interpretar.")
            continue
        if not f["neto"]:
            ceros.append(f["fila"])       # una comisión de 0,00 no es ningún movimiento
            continue
        moneda = f["moneda"] or cuenta_moneda(f["cuenta"])
        importe_eur, tasa = a_eur(f["neto"], moneda, f["fecha"])
        if importe_eur is None:
            plan.error(f["fila"], f"No encuentro el cambio de {moneda} a euros del "
                                  f"{almacen.fmt_fecha(f['fecha'])}.")
            sin_cambio += 1
            continue
        com_eur, _ = a_eur(f["comision"], moneda, f["fecha"])
        imp_eur, _ = a_eur(f["impuestos"], moneda, f["fecha"])
        # Portfolio Performance anota la retención de unos dividendos en «Impuestos»
        # y la de otros en «Comisiones». Un dividendo no tiene comisión: se unifica
        # en impuestos para que los totales coincidan con los de PP.
        if tipo == "dividendo" and com_eur and not imp_eur:
            imp_eur, com_eur = com_eur, 0.0
        ref_c = ref_cuenta.get(f["cuenta"])
        ref_cp = ref_cuenta.get(f["contrapartida"])
        hay_cp = bool(f["contrapartida"]) and f["contrapartida"] != f["cuenta"]
        nota = f["nota"]

        # --- efectivo en las cuentas: se recalcula siempre, igual que en Portfolio Performance
        if tipo == "compra":
            mueve(f["contrapartida"] if hay_cp else f["cuenta"], f["neto"], moneda, f["fecha"], -1)
        elif tipo == "venta":
            mueve(f["contrapartida"] if hay_cp else f["cuenta"], f["neto"], moneda, f["fecha"], 1)
        elif tipo == "transferencia":
            mueve(f["cuenta"], f["neto"], moneda, f["fecha"], signo)
            if hay_cp:
                v = a_moneda(f["neto"], moneda, cuenta_moneda(f["contrapartida"]), f["fecha"])
                if v is not None:
                    s = saldos[f["contrapartida"]]
                    s["acum"] = round(s["acum"] - signo * v, 2)
                    s["serie"][f["fecha"]] = s["acum"]
        elif tipo != "traspaso" and tipo != "entrega":
            # La entrega entrante (escisión) NO mueve dinero: el «valor neto» del CSV
            # es el coste que se le asigna a los títulos que entran, no un abono.
            mueve(f["cuenta"], f["neto"], moneda, f["fecha"], signo)

        # --- el movimiento en sí
        es_fx = tipo == "comision" and sin_tildes(f["activo"]).lower() in ("eur usd", "usd eur")
        ref_p = producto_de(f["activo"], f, moneda) if f["activo"] and not es_fx else None
        if not ref_p and not ref_c:
            plan.error(f["fila"], "No tiene ni producto ni cuenta: no sé dónde apuntarlo.")
            continue
        marcas = []
        if moneda != "EUR":
            marcas.append(f"convertido de {moneda}")
        if es_fx:
            marca_nota = "Cambio de divisa " + f["activo"]
            nota = (nota + " · " + marca_nota).strip(" ·")
        mv = {"fila": f["fila"], "fecha": f["fecha"], "tipo": tipo, "producto": ref_p,
              "unidades": f["unidades"], "importe": round(importe_eur, 2),
              "importeOriginal": round(f["neto"], 6), "monedaOriginal": moneda,
              "tipoCambio": round(tasa, 8) if tasa else 1.0,
              "comision": round(com_eur, 2) if com_eur else None,
              "impuestos": round(imp_eur, 2) if imp_eur else None,
              "cuenta": ref_c, "contrapartida": ref_cp if hay_cp else None,
              "propietario": cuenta_propietario(f["cuenta"]) if f["cuenta"] else None,
              "nota": nota, "marcas": marcas, "origen": "portfolio", "fuente": f["fuente"]}
        if hay_cp and moneda != cuenta_moneda(f["contrapartida"]):
            v = a_moneda(f["neto"], moneda, cuenta_moneda(f["contrapartida"]), f["fecha"])
            if v is not None:
                mv["contrapartidaImporte"] = round(v, 6)
                mv["contrapartidaMoneda"] = cuenta_moneda(f["contrapartida"])
        plan.movimientos.append(mv)
        if ref_p:
            prod_info[ref_p]["movs"].append(mv)

    # ---------------------------------------------------------------- saldos -> valoraciones
    efectivos = []
    for nombre in nombres_cuentas:
        serie = saldos[nombre].get("serie") or {}
        if not serie:
            continue
        ultimo = sorted(serie)[-1]
        if abs(serie[ultimo]) < 0.005:
            continue          # una cuenta de valores sin efectivo: no es un saldo que mostrar
        ref = ref_cuenta[nombre]
        existente = _producto_existente(cfg, "", nombre)
        p_ref = (existente or {}).get("id") or f"nuevo:{len(plan.productos_nuevos) + 1}"
        plan.productos_nuevos.append({
            "ref": p_ref,
            "datos": {"id": (existente or {}).get("id"), "nombre": nombre,
                      "corto": " ".join(nombre.split())[:24], "tipo": "efectivo",
                      "fuente": "manual", "moneda": cuenta_moneda(nombre), "largoPlazo": True,
                      "propietario": cuenta_propietario(nombre), "cuenta": ref,
                      "entidad": _entidad_cuenta(nombre)},
            "precio": None, "monedaPrecio": None, "fecha": None, "mercado": None})
        efectivos.append((p_ref, serie))
    for p_ref, serie in efectivos:
        for fecha in sorted(serie):
            plan.valoraciones.append({"fila": f"cuenta {p_ref}", "producto": p_ref,
                                      "fecha": fecha, "valor": round(serie[fecha], 2)})

    # ---------------------------------------------------------------- valor a coste de los manuales
    for info in prod_info.values():
        if not info["manual"]:
            continue
        movs = sorted(info["movs"], key=lambda m: (m["fecha"], ORDEN_PP.get(m["tipo"], 9)))
        if not movs:
            continue
        lotes, coste, por_fecha = [], 0.0, {}
        for m in movs:
            t, u, imp = m["tipo"], float(m.get("unidades") or 0), float(m.get("importe") or 0)
            if t in ("compra", "entrega"):
                # Una entrega entrante entra a coste, igual que una compra.
                lotes.append([u, imp])
                coste += imp
            elif t == "venta":
                q = u
                while q > 1e-9 and lotes:
                    lu, lc = lotes[0]
                    toma = min(lu, q)
                    parte = lc * toma / lu if lu else 0.0
                    q -= toma
                    coste -= parte
                    lotes[0] = [lu - toma, lc - parte]
                    if lotes[0][0] <= 1e-9:
                        lotes.pop(0)
            por_fecha[m["fecha"]] = round(max(coste, 0.0), 2)
        ref = info["movs"][0]["producto"]
        for fecha in sorted(por_fecha):
            plan.valoraciones.append({"fila": f"coste {info['nombre']}", "producto": ref,
                                      "fecha": fecha, "valor": por_fecha[fecha]})

    if sin_cambio:
        plan.avisos.append(f"{sin_cambio} filas en {', '.join(cambios)} se han dejado fuera por no "
                           "encontrar el cambio de esa divisa a euros.")
    if ceros:
        plan.avisos.append(f"{len(ceros)} filas con importe 0,00 (p. ej. la {ceros[0]}) se han omitido: "
                           "no cambian ni el saldo ni el patrimonio.")
    if any(p["datos"].get("revision") for p in plan.productos_nuevos):
        n = sum(1 for p in plan.productos_nuevos if p["datos"].get("revision"))
        plan.avisos.append(f"{n} productos no cotizan en internet: les he puesto su coste como valor "
                           "para que no falte nada. Ajústalos en «Valores sin cotización automática».")
    return plan


def celda_tipo(f):
    return f.get("tipo_pp") or ""


ORDEN_PP = {"apertura": 0, "deposito": 1, "compra": 2, "entrega": 2, "comision": 3,
            "interes": 4, "impuesto": 5, "dividendo": 6, "venta": 7, "retirada": 8,
            "transferencia": 9, "traspaso": 10, "cambio_divisa": 11, "saldo": 12}


# ---------------------------------------------------------------- aplicar

def aplicar(cfg, plan, excluir=None, tipos=None, vinculos=None):
    """Ejecuta el plan sobre cfg (la real o una copia) y devuelve el informe.

    `vinculos` es lo que el usuario ha vinculado a un precio en la vista previa:
    {ref del producto: {fuente, codigo, nombre, moneda, identificador, tipo}}.

    No modifica `plan`: la vista previa llama a esta función y después la
    confirmación la vuelve a llamar, así que todo lo que se añada va en listas
    aparte (si no, se duplicaría)."""
    ids, errores = {}, list(plan.errores)
    productos_extra, movs_extra, avisos_extra, ajustes = [], [], [], {}
    series_ajustadas = []      # [(ref del efectivo, [(fecha, cuánto sube)])]

    # 0) Exclusiones. Desmarcar una entidad en la vista previa significa «no lo
    # importes ahora», nunca «bórralo» (ver el barrido de más abajo). Un producto
    # que dependa de una cuenta excluida se va con ella: sin su cuenta no tiene
    # de dónde salir el dinero.
    fuera_cuentas, fuera_prod = _exclusiones(excluir)
    for n in list(getattr(plan, "productos_nuevos", None) or []):
        if n["datos"].get("cuenta") in fuera_cuentas:
            fuera_prod.add(n["ref"])

    # 0b) ¿Qué «cuentas» del CSV son en realidad un producto? Lo elige el usuario
    # en la vista previa (o lo detecta solo el importador), y llega como
    # {ref: tipo} para no tener que tocar el plan. La cuenta se queda como
    # monedero de dinero y el producto es el plan/fondo.
    tipos = tipos or {}
    conversiones = {}
    for c in getattr(plan, "cuentas", None) or []:
        tipo = tipos.get(c["ref"], c["datos"].get("tipo"))
        if tipo in TIPOS_INVERSION and c["datos"].get("nombre"):
            conversiones[c["ref"]] = tipo

    # 0c) Los movimientos que sí se importan. Se calcula ANTES de las aportaciones
    # sintéticas: si se excluye el producto pero no su cuenta, no puede añadirse
    # un ingreso para una compra que ya no se va a traer.
    movs_vivos = [m for m in plan.movimientos
                  if _se_importa(m, fuera_cuentas, fuera_prod)]

    # 1) las cuentas, primero: los productos y movimientos apuntan a sus ids
    ids_cuentas = {}
    for c in getattr(plan, "cuentas", None) or []:
        if c["ref"] in fuera_cuentas:
            continue                        # no se crea ni se toca
        datos = dict(c["datos"])
        if c["ref"] in conversiones:
            datos["tipo"] = "efectivo"      # la cuenta es el monedero, no el plan
        elif c["ref"] in tipos:
            datos["tipo"] = tipos[c["ref"]]
        if c.get("cuenta"):
            datos["id"] = c["cuenta"]
        try:
            guardada = almacen.guarda_cuenta(cfg, datos)
        except almacen.ErrorValidacion as e:
            errores.append({"fila": c["ref"], "mensaje": " ".join(e.errores)})
            continue
        ids_cuentas[c["ref"]] = guardada["id"]
        # Los saldos anotados antes para esa cuenta ya no valen.
        viejos = [p["id"] for p in cfg.get("productos", [])
                  if p.get("cuenta") == guardada["id"] and p.get("tipo") in almacen.SOLO_SALDO]
        if viejos:
            cfg["valoraciones"] = [v for v in cfg.get("valoraciones", [])
                                   if v.get("producto") not in viejos]
    c_real = lambda ref: ids_cuentas.get(ref, ref)

    # 1b) La cuenta convertida: un solo producto (el que ya trae el CSV o uno
    # nuevo con el nombre de la cuenta) y las aportaciones emparejadas.
    for c in getattr(plan, "cuentas", None) or []:
        tipo = conversiones.get(c["ref"])
        if not tipo:
            continue
        cuenta_id = ids_cuentas.get(c["ref"])
        if not cuenta_id:
            continue
        nombre = c["datos"]["nombre"]
        fuente, codigo = _fuente_para(nombre, tipo)
        # ¿El CSV ya trae el producto de inversión de esta cuenta? (las compras
        # apuntan a él). Si es así se reutiliza: nunca se duplica.
        ya = []
        for mv in plan.movimientos:
            if mv.get("cuenta") == c["ref"] and mv.get("producto") and mv["producto"] not in ya:
                ya.append(mv["producto"])
        if ya:
            ajustes[ya[0]] = {"tipo": tipo}
            if fuente:
                ajustes[ya[0]]["fuente"] = fuente
                ajustes[ya[0]]["codigo"] = codigo
        else:
            existente = _producto_existente_de(cfg, nombre, False)
            ref_prod = (existente or {}).get("id") or f"cuenta-prod:{c['ref']}"
            datos_prod = {"id": (existente or {}).get("id"), "nombre": nombre,
                          "corto": " ".join(nombre.split())[:24], "tipo": tipo,
                          "fuente": fuente or "manual", "codigo": codigo or "",
                          "moneda": c["datos"].get("moneda") or "EUR", "largoPlazo": True,
                          "propietario": c["datos"].get("propietario") or "david",
                          "cuenta": cuenta_id, "entidad": c["datos"].get("entidad", "")}
            if not fuente:
                datos_prod["revision"] = "valor a coste, pendiente de fijar"
            productos_extra.append({"ref": ref_prod, "datos": datos_prod})
        # El dinero del plan no puede salir de la nada: cada compra con su ingreso.
        # Solo cuentan los movimientos que de verdad se importan (movs_vivos).
        faltan, ajustes_serie = _aportaciones_que_faltan(
            plan, c["ref"], nombre, c["datos"].get("moneda") or "EUR", movs_vivos)
        if faltan:
            movs_extra += faltan
            # El saldo anotado de la cuenta (la serie que crea el importador) tiene
            # que subir lo mismo: si no, la cuenta sigue saliendo en negativo.
            ref_efectivo = next((p["ref"] for p in plan.productos_nuevos
                                 if p["datos"].get("cuenta") == c["ref"]
                                 and p["datos"].get("tipo") in almacen.SOLO_SALDO), None)
            series_ajustadas.append((ref_efectivo, ajustes_serie))
            avisos_extra.append(
                f"{nombre}: {len(faltan)} aportación(es) venían sin su ingreso en el CSV; "
                "se han añadido para que la cuenta de efectivo no quede en negativo.")

    # 2) los productos (sin duplicar: si ya existe uno con ese nombre, se reutiliza)
    for n in list(plan.productos_nuevos) + productos_extra:
        if n["ref"] in fuera_prod:
            continue                        # excluido: no se crea ni se actualiza
        datos = dict(n["datos"])
        datos.update(ajustes.get(n["ref"], {}))
        # Lo que el usuario haya vinculado a un precio en la vista previa manda
        # sobre lo que traiga el CSV, y va ANTES de buscar el producto existente:
        # así el nombre canónico entra en el deduplicado por familia.
        vinc = (vinculos or {}).get(n["ref"]) or {}
        if not (vinc.get("fuente") and vinc.get("codigo")):
            vinc = {}                       # sin fuente y código no es un vínculo
        if vinc:
            nombre_vinc = (vinc.get("nombre") or "").strip()
            if nombre_vinc and nombre_vinc != datos.get("nombre"):
                # El nombre del CSV no se pierde: queda en la descripción.
                datos.setdefault("papel", "")
                if not datos["papel"]:
                    datos["papel"] = f"Importado del CSV como «{datos.get('nombre', '')}»."
                datos["nombre"] = nombre_vinc
                datos["corto"] = " ".join(nombre_vinc.split())[:24]
            for campo in ("fuente", "codigo", "moneda", "identificador"):
                if vinc.get(campo):
                    datos[campo] = vinc[campo]
            if vinc.get("tipo") and not datos.get("tipo"):
                datos["tipo"] = vinc["tipo"]
            datos.pop("revision", None)     # ya cotiza: el aviso sobra
        if datos.get("fuente") not in (None, "", "manual"):
            datos.pop("revision", None)
        if datos.get("cuenta"):
            datos["cuenta"] = c_real(datos["cuenta"])
        if not datos.get("id"):
            existente = _producto_existente(
                cfg, datos.get("identificador") or datos.get("codigo") or "", None)
            if not existente:
                # Por nombre solo vale uno de la misma familia: el contenedor de
                # efectivo de una cuenta y su activo pueden llamarse igual.
                existente = _producto_existente_de(
                    cfg, datos.get("nombre") or "",
                    datos.get("tipo") in almacen.SOLO_SALDO)
            if existente:
                datos["id"] = existente["id"]
        try:
            prod, _ = almacen.guarda_producto(cfg, datos)
        except almacen.ErrorValidacion as e:
            errores.append({"fila": n["ref"], "mensaje": " ".join(e.errores)})
            continue
        ids[n["ref"]] = prod["id"]
    real = lambda ref: ids.get(ref, ref)

    # Ids REALES de la cartera de lo que el usuario ha excluido: sirven para no
    # borrar lo que ya había. Excluir es «no lo importes ahora», no «bórralo».
    ids_fuera_prod = {n["datos"]["id"] for n in list(plan.productos_nuevos) + productos_extra
                      if n["ref"] in fuera_prod and n["datos"].get("id")}
    ids_fuera_cuenta = {c["cuenta"] for c in (getattr(plan, "cuentas", None) or [])
                        if c["ref"] in fuera_cuentas and c.get("cuenta")}

    def es_de_excluida(m):
        return (m.get("producto") in ids_fuera_prod
                or m.get("cuenta") in ids_fuera_cuenta
                or m.get("contrapartida") in ids_fuera_cuenta)

    sustituidos = 0
    if getattr(plan, "reemplazarTodo", None):
        antes = len(cfg["movimientos"])
        cfg["movimientos"] = [m for m in cfg["movimientos"]
                              if m.get("origen") != plan.reemplazarTodo
                              or es_de_excluida(m)]
        sustituidos += antes - len(cfg["movimientos"])
    for ref, origen in plan.reemplazar:
        if real(ref) in ids_fuera_prod:
            continue                        # excluido: no se le borra nada
        antes = len(cfg["movimientos"])
        cfg["movimientos"] = [m for m in cfg["movimientos"]
                              if not (m.get("producto") == real(ref) and m.get("origen") == origen)]
        sustituidos += antes - len(cfg["movimientos"])

    def firma(m):
        return (m.get("producto"), m.get("cuenta"), m["fecha"], m["tipo"],
                round(float(m.get("unidades") or 0), 4), round(float(m.get("importe") or 0), 2))
    existentes = {firma(m) for m in cfg["movimientos"]}

    añadidos, duplicados, filas = 0, 0, []
    orden = {"apertura": 0, "deposito": 1, "compra": 2, "entrega": 2, "comision": 3,
             "interes": 4, "impuesto": 5, "dividendo": 6, "venta": 7, "retirada": 8,
             "transferencia": 9, "traspaso": 10, "cambio_divisa": 11, "saldo": 12}
    for mv in sorted(list(movs_vivos) + movs_extra,
                     key=lambda m: (m["fecha"], orden.get(m["tipo"], 9), m["fila"])):
        claves = ("fecha", "tipo", "unidades", "importe", "comision", "impuestos", "nota",
                  "importeOriginal", "monedaOriginal", "tipoCambio", "propietario",
                  "contrapartidaImporte", "contrapartidaMoneda", "fuente")
        datos = {k: mv[k] for k in claves if mv.get(k) is not None}
        if mv.get("producto"):
            datos["producto"] = real(mv["producto"])
        if mv.get("cuenta"):
            datos["cuenta"] = c_real(mv["cuenta"])
        if mv.get("contrapartida"):
            datos["contrapartida"] = c_real(mv["contrapartida"])
        estado = "nuevo"
        if firma(datos) in existentes:
            duplicados += 1
            estado = "repetido"
        else:
            try:
                guardado = almacen.guarda_movimiento(cfg, datos)
                guardado["origen"] = mv.get("origen", "portfolio")
                añadidos += 1
            except almacen.ErrorValidacion as e:
                errores.append({"fila": mv["fila"], "mensaje": " ".join(e.errores)})
                estado = "error"
        filas.append({"fila": mv["fila"], "fecha": mv["fecha"],
                      "producto": datos.get("producto"), "cuenta": datos.get("cuenta"),
                      "tipo": mv["tipo"],
                      "unidades": mv.get("unidades"), "importe": mv["importe"],
                      "marcas": mv.get("marcas") or [],
                      "estado": estado})

    saldos = 0
    for v in plan.valoraciones:
        if v.get("producto") in fuera_prod:
            continue                        # los saldos de un producto excluido no se traen
        valor = v["valor"]
        # La serie de saldo de una cuenta con aportaciones añadidas sube lo mismo.
        for ref_ef, deltas in series_ajustadas:
            if v.get("producto") == ref_ef:
                for fecha, delta in deltas:
                    if v["fecha"] >= fecha:
                        valor = round(valor + delta, 2)
        try:
            almacen.guarda_valoracion(cfg, {"producto": real(v["producto"]), "fecha": v["fecha"], "valor": valor})
            saldos += 1
            filas.append({"fila": v["fila"], "fecha": v["fecha"], "producto": real(v["producto"]), "tipo": "saldo",
                          "unidades": None, "importe": valor, "marcas": [], "estado": "nuevo"})
        except almacen.ErrorValidacion as e:
            errores.append({"fila": v["fila"], "mensaje": " ".join(e.errores)})

    def total(t):
        return round(sum(f["importe"] for f in filas if f["tipo"] == t and f["estado"] == "nuevo"), 2)
    nombres = {p["id"]: p.get("corto") or p["nombre"] for p in cfg["productos"]}
    nombres_c = {c["id"]: c["nombre"] for c in cfg.get("cuentas", [])}
    for f in filas:
        f["productoNombre"] = (nombres.get(f["producto"]) or nombres_c.get(f.get("cuenta"))
                               or f["producto"] or f.get("cuenta") or "")
    return {
        "añadidos": añadidos, "repetidos": duplicados, "saldos": saldos, "sustituidos": sustituidos,
        "errores": sorted(errores, key=lambda e: (str(type(e["fila"])), str(e["fila"]).zfill(6))),
        "avisos": list(plan.avisos) + avisos_extra,
        "totales": {"compras": total("compra"), "ventas": total("venta"),
                    "dividendos": total("dividendo"), "comisiones": total("comision"),
                    "intereses": total("interes"), "impuestos": total("impuesto"),
                    "depositos": total("deposito"), "retiradas": total("retirada"),
                    "transferencias": total("transferencia"),
                    "numCompras": sum(1 for f in filas if f["tipo"] == "compra" and f["estado"] == "nuevo")},
        "cuentasNuevas": [{"ref": c["ref"], "datos": dict(c["datos"]),
                           "existente": bool(c.get("cuenta"))}
                          for c in getattr(plan, "cuentas", None) or []],
        "productosNuevos": [{**n["datos"], "ref": n["ref"], "id": ids.get(n["ref"]),
                             "excluido": n["ref"] in fuera_prod,
                             "precio": n.get("precio"),
                             "monedaPrecio": n.get("monedaPrecio"), "fechaPrecio": n.get("fecha"),
                             "mercado": n.get("mercado")}
                            for n in list(plan.productos_nuevos) + productos_extra],
        # Lo que se ha quedado fuera, ya con la cascada aplicada: el navegador lo
        # usa para volver a pintar las casillas después de recalcular.
        "excluidas": {"cuentas": sorted(fuera_cuentas),
                      "productos": sorted(fuera_prod)},
        "filas": sorted(filas, key=lambda f: f["fecha"], reverse=True),
    }


def vista_previa(cfg, plan, excluir=None, tipos=None, vinculos=None):
    """El mismo informe que dará aplicar(), sin tocar la cartera de verdad."""
    return aplicar(copy.deepcopy(cfg), plan, excluir=excluir, tipos=tipos, vinculos=vinculos)
