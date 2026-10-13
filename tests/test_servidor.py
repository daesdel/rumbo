# -*- coding: utf-8 -*-
"""
test_servidor.py  ·  El servidor local y su blindaje
=====================================================
El middleware de Host/Origin (contra DNS rebinding y CSRF), la ruta de salud
y la guardia del modo demostración.
"""
import os

import pytest

from app import servidor as s


@pytest.fixture
def cliente():
    return s.app.test_client()


@pytest.fixture(autouse=True)
def puerto_activo():
    """El middleware conoce el puerto como si estuviera escuchando en 8765."""
    anterior = s.PUERTO_ACTIVO
    s.PUERTO_ACTIVO = 8765
    yield
    s.PUERTO_ACTIVO = anterior


# ---------------------------------------------------------------- /datos.js

def test_datos_js_se_recalcula_si_el_calculo_guardado_es_null(cliente):
    """Un 'null' guardado (cartera que no pudo calcularse) no debe dejar la app
    pillada: la siguiente carga recalcula al vuelo."""
    import json
    import os

    ruta = os.path.join(s.DATOS, "cartera.json")
    calc = os.path.join(s.DATOS, "calculado_propio.json")
    cartera_antes = s.lee_json(ruta)
    calc_antes = s.lee_json(calc, "ausente")
    try:
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump({"productos": [
                            {"id": "c1", "nombre": "Cuenta", "corto": "Cuenta",
                             "tipo": "efectivo", "fuente": "manual"},
                            {"id": "f1", "nombre": "Fondo", "corto": "Fondo",
                             "tipo": "otro", "fuente": "manual", "slot": 1}],
                        "movimientos": [],
                        "valoraciones": [
                            {"id": "v1", "producto": "f1", "fecha": "2025-06-01", "valor": 1000.0},
                            {"id": "v2", "producto": "c1", "fecha": "2025-06-01", "valor": 500.0}]}, f)
        with open(calc, "w", encoding="utf-8") as f:
            f.write("null")

        cuerpo = cliente.get("/datos.js").get_data(as_text=True)
        assert "window.DATOS = {" in cuerpo               # no "null"
        assert cuerpo.startswith('window.VERSION = "V')  # la versión va primero
    finally:
        if cartera_antes is None:
            if os.path.exists(ruta):
                os.remove(ruta)
        else:
            s.escribe_json(ruta, cartera_antes)
        if calc_antes == "ausente":
            if os.path.exists(calc):
                os.remove(calc)
        else:
            s.escribe_json(calc, calc_antes)


# ---------------------------------------------------------------- blindaje

def test_lecturas_solo_desde_este_ordenador(cliente):
    assert cliente.get("/api/ping").status_code == 200
    assert cliente.get("/api/ping", base_url="http://127.0.0.1:8765/").status_code == 200
    assert cliente.get("/api/ping", base_url="http://localhost:8765/").status_code == 200


def test_host_de_un_dominio_ajeno_es_dns_rebinding_y_pasa_a_403(cliente):
    r = cliente.get("/api/ping", base_url="http://evil.com/")
    assert r.status_code == 403
    assert "rechazada" in r.get_data(as_text=True)


def test_host_con_puerto_ajeno_tambien(cliente):
    assert cliente.get("/api/ping", base_url="http://127.0.0.1:9999/").status_code == 403


def test_escritura_con_origin_de_otra_web_es_csrf_y_pasa_a_403(cliente):
    for metodo in ("post", "delete"):
        r = getattr(cliente, metodo)("/api/ping", headers={"Origin": "http://evil.com"})
        assert r.status_code == 403, metodo

    r = cliente.post("/api/reiniciar", headers={"Origin": "https://otra.web"}, json={})
    assert r.status_code == 403
    # la cartera no existía, pero en cualquier caso el filtro ni la deja llegar
    assert "rechazada" in r.get_data(as_text=True)


def test_origin_null_de_un_iframe_aislado_tambien(cliente):
    r = cliente.post("/api/reiniciar", headers={"Origin": "null"}, json={})
    assert r.status_code == 403


def test_origin_de_esta_app_lo_deja_pasar(cliente):
    r = cliente.post("/api/ping", headers={"Origin": "http://localhost:8765"})
    assert r.status_code != 403    # la ruta no existe para POST (404/405), eso ya va aparte


def test_sin_origin_ni_referer_no_es_navegador_y_pasa(cliente):
    assert cliente.post("/api/ping").status_code != 403
    r = cliente.delete("/api/productos/x")
    # la app puede responder 403 de la demo (no hay cartera propia en los tests),
    # pero eso es la guardia normal: lo que no aparece es el 403 del blindaje
    assert "rechazada" not in r.get_data(as_text=True)


def test_referer_de_esta_app_lo_deja_pasar(cliente):
    r = cliente.post("/api/ping", headers={"Referer": "http://127.0.0.1:8765/api/algo"})
    assert r.status_code != 403


def test_referer_de_otra_web_rechazado(cliente):
    r = cliente.post("/api/ping", headers={"Referer": "https://evil.com/x"})
    assert r.status_code == 403


# ------------------------------------------------- proxy inverso (Pangolin)
# En tests, conftest.py fija PATRIMONIO_ORIGENES=https://rumbo.daesdel.es

def test_host_del_proxy_publico_lo_deja_pasar(cliente):
    r = cliente.get("/api/ping", base_url="https://rumbo.daesdel.es/")
    assert r.status_code == 200


def test_origin_del_proxy_en_post_lo_deja_pasar(cliente):
    r = cliente.post("/api/ping", headers={"Origin": "https://rumbo.daesdel.es"})
    assert r.status_code != 403


def test_referer_del_proxy_lo_deja_pasar(cliente):
    r = cliente.post("/api/ping", headers={"Referer": "https://rumbo.daesdel.es/api/x"})
    assert r.status_code != 403


def test_el_proxy_no_abre_la_puerta_a_cualquier_dominio(cliente):
    # la lista es cerrada: otro subdominio igual de "bonito" sigue fuera
    assert cliente.get("/api/ping", base_url="https://otro.daesdel.es/").status_code == 403
    assert cliente.post("/api/ping",
                        headers={"Origin": "https://evil.daesdel.es"}).status_code == 403


# ---------------------------------------------------------------- API

def test_ping(cliente):
    r = cliente.get("/api/ping")
    assert r.status_code == 200
    assert r.get_json()["app"] == "patrimonio"


def test_cartera_en_modo_demo(cliente):
    r = cliente.get("/api/cartera")
    assert r.status_code == 200
    assert r.get_json()["modo"] == "demo"       # sin cartera.json en los datos de test


def test_en_demo_no_se_puede_escribir(cliente):
    r = cliente.post("/api/productos",
                     json={"nombre": "No me guardes", "tipo": "fondo",
                           "fuente": "yahoo", "codigo": "X"})
    assert r.status_code == 403
    assert "ejemplo" in r.get_json()["errores"][0]


def test_coleccion_desconocida_es_404(cliente):
    assert cliente.post("/api/loquesea", json={}).status_code == 404
    assert cliente.delete("/api/loquesea/x").status_code == 404


# ------------------------------------------- actualizar el precio de UN producto
def test_actualizar_un_producto(cliente, monkeypatch):
    """Baja el precio de un solo producto (sin bajar los demás), recalcula el
    panel y deja claro qué es lo que no se puede actualizar."""
    import os

    ruta = os.path.join(s.DATOS, "cartera.json")
    calc = os.path.join(s.DATOS, "calculado_propio.json")
    cartera_antes = s.lee_json(ruta)
    calc_antes = s.lee_json(calc, "ausente")
    try:
        s.escribe_json(ruta, {
            "productos": [{"id": "f1", "nombre": "Fondo", "corto": "Fondo", "tipo": "fondo",
                           "fuente": "yahoo", "codigo": "ABC"},
                          {"id": "m1", "nombre": "Piso", "corto": "Piso", "tipo": "otro",
                           "fuente": "manual"}],
            "movimientos": [],
            "valoraciones": [{"id": "v1", "producto": "m1", "fecha": "2025-06-01", "valor": 100000.0}]})
        llamado = {}

        def serie_fingida(p, carpeta, fresca=False):
            llamado.update(id=p["id"], fresca=fresca)
            return {"2025-05-01": 10.0, "2025-06-01": 11.5}

        monkeypatch.setattr(s.motor, "serie_producto", serie_fingida)

        r = cliente.post("/api/productos/f1/actualizar")
        assert r.status_code == 200, r.get_data(as_text=True)
        j = r.get_json()
        assert j["ok"] is True
        assert llamado == {"id": "f1", "fresca": True}      # descarga fresca de ese producto
        assert j["nav"] == 11.5 and j["navFecha"] == "2025-06-01"
        datos = s.lee_json(calc) or {}
        assert any(p.get("id") == "m1" for p in datos.get("productos", []))   # panel al día

        # valorado a mano y sin URL: no hay precio que bajar
        r2 = cliente.post("/api/productos/m1/actualizar")
        assert r2.status_code == 400
        assert "a mano" in r2.get_json()["errores"][0]

        # producto que no existe
        assert cliente.post("/api/productos/nada/actualizar").status_code == 404
    finally:
        if cartera_antes is None:
            if os.path.exists(ruta):
                os.remove(ruta)
        else:
            s.escribe_json(ruta, cartera_antes)
        if calc_antes == "ausente":
            if os.path.exists(calc):
                os.remove(calc)
        else:
            s.escribe_json(calc, calc_antes)


def test_actualizar_un_producto_en_demo_no_se_puede(cliente):
    r = cliente.post("/api/productos/x/actualizar")
    assert r.status_code == 403
    assert "ejemplo" in r.get_json()["errores"][0]


# ------------------------------------------------------------ fuentes de precio
# (lo que antes era «sólo URL automática»: ahora JSON con rutas, tabla web o
#  el precio marcado en la página, como en Portfolio Performance)

def test_lee_fuente_json_con_rutas_estilo_pp():
    p = {"urlFuente": "https://ejemplo.org/kurs.json", "urlModo": "json",
         "urlRutaFecha": "$[*].datum", "urlRutaPrecio": "$[*].kurs"}
    datos = '[{"datum": "2025-01-30", "kurs": "3.650,10"},'
    datos += ' {"datum": "2025-01-31", "kurs": "3.682,65"}]'
    filas = s.lee_fuente(p, html=datos)
    assert filas == [("2025-01-30", 3650.10), ("2025-01-31", 3682.65)]


def test_lee_fuente_json_formato_y_factor():
    p = {"urlFuente": "https://ejemplo.org/x.json", "urlModo": "json",
         "urlRutaFecha": "$.data[*].d", "urlRutaPrecio": "$.data[*].p",
         "urlFormatoFecha": "%d.%m.%Y", "urlFactor": "0,001"}
    datos = '{"data": [{"d": "31.01.2025", "p": 3682650}]}'
    assert s.lee_fuente(p, html=datos) == [("2025-01-31", 3682.65)]


def test_lee_fuente_json_solo_precios_da_el_de_hoy():
    p = {"urlFuente": "https://ejemplo.org/p.json", "urlModo": "json",
         "urlRutaPrecio": "$[*].kurs"}
    import datetime as dt
    filas = s.lee_fuente(p, html='[{"kurs": 123.45}]')
    assert filas == [(dt.date.today().isoformat(), 123.45)]


def test_lee_fuente_tabla_web():
    p = {"urlFuente": "https://ejemplo.org/historico.html", "urlModo": "tabla",
         "urlColFecha": "Fecha", "urlColPrecio": "Precio de cierre"}
    html = "<table><tr><th>Fecha</th><th>Precio de cierre</th><th>Volumen</th></tr>"
    html += "<tr><td>31/01/2025</td><td>3.682,65</td><td>1.200</td></tr>"
    html += "<tr><td>30/01/2025</td><td>3.650,10</td><td>900</td></tr></table>"
    assert s.lee_fuente(p, html=html) == [("2025-01-31", 3682.65),
                                          ("2025-01-30", 3650.10)]


def test_lee_fuente_web_por_selector():
    p = {"urlFuente": "https://ejemplo.org/oro", "urlModo": "web",
         "urlSelector": "span#precio"}
    html = '<html><body><span id="precio"> 3.682,65 </span></body></html>'
    import datetime as dt
    assert s.lee_fuente(p, html=html) == [(dt.date.today().isoformat(), 3682.65)]


def test_lee_fuente_web_por_texto_marcado():
    p = {"urlFuente": "https://investing.example/xau-eur", "urlModo": "web",
         "urlSelector": "Oro al contado a Euro"}
    html = '<h1>Oro al contado a Euro - XAU/EUR</h1><span>3.682,65</span>'
    import datetime as dt
    assert s.lee_fuente(p, html=html) == [(dt.date.today().isoformat(), 3682.65)]


def test_lee_fuente_error_si_falta_algo():
    with pytest.raises(ValueError) as e:
        s.lee_fuente({"urlFuente": "ftp://mal"})
    assert "http" in str(e.value)
    with pytest.raises(ValueError):
        s.lee_fuente({"urlFuente": "https://x.org/a", "urlModo": "json",
                      "urlRutaPrecio": "$.nada"}, html="{}")
    with pytest.raises(ValueError):
        s.lee_fuente({"urlFuente": "https://x.org/a", "urlModo": "web",
                      "urlSelector": "#no-existe"}, html="<p>hola</p>")
    with pytest.raises(ValueError):
        s.lee_fuente({"urlFuente": "https://x.org/a", "urlModo": "tabla",
                      "urlColFecha": "Fecha", "urlColPrecio": "Precio"},
                     html="<p>sin tablas</p>")


def test_config_fuente_valida_lo_que_manda_el_formulario():
    p = {"urlFuente": "https://x.org/a.json"}
    s._config_fuente(p, {"urlModo": "json", "urlRutaPrecio": "$[*].kurs"})
    assert p["urlModo"] == "json" and p["urlRutaPrecio"] == "$[*].kurs"
    with pytest.raises(Exception):
        s._config_fuente({"urlFuente": "https://x.org/a.json"},
                         {"urlModo": "json"})            # falta la ruta del precio
    with pytest.raises(Exception):
        s._config_fuente({}, {"urlFuente": "javascript:alert(1)"})
    # al vaciar un campo se borra (no se queda la ristra vieja)
    p2 = {"urlFuente": "https://x.org/a", "urlSelector": "#precio"}
    s._config_fuente(p2, {"urlSelector": ""})
    assert "urlSelector" not in p2


def test_probar_fuente_ensena_filas_sin_guardar(cliente, monkeypatch):
    """El «Mostrar respuesta del servidor» devuelve filas de prueba y no toca nada."""
    import os

    ruta = os.path.join(s.DATOS, "cartera.json")
    cartera_antes = s.lee_json(ruta)
    try:
        s.escribe_json(ruta, {"productos": [
            {"id": "x", "nombre": "Oro", "corto": "Oro", "tipo": "otro",
             "fuente": "manual"}], "movimientos": [], "valoraciones": []})
        html_tabla = ("<table><tr><th>Fecha</th><th>Precio</th></tr>"
                      "<tr><td>2025-01-31</td><td>100,50</td></tr>"
                      "<tr><td>2025-02-01</td><td>101,25</td></tr></table>")
        monkeypatch.setattr(s, "_http", lambda url, timeout=15: html_tabla)
        r = cliente.post("/api/productos/x/fuente/probar", json={
            "urlFuente": "https://ejemplo.org/tabla", "urlModo": "tabla",
            "urlColFecha": "Fecha", "urlColPrecio": "Precio"})
        j = r.get_json()
        assert r.status_code == 200 and j["ok"] is True
        assert j["filas"] == [["2025-01-31", 100.5], ["2025-02-01", 101.25]]
        assert j["precio"] == 101.25 and j["total"] == 2

        # nada se ha guardado en la cartera: probar es sólo mirar
        assert "urlFuente" not in (s.lee_json(ruta) or {}).get("productos", [{}])[0]

        # sin URL → 400 con el aviso
        r2 = cliente.post("/api/productos/x/fuente/probar", json={})
        assert r2.status_code == 400
        assert cliente.post("/api/productos/nada/fuente/probar",
                            json={"urlFuente": "https://x.org/a"}).status_code == 404
    finally:
        if cartera_antes is None:
            if os.path.exists(ruta):
                os.remove(ruta)
        else:
            s.escribe_json(ruta, cartera_antes)


def test_aplica_filas_no_pisa_lo_que_ya_habia():
    cfg = {"productos": [{"id": "p1", "nombre": "X", "corto": "X",
                          "tipo": "accion", "fuente": "manual"}],
           "movimientos": [],
           "valoraciones": [{"id": "v0", "producto": "p1",
                             "fecha": "2025-01-31", "valor": 100.0}]}
    n = s._aplica_filas(cfg, "p1", [("2025-01-30", 99.0),   # anterior: se ignora
                                     ("2025-01-31", 101.0),  # mismo día: se sustituye
                                     ("2025-02-01", 102.0),
                                     ("2999-01-01", 1.0)])   # futuro: se ignora
    assert n == 2
    vals = [(v["fecha"], v["valor"]) for v in cfg["valoraciones"]]
    assert ("2025-01-31", 101.0) in vals and ("2025-01-30", 99.0) not in vals
    assert ("2999-01-01", 1.0) not in vals


# ---------------------------------------------------------------- copias de seguridad

def _restaura_estados(ruta, cartera_antes, calc, calc_antes):
    import os
    if cartera_antes is None:
        if os.path.exists(ruta):
            os.remove(ruta)
    else:
        s.escribe_json(ruta, cartera_antes)
    if calc_antes == "ausente":
        if os.path.exists(calc):
            os.remove(calc)
    else:
        s.escribe_json(calc, calc_antes)


def test_copia_con_frase_de_paso_se_cifra_y_vuelve_a_abrirse(cliente):
    """La copia descargada con contraseña sale opaca y solo se restaura con ella."""
    import io
    import os

    from app import seguro

    ruta = os.path.join(s.DATOS, "cartera.json")
    calc = os.path.join(s.DATOS, "calculado_propio.json")
    cartera_antes = s.lee_json(ruta)
    calc_antes = s.lee_json(calc, "ausente")
    try:
        s.escribe_json(ruta, {"productos": [
                                {"id": "x", "nombre": "Oro", "corto": "Oro",
                                 "tipo": "otro", "fuente": "manual"}],
                            "movimientos": [], "valoraciones": []})

        # sin frase de paso: la copia sigue siendo el json de siempre
        r = cliente.get("/api/copia/descargar")
        assert r.status_code == 200 and b'"productos"' in r.get_data()

        # con frase de paso: sale cifrada y sin un solo dato legible
        r = cliente.post("/api/copia/descargar", json={"clave": "para la nube"})
        assert r.status_code == 200
        crudo = r.get_data()
        assert seguro.es_cifrada(crudo)
        assert b"Oro" not in crudo
        assert ".cifrada.json" in r.headers["Content-Disposition"]

        # subirla sin frase (o con la equivocada) no puede: avisa y no toca nada
        for datos in ({"archivo": (io.BytesIO(crudo), "copia.cifrada.json")},
                      {"archivo": (io.BytesIO(crudo), "copia.cifrada.json"), "clave": "mala"}):
            r = cliente.post("/api/copia/subir", data=datos,
                             content_type="multipart/form-data")
            assert r.status_code == 400
            assert r.get_json()["errores"]

        # con la frase buena, la cartera anterior vuelve tal cual
        s.escribe_json(ruta, {"productos": [], "movimientos": [], "valoraciones": []})
        r = cliente.post("/api/copia/subir",
                         data={"archivo": (io.BytesIO(crudo), "copia.cifrada.json"),
                               "clave": "para la nube"},
                         content_type="multipart/form-data")
        assert r.status_code == 200 and r.get_json()["ok"] is True
        assert s.lee_json(ruta)["productos"][0]["id"] == "x"
    finally:
        _restaura_estados(ruta, cartera_antes, calc, calc_antes)


def test_subir_una_copia_normal_sigue_funcionando_sin_frase(cliente):
    import io
    import os

    ruta = os.path.join(s.DATOS, "cartera.json")
    calc = os.path.join(s.DATOS, "calculado_propio.json")
    cartera_antes = s.lee_json(ruta)
    calc_antes = s.lee_json(calc, "ausente")
    try:
        original = {"productos": [{"id": "y", "nombre": "Plata", "corto": "Plata",
                                    "tipo": "otro", "fuente": "manual"}],
                    "movimientos": [], "valoraciones": []}
        s.escribe_json(ruta, original)
        r = cliente.get("/api/copia/descargar")
        s.escribe_json(ruta, {"productos": [], "movimientos": [], "valoraciones": []})
        r = cliente.post("/api/copia/subir",
                         data={"archivo": (io.BytesIO(r.get_data()), "copia.json")},
                         content_type="multipart/form-data")
        assert r.status_code == 200 and r.get_json()["ok"] is True
        assert s.lee_json(ruta)["productos"][0]["id"] == "y"
    finally:
        _restaura_estados(ruta, cartera_antes, calc, calc_antes)


def test_escribe_json_deja_el_fichero_solo_para_el_dueno(tmp_path):
    import os
    import stat
    if os.name == "nt":
        pytest.skip("en Windows no hay permisos unix")
    ruta = str(tmp_path / "estado.json")
    s.escribe_json(ruta, {"x": 1})
    assert stat.S_IMODE(os.stat(ruta).st_mode) == 0o600


def test_protege_datos_arregla_tambien_los_ficheros_viejos(monkeypatch, tmp_path):
    """Al arrancar, los datos escritos antes de esta versión pasan a 600."""
    import os
    import stat
    if os.name == "nt":
        pytest.skip("en Windows no hay permisos unix")
    (tmp_path / "copias").mkdir()
    for ruta in (tmp_path / "cartera.json", tmp_path / "copias" / "auto_1.json"):
        ruta.write_text("{}", encoding="utf-8")
        os.chmod(ruta, 0o644)
    monkeypatch.setattr(s, "DATOS", str(tmp_path))
    s.protege_datos()
    for ruta in (tmp_path / "cartera.json", tmp_path / "copias" / "auto_1.json"):
        assert stat.S_IMODE(os.stat(ruta).st_mode) == 0o600


# --------------------------------- movimientos en la moneda real del movimiento

def _cartera_dolares():
    return {
        "titular": "Prueba",
        "cuentas": [{"id": "rev", "nombre": "Revolut USD", "moneda": "USD"}],
        "productos": [{"id": "f1", "nombre": "Tesla", "corto": "Tesla", "tipo": "accion",
                       "fuente": "manual", "moneda": "USD", "cuenta": "rev"}],
        "movimientos": [], "valoraciones": [],
    }


def _post_mov(cliente, **campos):
    cuerpo = {"fecha": "2025-06-20", "tipo": "compra", "producto": "f1",
              "cuenta": "rev", "unidades": 1, "importe": "100", "comision": "5",
              "moneda": "USD"}
    cuerpo.update(campos)
    r = cliente.post("/api/movimientos", json=cuerpo)
    return r, (r.get_json() if r.status_code == 200 else
               (r.get_json(silent=True) or {}))


def test_movimiento_en_dolares_se_anota_en_dolares_y_se_guarda_en_euros(cliente, monkeypatch):
    """El formulario manda el importe en la moneda elegida (la real del movimiento):
    el servidor lo pasa a euros con el cambio del DÍA y guarda también el original.
    Editar sin cambiar la moneda lo mantiene; cambiarlo a euros lo limpia; volver a
    dólares lo vuelve a anotar."""
    import os

    ruta = os.path.join(s.DATOS, "cartera.json")
    calc = os.path.join(s.DATOS, "calculado_propio.json")
    cartera_antes = s.lee_json(ruta)
    calc_antes = s.lee_json(calc, "ausente")
    monkeypatch.setattr(s.motor, "serie_cambio",
                        lambda mon, carpeta: {"2025-06-20": 0.92} if mon == "USD" else {})
    monkeypatch.setattr(s.motor, "descargar_serie", lambda *a, **k: {})
    try:
        s.escribe_json(ruta, _cartera_dolares())
        r, j = _post_mov(cliente)
        assert r.status_code == 200, r.get_data(as_text=True)
        m = j["item"]
        assert m["importe"] == pytest.approx(92.0)          # 100 $ × 0,92 €/$
        assert m["importeOriginal"] == pytest.approx(100.0)
        assert m["monedaOriginal"] == "USD"
        assert m["tipoCambio"] == pytest.approx(0.92)
        assert m["comision"] == pytest.approx(4.6)           # 5 $ → 4,60 €
        assert len(s.lee_json(ruta)["movimientos"]) == 1

        # Editar sin tocar la moneda: sigue siendo el movimiento de 100 $
        r2, j2 = _post_mov(cliente, id=m["id"])
        assert r2.status_code == 200, r2.get_data(as_text=True)
        m2 = j2["item"]
        assert m2["importeOriginal"] == pytest.approx(100.0)
        assert m2["monedaOriginal"] == "USD"
        assert len(s.lee_json(ruta)["movimientos"]) == 1

        # Pasarlo a euros: queda en euros puro, sin importe original
        r3, j3 = _post_mov(cliente, id=m["id"], moneda="EUR", importe="92", comision="4,6")
        assert r3.status_code == 200, r3.get_data(as_text=True)
        m3 = j3["item"]
        assert m3["importe"] == pytest.approx(92.0)
        assert "monedaOriginal" not in m3 and "tipoCambio" not in m3
        assert len(s.lee_json(ruta)["movimientos"]) == 1

        # Y si se vuelve a poner en dólares, se anota de nuevo con su cambio
        r4, j4 = _post_mov(cliente, id=m["id"])
        assert r4.status_code == 200, r4.get_data(as_text=True)
        m4 = j4["item"]
        assert m4["importeOriginal"] == pytest.approx(100.0)
        assert m4["monedaOriginal"] == "USD"
        assert m4["importe"] == pytest.approx(92.0)
    finally:
        _restaura_estados(ruta, cartera_antes, calc, calc_antes)


def test_no_se_puede_anotar_en_dolares_sin_cambio_conocido(cliente, monkeypatch):
    import os

    ruta = os.path.join(s.DATOS, "cartera.json")
    calc = os.path.join(s.DATOS, "calculado_propio.json")
    cartera_antes = s.lee_json(ruta)
    calc_antes = s.lee_json(calc, "ausente")
    monkeypatch.setattr(s.motor, "serie_cambio", lambda mon, carpeta: {})
    monkeypatch.setattr(s.motor, "descargar_serie", lambda *a, **k: {})
    try:
        s.escribe_json(ruta, _cartera_dolares())
        r, j = _post_mov(cliente)
        assert r.status_code == 400, r.get_data(as_text=True)
        assert "No encuentro el cambio de USD" in j["errores"][0]
        assert not s.lee_json(ruta)["movimientos"]   # no se guarda nada a medias
    finally:
        _restaura_estados(ruta, cartera_antes, calc, calc_antes)


# ------------------------- dividendos e intereses: el efectivo de la cuenta sube

def _cartera_efectivo():
    """Una cuenta con su producto de efectivo (ahí se guarda su saldo) y un fondo."""
    return {
        "titular": "Prueba",
        "cuentas": [{"id": "c1", "nombre": "Banco", "moneda": "EUR"}],
        "productos": [{"id": "f1", "nombre": "Fondo", "corto": "Fondo", "tipo": "fondo",
                       "fuente": "manual", "moneda": "EUR"},
                      {"id": "cash", "nombre": "Banco", "corto": "Banco", "tipo": "efectivo",
                       "fuente": "manual", "moneda": "EUR", "cuenta": "c1"}],
        "movimientos": [],
        "valoraciones": [{"id": "v1", "producto": "cash", "fecha": "2025-06-01", "valor": 1000.0}],
    }


def _valor_de(cfg, fecha):
    v = next((x for x in cfg["valoraciones"] if x["fecha"] == fecha), None)
    return (v["valor"], v.get("auto")) if v else (None, None)


def test_un_dividendo_sube_el_efectivo_de_la_cuenta():
    cfg = _cartera_efectivo()
    mov = {"id": "m1", "fecha": "2025-06-10", "tipo": "dividendo", "producto": "f1",
           "cuenta": "c1", "importe": 25.0}
    cfg["movimientos"].append(mov)
    avisos = []
    assert s.refresca_efectivo(cfg, mov, avisos) is True
    assert _valor_de(cfg, "2025-06-10") == (pytest.approx(1025.0), True)
    assert avisos == []


def test_un_interes_sin_producto_tambien_sube_el_efectivo():
    """El interés es sobre el capital de la cuenta: no hace falta producto y el
    saldo de esa cuenta sube en lo cobrado."""
    cfg = _cartera_efectivo()
    mov = {"id": "m1", "fecha": "2025-06-20", "tipo": "interes", "cuenta": "c1", "importe": 7.5}
    cfg["movimientos"].append(mov)
    assert s.refresca_efectivo(cfg, mov) is True
    assert _valor_de(cfg, "2025-06-20") == (pytest.approx(1007.5), True)


def test_varios_del_mismo_dia_y_borrado_dejan_el_saldo_derecho():
    cfg = _cartera_efectivo()
    m1 = {"id": "m1", "fecha": "2025-06-10", "tipo": "dividendo", "cuenta": "c1", "importe": 10.0}
    m2 = {"id": "m2", "fecha": "2025-06-10", "tipo": "interes", "cuenta": "c1", "importe": 5.0}
    cfg["movimientos"] += [m1, m2]
    s.refresca_efectivo(cfg, m1)
    s.refresca_efectivo(cfg, m2)                # recalcula el día entero: sin duplicar
    assert _valor_de(cfg, "2025-06-10") == (pytest.approx(1015.0), True)

    cfg["movimientos"] = [m1]                   # borrado uno, el día se rehace solo
    s.refresca_efectivo(cfg, m2)
    assert _valor_de(cfg, "2025-06-10") == (pytest.approx(1010.0), True)

    cfg["movimientos"] = []                     # sin ninguno, el saldo auto se retira
    s.refresca_efectivo(cfg, m1)
    assert _valor_de(cfg, "2025-06-10") == (None, None)


def test_no_toca_un_saldo_anotado_a_mano_y_lo_deja_a_la_vista():
    """Si ese día ya hay un saldo escrito a mano es el real del banco: no se le
    suma nada (casi siempre ya incluye lo cobrado) ni se le quita nada (se pisaría
    el dato del banco), PERO tampoco se esconde: el aviso da las dos cifras."""
    cfg = _cartera_efectivo()
    cfg["valoraciones"].append({"id": "v2", "producto": "cash", "fecha": "2025-06-10", "valor": 1003.0})
    mov = {"id": "m1", "fecha": "2025-06-10", "tipo": "dividendo", "cuenta": "c1", "importe": 25.0}
    cfg["movimientos"].append(mov)
    avisos = []
    assert s.refresca_efectivo(cfg, mov, avisos) is False
    assert _valor_de(cfg, "2025-06-10") == (pytest.approx(1003.0), None)
    assert avisos and "anotado a mano" in avisos[0]
    # …con lo anotado ese día (25) y con lo que habría que poner si el saldo era
    # anterior a ese dividendo (1.003 + 25): nada de «se ha ignorado en silencio».
    assert "25" in avisos[0] and "1.028" in avisos[0]


def test_un_deposito_sube_el_efectivo_y_una_retirada_lo_baja():
    """El dinero que entra o sale de una cuenta (ingreso, retirada) también tiene
    que reflejarse en su saldo, con su signo."""
    cfg = _cartera_efectivo()
    dep = {"id": "m1", "fecha": "2025-06-10", "tipo": "deposito", "cuenta": "c1", "importe": 500.0}
    cfg["movimientos"].append(dep)
    assert s.refresca_efectivo(cfg, dep) is True
    assert _valor_de(cfg, "2025-06-10") == (pytest.approx(1500.0), True)   # 1.000 + 500

    ret = {"id": "m2", "fecha": "2025-06-12", "tipo": "retirada", "cuenta": "c1", "importe": 200.0}
    cfg["movimientos"].append(ret)
    assert s.refresca_efectivo(cfg, ret) is True
    assert _valor_de(cfg, "2025-06-12") == (pytest.approx(1300.0), True)   # 1.500 − 200

    # Borrar la retirada rehace su día y el saldo vuelve a subir: no queda nada huérfano.
    cfg["movimientos"] = [dep]
    s.refresca_efectivo(cfg, ret)
    assert not any(v["fecha"] == "2025-06-12" for v in cfg["valoraciones"])


def test_una_transferencia_mueve_las_dos_cuentas():
    """Una transferencia es dinero que sale de una cuenta y entra en la otra: los
    dos saldos se refrescan (y el día entero se rehace, así que no se duplica)."""
    cfg = _cartera_efectivo()
    cfg["cuentas"].append({"id": "c2", "nombre": "Ahorro", "moneda": "EUR"})
    cfg["productos"].append({"id": "cash2", "nombre": "Ahorro", "corto": "Ahorro",
                             "tipo": "efectivo", "fuente": "manual", "moneda": "EUR", "cuenta": "c2"})
    cfg["valoraciones"].append({"id": "v2", "producto": "cash2", "fecha": "2025-06-01", "valor": 300.0})
    mov = {"id": "m1", "fecha": "2025-06-10", "tipo": "transferencia", "cuenta": "c1",
           "contrapartida": "c2", "importe": 150.0}
    cfg["movimientos"].append(mov)

    def valor(pid, f):
        v = next((v for v in cfg["valoraciones"] if v["producto"] == pid and v["fecha"] == f), None)
        return (v["valor"], v.get("auto")) if v else (None, None)

    assert s.refresca_efectivo(cfg, mov) is True
    assert valor("cash", "2025-06-10") == (pytest.approx(850.0), True)     # 1.000 − 150
    assert valor("cash2", "2025-06-10") == (pytest.approx(450.0), True)    #   300 + 150
    # Los saldos de los días anteriores siguen intactos.
    assert valor("cash", "2025-06-01") == (pytest.approx(1000.0), None)
    assert valor("cash2", "2025-06-01") == (pytest.approx(300.0), None)


def test_una_compra_baja_el_efectivo_de_la_cuenta_que_la_paga():
    """Compras, ventas, comisiones e impuestos también mueven dinero: el modelo
    ancla + libro antes solo miraba intereses, dividendos, depósitos y retiradas,
    y era el hueco principal (comprar no bajaba el saldo de nadie)."""
    cfg = _cartera_efectivo()
    comp = {"id": "m1", "fecha": "2025-06-10", "tipo": "compra", "producto": "f1",
            "cuenta": "c1", "unidades": 1, "importe": 500.0}
    cfg["movimientos"].append(comp)
    assert s.refresca_efectivo(cfg, comp) is True
    assert _valor_de(cfg, "2025-06-10") == (pytest.approx(500.0), True)   # 1.000 − 500

    # Borrada, el día se rehace entero y el saldo vuelve a estar como estaba.
    cfg["movimientos"] = []
    s.refresca_efectivo(cfg, comp)
    assert not any(v["fecha"] == "2025-06-10" for v in cfg["valoraciones"])


def test_en_una_compra_con_contrapartida_el_dinero_lo_saca_la_que_paga():
    """Si la compra trae contrapartida, el dinero lo desembolsa esa cuenta (es la
    cuenta corriente que paga; «cuenta» es donde guardas el activo): solo baja su
    saldo, no el de las dos."""
    cfg = _cartera_efectivo()
    cfg["cuentas"].append({"id": "c2", "nombre": "Ahorro", "moneda": "EUR"})
    cfg["productos"].append({"id": "cash2", "nombre": "Ahorro", "corto": "Ahorro",
                             "tipo": "efectivo", "fuente": "manual", "moneda": "EUR", "cuenta": "c2"})
    cfg["valoraciones"].append({"id": "v2", "producto": "cash2", "fecha": "2025-06-01", "valor": 300.0})
    comp = {"id": "m1", "fecha": "2025-06-10", "tipo": "compra", "producto": "f1",
            "cuenta": "c1", "contrapartida": "c2", "unidades": 1, "importe": 150.0}
    cfg["movimientos"].append(comp)
    s.refresca_efectivo(cfg, comp)

    def valor(pid, f):
        v = next((v for v in cfg["valoraciones"] if v["producto"] == pid and v["fecha"] == f), None)
        return (v["valor"], v.get("auto")) if v else (None, None)

    assert valor("cash2", "2025-06-10") == (pytest.approx(150.0), True)   #   300 − 150: paga ella
    assert valor("cash", "2025-06-10") == (None, None)                    # la otra, ni se entera
    assert valor("cash", "2025-06-01") == (pytest.approx(1000.0), None)   # su ancla, intacta


def test_una_venta_sube_el_efectivo_y_comision_e_impuesto_lo_bajan():
    cfg = _cartera_efectivo()
    ven = {"id": "m1", "fecha": "2025-06-10", "tipo": "venta", "producto": "f1",
           "cuenta": "c1", "unidades": 1, "importe": 700.0}
    cfg["movimientos"].append(ven)
    assert s.refresca_efectivo(cfg, ven) is True
    assert _valor_de(cfg, "2025-06-10") == (pytest.approx(1700.0), True)  # 1.000 + 700

    com = {"id": "m2", "fecha": "2025-06-12", "tipo": "comision", "cuenta": "c1", "importe": 2.5}
    imp = {"id": "m3", "fecha": "2025-06-12", "tipo": "impuesto", "cuenta": "c1", "importe": 10.0}
    cfg["movimientos"] += [com, imp]
    s.refresca_efectivo(cfg, com)
    s.refresca_efectivo(cfg, imp)
    assert _valor_de(cfg, "2025-06-12") == (pytest.approx(1687.5), True)  # 1.700 − 2,5 − 10


def test_una_compra_el_mismo_dia_de_un_saldo_a_mano_no_lo_pisa_y_lo_avisa():
    """Misma regla que con los intereses: manda el saldo anotado a mano, pero el
    dinero anotado ese día no se esconde —el aviso da las dos cifras—."""
    cfg = _cartera_efectivo()
    cfg["valoraciones"].append({"id": "v2", "producto": "cash", "fecha": "2025-06-10", "valor": 600.0})
    comp = {"id": "m1", "fecha": "2025-06-10", "tipo": "compra", "producto": "f1",
            "cuenta": "c1", "unidades": 1, "importe": 500.0}
    cfg["movimientos"].append(comp)
    avisos = []
    assert s.refresca_efectivo(cfg, comp, avisos) is False
    assert _valor_de(cfg, "2025-06-10") == (pytest.approx(600.0), None)   # intacto
    assert avisos and "Compra" in avisos[0] and "500" in avisos[0] and "100" in avisos[0]


def test_un_saldo_manual_posterior_deja_el_historico_como_esta():
    """Un movimiento antiguo no sube nada si después hay un saldo anotado a mano:
    ese saldo real ya recoge lo cobrado (los movimientos llegan con el extracto) y
    meter un punto calculado dejaría el histórico contradiciéndose."""
    cfg = _cartera_efectivo()
    cfg["valoraciones"].append({"id": "v2", "producto": "cash", "fecha": "2025-06-20", "valor": 1040.0})
    mov = {"id": "m1", "fecha": "2025-06-10", "tipo": "dividendo", "cuenta": "c1", "importe": 25.0}
    cfg["movimientos"].append(mov)
    avisos = []
    assert s.refresca_efectivo(cfg, mov, avisos) is False
    assert not any(v["fecha"] == "2025-06-10" for v in cfg["valoraciones"])
    assert avisos == []                      # es lo normal: no hay nada que avisar


def test_un_dividendo_se_apoya_en_el_ultimo_saldo_anotado():
    """El flujo normal: hay un saldo anotado a mano más reciente y después entra
    un dividendo → el nuevo saldo sale de ese más lo cobrado, sin tocar los otros."""
    cfg = _cartera_efectivo()
    cfg["valoraciones"].append({"id": "v2", "producto": "cash", "fecha": "2025-06-08", "valor": 1010.0})
    mov = {"id": "m1", "fecha": "2025-06-10", "tipo": "dividendo", "cuenta": "c1", "importe": 25.0}
    cfg["movimientos"].append(mov)
    assert s.refresca_efectivo(cfg, mov) is True
    assert _valor_de(cfg, "2025-06-10") == (pytest.approx(1035.0), True)   # 1.010 + 25
    assert _valor_de(cfg, "2025-06-08") == (pytest.approx(1010.0), None)   # el de antes, intacto


def test_cuenta_sin_producto_de_efectivo_se_le_crea_su_saldo(monkeypatch):
    """Una cuenta sin producto de efectivo (REVOLUT_EUR y otras) era invisible: no
    estaba en «Saldos y valores» y su dinero no subía nada. Ahora se le crea su
    saldo al anotar el primer movimiento, y la cuenta queda localizable."""
    monkeypatch.setattr(s, "_tc_eur", lambda mon, f: 1.0)     # sin salir a buscar el cambio
    cfg = _cartera_efectivo()
    cfg["cuentas"].append({"id": "c2", "nombre": "Revolut", "moneda": "USD"})
    mov = {"id": "m1", "fecha": "2025-06-10", "tipo": "dividendo", "cuenta": "c2", "importe": 3.0}
    cfg["movimientos"].append(mov)
    avisos = []
    assert s.refresca_efectivo(cfg, mov, avisos) is True
    p = s.almacen.producto_efectivo_de(cfg, "c2")
    assert p and p["moneda"] == "USD" and p["cuenta"] == "c2"
    assert _valor_de(cfg, "2025-06-10") == (pytest.approx(3.0), True)   # 0 + lo anotado
    assert avisos and "Revolut" in avisos[0] and "efectivo" in avisos[0]
    # …y se puede corregir a mano en «Saldos y valores»: el producto ya existe.
    assert any(x["producto"] == p["id"] for x in cfg["valoraciones"])


def test_el_importe_se_pasa_a_la_moneda_de_la_cuenta(monkeypatch):
    cfg = _cartera_efectivo()
    cfg["cuentas"].append({"id": "c2", "nombre": "Dólares", "moneda": "USD"})
    cfg["productos"].append({"id": "cash_usd", "nombre": "Dólares", "corto": "Dólares",
                             "tipo": "efectivo", "fuente": "manual", "moneda": "USD", "cuenta": "c2"})
    # anotado en la moneda de la cuenta: se usa el importe original, sin convertir
    en_usd = {"cuenta": "c2", "fecha": "2025-06-10", "importe": 92.0,
              "monedaOriginal": "USD", "importeOriginal": 100.0}
    assert s._importe_en_producto(cfg, en_usd) == pytest.approx(100.0)
    # anotado en euros: se pasa con el cambio del día
    monkeypatch.setattr(s, "_tc_eur", lambda mon, f: 1.10)
    en_eur = {"cuenta": "c2", "fecha": "2025-06-10", "importe": 92.0}
    assert s._importe_en_producto(cfg, en_eur) == pytest.approx(92.0 / 1.10)
    # sin cambio conocido no se inventa nada
    monkeypatch.setattr(s, "_tc_eur", lambda mon, f: None)
    assert s._importe_en_producto(cfg, en_eur) is None


def test_api_un_interes_sube_el_saldo_y_borrarlo_lo_quita(cliente, monkeypatch):
    """De punta a punta: anotar un interés desde el formulario sube el saldo de la
    cuenta (y se guarda su retención); borrar el movimiento retira ese saldo."""
    import os

    ruta = os.path.join(s.DATOS, "cartera.json")
    calc = os.path.join(s.DATOS, "calculado_propio.json")
    cartera_antes = s.lee_json(ruta)
    calc_antes = s.lee_json(calc, "ausente")
    monkeypatch.setattr(s.motor, "serie_cambio", lambda mon, carpeta: {})
    monkeypatch.setattr(s.motor, "descargar_serie", lambda *a, **k: {})
    try:
        s.escribe_json(ruta, _cartera_efectivo())
        r, j = _post_mov(cliente, tipo="interes", producto="", cuenta="c1",
                         importe="12", moneda="EUR", comision="", unidades="",
                         impuestos="3,5")
        assert r.status_code == 200, r.get_data(as_text=True)
        m = j["item"]
        assert "producto" not in m and m["cuenta"] == "c1"
        assert m["impuestos"] == pytest.approx(3.5)
        assert _valor_de(j["cartera"], "2025-06-20") == (pytest.approx(1012.0), True)

        r2 = cliente.delete(f"/api/movimientos/{m['id']}")
        assert r2.status_code == 200, r2.get_data(as_text=True)
        assert _valor_de(r2.get_json()["cartera"], "2025-06-20") == (None, None)
        assert len(s.lee_json(ruta)["valoraciones"]) == 1
    finally:
        _restaura_estados(ruta, cartera_antes, calc, calc_antes)


def test_api_al_mover_un_interes_el_dia_viejo_se_rehace(cliente, monkeypatch):
    """Si al corregir un interés le cambias la fecha, el saldo del día anterior deja
    de contarlo y el día nuevo lo recoge: no se queda ningún saldo huérfano."""
    import os

    ruta = os.path.join(s.DATOS, "cartera.json")
    calc = os.path.join(s.DATOS, "calculado_propio.json")
    cartera_antes = s.lee_json(ruta)
    calc_antes = s.lee_json(calc, "ausente")
    monkeypatch.setattr(s.motor, "serie_cambio", lambda mon, carpeta: {})
    monkeypatch.setattr(s.motor, "descargar_serie", lambda *a, **k: {})
    try:
        s.escribe_json(ruta, _cartera_efectivo())
        r, j = _post_mov(cliente, tipo="interes", producto="", cuenta="c1",
                         importe="25", moneda="EUR", comision="", unidades="")
        assert r.status_code == 200, r.get_data(as_text=True)
        assert _valor_de(j["cartera"], "2025-06-20") == (pytest.approx(1025.0), True)

        r2, j2 = _post_mov(cliente, id=j["item"]["id"], tipo="interes", producto="",
                           cuenta="c1", importe="25", moneda="EUR", fecha="2025-06-22",
                           comision="", unidades="")
        assert r2.status_code == 200, r2.get_data(as_text=True)
        vals = {v["fecha"]: v for v in j2["cartera"]["valoraciones"] if v["producto"] == "cash"}
        assert "2025-06-20" not in vals                 # el día que quedó vacío se retira
        assert vals["2025-06-22"]["valor"] == pytest.approx(1025.0)   # y el nuevo sube
    finally:
        _restaura_estados(ruta, cartera_antes, calc, calc_antes)


def test_api_al_crear_una_cuenta_se_le_crea_su_producto_de_efectivo(cliente, monkeypatch):
    """Invariante del modelo cuentas/valores: al crear una cuenta se le crea su
    producto de efectivo (1:1), que es donde se anota su saldo y donde sube. Sin
    él la cuenta existía pero era invisible: REVOLUT_EUR no aparecía por ningún
    sitio y su dinero no podía subir."""
    import os

    ruta = os.path.join(s.DATOS, "cartera.json")
    calc = os.path.join(s.DATOS, "calculado_propio.json")
    cartera_antes = s.lee_json(ruta)
    calc_antes = s.lee_json(calc, "ausente")
    monkeypatch.setattr(s.motor, "serie_cambio", lambda mon, carpeta: {})
    monkeypatch.setattr(s.motor, "descargar_serie", lambda *a, **k: {})
    try:
        s.escribe_json(ruta, _cartera_efectivo())
        r = cliente.post("/api/cuentas", json={"nombre": "REVOLUT_EUR", "tipo": "broker",
                                               "moneda": "eur", "entidad": "Revolut"})
        assert r.status_code == 200, r.get_data(as_text=True)
        j = r.get_json()
        cid = j["item"]["id"]
        p = s.almacen.producto_efectivo_de(j["cartera"], cid)
        assert p and p["tipo"] == "efectivo" and p["moneda"] == "EUR"
        assert p["cuenta"] == cid and p["nombre"] == "REVOLUT_EUR"
        # La migración deja TODAS las cuentas con su producto (la vieja c1 incluida).
        assert all(s.almacen.producto_efectivo_de(j["cartera"], c["id"])
                   for c in j["cartera"]["cuentas"])
        # Y los tipos de cuenta llegan al formulario de «Mis datos → Cuentas».
        tipos = cliente.get("/api/cartera").get_json()["tiposCuenta"]
        assert tipos["broker"] == "Bróker" and "efectivo" in tipos
    finally:
        _restaura_estados(ruta, cartera_antes, calc, calc_antes)


# ------------------------------------------------------- versión de la app

def test_app_version_tiene_el_formato_acordado():
    """La versión vive en un solo sitio (app/VERSION) y en formato V<mayor>.<menor>
    con DOS dígitos en la menor: V1.00, V1.01, … V1.99, V2.00."""
    import re
    with open(os.path.join(s.RAIZ, "app", "VERSION"), encoding="utf-8") as f:
        version = f.read().strip()
    assert re.fullmatch(r"\d+\.\d{2}", version), version
    etiqueta = s.version_etiqueta()
    assert etiqueta == "V" + version
    assert re.fullmatch(r"V\d+\.\d{2}", etiqueta), etiqueta


def test_el_comparador_de_versiones_ordena_bien(cliente):
    """V1.99 < V2.00 y V1.01 > V1.00: el orden tiene que ser el de los números, no
    el alfabético, o el aviso de «hay versión nueva» mentiría."""
    como_tupla = lambda v: tuple(int(x) for x in __import__("re").findall(r"\d+", v))
    assert como_tupla("1.99") < como_tupla("2.00")
    assert como_tupla("1.00") < como_tupla("1.01")
    assert como_tupla("2.00") > como_tupla("1.99")
    assert como_tupla(s.version_actual()) == como_tupla(s.version_actual())


def test_api_version_devuelve_la_etiqueta_los_dos_repos_y_la_publica(cliente):
    """El navegador no formatea versiones: se lo da el backend ya hecho. Y los
    enlaces son los dos: el repo propio y el proyecto original."""
    j = cliente.get("/api/version").get_json()
    assert j["etiqueta"] == "V" + j["actual"]
    assert j["repo"] == s.REPO == "https://github.com/daesdel/rumbo"
    assert j["repoOriginal"] == s.REPO_ORIGINAL == "https://github.com/danidm98/rumbo"
    # El aviso de versión nueva se lee del repo PROPIO, no del original.
    assert "danidm98" not in j["repo"]
    assert "hayNueva" in j


def test_datos_js_lleva_la_version_al_navegador(cliente):
    """El header se pinta sin ida y vuelta: /datos.js ya entrega window.VERSION."""
    cuerpo = cliente.get("/datos.js").get_data(as_text=True)
    assert cuerpo.startswith('window.VERSION = "V')
    assert "window.DATOS = {" in cuerpo
