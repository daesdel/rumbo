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
import urllib.parse
import urllib.request
import webbrowser

from flask import Flask, Response, jsonify, request, send_from_directory
from werkzeug.serving import make_server

import math
import copy

from . import almacen, buscar, exportar, importar, motor, plantilla

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


def modo():
    """'propio' si ya hay una cartera en mis_datos; si no, 'demo'."""
    return "propio" if os.path.exists(os.path.join(DATOS, "cartera.json")) else "demo"


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
    cuerpo = "window.DATOS = " + json.dumps(datos, ensure_ascii=False, separators=(",", ":")) + ";\n"
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
        total = max(motor._prev_descargas(productos), 1)
        motor.PROGRESO.update(activo=True, total=total, hecho=0, pct=0, texto="", errores=[])
        tam = _tramos(n)
        for i in range(0, max(n, 1), tam):
            lote = productos[i:i + tam]
            if not lote:
                break
            with cerrojo:
                motor.PROGRESO["activo"] = True
                motor.AVISOS.clear()
                _pon_cache_en_marcha()
                # El contador sigue de donde iba: el panel se ve llenar de verde.
                motor.descarga_series(lote, avance=motor._prev_descargas(productos[:i]),
                                      total=total)
                motor.PROGRESO["errores"] = sorted(set(motor.PROGRESO.get("errores", []) + list(motor.AVISOS)))
            # El panel se recalcula con lo que ya hay en la cache: sale vivo.
            with cerrojo:
                parcial = motor.construir(cartera(), DATOS, descargar=False)
                if parcial is not None:
                    parcial["modo"] = modo()
                    parcial["preciosActualizados"] = estado().get("preciosActualizados")
                    escribe_json(ruta_calculado(), parcial)
        with cerrojo:
            motor.PROGRESO["activo"] = True
            motor.PROGRESO["texto"] = "Referencias y cambio de divisa"
            motor.AVISOS.clear()
            _pon_cache_en_marcha()
            for sim in sorted({s for r in motor.REFERENCIAS.values() for s, _ in r["piezas"]} | {"EURUSD=X"}):
                motor.descargar_serie(sim)
            # Productos sin cotización con una URL de fuente: se lee el precio de ahí.
            hechos, fallidos = _actualiza_urls(cartera())
            if hechos:
                motor.PROGRESO["texto"] = f"{len(hechos)} valores leídos de su web"
            motor.PROGRESO["errores"] = sorted(set(motor.PROGRESO.get("errores", [])
                                                    + list(motor.AVISOS) + list(fallidos)))
        with cerrojo:
            datos = motor.construir(cartera(), DATOS, descargar=False)
            est = estado()
            est["preciosActualizados"] = dt.datetime.now().replace(microsecond=0).isoformat()
            escribe_json(os.path.join(DATOS, "estado.json"), est)
            if datos is not None:
                datos["modo"] = modo()
                datos["preciosActualizados"] = est["preciosActualizados"]
                escribe_json(ruta_calculado(), datos)
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
    t = t.strip().replace(" ", "")
    if "," in t and "." in t:
        return motor.num_es(t) if t.rfind(",") > t.rfind(".") else float(t.replace(",", ""))
    if "," in t:
        return float(t.replace(".", "").replace(",", "."))
    try:
        return float(t)
    except ValueError:
        return None


def _actualiza_urls(cfg):
    """Productos con una URL de fuente: intenta leer su precio de ahí. Nunca corta."""
    hechos, fallidos = [], []
    for p in cfg.get("productos", []):
        url = (p.get("urlFuente") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        try:
            v = _valor_de_url(url)
            if not v or v <= 0:
                raise ValueError("no he encontrado ningún precio en la página")
            almacen.guarda_valoracion(cfg, {"producto": p["id"],
                                             "fecha": dt.date.today().isoformat(), "valor": round(v, 2)})
            hechos.append(p.get("corto") or p["nombre"])
        except Exception as e:
            fallidos.append(f"{p.get('corto') or p['nombre']}: {e}")
    if hechos and modo() == "propio":
        almacen.guarda(os.path.join(DATOS, "cartera.json"), cfg)
    return hechos, fallidos


@app.post("/api/productos/<pid>/url")
def api_producto_url(pid):
    """Guarda la URL de fuente de un producto que no cotiza solo (se leera al actualizar)."""
    datos = request.get_json(silent=True) or {}

    def fn(cfg):
        p = almacen.producto(cfg, pid)
        if not p:
            raise almacen.ErrorValidacion(["Ese producto ya no existe."])
        url = (datos.get("urlFuente") or "").strip()
        if url and not url.startswith(("http://", "https://")):
            raise almacen.ErrorValidacion(["La URL tiene que empezar por http:// o https://."])
        if url:
            p["urlFuente"] = url[:200]
        else:
            p.pop("urlFuente", None)
        return p
    return cambia(fn)


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
                # Sin cotización: se lee el precio de la URL de su fuente.
                v = _valor_de_url(p["urlFuente"].strip())
                if not v or v <= 0:
                    raise ValueError("no he encontrado ningún precio en la página")
                nav_fecha = dt.date.today().isoformat()
                almacen.guarda_valoracion(cfg, {"producto": pid, "fecha": nav_fecha,
                                                 "valor": round(v, 2)})
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
                   tiposMovimiento=almacen.TIPOS_MOV)


@app.get("/api/buscar")
def api_buscar():
    n = len(buscar.FALLOS)
    res = buscar.buscar(request.args.get("q", ""))
    return jsonify(resultados=res, sinConexion=(not res and bool(buscar.hubo_fallos_desde(n))))


GUARDAR = {"productos": almacen.guarda_producto, "movimientos": almacen.guarda_movimiento,
           "valoraciones": almacen.guarda_valoracion}
BORRAR = {"productos": almacen.borra_producto, "movimientos": almacen.borra_movimiento,
          "valoraciones": almacen.borra_valoracion}
AVISO_DEMO = ("Estás viendo la cartera de ejemplo. Pulsa «Empezar con mis datos» "
              "para crear la tuya y poder guardar cambios.")


def cambia(fn):
    """Aplica un cambio a la cartera, la guarda (con copia automática) y recalcula."""
    if modo() == "demo":
        return jsonify(ok=False, errores=[AVISO_DEMO]), 403
    with cerrojo:
        ruta = os.path.join(DATOS, "cartera.json")
        cfg = almacen.carga(ruta)
        try:
            item = fn(cfg)
        except almacen.ErrorValidacion as e:
            return jsonify(ok=False, errores=e.errores), 400
        almacen.guarda(ruta, cfg)
        datos = recalcula(descargar="faltan")
    return jsonify(ok=True, item=item, cartera=cfg, avisos=(datos or {}).get("avisos", []))


@app.post("/api/<coleccion>")
def api_guardar(coleccion):
    if coleccion not in GUARDAR:
        return jsonify(ok=False, errores=["No sé guardar eso."]), 404
    datos = request.get_json(silent=True) or {}

    def fn(cfg):
        if coleccion != "productos":
            return GUARDAR[coleccion](cfg, datos)
        prod, cambio = almacen.guarda_producto(cfg, datos)
        # Antes de guardar un producto con precio online, se comprueba que lo hay.
        if cambio and prod["fuente"] != "manual" and not buscar.probar(prod["fuente"], prod["codigo"]):
            raise almacen.ErrorValidacion([
                f"No encuentro precio para «{prod['codigo']}» en {motor.FUENTES[prod['fuente']]}. "
                "Revisa el código con el buscador o elige «a mano» y anota tú su valor."])
        return prod
    return cambia(fn)


@app.delete("/api/<coleccion>/<ident>")
def api_borrar(coleccion, ident):
    if coleccion not in BORRAR:
        return jsonify(ok=False, errores=["No sé borrar eso."]), 404
    return cambia(lambda cfg: BORRAR[coleccion](cfg, ident))


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
    plan = PLANES.pop((request.get_json(silent=True) or {}).get("token"), None)
    if plan is None:
        return jsonify(ok=False, errores=["Esa vista previa ya no vale: vuelve a revisar el archivo."]), 400
    informe = {}

    def fn(cfg):
        informe.update(importar.aplicar(cfg, plan))
        return None
    respuesta = cambia(fn)
    if isinstance(respuesta, tuple):
        return respuesta
    datos = respuesta.get_json()
    datos["informe"] = {k: informe[k] for k in ("añadidos", "repetidos", "saldos", "sustituidos")}
    return jsonify(datos)


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


@app.get("/api/copia/descargar")
def api_copia_descargar():
    if modo() != "propio":
        return jsonify(ok=False, errores=["Todavía no tienes una cartera propia que guardar."]), 400
    with open(os.path.join(DATOS, "cartera.json"), "rb") as f:
        contenido = f.read()
    nombre = f"copia_patrimonio_{dt.date.today().isoformat()}.json"
    return Response(contenido, mimetype="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


@app.post("/api/copia/subir")
def api_copia_subir():
    """Importa una copia descargada antes (por ejemplo, al cambiar de ordenador)."""
    f = request.files.get("archivo")
    if not f:
        return jsonify(ok=False, errores=["Elige el archivo de la copia (termina en .json)."]), 400
    try:
        cfg = valida_copia(json.loads(importar.decodifica(f.read())))
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
        with open(os.path.join(DATOS, "cartera.json"), "rb") as a, \
                open(os.path.join(ruta_copias(), f"antes_de_recuperar_{sello}.json"), "wb") as b:
            b.write(a.read())
    restaura(cfg)
    return jsonify(ok=True)


# ---------------------------------------------------------------- web estática y versión

@app.get("/api/exportar-web")
def api_exportar_web():
    datos = lee_json(ruta_calculado())
    if not datos:
        return jsonify(ok=False, errores=["Todavía no hay nada que exportar."]), 400
    ocultar = request.args.get("ocultar") == "1"
    html = exportar.pagina(WEB, datos, ocultar=ocultar, titulo=datos.get("titular") or "Mi patrimonio")
    nombre = "patrimonio_sin_importes.html" if ocultar else "patrimonio.html"
    return Response(html.encode("utf-8"), mimetype="text/html",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


REPO = "https://github.com/danidm98/rumbo"
_VERSION = {}


def version_actual():
    with open(os.path.join(RAIZ, "app", "VERSION"), encoding="utf-8") as f:
        return f.read().strip()


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
    return jsonify(actual=actual, ultima=ultima, repo=REPO,
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
