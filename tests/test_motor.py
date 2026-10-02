# -*- coding: utf-8 -*-
"""
test_motor.py  ·  Los cálculos del corazón de la app
=====================================================
TIR (XIRR), ventas FIFO como Hacienda, números en castellano y el cálculo
completo del panel sin salir a internet (descargar=False).
"""
import copy
import datetime as dt
import json

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


# ------------------------------------------------- divisas (Yahoo a diario)
def _payload(granularidad, fechas, cierres):
    return {"chart": {"result": [{
        "meta": {"dataGranularity": granularidad},
        "timestamp": [int(dt.datetime.fromisoformat(f).timestamp()) for f in fechas],
        "indicators": {"quote": [{"close": cierres}]}}]}}


class _Respuesta:
    def __init__(self, datos):
        self._datos = json.dumps(datos).encode("utf-8")

    def read(self):
        return self._datos

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _fija_cache(monkeypatch, tmp_path, serie):
    (tmp_path / "USDEUR_X.json").write_text(json.dumps(serie), encoding="utf-8")
    monkeypatch.setattr(motor, "CACHE", str(tmp_path))
    monkeypatch.setattr(motor, "SIN_RED", False)


def test_yahoo_da_la_divisa_mensual_y_se_vuelve_a_pedir_a_diario(monkeypatch, tmp_path):
    # range=max trae la divisa con un punto por mes: no sirve para convertir
    # un importe del día 17. Tiene que repetir la petición acotando el periodo.
    mensual = _payload("1mo", ["2025-01-01", "2025-02-01"], [0.9, 0.91])
    diario = _payload("1d", ["2025-01-01", "2025-01-02", "2025-01-03"], [0.9, 0.92, 0.93])
    llamadas = []

    def fake(req, timeout=None):
        llamadas.append(req.full_url)
        return _Respuesta(diario if "period1" in req.full_url else mensual)

    monkeypatch.setattr(motor.urllib.request, "urlopen", fake)
    monkeypatch.setattr(motor, "SOLO_FALTAN", False)
    _fija_cache(monkeypatch, tmp_path, {})

    serie = motor.descargar_serie("USDEUR=X")
    assert len(llamadas) == 2
    assert "period1" in llamadas[1]
    assert serie["2025-01-02"] == 0.92            # cierres diarios, no uno por mes
    assert motor.valor_en(serie, dt.date(2025, 1, 3), margen=6) == 0.93


def test_cache_diaria_se_reutiliza_sin_volver_a_red(monkeypatch, tmp_path):
    serie = {f"{a}-{m:02d}-{d:02d}": 0.9 for a in (2024, 2025) for m in range(1, 13)
             for d in range(1, 26)}                   # ~250 puntos al año
    _fija_cache(monkeypatch, tmp_path, serie)
    monkeypatch.setattr(motor, "SOLO_FALTAN", True)

    def no_debe_llamar(*args, **kwargs):
        raise AssertionError("no debería ir a internet: la cache ya es diaria")

    monkeypatch.setattr(motor.urllib.request, "urlopen", no_debe_llamar)
    assert motor.descargar_serie("USDEUR=X") == serie


def test_cache_mensual_guardada_de_antes_se_vuelve_a_descargar(monkeypatch, tmp_path):
    # La cache que quedó de la versión anterior: un punto por mes durante años.
    mensual = {f"{a}-{m:02d}-01": 0.9 for a in range(2020, 2026) for m in range(1, 13)}
    _fija_cache(monkeypatch, tmp_path, mensual)
    monkeypatch.setattr(motor, "SOLO_FALTAN", True)
    diario = _payload("1d", ["2025-01-16", "2025-01-17"], [0.9, 0.97])
    llamadas = []

    def fake(req, timeout=None):
        llamadas.append(req.full_url)
        return _Respuesta(diario)

    monkeypatch.setattr(motor.urllib.request, "urlopen", fake)
    serie = motor.descargar_serie("USDEUR=X")
    assert llamadas                         # la cache mensual no se da por buena
    assert serie["2025-01-17"] == 0.97


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
