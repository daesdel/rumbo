# -*- coding: utf-8 -*-
"""
test_almacen.py  ·  Validación y guardado
==========================================
Lo que protege cartera.json: números y fechas en castellano, validación de
productos y movimientos, y la copia automática antes de cada escritura.
"""
import datetime as dt
import json

import pytest

from app import almacen


# ---------------------------------------------------------------- campos

def test_numero_acepta_formatos_y_da_error_si_no_lo_es():
    errores = []
    assert almacen.numero("1.234,56", "el importe", errores) == 1234.56
    assert almacen.numero("9,5", "el importe", errores) == 9.5
    assert almacen.numero(10, "el importe", errores) == 10.0
    assert errores == []

    assert almacen.numero(None, "el importe", errores) is None
    assert errores and "Falta" in errores[0]

    errores.clear()
    assert almacen.numero("no sé", "el importe", errores) is None
    assert any("no es un número" in e for e in errores)


def test_numero_con_minimo():
    errores = []
    assert almacen.numero(0.5, "el TER", errores, minimo=0) == 0.5
    assert almacen.numero(-1, "el TER", errores, minimo=0) == -1.0
    assert any("menor" in e for e in errores)


def test_fecha_rechaza_futura_y_antigua():
    errores = []
    assert almacen.fecha("2025-03-10", errores) == "2025-03-10"
    assert errores == []

    # una fecha futura o de hace demasiado se anota como error (la validación
    # posterior la rechaza), aunque la función devuelva la fecha leída
    mañana = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    almacen.fecha(mañana, errores)
    assert any("futura" in e for e in errores)

    errores.clear()
    almacen.fecha("1940-01-01", errores)
    assert errores

    errores.clear()
    assert almacen.fecha("31/02/2025", errores) is None   # no existe
    assert errores

    errores.clear()
    assert almacen.fecha("no sé", errores) is None
    assert errores


def test_slug_no_se_repite():
    assert almacen.slug("Fondo MSCI World", set()) == "fondo_msci_world"
    assert almacen.slug("Fondo MSCI World", {"fondo_msci_world"}) == "fondo_msci_world_2"
    assert almacen.slug("", set()) == "producto"


# ---------------------------------------------------------------- productos

def test_guarda_producto_valida_los_campos_obligatorios():
    cfg = {"productos": [], "movimientos": [], "valoraciones": []}
    with pytest.raises(almacen.ErrorValidacion) as ex:
        almacen.guarda_producto(cfg, {"nombre": "", "tipo": "fondo", "fuente": "yahoo"})
    assert any("nombre" in e for e in ex.value.errores)

    with pytest.raises(almacen.ErrorValidacion):
        # cotiza en internet pero sin código no puede buscar precio
        almacen.guarda_producto(cfg, {"nombre": "Fondo", "tipo": "fondo", "fuente": "yahoo", "codigo": ""})

    with pytest.raises(almacen.ErrorValidacion):
        almacen.guarda_producto(cfg, {"nombre": "Fondo", "tipo": "tipoinventado", "fuente": "yahoo", "codigo": "X"})


def test_guarda_producto_crea_y_actualiza_sin_duplicar():
    cfg = {"productos": [], "movimientos": [], "valoraciones": []}
    prod, cambio = almacen.guarda_producto(
        cfg, {"nombre": "Fondo X", "tipo": "fondo", "fuente": "yahoo", "codigo": "XYZ"})
    assert prod["id"] == "fondo_x"
    assert cambio is True
    assert len(cfg["productos"]) == 1

    # segunda llamada con id: actualiza, no duplica
    prod2, cambio2 = almacen.guarda_producto(
        cfg, {"id": "fondo_x", "nombre": "Fondo X", "tipo": "fondo", "fuente": "yahoo", "codigo": "XYZ"})
    assert prod2["id"] == "fondo_x"
    assert cambio2 is False
    assert len(cfg["productos"]) == 1


def test_borra_producto_limpia_sus_movimientos():
    cfg = {
        "productos": [{"id": "f", "nombre": "F", "corto": "F", "tipo": "fondo", "fuente": "manual"}],
        "movimientos": [{"id": "m1", "fecha": "2025-01-01", "producto": "f",
                         "tipo": "compra", "unidades": 1, "importe": 10.0}],
        "valoraciones": [{"id": "v1", "producto": "f", "fecha": "2025-01-01", "valor": 10.0}],
        "comparador": [{"id": "real", "real": True}],
    }
    almacen.borra_producto(cfg, "f")
    assert cfg["productos"] == []
    assert cfg["movimientos"] == []
    assert cfg["valoraciones"] == []

    with pytest.raises(almacen.ErrorValidacion):
        almacen.borra_producto(cfg, "f")


# ---------------------------------------------------------------- movimientos

def test_venta_no_puede_superar_las_unidades_que_tienes():
    cfg = {
        "productos": [{"id": "f", "nombre": "F", "corto": "F", "tipo": "accion",
                       "fuente": "yahoo", "codigo": "ABC"}],
        "movimientos": [{"id": "m1", "fecha": "2025-01-01", "producto": "f",
                         "tipo": "compra", "unidades": 5, "importe": 500.0}],
        "valoraciones": [],
    }
    with pytest.raises(almacen.ErrorValidacion) as ex:
        almacen.guarda_movimiento(
            cfg, {"producto": "f", "fecha": "2025-02-01", "tipo": "venta",
                  "unidades": 10, "importe": 900.0})
    assert any("solo tenías" in e for e in ex.value.errores)
    assert len(cfg["movimientos"]) == 1   # no se guarda nada


def test_una_cuenta_no_admite_movimientos():
    cfg = {
        "productos": [{"id": "c", "nombre": "Cuenta", "corto": "Cuenta",
                       "tipo": "efectivo", "fuente": "manual"}],
        "movimientos": [], "valoraciones": [],
    }
    with pytest.raises(almacen.ErrorValidacion) as ex:
        almacen.guarda_movimiento(
            cfg, {"producto": "c", "fecha": "2025-02-01", "tipo": "compra",
                  "unidades": 1, "importe": 50.0})
    assert any("saldos" in e for e in ex.value.errores)


def _cfg_tesla():
    return {
        "productos": [{"id": "f", "nombre": "Tesla", "corto": "Tesla", "tipo": "accion",
                       "fuente": "yahoo", "codigo": "TSLA"}],
        "cuentas": [{"id": "revolut_usd", "nombre": "REVOLUT USD", "tipo": "broker",
                     "moneda": "USD", "propietario": "david"}],
        "movimientos": [{"id": "m1", "fecha": "2025-01-17", "producto": "f",
                         "tipo": "compra", "unidades": 1, "importe": 291.21,
                         "cuenta": "revolut_usd", "propietario": "david",
                         "importeOriginal": 300.0, "monedaOriginal": "USD",
                         "tipoCambio": 0.9707, "origen": "portfolio",
                         "contrapartida": "revolut_dolares"}],
        "valoraciones": [],
    }


def test_editar_movimiento_conserva_importe_original_y_moneda():
    """El formulario solo vuelve a mandar unos pocos campos: al editar no se
    pierden los datos de la importación (importe original, moneda, cambio,
    contrapartida, origen)."""
    cfg = _cfg_tesla()
    m = almacen.guarda_movimiento(cfg, {
        "id": "m1", "fecha": "2025-01-17", "producto": "f", "tipo": "compra",
        "unidades": 1, "importe": 291.21, "cuenta": "revolut_usd",
        "propietario": "david"})
    assert m["importeOriginal"] == 300.0
    assert m["monedaOriginal"] == "USD"
    assert m["tipoCambio"] == 0.9707
    assert m["origen"] == "portfolio"
    assert m["contrapartida"] == "revolut_dolares"
    assert len(cfg["movimientos"]) == 1


def test_editar_movimiento_permite_corregir_cuenta_y_propietario():
    """Se puede corregir a mano a quién pertenece un movimiento importado mal
    (el caso de las compras de Tesla atribuidas al propietario equivocado)."""
    cfg = _cfg_tesla()
    m = almacen.guarda_movimiento(cfg, {
        "id": "m1", "fecha": "2025-01-17", "producto": "f", "tipo": "compra",
        "unidades": 1, "importe": 291.21, "cuenta": "revolut_usd",
        "propietario": "gina"})
    assert m["propietario"] == "gina"
    assert m["cuenta"] == "revolut_usd"


def test_al_cambiar_el_importe_se_actualiza_el_original():
    """Si se corrige el importe en euros, el de la moneda original se recalcula
    con el tipo de cambio guardado para que no quede descoherente."""
    cfg = _cfg_tesla()
    m = almacen.guarda_movimiento(cfg, {
        "id": "m1", "fecha": "2025-01-17", "producto": "f", "tipo": "compra",
        "unidades": 1, "importe": 194.14, "cuenta": "revolut_usd"})
    assert m["importeOriginal"] == pytest.approx(200.0)   # 194,14 € ÷ 0,9707
    assert m["importe"] == 194.14


# ---------------------------------------------------------------- disco

def test_guarda_hace_copia_automatica_y_escritura_atomica(tmp_path):
    ruta = str(tmp_path / "cartera.json")
    cfg = {"productos": [], "movimientos": [], "valoraciones": []}
    almacen.guarda(ruta, cfg)                 # primera escritura: no hay previa

    cfg["titular"] = "Cambiado"
    almacen.guarda(ruta, cfg)                 # segunda: copia la anterior

    copias = list((tmp_path / "copias").glob("auto_*.json"))
    assert len(copias) == 1
    with open(copias[0], encoding="utf-8") as f:
        previa = json.load(f)
    assert "titular" not in previa            # la copia es del ANTES

    with open(ruta, encoding="utf-8") as f:
        assert json.load(f)["titular"] == "Cambiado"
    assert not (tmp_path / "cartera.json.tmp").exists()   # sin temporales colgados
