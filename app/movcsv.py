# -*- coding: utf-8 -*-
"""
movcsv.py  ·  Movimientos de UN producto desde un CSV
=====================================================
Formato (la cabecera es obligatoria):

    fecha,tipo,unidades,importe,comision,impuestos,nota
    2025-01-15,compra,10,1000.00,0,0,Aporte inicial
    2025-06-30,dividendo,,25.50,0,5.10,Dividendo semestral

- `fecha` en ISO (AAAA-MM-DD).
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
import unicodedata

from . import almacen

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


def plantilla():
    """CSV de ejemplo, para el botón «Descargar plantilla»."""
    filas = [
        list(COLUMNAS),
        ["2025-01-15", "compra", "10", "1000.00", "0", "0", "Aporte inicial"],
        ["2025-06-30", "dividendo", "", "25.50", "0", "5.10", "Dividendo semestral"],
    ]
    salida = io.StringIO()
    w = csv.writer(salida, lineterminator="\n")
    w.writerows(filas)
    return salida.getvalue()


def lee(texto):
    """Lee el CSV y devuelve `(filas, errores)`.

    - `filas`: ``[{"linea", "fecha", "tipo", "unidades", "importe", "comision",
      "impuestos", "nota"}]`` con lo que se puede anotar. Los números ya son float
      (o None si la celda venía vacía).
    - `errores`: ``[{"linea", "motivo"}]`` con las filas que no se pueden usar.

    Si falta la cabecera devuelve ``([], [{"linea": 1, "motivo": ...}])``: el
    llamante decide que eso es un error de todo el fichero.
    """
    limpio = str(texto or "").lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if not limpio.strip():
        return [], [{"linea": 1, "motivo": "El archivo está vacío."}]

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

    filas, errores = [], []
    for n, fila in enumerate(lector, start=2):        # la 1 es la cabecera
        if not any((c or "").strip() for c in fila):
            continue                                   # líneas en blanco: se saltan
        motivo = None

        fecha_txt = celda(fila, "fecha")
        try:
            fecha = dt.date.fromisoformat(fecha_txt[:10])
            fecha = fecha.isoformat()
        except ValueError:
            fecha = None
            motivo = (f"Fecha inválida: «{fecha_txt}». Tiene que ser AAAA-MM-DD, "
                      "por ejemplo 2025-01-15.")

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

    return filas, errores
