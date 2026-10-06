# -*- coding: utf-8 -*-
"""
test_servidor.py  ·  El servidor local y su blindaje
=====================================================
El middleware de Host/Origin (contra DNS rebinding y CSRF), la ruta de salud
y la guardia del modo demostración.
"""
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
        assert cuerpo.startswith("window.DATOS = {")     # no "null"
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
