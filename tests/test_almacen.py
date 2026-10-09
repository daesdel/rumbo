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


# --------------------------------- cuentas de efectivo y contrapartida

def _cfg_cuentas():
    return {
        "productos": [{"id": "f", "nombre": "Tesla", "corto": "Tesla", "tipo": "accion",
                       "fuente": "yahoo", "codigo": "TSLA"}],
        "cuentas": [{"id": "efectivo", "nombre": "Caja", "tipo": "efectivo", "moneda": "EUR"},
                    {"id": "banco", "nombre": "Banco", "tipo": "banco", "moneda": "EUR"}],
        "movimientos": [], "valoraciones": [],
    }


def test_deposito_con_contrapartida_se_guarda():
    """Un depósito o una retirada pueden llevar la otra cuenta implicada."""
    cfg = _cfg_cuentas()
    m = almacen.guarda_movimiento(cfg, {"fecha": "2025-03-01", "tipo": "deposito",
                                        "importe": 500, "cuenta": "efectivo",
                                        "contrapartida": "banco"})
    assert m["cuenta"] == "efectivo" and m["contrapartida"] == "banco"


def test_contrapartida_invalida_o_igual_a_la_cuenta():
    cfg = _cfg_cuentas()
    # una contrapartida que no existe se ignora (igual que la cuenta)
    m = almacen.guarda_movimiento(cfg, {"fecha": "2025-03-01", "tipo": "retirada",
                                        "importe": 20, "cuenta": "efectivo",
                                        "contrapartida": "no_existe"})
    assert "contrapartida" not in m
    # la misma cuenta en los dos lados no tiene sentido
    with pytest.raises(almacen.ErrorValidacion) as ex:
        almacen.guarda_movimiento(cfg, {"fecha": "2025-03-02", "tipo": "retirada",
                                        "importe": 20, "cuenta": "efectivo",
                                        "contrapartida": "efectivo"})
    assert any("contrapartida" in e for e in ex.value.errores)


def test_compra_externa_y_vinculo_del_producto_a_su_cuenta():
    """Sin cuenta, una compra es dinero nuevo (externo); con el checkbox de
    vincular, el producto queda unido a la cuenta para futuros movimientos."""
    cfg = _cfg_cuentas()
    m = almacen.guarda_movimiento(cfg, {"fecha": "2025-03-01", "tipo": "compra", "producto": "f",
                                        "unidades": 1, "importe": 100})
    assert "cuenta" not in m                      # aportación externa
    assert cfg["productos"][0].get("cuenta") is None

    almacen.guarda_movimiento(cfg, {"fecha": "2025-03-02", "tipo": "compra", "producto": "f",
                                    "unidades": 1, "importe": 50, "cuenta": "banco",
                                    "vincular": "1"})
    assert cfg["productos"][0]["cuenta"] == "banco"

    # sin el checkbox no se toca el vínculo ya existente
    almacen.guarda_movimiento(cfg, {"fecha": "2025-03-03", "tipo": "dividendo", "producto": "f",
                                    "importe": 5, "cuenta": "efectivo"})
    assert cfg["productos"][0]["cuenta"] == "banco"


def test_guarda_producto_valida_la_cuenta_vinculada():
    cfg = _cfg_cuentas()
    with pytest.raises(almacen.ErrorValidacion) as ex:
        almacen.guarda_producto(cfg, {"nombre": "Fondo", "tipo": "fondo", "fuente": "yahoo",
                                      "codigo": "X", "cuenta": "no_existe"})
    assert any("cuenta" in e for e in ex.value.errores)

    prod, _ = almacen.guarda_producto(cfg, {"nombre": "Fondo", "tipo": "fondo", "fuente": "yahoo",
                                            "codigo": "X", "cuenta": "banco"})
    assert prod["cuenta"] == "banco"
    # y se puede quitar el vínculo
    prod2, _ = almacen.guarda_producto(cfg, {"id": prod["id"], "nombre": "Fondo", "tipo": "fondo",
                                             "fuente": "yahoo", "codigo": "X", "cuenta": ""})
    assert "cuenta" not in prod2


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


def test_los_ficheros_de_datos_quedan_solo_para_el_dueno(tmp_path):
    """Permisos 600: nadie más que el dueño del sistema puede leer la cartera
    (ni con cp, ni un backup, ni otro usuario del mismo ordenador)."""
    import os
    import stat
    if os.name == "nt":
        pytest.skip("en Windows no hay permisos unix")
    ruta = str(tmp_path / "cartera.json")
    cfg = {"productos": [], "movimientos": [], "valoraciones": []}
    almacen.guarda(ruta, cfg)
    assert stat.S_IMODE(os.stat(ruta).st_mode) == 0o600

    cfg["titular"] = "Cambiado"
    almacen.guarda(ruta, cfg)
    assert stat.S_IMODE(os.stat(ruta).st_mode) == 0o600
    copias = list((tmp_path / "copias").glob("auto_*.json"))
    assert copias and all(stat.S_IMODE(os.stat(c).st_mode) == 0o600 for c in copias)


# --------------------------------- escisiones (spin-off): entrega entrante

def _cfg_escision():
    return {
        "productos": [
            {"id": "ctva", "nombre": "Corteva", "corto": "CTVA", "tipo": "accion",
             "fuente": "yahoo", "codigo": "CTVA"},
            {"id": "vylr", "nombre": "Vylor", "corto": "VYLR", "tipo": "accion",
             "fuente": "yahoo", "codigo": "VYLR"}],
        "cuentas": [{"id": "broker", "nombre": "Bróker", "tipo": "broker", "moneda": "EUR"}],
        "movimientos": [{"id": "m1", "fecha": "2025-06-01", "producto": "ctva",
                         "tipo": "compra", "unidades": 20, "importe": 1000.0}],
        "valoraciones": [],
    }


def test_entrega_entrante_no_toca_efectivo_y_le_quita_coste_al_original():
    """La entrega entra con títulos y coste asignado, sin cuenta de efectivo; el
    coste sale del activo original para que no aparezca una pérdida falsa."""
    cfg = _cfg_escision()
    m = almacen.guarda_movimiento(cfg, {
        "producto": "vylr", "fecha": "2025-09-01", "tipo": "entrega",
        "unidades": 20, "importe": 400.0, "productoOrigen": "ctva"})
    assert m["tipo"] == "entrega"
    assert m["unidades"] == 20 and m["importe"] == 400.0
    assert m["productoOrigen"] == "ctva"
    assert "cuenta" not in m                                  # no mueve dinero
    assert almacen.aportado_de(cfg, "ctva") == pytest.approx(600.0)
    assert almacen.unidades_a(cfg, "vylr", "2025-09-30") == 20


def test_entrega_gratis_admite_importe_cero():
    cfg = _cfg_escision()
    m = almacen.guarda_movimiento(cfg, {
        "producto": "vylr", "fecha": "2025-09-01", "tipo": "entrega",
        "unidades": 20, "importe": 0, "productoOrigen": "ctva"})
    assert m["importe"] == 0
    assert almacen.aportado_de(cfg, "ctva") == pytest.approx(1000.0)   # intacto
    # sin coste tampoco hace falta descontar nada del original
    m2 = almacen.guarda_movimiento(cfg, {
        "producto": "vylr", "fecha": "2025-09-02", "tipo": "entrega",
        "unidades": 5, "importe": ""})
    assert m2["importe"] == 0
    assert "productoOrigen" not in m2


def test_entrega_no_puede_consumir_mas_coste_del_que_hay():
    cfg = _cfg_escision()
    with pytest.raises(almacen.ErrorValidacion) as ex:
        almacen.guarda_movimiento(cfg, {
            "producto": "vylr", "fecha": "2025-09-01", "tipo": "entrega",
            "unidades": 20, "importe": 5000.0, "productoOrigen": "ctva"})
    assert any("mayor que lo que tienes" in e for e in ex.value.errores)
    assert len(cfg["movimientos"]) == 1                     # no se guarda nada


def test_entrega_requiere_unidades_y_origen_valido():
    cfg = _cfg_escision()
    with pytest.raises(almacen.ErrorValidacion) as ex:
        almacen.guarda_movimiento(cfg, {
            "producto": "vylr", "fecha": "2025-09-01", "tipo": "entrega", "importe": 0})
    assert any("cuántas unidades entran" in e for e in ex.value.errores)

    with pytest.raises(almacen.ErrorValidacion) as ex:
        almacen.guarda_movimiento(cfg, {
            "producto": "vylr", "fecha": "2025-09-01", "tipo": "entrega",
            "unidades": 5, "importe": 0, "productoOrigen": "no_existe"})
    assert any("no existe" in e for e in ex.value.errores)

    with pytest.raises(almacen.ErrorValidacion) as ex:
        almacen.guarda_movimiento(cfg, {
            "producto": "vylr", "fecha": "2025-09-01", "tipo": "entrega",
            "unidades": 5, "importe": 0, "productoOrigen": "vylr"})
    assert any("distinto" in e for e in ex.value.errores)


def test_tras_una_entrega_se_puede_vender_lo_recibido():
    """Antes solo contaban compras y ventas: sin esto, vender los títulos de una
    escisión daba error de «solo tenías 0 unidades»."""
    cfg = _cfg_escision()
    almacen.guarda_movimiento(cfg, {
        "producto": "vylr", "fecha": "2025-09-01", "tipo": "entrega",
        "unidades": 20, "importe": 400.0, "productoOrigen": "ctva"})
    m = almacen.guarda_movimiento(cfg, {
        "producto": "vylr", "fecha": "2025-10-01", "tipo": "venta",
        "unidades": 20, "importe": 500.0})
    assert m["tipo"] == "venta"


# ------------------------------- dividendos e intereses: retención y comisión

def test_un_dividendo_guarda_sus_impuestos_y_su_comision():
    """El formulario puede indicar retención y comisión en un dividendo: se guardan
    aparte, como números, porque el importe ya es lo que llega a la cuenta."""
    cfg = _cfg_cuentas()
    m = almacen.guarda_movimiento(cfg, {"fecha": "2025-04-01", "tipo": "dividendo",
                                        "producto": "f", "cuenta": "efectivo",
                                        "importe": 100, "impuestos": "19,5", "comision": 0.5})
    assert m["impuestos"] == pytest.approx(19.5)
    assert m["comision"] == pytest.approx(0.5)
    assert m["importe"] == pytest.approx(100)      # el importe no se toca
    # vaciando los campos se borran: no se queda el valor viejo
    m2 = almacen.guarda_movimiento(cfg, {"id": m["id"], "fecha": "2025-04-01", "tipo": "dividendo",
                                         "producto": "f", "cuenta": "efectivo",
                                         "importe": 100, "impuestos": "", "comision": ""})
    assert "impuestos" not in m2 and "comision" not in m2


def test_los_impuestos_no_validos_no_se_guardan():
    cfg = _cfg_cuentas()
    for malo in ("abc", -5):
        with pytest.raises(almacen.ErrorValidacion):
            almacen.guarda_movimiento(cfg, {"fecha": "2025-04-01", "tipo": "interes",
                                            "cuenta": "efectivo", "importe": 10,
                                            "impuestos": malo})
    assert not cfg["movimientos"]


def test_un_interes_no_necesita_producto_si_tiene_cuenta():
    """El interés es sobre el capital que hay en la cuenta: sin producto se anota,
    y sin cuenta y sin producto no hay dónde cobrarlo."""
    cfg = _cfg_cuentas()
    m = almacen.guarda_movimiento(cfg, {"fecha": "2025-04-01", "tipo": "interes",
                                        "cuenta": "efectivo", "importe": 12.5, "impuestos": 3})
    assert "producto" not in m and m["cuenta"] == "efectivo"
    assert m["impuestos"] == pytest.approx(3)
    with pytest.raises(almacen.ErrorValidacion):
        almacen.guarda_movimiento(cfg, {"fecha": "2025-04-02", "tipo": "interes", "importe": 3})


def test_producto_efectivo_de_encuentra_el_saldo_de_la_cuenta():
    cfg = _cfg_cuentas()
    assert almacen.producto_efectivo_de(cfg, "efectivo") is None
    assert almacen.producto_efectivo_de(cfg, "que_no_existe") is None
    assert almacen.producto_efectivo_de(cfg, None) is None
    cfg["productos"].append({"id": "cash", "nombre": "Caja", "corto": "Caja", "tipo": "efectivo",
                             "fuente": "manual", "moneda": "EUR", "cuenta": "efectivo"})
    assert almacen.producto_efectivo_de(cfg, "efectivo")["id"] == "cash"
    # una deuda (pasivo) no es el efectivo de la cuenta
    cfg["productos"].append({"id": "debe", "nombre": "Deuda", "corto": "Deuda", "tipo": "deuda",
                             "fuente": "manual", "moneda": "EUR", "cuenta": "efectivo"})
    assert almacen.producto_efectivo_de(cfg, "efectivo")["id"] == "cash"
