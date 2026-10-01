# -*- coding: utf-8 -*-
"""
test_motor.py  ·  Los cálculos del corazón de la app
=====================================================
TIR (XIRR), ventas FIFO como Hacienda, números en castellano y el cálculo
completo del panel sin salir a internet (descargar=False).
"""
import copy
import datetime as dt

import pytest

from app import motor


# ---------------------------------------------------------------- números

def test_num_es_formatos_castellanos():
    assert motor.num_es("1.399,89") == 1399.89
    assert motor.num_es("3352,6") == 3352.6
    assert motor.num_es("13.25") == 13.25          # inglés: decimal
    assert motor.num_es("1.000") == 1000.0          # castellano: miles
    assert motor.num_es("1234") == 1234.0
    assert motor.num_es("1.234,56 €") == 1234.56
    assert motor.num_es("") == 0.0
    assert motor.num_es("no es un número") == 0.0


# ---------------------------------------------------------------- TIR

def test_xirr_deposito_de_un_ano():
    # 1.000 € metidos el 1/1/2024, 1.100 € el 1/1/2025: ~10 % al año.
    r = motor.xirr([(dt.date(2024, 1, 1), -1000.0), (dt.date(2025, 1, 1), 1100.0)])
    assert r is not None
    assert abs(r - 0.10) < 0.01


def test_xirr_sin_flujos_mixtos_no_inventa_nada():
    assert motor.xirr([]) is None
    assert motor.xirr([(dt.date(2024, 1, 1), -1000.0)]) is None
    # todo positivo (sin salida de dinero) no es una TIR
    assert motor.xirr([(dt.date(2024, 1, 1), 100.0), (dt.date(2025, 1, 1), 110.0)]) is None


def test_xirr_ignora_flujos_a_cero():
    r = motor.xirr([(dt.date(2024, 1, 1), -1000.0),
                    (dt.date(2024, 6, 1), 0.0),
                    (dt.date(2025, 1, 1), 1100.0)])
    assert r is not None
    assert abs(r - 0.10) < 0.01


# ---------------------------------------------------------------- FIFO

def _mov(fecha, tipo, unidades, importe, comision=None):
    return {"id": f"m{fecha}{tipo}", "fecha": fecha, "producto": "p",
            "tipo": tipo, "unidades": unidades, "importe": importe,
            **({"comision": comision} if comision else {})}


def test_fifo_la_venta_descuenta_lo_mas_antiguo():
    motor.AVISOS.clear()
    movs = [_mov("2025-01-01", "compra", 10, 1000.0),
            _mov("2025-02-01", "compra", 10, 2000.0),
            _mov("2025-03-01", "venta", 15, 4500.0)]
    r = motor.aplicar_movimientos({"corto": "test"}, movs)
    # Lo vendido sale de lo primero: coste = 1.000 (primer lote) + 5×200 = 2.000
    assert r["realizado"] == pytest.approx(2500.0)
    assert [v for _, v in r["flujos"]] == [-1000.0, -2000.0, 4500.0]
    # El evento de la venta: −15 unidades y −2.000 de coste
    assert r["eventos"][-1] == ("2025-03-01", -15.0, -2000.0)
    assert not motor.AVISOS   # vendió exactamente lo que había


def test_fifo_venta_de_mas_de_lo_que_tienes_avisas():
    motor.AVISOS.clear()
    movs = [_mov("2025-01-01", "compra", 10, 1000.0),
            _mov("2025-02-01", "venta", 15, 1500.0)]
    r = motor.aplicar_movimientos({"corto": "fondo raro"}, movs)
    assert any("vendes más unidades" in a for a in motor.AVISOS)
    assert r["eventos"][-1][1] == pytest.approx(-10.0)   # solo pudo vender 10
    assert r["realizado"] == pytest.approx(500.0)


def test_dividendos_suman_y_comisiones_restan():
    motor.AVISOS.clear()
    movs = [_mov("2025-01-01", "compra", 10, 1000.0, comision=2.0),
            _mov("2025-04-01", "dividendo", 0, 50.0),
            _mov("2025-05-01", "comision", 0, 3.0)]
    r = motor.aplicar_movimientos({"corto": "test"}, movs)
    assert r["realizado"] == pytest.approx(47.0)      # 50 − 3
    assert r["comisiones"] == pytest.approx(5.0)       # 2 de compra + 3 del año
    assert [v for _, v in r["flujos"]] == [-1000.0, 50.0, -3.0]


# ---------------------------------------------------------------- series

def test_valor_en_y_rellenar():
    serie = {"2025-01-10": 100.0, "2025-01-12": 102.0}
    assert motor.valor_en(serie, "2025-01-11") == 100.0      # arrastra el último
    assert motor.valor_en(serie, "2025-01-12") == 102.0
    assert motor.valor_en(serie, "2025-01-25") is None        # más allá del margen
    eje = [dt.date(2025, 1, 10), dt.date(2025, 1, 11), dt.date(2025, 1, 12)]
    assert motor.rellenar(serie, eje) == [100.0, 100.0, 102.0]


def test_mover_fin_de_semana():
    serie = {"2025-01-10": 1.0, "2025-01-11": 2.0}   # viernes y sábado
    salida = motor.mover_fin_de_semana(serie)
    assert "2025-01-11" not in salida
    assert salida["2025-01-10"] == 1.0


# ---------------------------------------------------------------- panel

def _cartera_de_prueba():
    return {
        "titular": "Prueba",
        "productos": [
            {"id": "cuenta", "nombre": "Cuenta", "corto": "Cuenta",
             "tipo": "efectivo", "fuente": "manual"},
            {"id": "fondo", "nombre": "Fondo raro", "corto": "Fondo raro",
             "tipo": "otro", "fuente": "manual", "clase": "Fondos", "slot": 1},
        ],
        "movimientos": [
            {"id": "m1", "fecha": "2025-01-01", "producto": "fondo",
             "tipo": "compra", "unidades": 10, "importe": 1000.0},
        ],
        "valoraciones": [
            {"id": "v1", "producto": "fondo", "fecha": "2025-06-01", "valor": 1200.0},
            {"id": "v2", "producto": "cuenta", "fecha": "2025-06-01", "valor": 500.0},
        ],
        "comparador": [{"id": "real", "nombre": "Mi cartera", "real": True}],
        "hitos": [10000],
        "objetivo": {"activo": True, "importe": 100000, "etiqueta": "x"},
    }


def test_construir_sin_red_calcula_el_panel(tmp_path):
    cfg = _cartera_de_prueba()
    datos = motor.construir(cfg, str(tmp_path), descargar=False)
    assert datos is not None
    assert datos["fechaExtracto"] == "2025-06-01"

    # 1.200 del fondo + 500 de la cuenta
    assert datos["total"]["patrimonio"] == pytest.approx(1700.0)
    # El aportado sale de los movimientos del fondo (la cuenta no aporta)
    assert datos["total"]["aportado"] == pytest.approx(1000.0)
    assert datos["total"]["plusvalia"] == pytest.approx(200.0)
    assert datos["total"]["tir"] is not None

    fondo = next(p for p in datos["productos"] if p["id"] == "fondo")
    assert fondo["valor"] == pytest.approx(1200.0)
    assert fondo["aportado"] == pytest.approx(1000.0)
    assert len(fondo["serie"]) == len(datos["fechas"])
    # Antes de la primera compra no dibuja nada, y la curva empieza el 1/1
    assert fondo["serie"][0] is None

    cuenta = datos["otrosActivos"][0]
    assert cuenta["valor"] == 500.0

    # El hito de 10.000 € no se ha alcanzado
    assert datos["total"]["hitos"][0]["fecha"] is None

    # Y la cartera original no se toca (construir no la muta)
    assert cfg["productos"][0]["tipo"] == "efectivo"


def test_construir_cartera_vacia_devuelve_none(tmp_path):
    cfg = {"titular": "Vacía", "productos": [], "movimientos": [], "valoraciones": []}
    assert motor.construir(cfg, str(tmp_path), descargar=False) is None


def test_construir_es_idempotente(tmp_path):
    """Dos cálculos seguidos dan las mismas cifras (y reutilizan la caché)."""
    a = motor.construir(_cartera_de_prueba(), str(tmp_path), descargar=False)
    b = motor.construir(_cartera_de_prueba(), str(tmp_path), descargar=False)
    assert a["total"]["patrimonio"] == b["total"]["patrimonio"]
    assert a["total"]["tir"] == b["total"]["tir"]
    assert copy.deepcopy(a["fechas"]) == b["fechas"]
