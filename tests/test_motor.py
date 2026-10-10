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

from app import almacen, motor


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
    # El aportado es lo del fondo (1.000) más el saldo de la cuenta (500):
    # el efectivo también es dinero metido, y sin él el patrimonio no cuadra.
    assert datos["total"]["aportado"] == pytest.approx(1500.0)
    assert datos["total"]["plusvalia"] == pytest.approx(200.0)
    assert datos["total"]["patrimonio"] == pytest.approx(
        datos["total"]["aportado"] + datos["total"]["plusvalia"])
    assert datos["total"]["tir"] is not None

    fondo = next(p for p in datos["productos"] if p["id"] == "fondo")
    assert fondo["valor"] == pytest.approx(1200.0)
    assert fondo["aportado"] == pytest.approx(1000.0)
    assert len(fondo["serie"]) == len(datos["fechas"])
    # Antes de la primera compra no dibuja nada, y la curva empieza el 1/1
    assert fondo["serie"][0] is None

    cuenta = datos["otrosActivos"][0]
    assert cuenta["valor"] == 500.0
    assert cuenta["aportado"] == pytest.approx(500.0)   # sin movimientos: todo el saldo

    # El hito de 10.000 € no se ha alcanzado
    assert datos["total"]["hitos"][0]["fecha"] is None

    # Y la cartera original no se toca (construir no la muta)
    assert cfg["productos"][0]["tipo"] == "efectivo"


# ------------------------------- identidad: patrimonio = aportado + ganancia

def _fondo_y_cuenta(saldo, moneda="EUR"):
    """Fondo manual (coste 1.000, vale 1.200) más una cuenta de efectivo
    con ese saldo anotado. La cuenta tiene su «cuenta» para que los
    movimientos de depósito e intereses le lleguen."""
    return {
        "titular": "Prueba",
        "cuentas": [{"id": "c1", "nombre": "Cuenta", "moneda": moneda}],
        "productos": [
            {"id": "fondo", "nombre": "Fondo", "corto": "Fondo",
             "tipo": "otro", "fuente": "manual", "clase": "Fondos", "slot": 1},
            {"id": "cta", "nombre": "Cuenta", "corto": "Cuenta",
             "tipo": "efectivo", "fuente": "manual", "moneda": moneda, "cuenta": "c1"},
        ],
        "movimientos": [
            {"id": "m1", "fecha": "2025-01-01", "producto": "fondo",
             "tipo": "compra", "unidades": 10, "importe": 1000.0},
        ],
        "valoraciones": [
            {"id": "v1", "producto": "fondo", "fecha": "2025-06-01", "valor": 1200.0},
            {"id": "v2", "producto": "cta", "fecha": "2025-06-01", "valor": saldo},
        ],
    }


def test_cuenta_con_intereses_aporta_saldo_menos_rendimiento(tmp_path):
    """1.000 depositados + 50 de intereses y saldo 1.050: la cuenta aporta
    1.000 (lo rendido no es dinero del bolsillo) y el patrimonio cuadra."""
    cfg = _fondo_y_cuenta(saldo=1050.0)
    cfg["movimientos"] += [
        {"id": "m2", "fecha": "2025-01-01", "tipo": "deposito",
         "importe": 1000.0, "cuenta": "c1"},
        {"id": "m3", "fecha": "2025-05-01", "tipo": "interes",
         "importe": 50.0, "cuenta": "c1"},
    ]
    datos = motor.construir(cfg, str(tmp_path), descargar=False)
    cuenta = datos["otrosActivos"][0]
    assert cuenta["aportado"] == pytest.approx(1000.0)     # 1.050 − 50 de intereses
    assert cuenta["plusvalia"] == pytest.approx(50.0)
    t = datos["total"]
    assert t["aportado"] == pytest.approx(2000.0)          # 1.000 fondo + 1.000 cuenta
    assert t["plusvalia"] == pytest.approx(250.0)          #   200 fondo +    50 cuenta
    assert t["patrimonio"] == pytest.approx(t["aportado"] + t["plusvalia"])


def test_aportado_de_cuenta_puede_ser_negativo_y_la_identidad_sigue(tmp_path):
    """Una cuenta cuyo saldo procede de dividendos ya reinvertidos en productos
    tiene aportado negativo: hay que contarlo igualmente; si se omite, su valor
    desaparece del aportado y el patrimonio deja de cuadrar (el hueco de la
    captura del usuario)."""
    cfg = _fondo_y_cuenta(saldo=150.0)
    cfg["movimientos"] += [
        {"id": "m2", "fecha": "2025-01-01", "tipo": "deposito",
         "importe": 100.0, "cuenta": "c1"},
        {"id": "m3", "fecha": "2025-03-01", "tipo": "dividendo",
         "importe": 200.0, "cuenta": "c1"},
    ]
    datos = motor.construir(cfg, str(tmp_path), descargar=False)
    cuenta = datos["otrosActivos"][0]
    assert cuenta["aportado"] == pytest.approx(-50.0)      # 150 − 200 de dividendos
    assert cuenta["plusvalia"] == pytest.approx(200.0)
    t = datos["total"]
    assert t["aportado"] == pytest.approx(950.0)           # 1.000 fondo − 50
    assert t["plusvalia"] == pytest.approx(400.0)
    assert t["patrimonio"] == pytest.approx(t["aportado"] + t["plusvalia"])


def test_el_panel_ensena_lo_anotado_que_el_saldo_a_mano_no_suma(tmp_path):
    """Si el último saldo de una cuenta está anotado a mano y ese día has anotado
    dinero (interés, dividendo…), ese dinero NO está sumado en ese saldo: el panel
    lo enseña al lado en lugar de esconderlo."""
    cfg = _fondo_y_cuenta(saldo=1050.0)
    cfg["movimientos"].append({"id": "m4", "fecha": "2025-06-01", "tipo": "interes",
                               "importe": 5.0, "cuenta": "c1"})
    datos = motor.construir(cfg, str(tmp_path), descargar=False)
    c = datos["cuentas"][0]
    assert c["saldo"] == pytest.approx(1050.0)              # manda el saldo a mano
    assert c["pendiente"]
    assert c["pendiente"]["fecha"] == "2025-06-01"
    assert c["pendiente"]["importe"] == pytest.approx(5.0)
    assert c["pendiente"]["saldo"] == pytest.approx(1050.0)
    # Un saldo CALCULADO ya recoge esos movimientos: no hay nada pendiente que enseñar.
    cfg["valoraciones"][-1]["auto"] = True
    datos = motor.construir(cfg, str(tmp_path), descargar=False)
    assert datos["cuentas"][0]["pendiente"] is None


def test_el_panel_ensena_la_compra_que_el_saldo_a_mano_no_suma(tmp_path):
    """El mismo criterio que con los intereses vale para las compras, ventas,
    comisiones e impuestos: si el último saldo está anotado a mano y ese día has
    comprado, ese dinero no está en él y sale al lado, no desaparece."""
    cfg = _fondo_y_cuenta(saldo=600.0)
    cfg["movimientos"].append({"id": "m4", "fecha": "2025-06-01", "producto": "fondo",
                               "tipo": "compra", "unidades": 1, "importe": 500.0,
                               "cuenta": "c1"})
    datos = motor.construir(cfg, str(tmp_path), descargar=False)
    c = datos["cuentas"][0]
    assert c["saldo"] == pytest.approx(600.0)               # manda el saldo a mano
    assert c["pendiente"]
    assert c["pendiente"]["importe"] == pytest.approx(-500.0)   # dinero que salió


def test_cuenta_sin_saldo_anotado_se_ensena_desconocida(tmp_path):
    """Una cuenta cuyo saldo no se ha anotado nunca no lleva «0,00» (eso diría que
    está vacía): se enseña «—», que es la verdad."""
    cfg = _fondo_y_cuenta(saldo=1050.0)
    cfg["cuentas"].append({"id": "c2", "nombre": "Sin anotar", "moneda": "EUR"})
    datos = motor.construir(cfg, str(tmp_path), descargar=False)
    por_id = {c["id"]: c for c in datos["cuentas"]}
    assert por_id["c2"]["saldo"] is None and por_id["c2"]["saldoEur"] is None
    assert por_id["c2"]["pendiente"] is None
    assert por_id["c1"]["saldo"] == pytest.approx(1050.0)  # la anotada, sigue visible


def test_saldo_negativo_de_una_cuenta_avisa(tmp_path):
    """Con el modelo ancla + libro la app puede crear sola un saldo calculado en
    negativo (un movimiento anotado en una cuenta sin saldo, o con el saldo en
    otra). Casi siempre es un apunte mal puesto: el panel tiene que avisar, decir
    de qué cuenta es y no dejarlo escondido."""
    cfg = _fondo_y_cuenta(saldo=-1500.0)
    cfg["valoraciones"][1]["auto"] = True          # saldo calculado con movimientos
    datos = motor.construir(cfg, str(tmp_path), descargar=False)
    c = datos["cuentas"][0]
    assert c["saldo"] == pytest.approx(-1500.0)
    assert c["saldoAuto"] is True
    avisos = [a for a in datos["avisos"] if a.startswith("Cuenta:")]
    assert len(avisos) == 1
    assert "saldo calculado" in avisos[0]
    assert "−1.500,00 EUR" in avisos[0]
    assert "¿Te falta anotar un saldo o el movimiento salió de otra cuenta?" in avisos[0]


def test_saldo_negativo_anotado_a_mano_tambien_avisa(tmp_path):
    """Si el saldo en negativo lo anotó la persona (no lo calculó la app), el aviso
    lo dice así: no se acusa a los movimientos de algo que no hicieron."""
    cfg = _fondo_y_cuenta(saldo=-50.0)             # sin «auto»: anotado a mano
    datos = motor.construir(cfg, str(tmp_path), descargar=False)
    assert datos["cuentas"][0]["saldoAuto"] is False
    assert any("saldo anotado a mano es −50,00 EUR" in a for a in datos["avisos"])


def test_saldo_positivo_no_avisa_de_negativo(tmp_path):
    cfg = _fondo_y_cuenta(saldo=1050.0)
    datos = motor.construir(cfg, str(tmp_path), descargar=False)
    assert datos["cuentas"][0]["saldoAuto"] is False
    assert not any("¿Te falta anotar un saldo" in a for a in datos["avisos"])


def test_cuenta_en_dolares_entra_convertida_a_euros(tmp_path):
    """El saldo anotado en la moneda de la cuenta (USD) entra en el panel en
    euros con el cambio de cada día: sin la serie de cambio, la cuenta sumaba
    dólares por euros y el patrimonio salía inflado."""
    (tmp_path / "cache").mkdir()
    cambio = {f"2025-{m:02d}-01": 0.5 for m in range(1, 7)}
    (tmp_path / "cache" / "USDEUR_X.json").write_text(json.dumps(cambio), encoding="utf-8")

    cfg = _fondo_y_cuenta(saldo=100.0, moneda="USD")
    datos = motor.construir(cfg, str(tmp_path), descargar=False)
    cuenta = datos["otrosActivos"][0]
    assert cuenta["valor"] == pytest.approx(50.0)          # 100 USD × 0,5
    assert cuenta["valorNat"] == pytest.approx(100.0)
    assert cuenta["aportado"] == pytest.approx(50.0)       # sin movimientos: todo el saldo
    c = datos["cuentas"][0]
    assert c["saldo"] == pytest.approx(100.0)              # en su moneda
    assert c["saldoEur"] == pytest.approx(50.0)            # y en euros
    assert not any("no tengo el cambio" in a for a in datos["avisos"])
    t = datos["total"]
    assert t["patrimonio"] == pytest.approx(t["aportado"] + t["plusvalia"])


def test_rentabilidad_en_euros_de_compra_en_dolares(tmp_path):
    """Una compra en dólares se mide en euros con los euros que COSTÓ ese día (el
    cambio de la fecha de la compra) y con los euros que VALE hoy (el cambio de
    hoy): aunque la acción suba en dólares, si el euro se ha reforzado la rentabilidad
    en euros recoge la pérdida por cambio."""
    (tmp_path / "cache").mkdir()
    # Precio en dólares: 100 al comprar, 110 al cerrar (+10 % en dólares)
    (tmp_path / "cache" / "AAA.json").write_text(json.dumps(
        {"2025-01-02": 100.0, "2025-05-30": 110.0}), encoding="utf-8")
    # Cambio a euros: 0,92 €/$ al comprar, 0,80 €/$ hoy (el euro se ha reforzado)
    (tmp_path / "cache" / "USDEUR_X.json").write_text(json.dumps(
        {"2025-01-02": 0.92, "2025-05-30": 0.80}), encoding="utf-8")
    # Y a propósito un par EURUSD de «otra casa» (serie aparte): el panel NO debe
    # usarlo. La vista en dólares sale del recíproco del mismo USDEUR de arriba.
    (tmp_path / "cache" / "EURUSD_X.json").write_text(json.dumps(
        {"2025-01-02": 1.02, "2025-05-30": 1.30}), encoding="utf-8")

    cfg = {
        "titular": "Prueba",
        "productos": [{"id": "acc", "nombre": "Acción", "corto": "Acción", "tipo": "accion",
                       "fuente": "yahoo", "codigo": "AAA", "moneda": "USD"},
                      {"id": "cta", "nombre": "Cuenta", "corto": "Cuenta",
                       "tipo": "efectivo", "fuente": "manual"}],
        # Comprada por 1.000 $ = 920 € al cambio del día (así se anota en la app)
        "movimientos": [{"id": "m1", "fecha": "2025-01-02", "producto": "acc",
                         "tipo": "compra", "unidades": 10, "importe": 920.0,
                         "importeOriginal": 1000.0, "monedaOriginal": "USD",
                         "tipoCambio": 0.92}],
        "valoraciones": [{"id": "v1", "producto": "cta", "fecha": "2025-06-01", "valor": 500.0}],
    }
    datos = motor.construir(cfg, str(tmp_path), descargar=False)
    p = next(x for x in datos["productos"] if x["id"] == "acc")
    # Valor hoy: 110 $ × 0,80 = 880 € (el cambio de HOY)
    assert p["valor"] == pytest.approx(880.0)
    # Aportado: los 920 € que costó, al cambio del DÍA DE LA COMPRA
    assert p["aportado"] == pytest.approx(920.0)
    assert p["plusvalia"] == pytest.approx(-40.0)
    # En dólares ganó (1.000 → 1.100); en euros pierde por el cambio
    assert p["rentabilidad"] == pytest.approx(round(-40.0 / 920.0, 4))
    # Y la vista en dólares devuelve las cifras nativas con el recíproco EXACTO del
    # par del motor: 920 € × (1/0,92) = 1.000 $ y 880 € × (1/0,80) = 1.100 $.
    fx = datos["fxSerie"]
    assert fx[0] == pytest.approx(1 / 0.92, abs=1e-6)
    assert fx[-1] == pytest.approx(1 / 0.80, abs=1e-6)
    assert p["aportado"] * fx[0] == pytest.approx(1000.0, abs=0.01)
    assert p["valor"] * fx[-1] == pytest.approx(1100.0, abs=0.01)
    # El cambio de hoy también es uno solo (el mismo USDEUR), no el EURUSD de la cache.
    assert datos["fx"]["USDEUR"] == pytest.approx(0.80, abs=1e-6)
    assert datos["fx"]["EURUSD"] == pytest.approx(1 / 0.80, abs=1e-6)
    # Y la identidad del panel sigue viva
    t = datos["total"]
    assert t["patrimonio"] == pytest.approx(t["aportado"] + t["plusvalia"])


def test_vista_en_dolares_ida_y_vuelta_al_centimo(tmp_path):
    """Un importe grande tiene que volver a sus dólares nativos sin perder céntimos:
    la serie del panel es el recíproco del MISMO par que usa el motor para pasar a
    euros (antes salía de otro par de Yahoo y quedaban céntimos de diferencia)."""
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "AAA.json").write_text(json.dumps(
        {"2025-01-02": 200.0, "2025-05-30": 210.0}), encoding="utf-8")
    (tmp_path / "cache" / "USDEUR_X.json").write_text(json.dumps(
        {"2025-01-02": 0.90, "2025-05-30": 0.95}), encoding="utf-8")
    # Otro par, y muy distinto: si el panel lo usara, el error se vería a simple vista.
    (tmp_path / "cache" / "EURUSD_X.json").write_text(json.dumps(
        {"2025-01-02": 1.09, "2025-05-30": 1.07}), encoding="utf-8")

    cfg = {
        "titular": "Prueba",
        "productos": [{"id": "acc", "nombre": "Acción", "corto": "Acción", "tipo": "accion",
                       "fuente": "yahoo", "codigo": "AAA", "moneda": "USD"}],
        # 500 títulos a 180 € cada uno = 90.000 €, que eran 100.000 $ al cambio del día.
        "movimientos": [{"id": "m1", "fecha": "2025-01-02", "producto": "acc",
                         "tipo": "compra", "unidades": 500, "importe": 90000.0}],
        "valoraciones": [],
    }
    datos = motor.construir(cfg, str(tmp_path), descargar=False)
    p = next(x for x in datos["productos"] if x["id"] == "acc")
    # 500 títulos × 210 $ × 0,95 = 99.750 €, que son los 105.000 $ nativos.
    assert p["valor"] == pytest.approx(500 * 210 * 0.95, abs=0.01)
    assert p["valor"] * datos["fxSerie"][-1] == pytest.approx(105000.0, abs=0.01)
    assert p["aportado"] * datos["fxSerie"][0] == pytest.approx(100000.0, abs=0.01)
    # Y el cambio de hoy es el mismo par, no el EURUSD de la cache.
    assert datos["fx"]["USDEUR"] == pytest.approx(0.95, abs=1e-6)
    assert datos["fxSerie"][0] == pytest.approx(1 / 0.90, abs=1e-6)


def test_construir_cartera_vacia_devuelve_none(tmp_path):
    cfg = {"titular": "Vacía", "productos": [], "movimientos": [], "valoraciones": []}
    assert motor.construir(cfg, str(tmp_path), descargar=False) is None


def test_fxserie_alineada_con_el_eje_de_fechas(tmp_path):
    """fxSerie lleva el cambio diario en dólares por euro, alineado con el eje:
    es lo que permite mostrar el panel en dólares con el cambio de CADA día
    (el cambio de hoy solo serviría para escalar, sin efecto real). Y sale del par
    del motor (USDEUR, euros por dólar) invertido, no de un par aparte."""
    (tmp_path / "cache").mkdir()
    # Euros por dólar, que es lo que guarda el par del motor.
    cambio = {"2024-12-31": 0.90, "2025-06-01": 0.80}
    (tmp_path / "cache" / "USDEUR_X.json").write_text(json.dumps(cambio), encoding="utf-8")

    cfg = _fondo_y_cuenta(saldo=100.0)
    datos = motor.construir(cfg, str(tmp_path), descargar=False)
    serie = datos["fxSerie"]
    assert len(serie) == len(datos["fechas"])          # alineada con el eje
    assert serie[0] is not None                        # días iniciales rellenados
    assert serie[0] == pytest.approx(1 / 0.90, abs=1e-6)
    assert serie[-1] == pytest.approx(1 / 0.80, abs=1e-6)   # último cambio conocido
    assert all(x is None or x > 0 for x in serie)


def test_fxserie_tambien_sale_de_una_cache_con_el_par_antiguo(tmp_path):
    """Carteras que ya tenían guardado el par EURUSD (el que se usaba antes): se
    invierte para seguir teniendo UN solo origen, en vez de quedarse sin vista en
    dólares hasta que se refresque la cache."""
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "EURUSD_X.json").write_text(
        json.dumps({"2024-12-31": 1.10, "2025-06-01": 1.25}), encoding="utf-8")

    datos = motor.construir(_fondo_y_cuenta(saldo=100.0), str(tmp_path), descargar=False)
    assert datos["fxSerie"][0] == pytest.approx(1.10)
    assert datos["fxSerie"][-1] == pytest.approx(1.25)
    assert datos["fx"]["USDEUR"] == pytest.approx(1 / 1.25, abs=1e-6)


def test_construir_es_idempotente(tmp_path):
    """Dos cálculos seguidos dan las mismas cifras (y reutilizan la caché)."""
    a = motor.construir(_cartera_de_prueba(), str(tmp_path), descargar=False)
    b = motor.construir(_cartera_de_prueba(), str(tmp_path), descargar=False)
    assert a["total"]["patrimonio"] == b["total"]["patrimonio"]
    assert a["total"]["tir"] == b["total"]["tir"]
    assert copy.deepcopy(a["fechas"]) == b["fechas"]


# ------------------------------- escisiones (spin-off): entrega entrante

def test_entrega_entrante_suma_titulos_sin_tocar_dinero():
    """Una escisión (VYLR recibida por mantener CTVA) entra con sus títulos y su
    coste asignado, pero sin que salga ni un euro del bolsillo."""
    r = motor.aplicar_movimientos({"corto": "VYLR"}, [
        {"fecha": "2025-09-01", "tipo": "entrega", "unidades": 20, "importe": 400.0}])
    assert r["eventos"] == [("2025-09-01", 20.0, 400.0)]
    assert r["flujos"] == []                 # no es una compra: la TIR no la ve
    assert r["realizado"] == 0.0


def test_reclasifica_solo_mueve_coste_de_un_activo_a_otro():
    r = motor.aplicar_movimientos({"corto": "CTVA"}, [
        {"fecha": "2025-09-01", "tipo": "reclasifica", "unidades": 0, "importe": -400.0}])
    assert r["eventos"] == [("2025-09-01", 0.0, -400.0)]   # ni unidades ni flujos
    assert r["flujos"] == []


def _cfg_escision():
    return {
        "titular": "Prueba",
        "cuentas": [],
        "productos": [
            {"id": "ctva", "nombre": "Corteva", "corto": "CTVA", "tipo": "otro",
             "fuente": "manual", "clase": "Renta variable", "slot": 1},
            {"id": "vylr", "nombre": "Vylor", "corto": "VYLR", "tipo": "otro",
             "fuente": "manual", "clase": "Renta variable", "slot": 2},
        ],
        "movimientos": [
            {"id": "m1", "fecha": "2025-01-01", "producto": "ctva", "tipo": "compra",
             "unidades": 20, "importe": 1000.0},
            {"id": "m2", "fecha": "2025-06-01", "producto": "vylr", "tipo": "entrega",
             "unidades": 20, "importe": 400.0, "productoOrigen": "ctva"},
        ],
        "valoraciones": [
            {"id": "v1", "producto": "ctva", "fecha": "2025-06-01", "valor": 600.0},
            {"id": "v2", "producto": "vylr", "fecha": "2025-06-01", "valor": 400.0},
        ],
    }


def test_escision_no_inventa_ninguna_perdida(tmp_path):
    """CTVA cae de golpe en el mercado y VYLR nace con su parte: el coste se
    REPARTA, no se crea. El aportado total, el patrimonio y la plusvalía no se
    mueven, así que no aparece la falsa pérdida de la escisión."""
    datos = motor.construir(_cfg_escision(), str(tmp_path), descargar=False)
    ctva = next(p for p in datos["productos"] if p["id"] == "ctva")
    vylr = next(p for p in datos["productos"] if p["id"] == "vylr")
    t = datos["total"]
    assert ctva["aportado"] == pytest.approx(600.0)     # cedió 400 de coste
    assert vylr["aportado"] == pytest.approx(400.0)     # y las recibió
    assert t["aportado"] == pytest.approx(1000.0)       # dinero real intacto
    assert t["patrimonio"] == pytest.approx(1000.0)     # 600 + 400
    assert t["plusvalia"] == pytest.approx(0.0)         # ni pérdida ni ganancia
    # Los dos quedan relacionados, para verlos juntos en la ficha
    assert ctva.get("relacionados") == ["vylr"]
    assert vylr.get("relacionados") == ["ctva"]


def test_entrega_gratis_no_toca_el_coste_del_original(tmp_path):
    cfg = _cfg_escision()
    cfg["movimientos"][1]["importe"] = 0.0
    datos = motor.construir(cfg, str(tmp_path), descargar=False)
    ctva = next(p for p in datos["productos"] if p["id"] == "ctva")
    vylr = next(p for p in datos["productos"] if p["id"] == "vylr")
    assert ctva["aportado"] == pytest.approx(1000.0)
    assert vylr["aportado"] is None                       # sin coste registrado
    assert datos["total"]["aportado"] == pytest.approx(1000.0)
    assert datos["total"]["patrimonio"] == pytest.approx(1000.0)


def test_comparacion_cuadra_con_el_patrimonio(tmp_path):
    """El gadget «¿y si lo hubieras metido en un indexado?» tiene que valer lo
    mismo que la pestaña Patrimonio (antes solo contaba los productos con
    compras y se quedaba muy por debajo)."""
    cfg = _cfg_escision()
    cfg["cuentas"] = [{"id": "c1", "nombre": "Caja", "moneda": "EUR"}]
    cfg["productos"].append({"id": "cta", "nombre": "Caja", "corto": "Caja",
                             "tipo": "efectivo", "fuente": "manual", "cuenta": "c1", "slot": 3})
    cfg["movimientos"].append({"id": "m3", "fecha": "2025-02-01", "tipo": "deposito",
                               "importe": 500.0, "cuenta": "c1"})
    cfg["valoraciones"].append({"id": "v3", "producto": "cta", "fecha": "2025-06-01",
                                "valor": 500.0})
    (tmp_path / "cache").mkdir()
    for sim in ("IWDA.AS", "SXR8.DE", "XEON.DE", "EUNA.DE"):
        (tmp_path / "cache" / f"{sim}.json").write_text(
            json.dumps({"2025-01-01": 100.0, "2025-06-01": 110.0}), encoding="utf-8")
    datos = motor.construir(cfg, str(tmp_path), descargar=False)
    c = datos["comparacion"]
    assert c is not None
    assert c["tuValor"] == pytest.approx(datos["total"]["patrimonio"])
    ap = [x for x in c["aportado"] if x is not None]
    assert ap[-1] == pytest.approx(datos["total"]["aportado"])


# ------------------- dividendos e intereses: retención y comisión en los KPI

def test_interes_con_retencion_y_comision_se_cuenta_completo(tmp_path):
    """Un interés anotado EN LA CUENTA (sin producto) entra neto en el saldo, pero
    los KPI cuentan lo bruto: neto + retención + comisión. La declaración se mira
    en «impuestos» y las comisiones en su propio contador."""
    cfg = _fondo_y_cuenta(saldo=1045.0)
    cfg["movimientos"] += [
        {"id": "m2", "fecha": "2025-01-01", "tipo": "deposito", "importe": 1000.0, "cuenta": "c1"},
        {"id": "m3", "fecha": "2025-05-01", "tipo": "interes", "importe": 45.0, "cuenta": "c1",
         "impuestos": 5.0, "comision": 1.0},
    ]
    datos = motor.construir(cfg, str(tmp_path), descargar=False)
    assert datos["total"]["intereses"] == pytest.approx(51.0)      # 45 + 5 + 1
    assert datos["total"]["impuestos"] == pytest.approx(5.0)
    assert datos["comisiones"]["compraventaPagada"] == pytest.approx(1.0)
    cuenta = datos["otrosActivos"][0]
    assert cuenta["valor"] == pytest.approx(1045.0)      # el saldo sube solo lo neto
    assert cuenta["aportado"] == pytest.approx(1000.0)   # 1.045 − 45 rendidos


def test_dividendo_en_cuenta_sin_producto_entra_en_los_kpi(tmp_path):
    """Lo mismo para un dividendo anotado solo en la cuenta: su retención y su
    comisión no se pierden ni del KPI de dividendos ni del de impuestos."""
    cfg = _fondo_y_cuenta(saldo=1012.0)
    cfg["movimientos"] += [
        {"id": "m2", "fecha": "2025-01-01", "tipo": "deposito", "importe": 1000.0, "cuenta": "c1"},
        {"id": "m3", "fecha": "2025-04-01", "tipo": "dividendo", "importe": 12.0, "cuenta": "c1",
         "impuestos": 3.0, "comision": 0.5},
    ]
    datos = motor.construir(cfg, str(tmp_path), descargar=False)
    assert datos["total"]["dividendos"] == pytest.approx(15.5)      # 12 + 3 + 0,5
    assert datos["total"]["impuestos"] == pytest.approx(3.0)
    assert datos["comisiones"]["compraventaPagada"] == pytest.approx(0.5)
    cuenta = datos["otrosActivos"][0]
    assert cuenta["valor"] == pytest.approx(1012.0)
    assert cuenta["aportado"] == pytest.approx(1000.0)             # 1.012 − 12 rendidos


def test_migrar_las_cuentas_no_cambia_los_totales(tmp_path):
    """La migración del modelo cuentas/valores (cada cuenta con su producto de
    efectivo) solo añade productos vacíos: patrimonio, aportado y ganancia no se
    mueven, y una cuenta sin saldo anotado sigue enseñando «—» (no «0,00»)."""
    cfg = _fondo_y_cuenta(saldo=1050.0)
    cfg["cuentas"] += [{"id": "c2", "nombre": "Revolut", "moneda": "USD"},
                       {"id": "c3", "nombre": "Plan 2040", "tipo": "pension", "moneda": "EUR"}]
    antes = motor.construir(copy.deepcopy(cfg), str(tmp_path), descargar=False)

    creados = almacen.migra_efectivo(cfg)
    assert len(creados) == 2 and almacen.migra_efectivo(cfg) == []      # solo los que faltaban
    datos = motor.construir(cfg, str(tmp_path), descargar=False)

    for k in ("patrimonio", "aportado", "plusvalia"):
        assert datos["total"][k] == pytest.approx(antes["total"][k])
    assert datos["total"]["dividendos"] == pytest.approx(antes["total"]["dividendos"])
    por_id = {c["id"]: c for c in datos["cuentas"]}
    assert por_id["c2"]["saldo"] is None and por_id["c3"]["saldo"] is None
    assert por_id["c1"]["saldo"] == pytest.approx(1050.0)
    assert datos["avisos"] == antes["avisos"]


def test_dividendo_de_un_producto_suma_el_bruto(tmp_path):
    """El dividendo de un producto ya sumaba bruto (neto + retención + comisión);
    se comprueba que sigue siendo así con todos los campos anotados."""
    cfg = _fondo_y_cuenta(saldo=0.0)
    cfg["movimientos"] += [
        {"id": "m2", "fecha": "2025-05-01", "tipo": "dividendo", "producto": "fondo",
         "cuenta": "c1", "importe": 12.0, "impuestos": 3.0, "comision": 0.5},
    ]
    datos = motor.construir(cfg, str(tmp_path), descargar=False)
    p = next(x for x in datos["productos"] if x["id"] == "fondo")
    assert p["dividendos"] == pytest.approx(15.5)
    assert p["impuestosPagados"] == pytest.approx(3.0)
    assert datos["comisiones"]["compraventaPagada"] == pytest.approx(0.5)
    assert datos["total"]["dividendos"] == pytest.approx(15.5)
    assert datos["total"]["impuestos"] == pytest.approx(3.0)


# ------------------------------------------- rentas (comisiones, impuestos, dividendos, intereses)

def test_la_comision_de_cualquier_tipo_de_movimiento_cuenta():
    """Una comisión (o una retención) anotada en un movimiento que no es compra, venta,
    dividendo ni interés también tiene que contar: antes se perdía sin que nadie la
    echara de menos. Se prueban una entrega y un depósito con comisión."""
    motor.AVISOS.clear()
    movs = [_mov("2025-01-01", "compra", 10, 1000.0, comision=2.0),
            {"id": "m2", "fecha": "2025-02-01", "producto": "p", "tipo": "entrega",
             "unidades": 1.0, "importe": 0.0, "comision": 4.0, "impuestos": 1.5}]
    r = motor.aplicar_movimientos({"corto": "test"}, movs)
    assert r["comisiones"] == pytest.approx(6.0)      # 2 de la compra + 4 de la entrega
    assert r["impuestos"] == pytest.approx(1.5)


def _cfg_rentas():
    """Cartera mínima con dos años: 2025 completo y 2026 a medias (hasta el 30/06)."""
    return {
        "productos": [{"id": "fondo", "nombre": "Fondo", "corto": "Fondo"},
                      {"id": "accion", "nombre": "Acción", "corto": "Acción", "cuenta": "b"}],
        "cuentas": [{"id": "a", "nombre": "Cuenta A"}, {"id": "b", "nombre": "Cuenta B"}],
        "movimientos": [
            {"id": "m1", "fecha": "2025-03-10", "tipo": "compra", "producto": "fondo",
             "unidades": 1, "importe": 100, "comision": 2},
            {"id": "m2", "fecha": "2025-05-10", "tipo": "dividendo", "producto": "accion",
             "cuenta": "b", "importe": 10, "impuestos": 2, "comision": 0.5},
            {"id": "m3", "fecha": "2025-06-10", "tipo": "interes", "cuenta": "a",
             "importe": 5, "impuestos": 1},
            {"id": "m4", "fecha": "2025-07-10", "tipo": "comision", "cuenta": "a", "importe": 3},
            {"id": "m5", "fecha": "2025-09-10", "tipo": "impuesto", "producto": "fondo",
             "cuenta": "b", "importe": 4},
            {"id": "m6", "fecha": "2026-02-10", "tipo": "dividendo", "cuenta": "a",
             "importe": 20, "impuestos": 4},
            {"id": "m7", "fecha": "2026-03-10", "tipo": "interes", "cuenta": "a", "importe": 6},
        ],
    }


def test_resumen_rentas_historico_anio_en_curso_y_prevision():
    r = motor.resumen_rentas(_cfg_rentas(), "2026-06-30")
    assert r["anioActual"] == 2026
    # Comisiones: 2025 = 2 (compra) + 0,5 (dividendo) + 3 (suelta) = 5,50; 2026 = 0
    assert r["comisiones"]["historico"]["total"] == pytest.approx(5.5)
    assert r["comisiones"]["promedioAnual"] == pytest.approx(5.5)
    assert r["comisiones"]["anio"]["anotado"] == pytest.approx(0.0)
    assert r["comisiones"]["anio"]["proyeccion"] == pytest.approx(5.5)   # la media manda
    # Impuestos: 2025 = 2 + 1 + 4 = 7; 2026 = 4
    assert r["impuestos"]["historico"]["total"] == pytest.approx(11.0)
    assert r["impuestos"]["anio"]["anotado"] == pytest.approx(4.0)
    assert r["impuestos"]["anio"]["proyeccion"] == pytest.approx(7.0)
    # Dividendos (bruto): 2025 = 10 + 2 + 0,5 = 12,50; 2026 = 20 + 4 = 24
    assert r["dividendos"]["historico"]["total"] == pytest.approx(36.5)
    assert r["dividendos"]["anio"]["anotado"] == pytest.approx(24.0)
    assert r["dividendos"]["anio"]["proyeccion"] == pytest.approx(24.0)  # lo anotado manda
    # Intereses: 2025 = 6; 2026 = 6
    assert r["intereses"]["historico"]["total"] == pytest.approx(12.0)
    assert r["intereses"]["promedioAnual"] == pytest.approx(6.0)
    assert r["intereses"]["anio"]["anotado"] == pytest.approx(6.0)
    # El año en curso NO entra en el promedio (solo cuenta 2025)
    assert r["dividendos"]["aniosCompletos"] == 1


def test_resumen_rentas_desglose_por_producto_y_por_cuenta():
    r = motor.resumen_rentas(_cfg_rentas(), "2026-06-30")
    div = {d["nombre"]: d for d in r["dividendos"]["desglose"]}
    assert div["Acción"]["bruto"] == pytest.approx(12.5)
    assert div["Acción"]["retencion"] == pytest.approx(2.0)
    assert div["Acción"]["comision"] == pytest.approx(0.5)
    assert div["Acción"]["neto"] == pytest.approx(10.0)
    assert div["Acción"]["cuenta"] == "Cuenta B"
    assert div["Acción"]["ultimo"] == "2025-05-10"
    # Un dividendo anotado solo en la cuenta (sin producto): se agrupa por cuenta
    assert div["Sin producto"]["bruto"] == pytest.approx(24.0)
    assert div["Sin producto"]["cuenta"] == "Cuenta A"
    assert sum(d["bruto"] for d in r["dividendos"]["desglose"]) == pytest.approx(36.5)
    # Intereses: por cuenta, con su retención
    inte = {d["nombre"]: d for d in r["intereses"]["desglose"]}
    assert inte["Cuenta A"]["bruto"] == pytest.approx(12.0)
    assert inte["Cuenta A"]["retencion"] == pytest.approx(1.0)
    assert sum(d["bruto"] for d in r["intereses"]["desglose"]) == pytest.approx(12.0)


def test_resumen_rentas_por_mes_y_por_anio():
    r = motor.resumen_rentas(_cfg_rentas(), "2026-06-30")
    com_mes = {x["mes"]: x["total"] for x in r["comisiones"]["porMes"]}
    assert com_mes["2025-03"] == pytest.approx(2.0)
    assert com_mes["2025-05"] == pytest.approx(0.5)
    assert com_mes["2025-07"] == pytest.approx(3.0)
    assert "2026-01" not in com_mes                    # los meses sin nada no se listan
    assert [x["anio"] for x in r["comisiones"]["porAnio"]] == [2025]
    assert r["comisiones"]["porAnio"][0]["n"] == 3
    assert r["dividendos"]["porAnio"][-1]["enCurso"] is True
    # El año en curso trae sus doce meses, con ceros donde aún no hay nada
    meses26 = r["dividendos"]["anio"]["porMes"]
    assert len(meses26) == 12 and meses26[1]["total"] == pytest.approx(24.0)
    assert meses26[5]["total"] == pytest.approx(0.0)


def test_las_rentas_cuadran_con_los_kpi_del_panel(tmp_path):
    """El histórico de cada sección tiene que ser el mismo número que el KPI del panel
    (si no, la pestaña Rendimiento contaría una cosa y el panel otra)."""
    cfg = _fondo_y_cuenta(saldo=1000.0)
    cfg["movimientos"] += [
        {"id": "m2", "fecha": "2025-05-01", "tipo": "dividendo", "producto": "fondo",
         "cuenta": "c1", "importe": 12.0, "impuestos": 3.0, "comision": 0.5},
        {"id": "m3", "fecha": "2025-06-01", "tipo": "interes", "cuenta": "c1", "importe": 8.0},
        {"id": "m4", "fecha": "2025-07-01", "tipo": "comision", "cuenta": "c1", "importe": 4.0},
        {"id": "m5", "fecha": "2025-08-01", "tipo": "impuesto", "cuenta": "c1", "importe": 2.5},
    ]
    datos = motor.construir(cfg, str(tmp_path), descargar=False)
    r = datos["rentas"]
    assert r["dividendos"]["historico"]["total"] == pytest.approx(datos["total"]["dividendos"])
    assert r["intereses"]["historico"]["total"] == pytest.approx(datos["total"]["intereses"])
    assert r["impuestos"]["historico"]["total"] == pytest.approx(datos["total"]["impuestos"])
    assert r["comisiones"]["historico"]["total"] == pytest.approx(
        datos["comisiones"]["compraventaPagada"])
    assert r["comisiones"]["historico"]["total"] == pytest.approx(4.5)   # 0,5 + 4
    assert r["impuestos"]["historico"]["total"] == pytest.approx(5.5)    # 3 + 2,5
