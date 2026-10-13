# -*- coding: utf-8 -*-
"""
servidor.py  ·  La app local
============================
Arranca un pequeño servidor web en tu propio ordenador (solo accesible desde él,
en 127.0.0.1) y abre el navegador. Tus datos nunca salen de la carpeta mis_datos;
a internet solo se sale para descargar precios.
"""

import datetime as dt
import json
import logging
import os
import re
import secrets
import sys
import threading
import unicodedata
import urllib.parse
import urllib.request
import webbrowser
from html.parser import HTMLParser

from flask import Flask, Response, jsonify, request, send_from_directory
from werkzeug.serving import make_server

import math
import copy

from . import almacen, buscar, exportar, importar, motor, plantilla, seguro

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(RAIZ, "app", "web")
# Otra carpeta de datos, solo para pruebas o capturas: PATRIMONIO_DATOS=ruta
DATOS = os.environ.get("PATRIMONIO_DATOS") or os.path.join(RAIZ, "mis_datos")
DEMO = os.path.join(RAIZ, "demo", "cartera.json")
PUERTO = int(os.environ.get("PATRIMONIO_PUERTO") or 8765)
# En qué interfaz escucha. Por defecto SOLO este ordenador; en un contenedor
# se pone PATRIMONIO_HOST=0.0.0.0 (combinado con PATRIMONIO_ORIGENES y con el
# cortafuegos o la red interna de Docker: nunca publicar el puerto a internet).
HOST = os.environ.get("PATRIMONIO_HOST") or "127.0.0.1"
HORAS_PRECIOS = 6          # al arrancar, se actualizan si tienen más de esto

app = Flask(__name__, static_folder=None)
app.json.sort_keys = False   # respeta el orden de tipos y listas al mandarlos al navegador
cerrojo = threading.RLock()  # el motor no admite dos cálculos (ni dos escrituras) a la vez


# ---------------------------------------------------------------- solo local
# Escuchar en 127.0.0.1 no basta: una web cualquiera del navegador puede
# intentar colarse de dos formas:
#   · DNS rebinding: su dominio pasa a resolver a 127.0.0.1 y el navegador
#     manda «Host: atacante.com». Sin más, LEERÍA tu cartera como si fuera
#     de su mismo origen (el navegador no aplica CORS en same-origin).
#   · CSRF: un formulario automático de otra web intenta ESCRIBIR (empezar de
#     cero o sobrescribir la cartera con una copia suya). El navegador manda
#     «Origin: https://otra.web» en ese POST.
# Este filtro corta las dos: el Host tiene que ser este ordenador y este
# puerto, y lo que escribe, además, tiene que venir del Origin (o del Referer)
# de esta misma app. Sin esas cabeceras no es un navegador (curl, un script),
# que no entran por aquí.
HOSTES_OK = ("127.0.0.1", "localhost", "::1", "[::1]")
PUERTO_ACTIVO = None   # lo fija main() con el puerto que queda escuchando

# Excepción para proxy inverso (Pangolin, nginx…): los Host y Origin que
# coincidan con estos orígenes también entran, p. ej.
#     PATRIMONIO_ORIGENES=https://rumbo.daesdel.es        (coma si hay varios)
# Sin esta variable el comportamiento es el de siempre: solo este ordenador.
_ext = [urllib.parse.urlsplit(o.strip().rstrip("/"))
        for o in os.environ.get("PATRIMONIO_ORIGENES", "").split(",") if o.strip()]
ORIGENES = tuple(f"{p.scheme}://{p.netloc}".lower() for p in _ext)
HOSTES_EXTRAS = frozenset(x for p in _ext
                          for x in (p.netloc.lower(), (p.hostname or "").lower()) if x)


def _host_valido(host):
    """¿Ese Host (o el netloc de un Origin) es este ordenador, este puerto
    o un orígen de proxy inverso permitido?"""
    h = (host or "").strip().lower()
    if h.startswith("["):                      # IPv6: [::1]:8765
        nombre, _, resto = h.partition("]")
        nombre, puerto = nombre + "]", resto[1:] if resto.startswith(":") else ""
    else:
        nombre, _, puerto = h.partition(":")
    if nombre in HOSTES_EXTRAS:                # p. ej. rumbo.daesdel.es vía Pangolin
        return True
    if nombre not in HOSTES_OK:
        return False
    if puerto and (not puerto.isdigit()
                   or PUERTO_ACTIVO is not None and int(puerto) != PUERTO_ACTIVO):
        return False
    return True


def _origen_local(url):
    """¿La URL de Origin (o solo esquema://host de un Referer) es esta app
    o un proxy inverso permitido?"""
    if (url or "").strip().rstrip("/").lower() in ORIGENES:
        return True
    try:
        p = urllib.parse.urlsplit(url)
        if p.scheme != "http" or not _host_valido(p.netloc):
            return False
        puerto = p.port
    except ValueError:                          # puerto sin números
        return False
    # Un Origin sin puerto usaría el 80: esta app nunca escucha en el 80.
    return PUERTO_ACTIVO is None or (puerto or 80) == PUERTO_ACTIVO


@app.before_request
def solo_este_ordenador():
    """Rechaza las peticiones que no vienen de esta app (nota más arriba)."""
    if not _host_valido(request.host):
        print(f"  [!] Petición rechazada: el Host «{request.host}» no es este ordenador.")
        return jsonify(ok=False, errores=["Petición rechazada: no es una llamada de esta app."]), 403
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origen = request.headers.get("Origin") or ""
        if not origen:
            ref = urllib.parse.urlsplit(request.headers.get("Referer") or "")
            origen = f"{ref.scheme}://{ref.netloc}" if ref.scheme and ref.netloc else ""
        if origen and not _origen_local(origen):
            print(f"  [!] Escritura rechazada: el origen «{origen}» no es esta app.")
            return jsonify(ok=False, errores=["Petición rechazada: no es una llamada de esta app."]), 403
    return None


# ---------------------------------------------------------------- archivos

def lee_json(ruta, defecto=None):
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return defecto


def escribe_json(ruta, datos):
    """Escribe en un archivo temporal y lo renombra: si se corta, no se pierde nada."""
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ruta)
    almacen.protege(ruta)


def modo():
    """'propio' si ya hay una cartera en mis_datos; si no, 'demo'."""
    return "propio" if os.path.exists(os.path.join(DATOS, "cartera.json")) else "demo"


def protege_datos():
    """Permisos 600 en los ficheros de datos: solo el dueño del sistema puede
    leerlos. Cubre también los ficheros antiguos, escritos antes de esta versión."""
    for base in (DATOS, os.path.join(DATOS, "copias")):
        if not os.path.isdir(base):
            continue
        for n in os.listdir(base):
            ruta = os.path.join(base, n)
            if os.path.isfile(ruta):
                almacen.protege(ruta)


def cartera():
    return lee_json(os.path.join(DATOS, "cartera.json") if modo() == "propio" else DEMO, {})


def ruta_calculado():
    return os.path.join(DATOS, f"calculado_{modo()}.json")


def estado():
    return lee_json(os.path.join(DATOS, "estado.json"), {})


# ---------------------------------------------------------------- cálculo

def recalcula(descargar):
    """Recalcula el panel. Con descargar=True baja antes los precios nuevos;
    con "faltan", solo los de productos que aún no tienen precios guardados."""
    with cerrojo:
        datos = motor.construir(cartera(), DATOS, descargar=descargar)
        est = estado()
        if descargar is True:
            est["preciosActualizados"] = dt.datetime.now().replace(microsecond=0).isoformat()
            escribe_json(os.path.join(DATOS, "estado.json"), est)
        if datos is not None:
            datos["modo"] = modo()
            datos["preciosActualizados"] = est.get("preciosActualizados")
        escribe_json(ruta_calculado(), datos)
        return datos


def precios_viejos():
    ultima = estado().get("preciosActualizados")
    if not ultima or not os.path.exists(ruta_calculado()):
        return True
    return dt.datetime.now() - dt.datetime.fromisoformat(ultima) > dt.timedelta(hours=HORAS_PRECIOS)


# ---------------------------------------------------------------- rutas

@app.get("/")
def inicio():
    return send_from_directory(WEB, "index.html")


@app.get("/datos.js")
def datos_js():
    datos = lee_json(ruta_calculado())
    if datos is None:
        # Nunca colgarse con un "null" guardado: si el cálculo no vale (cartera recién
        # importada, cálculo interrumpido...), se recalcula al vuelo y sin ir a internet.
        datos = recalcula(descargar=False)
    cuerpo = "window.VERSION = " + json.dumps(version_etiqueta()) + ";\n"
    cuerpo += "window.DATOS = " + json.dumps(datos, ensure_ascii=False, separators=(",", ":")) + ";\n"
    return Response(cuerpo, mimetype="application/javascript",
                    headers={"Cache-Control": "no-store"})


@app.post("/api/actualizar")
def api_actualizar():
    if modo() == "demo":
        return jsonify(ok=False, errores=[AVISO_DEMO]), 403
    hilo = _ACTUALIZA.get("hilo")
    if motor.PROGRESO.get("activo") or (hilo and hilo.is_alive()):
        return jsonify(ok=True, yaEnMarcha=True, progreso=_progreso())
    motor.PROGRESO.update(activo=True, total=0, hecho=0, pct=0, texto="", errores=[], error=None)
    hilo = threading.Thread(target=_actualiza_en_hilo, daemon=True, name="actualizar")
    _ACTUALIZA["hilo"] = hilo
    hilo.start()
    return jsonify(ok=True, progreso=_progreso())


_ACTUALIZA = {}


def _progreso():
    p = dict(motor.PROGRESO)
    hilo = _ACTUALIZA.get("hilo")
    activo = bool(motor.PROGRESO.get("activo")) and bool(hilo and hilo.is_alive())
    p["activo"] = activo
    p["activa"] = activo
    return p


def _tramos(n):
    """Cuántos productos se descargan de una vez (5 tramos: se ve avanzar el panel)."""
    return max(1, (n + 4) // 5)


def _pon_cache_en_marcha():
    """La cache de precios vive en mis_datos y sí se puede salir a internet."""
    motor.CACHE = os.path.join(DATOS, "cache")
    motor.SIN_RED = False
    motor.SOLO_FALTAN = False


def _actualiza_en_hilo():
    try:
        cfg = cartera()
        productos = [dict(p) for p in cfg.get("productos", [])]
        n = len(productos)
        # Unidades de progreso: consultas de precio + un recálculo por tramo +
        # referencias + cierre. Así las tres fases pesan lo mismo que tardan y
        # la barra avanza de forma lineal y siempre hacia delante.
        consultas = max(motor._prev_descargas(productos), 1)
        tam = _tramos(n)
        rangos = list(range(0, max(n, 1), tam)) or [0]
        total = consultas + len(rangos) + 2
        motor.PROGRESO.update(activo=True, total=total, hecho=0, pct=0, texto="", errores=[])
        hecho = {"n": 0}

        def avanza(u=1):
            hecho["n"] = min(total, hecho["n"] + u)
            motor.PROGRESO["hecho"] = hecho["n"]
            motor._pinta_pct()

        for i in rangos:
            lote = productos[i:i + tam]
            if not lote:
                break
            with cerrojo:
                motor.PROGRESO["activo"] = True
                motor.AVISOS.clear()
                _pon_cache_en_marcha()
                # El contador sigue de donde iba: el panel se ve llenar de verde.
                motor.descarga_series(lote, avance=hecho["n"], total=total)
                hecho["n"] = motor.PROGRESO.get("hecho") or hecho["n"]
                motor.PROGRESO["errores"] = sorted(set(motor.PROGRESO.get("errores", []) + list(motor.AVISOS)))
            # El panel se recalcula con lo que ya hay en la cache: sale vivo.
            with cerrojo:
                parcial = motor.construir(cartera(), DATOS, descargar=False)
                if parcial is not None:
                    parcial["modo"] = modo()
                    parcial["preciosActualizados"] = estado().get("preciosActualizados")
                    escribe_json(ruta_calculado(), parcial)
                avanza()
        with cerrojo:
            motor.PROGRESO["activo"] = True
            motor.PROGRESO["texto"] = "Referencias y cambio de divisa"
            motor.AVISOS.clear()
            _pon_cache_en_marcha()
            for sim in sorted({s for r in motor.REFERENCIAS.values() for s, _ in r["piezas"]} | {"USDEUR=X"}):
                motor.descargar_serie(sim)
            # Productos sin cotización con una URL de fuente: se lee el precio de ahí.
            hechos, fallidos = _actualiza_urls(cartera())
            if hechos:
                motor.PROGRESO["texto"] = f"{len(hechos)} valores leídos de su web"
            motor.PROGRESO["errores"] = sorted(set(motor.PROGRESO.get("errores", [])
                                                    + list(motor.AVISOS) + list(fallidos)))
            avanza()
        with cerrojo:
            datos = motor.construir(cartera(), DATOS, descargar=False)
            est = estado()
            est["preciosActualizados"] = dt.datetime.now().replace(microsecond=0).isoformat()
            escribe_json(os.path.join(DATOS, "estado.json"), est)
            if datos is not None:
                datos["modo"] = modo()
                datos["preciosActualizados"] = est["preciosActualizados"]
                escribe_json(ruta_calculado(), datos)
            avanza()
        motor.PROGRESO.update(activo=False, pct=100, texto="Listo")
    except Exception as e:
        logging.exception("Fallo al actualizar")
        motor.PROGRESO.update(activo=False, error=str(e))


@app.get("/api/actualizar/progreso")
def api_actualizar_progreso():
    """Para que el panel pinte la barra verde y se vaya actualizando en vivo."""
    datos = lee_json(ruta_calculado()) or {}
    return jsonify(progreso=_progreso(),
                   generado=datos.get("generado"),
                   avisos=(datos.get("avisos") or [])[:6])


# ------------------------------------- fuentes de precio a medida (JSON / tabla / web)
# Un producto sin cotización automática (oro físico, un depósito, un índice raro)
# puede leer su precio de una URL de tres formas, como en Portfolio Performance:
#   · «json»  → un JSON con rutas para la fecha y la cotización ($[*].datum)
#   · «tabla» → una tabla HTML con columnas de fecha y de precio
#   · «web»   → el precio marcado en una página (selector o el texto de al lado)
# «auto» (por defecto) sigue siendo el de siempre: JSON-LD, meta o el primer número.

def _http(url, timeout=15):
    req = urllib.request.Request(url, headers=motor.UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _ruta_json(nodo, ruta):
    """Ruta JSONPath a medias ($[*].datum, $.data[0].price, a.b) → lista de valores."""
    t = (ruta or "").strip()
    if not t:
        return []
    if t.startswith("$"):
        t = t[1:]
    vals, i = [nodo], 0
    while i < len(t) and vals:
        if t[i] == ".":
            j = i + 1
            while j < len(t) and t[j] not in ".[":
                j += 1
            nombre, i = t[i + 1:j], j
            if nombre == "*":
                out = []
                for v in vals:
                    out.extend(v if isinstance(v, list) else v.values() if isinstance(v, dict) else [])
                vals = out
            else:
                vals = [v[nombre] for v in vals if isinstance(v, dict) and nombre in v]
        elif t[i] == "[":
            j = t.find("]", i)
            if j < 0:
                break
            clave = t[i + 1:j].strip().strip("'\"")
            i = j + 1
            out = []
            for v in vals:
                if clave == "*":
                    if isinstance(v, list):
                        out.extend(v)
                elif clave.lstrip("-").isdigit() and isinstance(v, list):
                    k = int(clave)
                    if -len(v) <= k < len(v):
                        out.append(v[k])
                elif isinstance(v, dict) and clave in v:
                    out.append(v[clave])
            vals = out
        else:
            i += 1
    return [v for v in vals if v is not None]


def _fecha_fuente(txt, formato=""):
    """Fecha de una fila: época en segundos/milisegundos, formato propio (strftime)
    o cualquiera de los habituales (2025-01-31, 31.01.2025, 31/01/2025…)."""
    if txt is None or txt == "":
        return None
    s = str(txt).strip()
    if not s:
        return None
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]                                   # ISO, con hora o sin ella
    if s.isdigit() and len(s) >= 9:
        n = float(s) / (1000.0 if len(s) > 10 else 1.0)
        try:
            return dt.datetime.fromtimestamp(n, dt.timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    if formato:
        try:
            return dt.datetime.strptime(s, formato).date().isoformat()
        except ValueError:
            pass
    for f in ("%d.%m.%Y", "%d/%m/%Y", "%Y%m%d", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%y"):
        try:
            return dt.datetime.strptime(s, f).date().isoformat()
        except ValueError:
            continue
    return None


def _importe_fuente(v, factor=1.0):
    """Número de la fuente («3.682,65» en castellano, 3682.65 en inglés) × factor."""
    x = float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else _numero_web(str(v))
    if x is None or x <= 0:
        return None
    try:
        return round(x * float(factor or 1), 6)
    except (TypeError, ValueError):
        return round(x, 6)


class _LeeTablas(HTMLParser):
    """Lee todas las tablas de una página: [[cabecera], [fila], …]."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tablas, self._t, self._f, self._c = [], None, None, None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._t = []
        elif tag == "tr" and self._t is not None:
            self._f = []
        elif tag in ("td", "th") and self._f is not None:
            self._c = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._c is not None:
            self._f.append(" ".join("".join(self._c).split()))
            self._c = None
        elif tag == "tr" and self._f is not None:
            if any(x for x in self._f):
                self._t.append(self._f)
            self._f = None
        elif tag == "table" and self._t is not None:
            if self._t:
                self.tablas.append(self._t)
            self._t = None

    def handle_data(self, data):
        if self._c is not None:
            self._c.append(data)


def _sin_tildes(t):
    t = unicodedata.normalize("NFKD", str(t or ""))
    return "".join(c for c in t if not unicodedata.combining(c)).strip().lower()


def _columna(cab, texto):
    """Índice de una columna por número (1-based) o por su cabecera."""
    t = (texto or "").strip()
    if not t:
        return None
    if t.isdigit():
        k = int(t) - 1
        return k if 0 <= k < len(cab) else None
    q = _sin_tildes(t)
    for i, c in enumerate(cab):
        if _sin_tildes(c) == q:
            return i
    for i, c in enumerate(cab):
        if q in _sin_tildes(c):
            return i
    return None


def _tablas_de(html):
    p = _LeeTablas()
    p.feed(html)
    return p.tablas


def _filas_tabla(html, col_fecha, col_precio):
    """(cabeceras, [(fecha, precio)]) de la tabla que tiene esas dos columnas."""
    mejor = None
    for t in _tablas_de(html):
        if len(t) < 2:
            continue
        i_f, i_p = _columna(t[0], col_fecha), _columna(t[0], col_precio)
        if i_f is None or i_p is None:
            continue
        if mejor is None or len(t) > len(mejor[0]):
            mejor = (t, i_f, i_p)
    if not mejor:
        raise ValueError(f"no encuentro una tabla con las columnas «{col_fecha}» y «{col_precio}»")
    t, i_f, i_p = mejor
    filas = []
    for fila in t[1:]:
        if max(i_f, i_p) >= len(fila):
            continue
        filas.append((fila[i_f], fila[i_p]))
    return t[0], filas


class _Nodo:
    __slots__ = ("tag", "attrs", "hijos", "texto")
    def __init__(self, tag, attrs=None):
        self.tag, self.attrs, self.hijos, self.texto = tag, attrs or {}, [], ""


class _Dom(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.raiz = _Nodo("raiz")
        self.pila = [self.raiz]

    def handle_starttag(self, tag, attrs):
        if tag in ("br", "img", "meta", "link", "input", "hr", "source"):
            return
        n = _Nodo(tag, {k: (v or "") for k, v in attrs})
        self.pila[-1].hijos.append(n)
        self.pila.append(n)

    def handle_endtag(self, tag):
        for i in range(len(self.pila) - 1, 0, -1):
            if self.pila[i].tag == tag:
                del self.pila[i:]
                return

    def handle_data(self, data):
        if data and data.strip():
            self.pila[-1].texto += " " + data


def _texto_de(n):
    return " ".join((n.texto + " " + " ".join(_texto_de(h) for h in n.hijos)).split())


def _coincide(n, parte):
    """Selector a medias: etiqueta, #id, .clase, [attr=valor] y sus combinaciones."""
    m = re.match(r"^[a-zA-Z][\w-]*", parte)
    i = 0
    if m:
        if n.tag != m.group(0).lower():
            return False
        i = m.end()
    for x in re.finditer(r"#([\w-]+)|\.([\w-]+)|\[([\w-]+)(?:=[\"']?([^\"'\]]+)[\"']?)?\]", parte[i:]):
        if x.group(1) and n.attrs.get("id") != x.group(1):
            return False
        if x.group(2) and x.group(2) not in n.attrs.get("class", "").split():
            return False
        if x.group(3):
            v = n.attrs.get(x.group(3))
            if v is None or (x.group(4) and v != x.group(4)):
                return False
    return True


def _desc(n):
    for h in n.hijos:
        yield h
        yield from _desc(h)


def _busca_selector(raiz, selector):
    partes = [x for x in re.split(r"\s+", selector.strip()) if x]
    if not partes:
        return []
    actuales = list(_desc(raiz))
    for parte in partes:
        sig, vistos = [], set()
        for n in actuales:
            for h in _desc(n):
                if id(h) not in vistos and _coincide(h, parte):
                    vistos.add(id(h))
                    sig.append(h)
        actuales = sig
        if not actuales:
            break
    return actuales


def _es_selector(txt):
    """Un selector puro no lleva espacios ni tildes («span#precio»): lo que
    sobra es un texto de la página que aparece justo antes del precio."""
    return (" " not in txt and not re.search(r"[áéíóúñÁÉÍÓÚÑ¿¡]", txt)
            and bool(re.match(r"^[#.[a-zA-Z]", txt)))


def _precio_web(html, marcador):
    """Precio de una página: por selector o buscando el texto marcado y el
    primer número que hay después."""
    sel = (marcador or "").strip()
    if not sel:
        raise ValueError("indica dónde está el precio: un selector (span#precio) o el texto de al lado")
    if _es_selector(sel):
        dom = _Dom()
        dom.feed(html)
        nodos = _busca_selector(dom.raiz, sel)
        if not nodos:
            raise ValueError(f"no encuentro «{sel}» en la página")
        for n in nodos:
            t = _texto_de(n)
            m = re.search(r"\d[\d.,\s\u00a0]*", t)
            if m:
                x = _numero_web(m.group(0))
                if x is not None and x > 0:
                    return x
        raise ValueError(f"dentro de «{sel}» no hay ningún precio")
    i = html.lower().find(sel.lower())
    if i < 0:
        raise ValueError(f"no encuentro el texto «{sel}» en la página")
    # sólo el texto visible a partir de ahí: los números de las etiquetas
    # (</h1>, <span class="c2">…) no son precios
    resto = re.sub(r"<[^>]*>", " ", html[i + len(sel):i + len(sel) + 1500])
    m = re.search(r"\d[\d.,\s\u00a0]*", resto)
    if not m:
        raise ValueError(f"después de «{sel}» no hay ningún número")
    x = _numero_web(m.group(0))
    if not x or x <= 0:
        raise ValueError(f"después de «{sel}» no hay ningún precio")
    return x


def _factor_de(p):
    try:
        return float(str(p.get("urlFactor") or "1").replace(",", ".")) or 1.0
    except ValueError:
        return 1.0


def lee_fuente(p, html=None):
    """Lee las filas (fecha, precio) de la fuente configurada en el producto.
    Con historico (json o tabla) devuelve todas; con precio suelto, la de hoy."""
    url = (p.get("urlFuente") or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("la URL tiene que empezar por http:// o https://")
    modo = (p.get("urlModo") or "auto").strip() or "auto"
    hoy = dt.date.today().isoformat()
    if modo == "auto":
        v = _valor_de_url(url)
        if not v or v <= 0:
            raise ValueError("no he encontrado ningún precio en la página")
        return [(hoy, round(v, 4))]
    texto = html if html is not None else _http(url)
    factor = _factor_de(p)
    if modo == "json":
        datos = json.loads(texto)
        precios = _ruta_json(datos, p.get("urlRutaPrecio"))
        if not precios:
            raise ValueError("la ruta de la cotización no devuelve nada: revísala")
        fechas = _ruta_json(datos, p.get("urlRutaFecha"))
        if not fechas:
            x = _importe_fuente(precios[-1], factor)
            if not x:
                raise ValueError("la ruta de la cotización no devuelve ningún precio")
            return [(hoy, x)]
        filas = []
        for i, val in enumerate(precios):
            f = _fecha_fuente(fechas[i] if i < len(fechas) else None, p.get("urlFormatoFecha"))
            x = _importe_fuente(val, factor)
            if f and x:
                filas.append((f, x))
        if not filas:
            raise ValueError("la ruta de la fecha y la de la cotización no casan entre sí")
        return filas
    if modo == "tabla":
        _, brutas = _filas_tabla(texto, p.get("urlColFecha") or "fecha",
                                 p.get("urlColPrecio") or "precio")
        filas = []
        for f_txt, v_txt in brutas:
            f = _fecha_fuente(f_txt, p.get("urlFormatoFecha"))
            x = _importe_fuente(v_txt, factor)
            if f and x:
                filas.append((f, x))
        if not filas:
            raise ValueError("la tabla no tiene filas con fecha y precio legibles")
        return filas
    # modo «web»
    x = _precio_web(texto, p.get("urlSelector"))
    x = _importe_fuente(x, factor)
    if not x:
        raise ValueError("no he podido interpretar el precio de la página")
    return [(hoy, x)]


def _valor_de_url(url):
    """Mejor esfuerzo: lee un precio de la página (JSON-LD, meta o el primer número)."""
    req = urllib.request.Request(url, headers=motor.UA)
    with urllib.request.urlopen(req, timeout=12) as r:
        html = r.read().decode("utf-8", "replace")
    patrones = [r'"price"\s*:\s*"?([0-9][0-9.,]*)',
                r'property="product:price:amount"\s+content="([0-9][0-9.,]*)"',
                r'itemprop="price"\s+content="([0-9][0-9.,]*)"']
    for p in patrones:
        m = re.search(p, html, re.I)
        if m:
            return _numero_web(m.group(1))
    m = re.search(r"\b(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,4})?|\d+[.,]\d{1,4})\b", html)
    return _numero_web(m.group(1)) if m else None


def _numero_web(t):
    # primero se limpia lo que la página pega al número («3.692,40.» o «USD»):
    # sólo quedan dígitos, puntos y comas, y se quita lo que sobra al final
    t = re.sub(r"[^\d.,]", "", str(t).replace("\u00a0", " ")).strip(" .,")
    if not t:
        return None
    if "," in t and "." in t:
        try:
            return motor.num_es(t) if t.rfind(",") > t.rfind(".") else float(t.replace(",", ""))
        except ValueError:
            return None
    if "," in t:
        try:
            return float(t.replace(".", "").replace(",", "."))
        except ValueError:
            return None
    try:
        return float(t)
    except ValueError:
        return None


def _aplica_filas(cfg, pid, filas):
    """Escribe las filas leídas como valores del producto. Solo entran las fechas
    iguales o posteriores a la última anotada: la fuente aporta histórico nuevo sin
    pisar lo que ya tenías anotado (y el día de hoy se sustituye, no se duplica)."""
    hoy = dt.date.today().isoformat()
    filas = sorted({(f, round(float(x), 2)) for f, x in filas if f and x and f <= hoy})
    if not filas:
        return 0
    ultima = max((v["fecha"] for v in cfg.get("valoraciones", [])
                  if v.get("producto") == pid), default=None)
    nuevos = filas if ultima is None else [t for t in filas if t[0] >= ultima]
    if ultima is None and len(nuevos) > 3000:
        nuevos = nuevos[-3000:]          # por no hinchar cartera.json
    for f, x in nuevos:
        almacen.guarda_valoracion(cfg, {"producto": pid, "fecha": f, "valor": x})
    return len(nuevos)


def _actualiza_urls(cfg):
    """Productos con una URL de fuente: leen su precio (o su histórico) de ahí.
    Nunca corta: lo que falla se anota y sigue con el resto."""
    hechos, fallidos = [], []
    for p in cfg.get("productos", []):
        url = (p.get("urlFuente") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        nm = p.get("corto") or p.get("nombre") or p["id"]
        try:
            filas = sorted(lee_fuente(p))
            _aplica_filas(cfg, p["id"], filas)
            hechos.append(nm)
        except Exception as e:
            fallidos.append(f"{nm}: {e}")
    if hechos and modo() == "propio":
        almacen.guarda(os.path.join(DATOS, "cartera.json"), cfg)
    return hechos, fallidos


CAMPOS_FUENTE = ("urlModo", "urlRutaFecha", "urlRutaPrecio", "urlFormatoFecha",
                 "urlFactor", "urlColFecha", "urlColPrecio", "urlSelector")
MODOS_FUENTE = {"": "Automático", "auto": "Automático", "json": "JSON con rutas",
                "tabla": "Tabla en la web", "web": "Precio marcado en la web"}


def _config_fuente(p, datos):
    """Aplica al producto lo que mande el formulario de fuente (solo lo presente)."""
    if "urlFuente" in datos:
        url = str(datos.get("urlFuente") or "").strip()
        if url and not url.startswith(("http://", "https://")):
            raise almacen.ErrorValidacion(["La URL tiene que empezar por http:// o https://."])
        if url:
            p["urlFuente"] = url[:300]
        else:
            p.pop("urlFuente", None)
    for k in CAMPOS_FUENTE:
        if k not in datos:
            continue
        v = str(datos.get(k) or "").strip()[:200]
        if v:
            p[k] = v
        else:
            p.pop(k, None)
    if (p.get("urlFuente") or "").startswith("http"):
        modo = (p.get("urlModo") or "auto").strip() or "auto"
        if modo not in MODOS_FUENTE:
            raise almacen.ErrorValidacion(["Ese modo de lectura no existe."])
        faltan = {"json": ("urlRutaPrecio", "ruta de la cotización"),
                  "tabla": ("urlColPrecio", "la columna del precio"),
                  "web": ("urlSelector", "dónde está el precio")}.get(modo)
        if faltan and not p.get(faltan[0]):
            raise almacen.ErrorValidacion([f"Para leerlo como {MODOS_FUENTE[modo].lower()} hace falta {faltan[1]}."])
        if modo == "tabla" and not p.get("urlColFecha") and not p.get("urlFormatoFecha"):
            raise almacen.ErrorValidacion(["Indica también la columna de la fecha (o el formato de fecha)."])
    return p


@app.post("/api/productos/<pid>/url")
def api_producto_url(pid):
    """Guarda la URL de fuente de un producto que no cotiza solo y cómo leerla
    de ahí (automático, JSON con rutas, tabla web o precio marcado)."""
    datos = request.get_json(silent=True) or {}

    def fn(cfg):
        p = almacen.producto(cfg, pid)
        if not p:
            raise almacen.ErrorValidacion(["Ese producto ya no existe."])
        return _config_fuente(p, datos)
    return cambia(fn)


@app.post("/api/productos/<pid>/fuente/probar")
def api_fuente_probar(pid):
    """Baja la fuente y enseña lo que encuentra, sin guardar nada: el «Mostrar
    respuesta» de Portfolio Performance para poder ajustar rutas y columnas."""
    if modo() == "demo":
        return jsonify(ok=False, errores=[AVISO_DEMO]), 403
    datos = request.get_json(silent=True) or {}
    base = dict(almacen.producto(cartera(), pid) or {})
    if not base:
        return jsonify(ok=False, errores=["Ese producto ya no existe."]), 404
    _config_fuente(base, datos)
    if not (base.get("urlFuente") or "").startswith("http"):
        return jsonify(ok=False, errores=["Pon primero la URL de la fuente."]), 400
    try:
        m = (base.get("urlModo") or "auto").strip() or "auto"
        resp = {"ok": True, "modo": m}
        if m == "tabla":
            texto = _http(base["urlFuente"])
            tablas = _tablas_de(texto)
            if not tablas:
                raise ValueError("esa página no tiene ninguna tabla")
            resp["tablas"] = [{"cabeceras": t[0], "muestra": t[1:6]} for t in tablas[:4]]
            if base.get("urlColPrecio"):
                cab, brutas = _filas_tabla(texto, base.get("urlColFecha") or "",
                                           base["urlColPrecio"])
                filas = []
                for f_txt, v_txt in brutas:
                    f = _fecha_fuente(f_txt, base.get("urlFormatoFecha"))
                    x = _importe_fuente(v_txt, _factor_de(base))
                    if f and x:
                        filas.append((f, x))
                resp["cabeceras"], resp["filas"] = cab, [[f, v] for f, v in filas[:10]]
                resp["total"] = len(filas)
                if filas:
                    filas = sorted(filas)
                    resp["precio"], resp["fecha"] = filas[-1][1], filas[-1][0]
        else:
            filas = sorted(lee_fuente(base))
            resp["filas"] = [[f, v] for f, v in filas[:10]]
            resp["total"] = len(filas)
            resp["precio"] = filas[-1][1]
            resp["fecha"] = filas[-1][0]
    except Exception as e:
        return jsonify(ok=False, errores=[str(e)]), 400
    return jsonify(resp)


@app.post("/api/productos/<pid>/actualizar")
def api_producto_actualizar(pid):
    """Actualiza el precio de UN producto (sin bajar los demás) y recalcula el panel."""
    if modo() == "demo":
        return jsonify(ok=False, errores=[AVISO_DEMO]), 403
    hilo = _ACTUALIZA.get("hilo")
    if motor.PROGRESO.get("activo") or (hilo and hilo.is_alive()):
        return jsonify(ok=False, errores=["Hay una actualización de precios en marcha: "
                                          "espera a que termine y vuelve a intentarlo."]), 409
    cfg = cartera()
    p = next((x for x in cfg.get("productos", []) if x.get("id") == pid), None)
    if not p:
        return jsonify(ok=False, errores=["Ese producto ya no existe."]), 404
    nm = p.get("corto") or p.get("nombre") or pid
    con_url = (p.get("urlFuente") or "").strip().startswith(("http://", "https://"))
    if p.get("fuente") == "manual" and not con_url:
        return jsonify(ok=False, errores=[f"«{nm}» no cotiza en internet: se valora a mano. "
                                          "Anota su valor en «Mis datos → Saldos y valores»."]), 400
    try:
        with cerrojo:
            avisos = []
            nav = nav_fecha = None
            if p.get("fuente") == "manual":
                # Sin cotización: se lee el precio (y el histórico, si lo hay)
                # de la URL de su fuente.
                filas = sorted(lee_fuente(p))
                if not filas:
                    raise ValueError("la fuente no me ha devuelto ningún precio")
                nav_fecha, v = filas[-1]
                _aplica_filas(cfg, pid, filas)
                almacen.guarda(os.path.join(DATOS, "cartera.json"), cfg)
                nav = round(float(v), 4)
            else:
                _pon_cache_en_marcha()
                serie = motor.serie_producto(p, DATOS, fresca=True)
                pares = [(f, v) for f, v in sorted(serie.items()) if v]
                if not pares:
                    raise ValueError("la fuente no me ha devuelto ningún precio")
                nav_fecha, nav = pares[-1][0], round(float(pares[-1][1]), 4)
                avisos = sorted(set(motor.AVISOS))
            datos = recalcula(descargar=False)
            if datos:
                avisos = sorted(set(avisos) | set(datos.get("avisos") or []))
    except Exception as e:
        logging.exception("Fallo al actualizar un producto")
        return jsonify(ok=False, errores=[f"No he podido actualizar «{nm}»: {e}"]), 500
    return jsonify(ok=True, nav=nav, navFecha=nav_fecha, cartera=cfg, avisos=avisos)


@app.get("/api/cartera")
def api_cartera():
    return jsonify(modo=modo(), cartera=cartera(), tipos=motor.TIPOS, fuentes=motor.FUENTES,
                   tiposCuenta=almacen.TIPOS_CUENTA, tiposMovimiento=almacen.TIPOS_MOV)


@app.get("/api/buscar")
def api_buscar():
    n = len(buscar.FALLOS)
    res = buscar.buscar(request.args.get("q", ""))
    return jsonify(resultados=res, sinConexion=(not res and bool(buscar.hubo_fallos_desde(n))))


GUARDAR = {"productos": almacen.guarda_producto, "movimientos": almacen.guarda_movimiento,
           "valoraciones": almacen.guarda_valoracion, "cuentas": almacen.guarda_cuenta}
BORRAR = {"productos": almacen.borra_producto, "movimientos": almacen.borra_movimiento,
          "valoraciones": almacen.borra_valoracion}
AVISO_DEMO = ("Estás viendo la cartera de ejemplo. Pulsa «Empezar con mis datos» "
              "para crear la tuya y poder guardar cambios.")


def _tc_eur(moneda, fecha):
    """Cuántos euros cuesta 1 `moneda` en `fecha` (cambio diario, con su cache).
    None si no hay cambio conocido ni de fallback."""
    serie = motor.serie_cambio(moneda, DATOS)
    t = motor.valor_en(serie, fecha, 6) if serie else None
    if t:
        return float(t)
    if moneda == "USD":
        # Para los dólares casi siempre está guardado el par EURUSD: sirve de respaldo.
        inv = motor.valor_en(motor.descargar_serie("EURUSD=X"), fecha, 6)
        if inv:
            return 1.0 / float(inv)
    return None


def _importe_en_eur(datos):
    """El formulario manda el importe (y la comisión) en la moneda elegida: aquí se
    pasan a euros con el cambio del DÍA DEL MOVIMIENTO y se guarda también el importe
    original en su moneda. Así lo anotado siempre es el dinero real de la operación y
    las conversiones (para verlo en euros o en dólares) se aplican después."""
    mon = str(datos.get("moneda") or "").strip().upper() or "EUR"
    if mon == "EUR":
        # En euros no hace falta nada: y si el movimiento traía otra moneda, se limpia.
        datos["monedaOriginal"], datos["importeOriginal"], datos["tipoCambio"] = "", "", ""
        return datos
    try:
        f = dt.date.fromisoformat(str(datos.get("fecha") or "")[:10])
    except ValueError:
        return datos                 # la fecha la validará almacen, con su mensaje
    vacio = (None, "")
    errores = []
    imp = None if datos.get("importe") in vacio else almacen.numero(datos.get("importe"), "el importe", errores)
    com = None if datos.get("comision") in vacio else almacen.numero(datos.get("comision"), "la comisión", errores,
                                                                     obligatorio=False)
    if errores or imp is None:
        return datos                 # que sea almacen quien dé el error de validación
    tc = _tc_eur(mon, f)
    if not tc:
        raise almacen.ErrorValidacion([
            f"No encuentro el cambio de {mon} a euros del {almacen.fmt_fecha(f.isoformat())}: "
            f"anota el importe en euros o vuelve a intentarlo con conexión."])
    datos["importe"] = round(imp * tc, 2)
    datos["importeOriginal"] = round(imp, 6)
    datos["monedaOriginal"] = mon
    datos["tipoCambio"] = round(tc, 8)
    if com:
        datos["comision"] = round(com * tc, 2)
    return datos



def cambia(fn, avisos_extra=None):
    """Aplica un cambio a la cartera, la guarda (con copia automática) y recalcula.
    `avisos_extra` es una lista que `fn` puede ir llenando para contarle algo al
    usuario (p. ej. que una cuenta no tiene saldo de efectivo)."""
    if modo() == "demo":
        return jsonify(ok=False, errores=[AVISO_DEMO]), 403
    with cerrojo:
        ruta = os.path.join(DATOS, "cartera.json")
        cfg = almacen.carga(ruta)
        # Invariante cuentas/valores: cada cuenta con su producto de efectivo (1:1).
        # Se aplica también aquí para que cualquier cambio lo deje cumplido.
        almacen.migra_efectivo(cfg)
        try:
            item = fn(cfg)
        except almacen.ErrorValidacion as e:
            return jsonify(ok=False, errores=e.errores), 400
        almacen.guarda(ruta, cfg)
        datos = recalcula(descargar="faltan")
    return jsonify(ok=True, item=item, cartera=cfg,
                   avisos=[*(datos or {}).get("avisos", []), *(avisos_extra or [])])


# ---------------------------------------------------------------- efectivo de la cuenta
# El saldo de una cuenta no lo calcula el motor: vive en el producto de efectivo
# vinculado (lo que se anota en «Saldos y valores»). Cuando se anota un movimiento
# de DINERO —interés, dividendo, depósito, retirada, paso entre cuentas— ese saldo
# se recalcula para que lo anotado se refleje SIEMPRE y de forma visible. El saldo
# escrito se marca con «auto»; uno anotado a mano (el real del banco) manda y no se
# pisa jamás… pero tampoco se esconde: se avisa con sus dos cifras.


def _importe_en_producto(cfg, mov, cid=None):
    """El dinero que este movimiento mueve en la cuenta `cid` (por defecto, su
    `cuenta`), en la moneda del producto de efectivo donde se guarda su saldo."""
    p = almacen.producto_efectivo_de(cfg, cid or mov.get("cuenta"))
    if not p:
        return None
    mon = (p.get("moneda") or "EUR").upper()
    return motor.importe_en_cuenta(mov, mon, lambda f: _tc_eur(mon, f))


def _dinero(x):
    """26797.18 → '26.797,18' (siempre con dos decimales: es una cantidad de dinero)."""
    return f"{round(x, 2):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _refresca_cuenta(cfg, cid, f, avisos=None):
    """Recalcula el saldo del día `f` de una cuenta con TODOS los movimientos de
    dinero de ese día, con su signo (entra o sale). Como se rehace el día entero,
    corregir o borrar un movimiento deja el saldo derecho. Devuelve True si ha
    tocado el saldo."""
    c = almacen.cuenta(cfg, cid) or {}
    nombre_c = c.get("nombre") or cid
    movs = [m for m in cfg.get("movimientos", [])
            if m.get("fecha") == f and motor.efecto_de(m, cid)]
    p = almacen.producto_efectivo_de(cfg, cid)
    vals = sorted((v for v in cfg.get("valoraciones", []) if p and v.get("producto") == p["id"]),
                  key=lambda v: v["fecha"])
    actual = next((v for v in vals if v["fecha"] == f), None)
    if not movs:
        # Ese día ya no queda nada anotado: el saldo calculado se retira.
        if actual is not None and actual.get("auto"):
            almacen.borra_valoracion(cfg, actual["id"])
            return True
        return False
    if not p:
        # Sin producto de efectivo el dinero de la cuenta no aparece en ningún sitio:
        # se crea su saldo para que la cuenta sea visible y su dinero, subible.
        try:
            p = almacen.crea_producto_efectivo(cfg, cid)
        except almacen.ErrorValidacion as e:
            if avisos is not None:
                avisos.append(f"No he podido crear el saldo de efectivo de «{nombre_c}»: "
                              + " ".join(e.errores))
            return False
        if not p:
            return False
        if avisos is not None:
            avisos.append(f"«{nombre_c}» no tenía saldo de efectivo, así que le he creado uno "
                          "(ya aparece en «Productos» y en «Saldos y valores»). Su saldo sale "
                          "de lo que lleves anotado: si en tu banco hay otra cifra, anótala en "
                          "«Saldos y valores» y a partir de ahí manda ella.")
        vals = []
    # Neto del día en la moneda de la cuenta. Si falta algún cambio no se escribe
    # nada (una cifra a medias es peor que ninguna) y se avisa.
    neto, sin_cambio = 0.0, False
    for m in movs:
        x = _importe_en_producto(cfg, m, cid)
        if x is None:
            sin_cambio = True
        else:
            neto += motor.efecto_de(m, cid) * x
    neto = round(neto, 2)
    if sin_cambio:
        if avisos is not None:
            avisos.append(f"No encuentro el cambio a {(c.get('moneda') or 'EUR').upper()} del "
                          f"{almacen.fmt_fecha(f)}: el saldo de «{nombre_c}» no se ha "
                          "actualizado. Anótalo tú en «Saldos y valores».")
        return False
    if actual is not None and not actual.get("auto"):
        # Saldo anotado a mano: es el real del banco y casi siempre ya incluye lo
        # cobrado ese día, así que NO se le suma nada (se duplicaría) ni se le quita
        # nada (se pisaría tu dato). Pero no se esconde: se dicen las dos cifras, y
        # quien anotó un saldo anterior a este movimiento sabe cuánto subirlo.
        if avisos is not None:
            q = len(movs)
            uno = q == 1
            mon = (c.get("moneda") or "EUR").upper()
            tipos = ", ".join(sorted({almacen.TIPOS_MOV.get(m["tipo"], m["tipo"]) for m in movs}))
            cifra = f"+{_dinero(neto)}" if neto >= 0 else f"-{_dinero(abs(neto))}"
            nuevo = _dinero(round(actual["valor"] + neto, 2))
            avisos.append(
                f"«{nombre_c}» ya tiene un saldo anotado a mano para el {almacen.fmt_fecha(f)}: "
                f"{_dinero(actual['valor'])} {mon}. No lo he tocado (es el real del banco y casi "
                "siempre ya incluye ese dinero), pero no lo escondo: ese día tienes "
                f"{'un movimiento' if uno else f'{q} movimientos'} de dinero ({tipos}) que "
                f"{'no está' if uno else 'no están'} sumado{'' if uno else 's'} en ese saldo: "
                f"{cifra} {mon}. Si tu saldo era anterior, "
                f"{'súbelo' if neto >= 0 else 'bájalo'} a {nuevo} {mon} en «Saldos y valores».")
        return False
    # Un saldo anotado a mano DESPUÉS de esta fecha es posterior al movimiento y ya
    # lo recoge (los movimientos se anotan cuando llega el extracto, a menudo con
    # días de retraso): no se sube nada, para no meter en el histórico un punto
    # calculado que ese saldo real contradice después.
    if any(v["fecha"] > f and not v.get("auto") for v in vals):
        return False
    previo = next((v for v in reversed(vals) if v["fecha"] < f), None)
    val = almacen.guarda_valoracion(cfg, {"producto": p["id"], "fecha": f,
                                          "valor": round((float(previo["valor"]) if previo else 0.0) + neto, 2)})
    val["auto"] = True
    return True


def refresca_efectivo(cfg, mov, avisos=None):
    """Recalcula el saldo del día en TODAS las cuentas que mueve este movimiento
    (su `cuenta` y su `contrapartida`). Devuelve True si ha tocado algún saldo."""
    mov = mov or {}
    f = mov.get("fecha")
    if not f:
        return False
    tocado = False
    for cid in {mov.get("cuenta"), mov.get("contrapartida")} - {None, ""}:
        if motor.efecto_de(mov, cid):
            tocado = _refresca_cuenta(cfg, cid, f, avisos) or tocado
    return tocado


@app.post("/api/<coleccion>")
def api_guardar(coleccion):
    if coleccion not in GUARDAR:
        return jsonify(ok=False, errores=["No sé guardar eso."]), 404
    datos = request.get_json(silent=True) or {}
    avisos = []

    def fn(cfg):
        if coleccion == "movimientos":
            # Al corregir un dividendo o un interés puede cambiar su cuenta o su
            # fecha: hay que refrescar el día nuevo y también el de antes. Se copia
            # el movimiento ANTES de guardarlo: guarda_movimiento() modifica el mismo
            # dict, y con la referencia lo «anterior» resultaría ser lo nuevo.
            previo = None
            if datos.get("id"):
                m0 = next((m for m in cfg.get("movimientos", [])
                           if m.get("id") == datos.get("id")), None)
                previo = dict(m0) if m0 else None
            mov = GUARDAR[coleccion](cfg, _importe_en_eur(datos))
            # Primero el día que queda atrás (el movimiento ya no cuenta en él, así
            # que su saldo se rehace sin él) y después el nuevo: al revés, el nuevo
            # se apoyaría en un saldo que aún llevaba este movimiento y lo duplicaría.
            if previo and (previo.get("cuenta"), previo.get("fecha")) != (mov.get("cuenta"), mov.get("fecha")):
                refresca_efectivo(cfg, previo, avisos)
            refresca_efectivo(cfg, mov, avisos)
            return mov
        if coleccion != "productos":
            return GUARDAR[coleccion](cfg, datos)
        prod, cambio = almacen.guarda_producto(cfg, datos)
        # Antes de guardar un producto con precio online, se comprueba que lo hay.
        if cambio and prod["fuente"] != "manual" and not buscar.probar(prod["fuente"], prod["codigo"]):
            raise almacen.ErrorValidacion([
                f"No encuentro precio para «{prod['codigo']}» en {motor.FUENTES[prod['fuente']]}. "
                "Revisa el código con el buscador o elige «a mano» y anota tú su valor."])
        return prod
    return cambia(fn, avisos)


@app.delete("/api/<coleccion>/<ident>")
def api_borrar(coleccion, ident):
    if coleccion not in BORRAR:
        return jsonify(ok=False, errores=["No sé borrar eso."]), 404
    avisos = []

    def fn(cfg):
        mov = None
        if coleccion == "movimientos":
            mov = next((m for m in cfg.get("movimientos", []) if m.get("id") == ident), None)
        item = BORRAR[coleccion](cfg, ident)
        # Borrado un dividendo o un interés, el dinero deja de estar en la cuenta.
        refresca_efectivo(cfg, mov, avisos)
        return item
    return cambia(fn, avisos)


@app.post("/api/repartir-colores")
def api_repartir_colores():
    calc = lee_json(ruta_calculado()) or {}
    grandes = [p["id"] for p in sorted(calc.get("productos", []) + calc.get("otrosActivos", []),
                                       key=lambda p: -(p.get("valor") or 0))]
    return cambia(lambda cfg: almacen.reparte_colores(cfg, grandes))


@app.post("/api/empezar")
def api_empezar():
    """Sale de la demo: crea tu cartera, vacía o como copia del ejemplo para practicar."""
    if modo() != "demo":
        return jsonify(ok=False, errores=["Ya tienes tu propia cartera."]), 400
    with cerrojo:
        if (request.get_json(silent=True) or {}).get("desde") == "ejemplo":
            cfg = dict(lee_json(DEMO, {}), titular="Mi patrimonio (copia del ejemplo)")
        else:
            cfg = json.loads(json.dumps(almacen.CARTERA_VACIA))
        almacen.guarda(os.path.join(DATOS, "cartera.json"), cfg)
        recalcula(descargar="faltan")
    return jsonify(ok=True)


# ---------------------------------------------------------------- importar

PLANES = {}   # vista previa pendiente de confirmar: {token: plan}


@app.post("/api/importar/previsualizar")
def api_importar_previsualizar():
    """Lee lo que se quiere importar y devuelve la vista previa, sin guardar nada."""
    if modo() == "demo":
        return jsonify(ok=False, errores=[AVISO_DEMO]), 403
    origen = request.form.get("origen")
    archivos = [(f.filename, f.read()) for f in request.files.getlist("archivos") if f.filename]
    texto = (request.form.get("texto") or "").strip()
    with cerrojo:
        cfg = almacen.carga(os.path.join(DATOS, "cartera.json"))
        if origen == "myinvestor":
            if not archivos:
                return jsonify(ok=False, errores=["Elige los archivos CSV que has descargado de MyInvestor."]), 400
            plan = importar.preparar_myinvestor(cfg, archivos, DATOS)
        elif origen == "portfolio":
            if not archivos and not texto:
                return jsonify(ok=False, errores=["Elige el CSV «Todas las transacciones» de Portfolio Performance."]), 400
            contenido = archivos[0][1] if archivos else texto
            plan = importar.preparar_portfolio(cfg, contenido, DATOS)
        else:
            if not archivos and not texto:
                return jsonify(ok=False, errores=["Elige un archivo o pega el texto que te ha dado la IA."]), 400
            filas, error = [], None
            for nombre, contenido in archivos or [("pegado.csv", texto)]:
                leidas, error = importar.leer_tabla(nombre, contenido)
                if error:
                    return jsonify(ok=False, errores=[f"{nombre}: {error}" if archivos else error]), 400
                filas += leidas
            plan = importar.preparar_tabla(cfg, filas, DATOS)
        informe = importar.vista_previa(cfg, plan)
    token = secrets.token_hex(8)
    PLANES.clear()   # solo una importación pendiente a la vez
    PLANES[token] = plan
    return jsonify(ok=True, token=token, informe=informe)


@app.post("/api/importar/confirmar")
def api_importar_confirmar():
    datos_req = request.get_json(silent=True) or {}
    plan = PLANES.pop(datos_req.get("token"), None)
    if plan is None:
        return jsonify(ok=False, errores=["Esa vista previa ya no vale: vuelve a revisar el archivo."]), 400
    # Tipos de cuenta elegidos en la vista previa y entidades desmarcadas. Llegan
    # como parámetros (no se toca el plan): así volver a recalcular la vista previa
    # da el mismo resultado y la confirmación no depende del orden de las llamadas.
    tipos, excluir = _cambios_de_importacion(datos_req)
    informe = {}

    def fn(cfg):
        informe.update(importar.aplicar(cfg, plan, excluir=excluir, tipos=tipos))
        return None
    respuesta = cambia(fn)
    if isinstance(respuesta, tuple):
        return respuesta
    datos = respuesta.get_json()
    datos["informe"] = {k: informe[k] for k in ("añadidos", "repetidos", "saldos", "sustituidos")}
    return jsonify(datos)


def _cambios_de_importacion(datos_req):
    """Saca de la petición los tipos elegidos y lo que se ha desmarcado."""
    tipos = {}
    for cambio in datos_req.get("cuentas") or []:
        ref, tipo = cambio.get("ref"), cambio.get("tipo")
        if ref and tipo:
            tipos[ref] = tipo
    excluir = {"cuentas": [r for r in (datos_req.get("omitirCuentas") or []) if r],
               "productos": [r for r in (datos_req.get("omitirProductos") or []) if r]}
    return tipos, excluir


@app.post("/api/importar/excluir")
def api_importar_excluir():
    """Recalcula la vista previa con lo que el usuario ha ido desmarcando, para que
    vea el impacto de verdad (totales y movimientos), no solo un contador. No
    consume el token: sigue valiendo para confirmar."""
    datos_req = request.get_json(silent=True) or {}
    plan = PLANES.get(datos_req.get("token"))
    if plan is None:
        return jsonify(ok=False, errores=["Esa vista previa ya no vale: vuelve a revisar el archivo."]), 400
    tipos, excluir = _cambios_de_importacion(datos_req)
    cfg = almacen.carga(os.path.join(DATOS, "cartera.json"))
    return jsonify(ok=True, informe=importar.vista_previa(cfg, plan, excluir=excluir, tipos=tipos))


@app.get("/api/plantilla.xlsx")
def api_plantilla_xlsx():
    return Response(plantilla.excel(), headers={"Content-Disposition": 'attachment; filename="plantilla_patrimonio.xlsx"'},
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/plantilla.csv")
def api_plantilla_csv():
    return Response(plantilla.csv_vacio(), mimetype="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="plantilla_patrimonio.csv"'})


# ------------------------------------------- valores sin cotización automática

def sin_cotizacion(cfg):
    """Productos cuyo precio no se puede bajar de internet (plan, oro, depósito...)."""
    return [p for p in cfg.get("productos", [])
            if p.get("fuente") == "manual" and p.get("tipo") not in almacen.SOLO_SALDO]


def ultimo_valor(cfg, pid):
    vals = [v for v in cfg.get("valoraciones", []) if v.get("producto") == pid]
    return max(vals, key=lambda v: v["fecha"]) if vals else None


def _csv(cuerpo, nombre):
    return Response(cuerpo, mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


@app.get("/api/valores/plantilla")
def api_plantilla_valores():
    """Plantilla de valores manuales: fecha;valor (con ?producto=id) o
    producto;fecha;valor con todos los que no cotizan solos."""
    cfg = cartera()
    pid = (request.args.get("producto") or "").strip()
    if pid:
        p = next((x for x in sin_cotizacion(cfg) if x["id"] == pid), None)
        if p is None:
            return jsonify(ok=False, errores=["Ese producto no está en la lista de valores manuales."]), 404
        ult = ultimo_valor(cfg, pid)
        filas = ["fecha;valor"]
        if ult:
            filas.append(f"{ult['fecha']};{almacen.fmt_num(ult['valor'])}")
        return _csv("\n".join(filas) + "\n", f"valores_{pid}.csv")
    filas = ["producto;fecha;valor"]
    for p in sin_cotizacion(cfg):
        ult = ultimo_valor(cfg, p["id"])
        filas.append(f"{p['id']};{ult['fecha'] if ult else ''};"
                     f"{almacen.fmt_num(ult['valor']) if ult else ''}")
    return _csv("\n".join(filas) + "\n", "valores.csv")


def _lee_plantilla_valores(texto, pid):
    """Devuelve ([(producto, fecha, valor)], errores de filas). Acepta las dos formas."""
    lineas = [l.strip() for l in (texto or "").splitlines() if l.strip() and not l.strip().startswith("#")]
    if not lineas:
        return [], ["El archivo está vacío."]
    primera = [x.strip().lower() for x in lineas[0].split(";")]
    if primera[0] in ("producto", "id", "producto_id"):
        col_prod, desde = 0, 1
    elif primera[0] == "fecha":
        col_prod, desde = -1, 1
    else:                                    # sin cabecera: lo dice el número de columnas
        col_prod, desde = (0 if len(primera) >= 3 else -1), 0
    if col_prod == -1 and not pid:
        return [], ["Esa plantilla es de un solo producto: sube producto;fecha;valor "
                    "(o descárgala desde la fila del producto)."]
    errores, filas = [], []
    for n, linea in enumerate(lineas[desde:], desde + 1):
        partes = [x.strip() for x in linea.split(";")]
        if col_prod == -1:
            if len(partes) < 2 or not partes[1]:
                errores.append(f"Fila {n}: falta el valor.")
                continue
            quien, f_txt, v_txt = pid, partes[0], partes[1]
        else:
            if len(partes) < 3 or not partes[1] or not partes[2]:
                errores.append(f"Fila {n}: usa producto;fecha;valor.")
                continue
            quien, f_txt, v_txt = partes[0], partes[1], partes[2]
        err = []
        if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", f_txt):
            d, m, a = f_txt.split("/")
            f_txt = f"{a}-{m.zfill(2)}-{d.zfill(2)}"
        f = almacen.fecha(f_txt, err)
        v = almacen.numero(v_txt, "el valor", err, minimo=0)
        if err:
            errores.append(f"Fila {n}: " + " ".join(err))
        else:
            filas.append((quien, f, v))
    return filas, errores


@app.post("/api/valores/plantilla")
def api_aplica_plantilla_valores():
    """Carga un CSV de valores manuales y los aplica todos de una vez."""
    if modo() == "demo":
        return jsonify(ok=False, errores=[AVISO_DEMO]), 403
    arch = request.files.get("archivos")
    if arch and arch.filename:
        texto = arch.read().decode("utf-8-sig", "replace")
    else:
        texto = (request.form.get("texto") or "").strip()
    pid = (request.form.get("producto") or "").strip()
    filas, errores = _lee_plantilla_valores(texto, pid)
    if not filas:
        return jsonify(ok=False, errores=(errores or ["No he leído ninguna fila."])[:12]), 400
    # Un producto por id, por nombre o por como se le llama en la interfaz.
    cfg0 = cartera()
    def _buscar(quien):
        q = (quien or "").strip().lower()
        for p in cfg0.get("productos", []):
            if p["id"] == quien or q in (str(p.get("nombre", "")).lower(),
                                          str(p.get("corto", "")).lower()):
                return p["id"]
        return None
    aplicados, saltados = [], []
    for quien, f, v in filas:
        real = _buscar(quien)
        if real is None:
            saltados.append(f"No encuentro el producto «{quien}».")
            continue
        aplicados.append((real, f, v))
    if not aplicados:
        return jsonify(ok=False, errores=(errores + saltados)[:12]), 400

    def fn(cfg):
        for real, f, v in aplicados:
            almacen.guarda_valoracion(cfg, {"producto": real, "fecha": f, "valor": v})
        return None
    respuesta = cambia(fn)
    if isinstance(respuesta, tuple):
        return respuesta
    out = respuesta.get_json()
    out["guardados"] = len(aplicados)
    out["avisos"] = (errores + saltados)[:12]
    return jsonify(out)


@app.get("/api/prompt")
def api_prompt():
    with open(os.path.join(RAIZ, "app", "prompt_ia.txt"), encoding="utf-8") as f:
        return jsonify(texto=f.read())


# ---------------------------------------------------------------- copias de seguridad

def ruta_copias():
    return os.path.join(DATOS, "copias")


def valida_copia(cfg):
    """Comprueba que un JSON tiene pinta de cartera de esta app."""
    if not isinstance(cfg, dict) or not all(isinstance(cfg.get(k), list)
                                            for k in ("productos", "movimientos", "valoraciones")):
        raise almacen.ErrorValidacion(["Ese archivo no es una copia de seguridad de esta app."])
    return cfg


def restaura(cfg):
    """Pone cfg como cartera. Lo que hubiera antes queda en las copias automáticas."""
    with cerrojo:
        almacen.guarda(os.path.join(DATOS, "cartera.json"), cfg)
        for viejo in ("calculado_propio.json", "historico.json"):
            if os.path.exists(os.path.join(DATOS, viejo)):
                os.remove(os.path.join(DATOS, viejo))
        recalcula(descargar="faltan")


@app.get("/api/copias")
def api_copias():
    lista = []
    if os.path.isdir(ruta_copias()):
        for n in os.listdir(ruta_copias()):
            if not n.endswith(".json"):
                continue
            ruta = os.path.join(ruta_copias(), n)
            cfg = lee_json(ruta, {}) or {}
            lista.append({"archivo": n,
                          "fecha": dt.datetime.fromtimestamp(os.path.getmtime(ruta)).isoformat(timespec="minutes"),
                          "motivo": "Antes de empezar de nuevo" if n.startswith("antes_de_reiniciar")
                          else "Antes de recuperar una copia" if n.startswith("antes_de_recuperar")
                          else "Automática",
                          "productos": len(cfg.get("productos", [])),
                          "movimientos": len(cfg.get("movimientos", []))})
    lista.sort(key=lambda c: c["fecha"], reverse=True)
    return jsonify(copias=lista)


def _descarga_copia(clave):
    if modo() != "propio":
        return jsonify(ok=False, errores=["Todavía no tienes una cartera propia que guardar."]), 400
    with open(os.path.join(DATOS, "cartera.json"), "rb") as f:
        contenido = f.read()
    nombre = f"copia_patrimonio_{dt.date.today().isoformat()}.json"
    if clave:
        try:
            contenido = seguro.cifra(contenido, clave)
        except seguro.ErrorSeguro as e:
            return jsonify(ok=False, errores=[str(e)]), 400
        nombre = f"copia_patrimonio_{dt.date.today().isoformat()}.cifrada.json"
    return Response(contenido, mimetype="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


@app.get("/api/copia/descargar")
def api_copia_descargar():
    return _descarga_copia("")


@app.post("/api/copia/descargar")
def api_copia_descargar_clave():
    """Descarga cifrada: el contenido va con la frase de paso que se pida."""
    clave = str((request.get_json(silent=True) or {}).get("clave") or "")
    return _descarga_copia(clave)


@app.post("/api/copia/subir")
def api_copia_subir():
    """Importa una copia descargada antes (por ejemplo, al cambiar de ordenador).
    Si la copia viene cifrada, hace falta la frase de paso con la que se guardó."""
    f = request.files.get("archivo")
    if not f:
        return jsonify(ok=False, errores=["Elige el archivo de la copia (termina en .json)."]), 400
    crudo = f.read()
    if seguro.es_cifrada(crudo):
        clave = (request.form.get("clave") or "").strip()
        if not clave:
            return jsonify(ok=False, errores=["Esa copia está cifrada: escribe su frase de paso."]), 400
        try:
            crudo = seguro.descifra(crudo, clave)
        except seguro.ErrorSeguro as e:
            return jsonify(ok=False, errores=[str(e)]), 400
    try:
        cfg = valida_copia(json.loads(importar.decodifica(crudo)))
    except ValueError:
        return jsonify(ok=False, errores=["Ese archivo no es una copia de seguridad de esta app."]), 400
    except almacen.ErrorValidacion as e:
        return jsonify(ok=False, errores=e.errores), 400
    restaura(cfg)
    return jsonify(ok=True)


@app.post("/api/copia/recuperar")
def api_copia_recuperar():
    nombre = os.path.basename((request.get_json(silent=True) or {}).get("archivo") or "")
    ruta = os.path.join(ruta_copias(), nombre)
    if not nombre.endswith(".json") or not os.path.exists(ruta):
        return jsonify(ok=False, errores=["Esa copia ya no existe."]), 400
    try:
        cfg = valida_copia(lee_json(ruta))
    except almacen.ErrorValidacion as e:
        return jsonify(ok=False, errores=e.errores), 400
    if modo() == "propio":
        # Además de la copia automática, una con nombre propio que no se borra sola.
        sello = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        destino = os.path.join(ruta_copias(), f"antes_de_recuperar_{sello}.json")
        with open(os.path.join(DATOS, "cartera.json"), "rb") as a, open(destino, "wb") as b:
            b.write(a.read())
        almacen.protege(destino)
    restaura(cfg)
    return jsonify(ok=True)


# ---------------------------------------------------------------- web estática y versión

@app.get("/api/exportar-web")
def api_exportar_web():
    datos = lee_json(ruta_calculado())
    if not datos:
        return jsonify(ok=False, errores=["Todavía no hay nada que exportar."]), 400
    ocultar = request.args.get("ocultar") == "1"
    html = exportar.pagina(WEB, datos, ocultar=ocultar, titulo=datos.get("titular") or "Mi patrimonio",
                           version=version_etiqueta())
    nombre = "patrimonio_sin_importes.html" if ocultar else "patrimonio.html"
    return Response(html.encode("utf-8"), mimetype="text/html",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


REPO = "https://github.com/daesdel/rumbo"
REPO_ORIGINAL = "https://github.com/danidm98/rumbo"
_VERSION = {}


def version_actual():
    with open(os.path.join(RAIZ, "app", "VERSION"), encoding="utf-8") as f:
        return f.read().strip()


def version_etiqueta():
    """La versión como se enseña: V1.00. El número vive solo en app/VERSION y el
    navegador no lo formatea nunca (así no hay que cambiarlo en dos sitios)."""
    return "V" + version_actual()


@app.get("/api/version")
def api_version():
    """Compara esta versión con la publicada en GitHub (se consulta como mucho una vez al día)."""
    actual = version_actual()
    if not _VERSION or dt.datetime.now() - _VERSION["cuando"] > dt.timedelta(hours=24):
        try:
            url = REPO.replace("github.com", "raw.githubusercontent.com") + "/main/app/VERSION"
            with urllib.request.urlopen(urllib.request.Request(url, headers=motor.UA), timeout=5) as r:
                _VERSION.update(ultima=r.read().decode().strip(), cuando=dt.datetime.now())
        except Exception:
            _VERSION.update(ultima=None, cuando=dt.datetime.now())
    ultima = _VERSION.get("ultima")
    como_tupla = lambda v: tuple(int(x) for x in re.findall(r"\d+", v or "0"))
    return jsonify(actual=actual, etiqueta="V" + actual, ultima=ultima,
                   repo=REPO, repoOriginal=REPO_ORIGINAL,
                   hayNueva=bool(ultima) and como_tupla(ultima) > como_tupla(actual))


@app.post("/api/reiniciar")
def api_reiniciar():
    """Empieza de cero o vuelve a la demo. Lo que había se guarda antes en mis_datos/copias."""
    if modo() != "propio":
        return jsonify(ok=False, errores=["Ahora mismo no tienes ninguna cartera propia."]), 400
    a = (request.get_json(silent=True) or {}).get("a")
    with cerrojo:
        ruta = os.path.join(DATOS, "cartera.json")
        copias = os.path.join(DATOS, "copias")
        os.makedirs(copias, exist_ok=True)
        sello = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        os.replace(ruta, os.path.join(copias, f"antes_de_reiniciar_{sello}.json"))
        for viejo in ("calculado_propio.json", "historico.json"):
            if os.path.exists(os.path.join(DATOS, viejo)):
                os.remove(os.path.join(DATOS, viejo))
        if a == "vacia":
            almacen.guarda(ruta, json.loads(json.dumps(almacen.CARTERA_VACIA)))
        recalcula(descargar="faltan")
    return jsonify(ok=True)


@app.get("/api/ping")
def api_ping():
    return jsonify(app="patrimonio")


@app.get("/api/datos/vigente")
def api_datos_vigente():
    """Para que el panel sepa, sin bajarse el JSON entero, si los datos han cambiado."""
    try:
        return jsonify(vigente=os.path.getmtime(ruta_calculado()))
    except OSError:
        return jsonify(vigente=0)


@app.get("/<path:archivo>")
def estaticos(archivo):
    return send_from_directory(WEB, archivo)


# ---------------------------------------------------------------- arranque

def ya_abierta(puerto):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/api/ping", timeout=1) as r:
            return json.load(r).get("app") == "patrimonio"
    except Exception:
        return False


def main():
    global PUERTO_ACTIVO
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    # Datos con permisos de solo-dueño (los de antes de esta versión incluidos).
    protege_datos()

    # Modelo cuentas/valores: si la cartera es de antes, se le crea a cada cuenta su
    # producto de efectivo (1:1) y se guarda. Solo añade productos vacíos, así que
    # los totales del panel no cambian; sin esto, el dinero de esas cuentas no
    # aparecía en ningún sitio ni podía subir al anotarle un movimiento.
    if modo() == "propio":
        try:
            ruta = os.path.join(DATOS, "cartera.json")
            cfg = almacen.carga(ruta)
            creados = almacen.migra_efectivo(cfg)
            if creados:
                almacen.guarda(ruta, cfg)
                print(f"  Cuentas con saldo nuevo preparado: {len(creados)} productos de efectivo creados.")
        except Exception as e:
            print(f"  [!] No he podido preparar el efectivo de las cuentas: {e}")

    # Si la app ya está abierta (otra ventana), basta con enseñarla.
    if ya_abierta(PUERTO):
        print("La app ya estaba abierta: te la enseño en el navegador.")
        if not os.environ.get("PATRIMONIO_NO_ABRIR"):
            webbrowser.open(f"http://127.0.0.1:{PUERTO}/")
        return

    print("\n  RUMBO  ·  tu patrimonio neto")
    print("  " + "-" * 40)
    if modo() == "demo":
        print("  Modo demostración: estás viendo una cartera de ejemplo.")
    # Siempre se recalcula al arrancar (sin internet es un momento): así, tras
    # actualizar la app a una versión nueva, el panel nunca usa cálculos viejos.
    viejos = precios_viejos()
    if viejos:
        print("  Actualizando precios (tarda unos segundos)...")
    try:
        recalcula(descargar=viejos or "faltan")
    except Exception as e:
        print(f"\n  [!] No he podido actualizar los precios: {e}")
        print("      Abro la app con los últimos datos guardados.")

    srv = None
    for puerto in range(PUERTO, PUERTO + 10):
        try:
            srv = make_server(HOST, puerto, app, threaded=True)
            break
        except OSError:
            continue
    if srv is None:
        print("  [!] No encuentro ningún puerto libre para abrir la app.")
        return
    PUERTO_ACTIVO = srv.server_port
    url = f"http://127.0.0.1:{srv.server_port}/"
    if not os.environ.get("PATRIMONIO_NO_ABRIR"):   # para pruebas: no abre el navegador
        threading.Timer(0.8, webbrowser.open, [url]).start()
    print(f"\n  App abierta en {url}")
    print("  Deja esta ventana abierta mientras la uses. Para salir, ciérrala.\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
