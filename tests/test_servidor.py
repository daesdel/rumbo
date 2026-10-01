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
