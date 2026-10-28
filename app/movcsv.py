# -*- coding: utf-8 -*-
"""
movcsv.py  ·  Movimientos de UN producto desde un CSV
=====================================================
Formato (la cabecera es obligatoria):

    fecha,tipo,unidades,importe,comision,impuestos,nota
    2025-01-15,compra,10,1000.00,0,0,Aporte inicial
    2025-06-30,dividendo,,25.50,0,5.10,Dividendo semestral

- `fecha`: acepta varios formatos (ver `_fecha`). Lo normal es AAAA-MM-DD, pero
  también vale con hora detrás (AAAA-MM-DD HH:MM:SS) y a la española o a la
  americana (DD/MM/AAAA, MM/DD/AAAA, con guiones o puntos).
- `tipo`: los mismos que usa la app (compra, venta, dividendo, interes, comision,
  impuesto, deposito, retirada, transferencia…). Se aceptan también sus etiquetas
  («Dividendo o cupón»), con o sin tildes y en cualquier caja.
- Números con **punto o coma** decimal, y con separador de miles opcional.
- `nota` es texto libre.

Este módulo SOLO lee y valida texto: no toca la cartera ni conoce la app. La
aplicación de los movimientos vive en `servidor.py`, que es quien sabe de cuentas
de efectivo y de saldos.
"""
import csv
import datetime as dt
import io
import re
import unicodedata

from . import almacen, importar

COLUMNAS = ("fecha", "tipo", "unidades", "importe", "comision", "impuestos", "nota")
# Sin estas dos no hay movimiento que anotar; el resto puede faltar en el fichero.
OBLIGATORIAS = ("fecha", "tipo")


def _plano(txt):
    """Minúsculas, sin tildes y con los espacios colapsados. Para cabeceras y tipos."""
    s = unicodedata.normalize("NFD", str(txt or "")).encode("ascii", "ignore").decode()
    return " ".join(s.lower().replace("_", " ").split())


# «Dividendo o cupón» -> dividendo, «interés» -> interes, etc. Se construye desde
# almacen.TIPOS_MOV para que no haya dos listas que se puedan desincronizar.
_ALIAS = {}
for _clave, _etiqueta in almacen.TIPOS_MOV.items():
    _ALIAS[_plano(_clave)] = _clave
    _ALIAS[_plano(_etiqueta)] = _clave
_ALIAS.update({"interés": "interes", "interes": "interes",
               "comisión": "comision", "comisiones": "comision",
               "impuestos": "impuesto", "retencion": "impuesto", "retención": "impuesto",
               "depósito": "deposito", "retirada de efectivo": "retirada",
               "traspaso de entrada": "traspaso", "venta parcial": "venta"})


# ------------------------------------------------------------------- fechas
# Dos formas: el año primero (ISO y sus primos) o el año al final (día/mes y sus
# primos). Detrás puede venir la hora, que se acepta y se ignora: de un movimiento
# solo nos importa el día.
_ANIO_PRIMERO = re.compile(
    r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})"
    r"(?:[ T]+(\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?$")
_DIA_MES = re.compile(
    r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})"
    r"(?:[ T]+(\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?$")

# Lo que se le enseña a quien se equivoca, tal cual, para que sepa qué vale.
FORMATOS_FECHA = ("AAAA-MM-DD, AAAA-MM-DD HH:MM:SS, DD/MM/AAAA, MM/DD/AAAA, "
                  "DD-MM-AAAA")


def _motivo_fecha(crudo):
    return (f"Fecha inválida: «{crudo}». Formatos aceptados: {FORMATOS_FECHA}.")


def _compone(anio, mes, dia, crudo):
    """La fecha como ISO, o ValueError con el motivo si no existe (31 de febrero)."""
    try:
        return dt.date(anio, mes, dia).isoformat()
    except ValueError:
        raise ValueError(_motivo_fecha(crudo)) from None


def _fecha(txt, convencion=None):
    """La fecha de una celda, en ISO. Devuelve `(iso, ambigua)`.

    Acepta el año primero (2026-10-05, 2026/10/05) y el año al final
    (05/10/2026, 10/05/2026, 05-10-2026), con la hora detrás opcional.

    `convencion` es el orden que ha delatado el resto del fichero ("dmy" o "mdy");
    si viene, se usa para las fechas en las que el día y el mes caben los dos en
    1..12. Si no viene, se resuelve fila a fila: manda el número que pase de 12 y,
    cuando ninguno pasa, se lee como **DD/MM** (español) marcándolo `ambigua` para
    que el llamante pueda avisar.

    Con `convencion="iso"` (lo elige el usuario en el desplegable) solo valen las
    fechas que empiezan por el año: así no hay forma de equivocarse de orden.

    Lanza ValueError con el motivo si no se reconoce.
    """
    s = str(txt or "").strip().replace("\u00a0", " ")
    m = _ANIO_PRIMERO.match(s)
    if m:
        return _compone(int(m.group(1)), int(m.group(2)), int(m.group(3)), s), False
    m = _DIA_MES.match(s)
    if m:
        if convencion == "iso":
            raise ValueError(
                f"Fecha inválida: «{s}». Con el formato «AAAA-MM-DD (ISO)» solo valen "
                "las fechas que empiezan por el año, como 2026-10-05.")
        x, y, anio = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if x > 12 and y > 12:
            raise ValueError(_motivo_fecha(s))
        if convencion == "mdy":          # lo ha elegido el usuario: manda él
            if x > 12:
                raise ValueError(
                    f"Fecha inválida: «{s}». Con «MM/DD/AAAA» el mes sería {x}, que no "
                    "existe. Cambia «Formato de fecha» si va día primero.")
            dia, mes, ambigua = y, x, False
        elif convencion == "dmy":
            if y > 12:
                raise ValueError(
                    f"Fecha inválida: «{s}». Con «DD/MM/AAAA» el mes sería {y}, que no "
                    "existe. Cambia «Formato de fecha» si va mes primero.")
            dia, mes, ambigua = x, y, False
        elif x > 12:                     # 25/10: solo puede ser día/mes
            dia, mes, ambigua = x, y, False
        elif y > 12:                     # 10/25: solo puede ser mes/día
            dia, mes, ambigua = y, x, False
        else:                            # 10/05: las dos caben -> DD/MM + aviso
            dia, mes, ambigua = x, y, True
        return _compone(anio, mes, dia, s), ambigua
    raise ValueError(_motivo_fecha(s))


def _convencion(filas, celda):
    """El orden día/mes que delata el fichero, o None si no hay forma de saberlo.

    Basta una fecha con el día > 12 (25/10/2026) para saber que va día primero, y
    una con el mes > 12 (10/25/2026) para saber que va mes primero. Si aparecen
    las dos cosas, el fichero se contradice y no se impone nada.
    """
    dmy = mdy = False
    for fila in filas:
        m = _DIA_MES.match(celda(fila, "fecha").replace("\u00a0", " "))
        if not m:
            continue
        x, y = int(m.group(1)), int(m.group(2))
        if x > 12 >= y:
            dmy = True
        elif y > 12 >= x:
            mdy = True
    if dmy and not mdy:
        return "dmy"
    if mdy and not dmy:
        return "mdy"
    return None


def _numero(txt):
    """Número con punto o coma decimal, o None si la celda está vacía.
    Acepta `1234.56`, `1234,56`, `1.234,56` y `1,234.56`: si aparecen los dos
    separadores, el último es el decimal; si solo hay uno, es el decimal.
    Lanza ValueError si no se puede leer.
    """
    s = str(txt or "").strip().replace(" ", "").replace("\u00a0", "")
    if not s:
        return None
    for malo in ("€", "$", "%"):
        s = s.replace(malo, "")
    tiene_punto, tiene_coma = "." in s, "," in s
    if tiene_punto and tiene_coma:
        decimal = "." if s.rfind(".") > s.rfind(",") else ","
        miles = "," if decimal == "." else "."
        s = s.replace(miles, "").replace(decimal, ".")
    elif tiene_coma:
        s = s.replace(",", ".")
    return float(s)


def _limpia_cabecera(nombres):
    """Deja solo las columnas que conocemos, sin tildes ni mayúsculas."""
    return [_plano(n) for n in nombres]


def plantilla(para="producto"):
    """CSV de ejemplo, para el botón «Descargar plantilla».

    Con `para="cuenta"` los ejemplos son de cuenta (depósito, interés): en una
    cuenta una compra o una venta se rechazan.
    """
    if para == "cuenta":
        filas = [
            list(COLUMNAS),
            ["2025-01-15", "deposito", "", "1000.00", "0", "0", "Entrada de dinero"],
            ["2025-02-28", "interes", "", "12.35", "0", "1.85", "Intereses del mes"],
            ["2025-03-10", "retirada", "", "200.00", "0", "0", "Salida a mi banco"],
        ]
    else:
        filas = [
            list(COLUMNAS),
            ["2025-01-15", "compra", "10", "1000.00", "0", "0", "Aporte inicial"],
            ["2025-06-30", "dividendo", "", "25.50", "0", "5.10", "Dividendo semestral"],
        ]
    salida = io.StringIO()
    w = csv.writer(salida, lineterminator="\n")
    w.writerows(filas)
    return salida.getvalue()


# --------------------------------------------------- export de Portfolio Performance
# El export «Todas las transacciones» de PP es otro mundo: separador `;`, trece
# columnas y sus propios nombres de tipo. En vez de repetir el mapeo, se reutiliza
# el del importador global (`importar.leer_portfolio`), que ya está probado y
# mantiene la tabla `PP_TIPOS`. Aquí solo se traduce su fila a la nuestra.
_PP_OBLIGATORIAS = ("fecha", "valor neto", "cuenta")


def _es_pp(cabecera):
    """¿La primera línea es la cabecera de un export de Portfolio Performance?"""
    return importar.es_portfolio_performance(cabecera)


def _clave(txt):
    """Para comparar nombres de activo con los del producto: sin tildes ni cajas."""
    return " ".join(_plano(txt).split())


def _activo_es(activo, producto):
    """¿La columna «Activo» de esa fila es este producto?

    Se compara con lo que el usuario ve y con lo que usa para identificarlo: el
    nombre, el corto, el ISIN/ticker y el código de la fuente.
    """
    if not producto:
        return True
    a = _clave(activo)
    if not a:
        return False
    candidatos = {_clave(producto.get(k)) for k in
                  ("nombre", "corto", "identificador", "codigo") if producto.get(k)}
    return a in candidatos


def _fechas_pp_no_iso(texto):
    """{número de línea: fecha tal cual} de las filas de PP cuya «Fecha» no va en ISO.

    Portfolio Performance escribe las fechas en ISO. Si alguna no lo está es que el
    fichero ha pasado por algo que las ha reescrito (Excel). Ahí NO se adivina el
    orden día/mes: leer «3/12/2026» como diciembre puede inventarse una fecha futura.
    """
    lineas = [l for l in texto.split("\n") if l.strip()]
    if not lineas:
        return {}
    cab = next(csv.reader([lineas[0]], delimiter=";"))
    try:
        i = [_plano(c) for c in cab].index("fecha")
    except ValueError:
        return {}
    malas = {}
    for n, linea in enumerate(lineas[1:], start=2):
        campos = next(csv.reader([linea], delimiter=";"))
        v = (campos[i].strip() if i < len(campos) else "")
        if v and not re.match(r"^\d{4}-\d{1,2}-\d{1,2}", v):
            malas[n] = v
    return malas


def es_pp(texto):
    """¿Este texto es un export de Portfolio Performance? (Lo usa el servidor para
    saber si el selector de formato de fecha pinta algo: con PP, no.)"""
    limpio = str(texto or "").lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    primera = next((l for l in limpio.split("\n") if l.strip()), "")
    return _es_pp(primera.replace(";", " "))


def _lee_pp(texto, avisos, producto, moneda):
    """Lee el CSV de PP tal cual. Devuelve la misma forma que `lee`."""
    crudas, error = importar.leer_portfolio(texto)
    if error:
        return [], [{"linea": 1, "motivo": error}]

    # ¿De qué producto son las filas? Si el fichero trae varios, solo entran las suyas.
    vistos = sorted({f.get("activo") for f in crudas if f.get("activo")})
    if producto:
        suyas = [f for f in crudas if _activo_es(f.get("activo"), producto)]
        if not suyas:
            nombre = producto.get("corto") or producto.get("nombre") or producto.get("id")
            pista = (" El CSV trae: " + ", ".join(vistos[:6]) + ".") if vistos else ""
            # `sin_match` lo lee la previsualización para ofrecer elegir el destino.
            return [], [{"linea": 1, "sin_match": True, "activos": vistos,
                         "motivo": f"Este CSV no tiene movimientos de «{nombre}»." + pista}]
        crudas = suyas
    else:
        crudas = list(crudas)

    moneda_elegida = (moneda or "").upper()
    no_iso = _fechas_pp_no_iso(texto)
    filas, errores = [], []
    for f in crudas:
        linea = f.get("fila") or 0
        if linea in no_iso:
            errores.append({"linea": linea, "motivo":
                            f"Fecha inválida: «{no_iso[linea]}». El CSV de Portfolio "
                            "Performance escribe las fechas en ISO (AAAA-MM-DD); esta "
                            "no lo está, así que no adivino el orden día/mes."})
            continue
        tipo_pp = f.get("tipo_pp") or ""
        tipo = (importar.PP_TIPOS.get(tipo_pp) or (None, 0))[0]
        if not tipo:
            errores.append({"linea": linea, "motivo":
                            f"Tipo de Portfolio Performance no reconocido: «{tipo_pp}»."})
            continue
        moneda = (f.get("moneda") or "").upper()
        if moneda and moneda_elegida and moneda != moneda_elegida:
            errores.append({"linea": linea, "motivo":
                            f"La fila viene en {moneda} y has elegido {moneda_elegida}. "
                            "Cambia la moneda del importador o separa esas filas."})
            continue
        filas.append({
            "linea": linea, "fecha": f["fecha"], "tipo": tipo,
            "unidades": f.get("unidades"), "importe": f.get("neto"),
            "comision": f.get("comision"), "impuestos": f.get("impuestos"),
            "nota": f.get("nota") or "",
        })

    if avisos is not None:
        avisos.append("He leído el CSV como export de Portfolio Performance: "
                      + f"{len(filas)} movimiento{'s' if len(filas) != 1 else ''}"
                      + (f" de «{crudas[0].get('activo')}»" if producto else "")
                      + ". Se han tomado «Valor neto de transacción» como importe, "
                      "«Títulos» como unidades y «Comisiones»/«Impuestos» como tales.")
    return filas, errores


def lee(texto, avisos=None, formato=None, producto=None, moneda=None):
    """Lee el CSV y devuelve `(filas, errores)`.

    - `filas`: ``[{"linea", "fecha", "tipo", "unidades", "importe", "comision",
      "impuestos", "nota"}]`` con lo que se puede anotar. Los números ya son float
      (o None si la celda venía vacía).
    - `errores`: ``[{"linea", "motivo"}]`` con las filas que no se pueden usar.
    - `avisos`: si se pasa una lista, se le añaden los avisos que no son errores
      (hoy, fechas ambiguas en las que no se sabe si el mes va primero).

    Si falta la cabecera devuelve ``([], [{"linea": 1, "motivo": ...}])``: el
    llamante decide que eso es un error de todo el fichero.
    """
    limpio = str(texto or "").lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if not limpio.strip():
        return [], [{"linea": 1, "motivo": "El archivo está vacío."}]

    # ¿Es el export de Portfolio Performance? Se mira la primera línea sin partirla:
    # ese fichero usa `;`, así que leerlo con el separador de casa daría una sola
    # columna y el error de cabecera de siempre.
    primera = next((l for l in limpio.split("\n") if l.strip()), "")
    if _es_pp(primera.replace(";", " ")):
        return _lee_pp(limpio, avisos, producto, moneda)

    lector = csv.reader(io.StringIO(limpio))
    try:
        cabecera = next(lector)
    except StopIteration:
        return [], [{"linea": 1, "motivo": "El archivo está vacío."}]

    nombres = _limpia_cabecera(cabecera)
    faltan = [c for c in OBLIGATORIAS if c not in nombres]
    if faltan:
        return [], [{"linea": 1, "motivo":
                     "Falta la cabecera: la primera fila tiene que traer los nombres de las "
                     f"columnas. No encuentro {', '.join(faltan)}. Columnas: "
                     + ", ".join(COLUMNAS) + "."}]

    # Columna -> índice; si el fichero no trae alguna, se queda vacía.
    pos = {c: nombres.index(c) for c in COLUMNAS if c in nombres}

    def celda(fila, col):
        i = pos.get(col)
        return fila[i].strip() if i is not None and i < len(fila) else ""

    # El orden día/mes se decide mirando TODO el fichero: si alguna fecha trae el
    # día (o el mes) por encima de 12, ya sabemos cómo van las demás y no hay nada
    # que adivinar. Solo si el fichero no lo delata se resuelve fila a fila.
    resto = list(lector)
    # El desplegable del modal manda: "dmy"/"mdy"/"iso" fijan el orden para todas
    # las filas; sin él (o con "auto") decide el propio fichero.
    elegido = (formato or "auto").lower()
    convencion = elegido if elegido in ("dmy", "mdy", "iso") else _convencion(resto, celda)

    filas, errores, ambiguas = [], [], []
    for n, fila in enumerate(resto, start=2):        # la 1 es la cabecera
        if not any((c or "").strip() for c in fila):
            continue                                   # líneas en blanco: se saltan
        motivo = None

        fecha_txt = celda(fila, "fecha")
        try:
            fecha, ambigua = _fecha(fecha_txt, convencion)
            if ambigua:
                ambiguas.append(n)
        except ValueError as e:
            fecha = None
            motivo = str(e)

        tipo_txt = celda(fila, "tipo")
        tipo = _ALIAS.get(_plano(tipo_txt))
        if not tipo and not motivo:
            motivo = (f"Tipo desconocido: «{tipo_txt}». Válidos: "
                      + ", ".join(sorted(t for t in almacen.TIPOS_MOV)) + ".")

        numeros = {}
        for col in ("unidades", "importe", "comision", "impuestos"):
            try:
                numeros[col] = _numero(celda(fila, col))
            except ValueError:
                crudo = celda(fila, col)
                if not motivo:
                    motivo = (f"«{col}» ilegible: «{crudo}». Usa números con punto o coma "
                              "decimal, por ejemplo 1000.50 o 1000,50.")
                numeros[col] = None

        if motivo:
            errores.append({"linea": n, "motivo": motivo})
            continue

        filas.append({
            "linea": n, "fecha": fecha, "tipo": tipo,
            "unidades": numeros["unidades"], "importe": numeros["importe"],
            "comision": numeros["comision"], "impuestos": numeros["impuestos"],
            "nota": celda(fila, "nota"),
        })

    if ambiguas and avisos is not None:
        cuantas = ("1 fecha ambigua" if len(ambiguas) == 1
                   else f"{len(ambiguas)} fechas ambiguas")
        donde = ", ".join(str(x) for x in ambiguas[:8]) + ("…" if len(ambiguas) > 8 else "")
        avisos.append(
            f"{cuantas} (línea{'s' if len(ambiguas) > 1 else ''} {donde}), tipo "
            "«10/5/2026»: las he leído como DD/MM/AAAA. Si son MM/DD/AAAA o tienes dudas, "
            "cambia «Formato de fecha» en esta ventana (o reformatea el CSV a ISO).")
    return filas, errores
