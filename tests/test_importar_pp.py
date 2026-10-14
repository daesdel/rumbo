# -*- coding: utf-8 -*-
"""
test_importar_pp.py  ·  Importar el CSV de Portfolio Performance
================================================================
Todas las filas de aquí están copiadas tal cual del export real
«Todas las transacciones.csv» de la cartera del usuario (1.233 filas),
para que lo que se comprueba sea exactamente lo que pasa al importarlo.
"""
import copy
import datetime as dt
import json
import os
from collections import Counter

import pytest

from app import importar, almacen


CAB = ("Fecha;Tipo;Activo;Títulos;Precio;Cantidad;Comisiones;Impuestos;"
       "Valor neto de transacción;Cuenta;Cuenta de contrapartida;Nota;Fuente")

# Filas literales del export (se conservan los espacios y el formato español).
TESLA_COMPRA = ("2025-01-17 00:00:00;Compra;Tesla Inc.;0,69915402;USD 429,09;"
                "USD 300,00;;;USD 300,00;REVOLUT_USD;REVOLUT_DOLARES;;")
TESLA_VENTA = ("2025-07-21 00:00:00;Venta;Tesla Inc.;1,02874602;USD 334,40;"
               "USD 344,01;USD 0,01;;USD 344,00;REVOLUT_USD;REVOLUT_DOLARES;;")
COSTCO_COMPRA = ("2025-12-19 00:00:00;Compra;COSTCO WHOLESALE CORP;3;USD 855,00;"
                 "USD 2.565,00;;;USD 2.565,00;FREEDOM USD;FREEDOM DOLAR;;")
COSTCO_COMISION = ("2025-12-19 00:00:00;Comisiones;COSTCO WHOLESALE CORP;;;1,75;;;"
                   "1,75;FREEDOM EURO;;;")
FIDELITY_EURO = ("2025-02-24 00:00:00;Compra;FIDELITY-MSCI EURO IN-PA EUR;0,241;"
                 "8,84;2,13;;;2,13;CARTERA METAL MY INVESTOR;MY INVESTOR;;")
FIDELITY_JP_166 = ("2025-02-25 00:00:00;Compra;FIDELITY-MSCI JP INDX-PA EUR;0,166;"
                   "8,61;1,43;;;1,43;CARTERA METAL MY INVESTOR;MY INVESTOR;;")
FIDELITY_JP_598 = ("2025-02-25 00:00:00;Compra;FIDELITY-MSCI JP INDX-PA EUR;0,598;"
                   "8,24;4,93;;;4,93;CARTERA METAL MY INVESTOR;MY INVESTOR;;")
PLAN2040 = ("2025-12-02 00:00:00;Compra;PLAN2040 ING;2,296;24,35;55,90;;;55,90;"
            "PLAN 2040 ING;PLAN 2040 ING;;")
INTERESES_TR = "2026-09-01 00:00:00;Intereses;;;;53,71;;10,20;43,51;TRADE REPUBLIC;;;"
IMPUESTO_DIVIDENDO = ("2025-07-02 00:00:00;Impuestos;Microsoft Corp.;;;USD 0,52;;;"
                      "USD 0,52;REVOLUT_DOLARES;;;")
AGNC_DIVIDENDO = ("2026-08-12 10:47:00;Dividendo;AGNC INVESTMENT CORP;57;;USD 6,84;;"
                  "USD 1,03;USD 5,81;FREEDOM DOLAR;;31/12/2025;")
# La retención de estos tres va en la columna «Comisiones» (PP es inconsistente).
QUALCOMM_COMO_COMISION = ("2025-09-26 00:00:00;Dividendo;QUALCOMM INC;3;;USD 2,67;"
                          "USD 0,40;;USD 2,27;FREEDOM DOLAR;;;")
TRANSFERENCIA = ("2025-12-21 00:00:00;Transferencia (salida);;;;2.173,46;;;2.173,46;"
                 "FREEDOM EURO;FREEDOM DOLAR;;;")
TRANSFERENCIA_COMPRA = ("2025-11-13 00:00:00;Transferencia (salida);;;;950,00;;;950,00;"
                        "MY INVESTOR;FREEDOM EURO;Para compra ATE;")
GINA_COMPRA = ("2026-06-02 15:32:00;Compra;Amazon.com Inc.;1,79901607;221,18;397,90;;;"
               "397,90;REVOUT GINA USD;REVOLUT GINA USD;;")
GINA_DEPOSITO = "2026-06-03 00:00:00;Depósito;;;;13,57;;;13,57;REVOLUT GINA EUROS;;;"
# Escisión Corteva -> Vylor (fila 5 del export real): PP la exporta como «Entrega
# (entrante)». Los USD 546,08 son el COSTE asignado a los 8 títulos, no un abono.
ENTREGA_VYLOR = ("2026-10-01 00:00:00;Entrega (entrante);Vylor Inc;8;USD 68,26;"
                 "USD 546,08;;;USD 546,08;FREEDOM USD;;;")
# Filas literales de los productos que estaban «a coste» por tener el código vacío.
IBEX_ETF = ("2026-09-02 20:00:00;Compra;Amundi IBEX35 UCITS ETF Acc;0,3940211;511,80;"
            "201,66;;;201,66;REVOLUT_EUR;REVOLUT_EUROS;;")
VINCI_CLASE_A = ("2026-04-23 00:00:00;Dividendo;VINCI S.A.                    A;4,060089;;"
                 "16,04;;4,71;11,33;TRADE REPUBLIC;;;")
MORNINGSTAR = ("2026-03-24 00:00:00;Venta;0P0001XF41.F;10;10,31;103,10;;;103,10;"
               "CARTERA METAL MY INVESTOR;MY INVESTOR;;")


def csv_pp(*filas):
    return CAB + "\n" + "\n".join(filas) + "\n"


def _cartera():
    return {"version": 2, "titular": "Mi patrimonio",
            "propietarios": [dict(p) for p in almacen.PROPIETARIOS_BASE],
            "cuentas": [], "productos": [], "movimientos": [], "valoraciones": []}


def _cache_cambio(carpeta, valor=0.92, desde="2024-01-01", hasta="2026-12-31"):
    """USDEUR diario en la cache: así el importador no sale a internet en los tests."""
    ruta = os.path.join(carpeta, "cache")
    os.makedirs(ruta, exist_ok=True)
    serie, f = {}, dt.date.fromisoformat(desde)
    fin = dt.date.fromisoformat(hasta)
    while f <= fin:
        serie[f.isoformat()] = valor
        f += dt.timedelta(days=1)
    with open(os.path.join(ruta, "USDEUR_X.json"), "w", encoding="utf-8") as g:
        json.dump(serie, g)
    return serie


def prepara(tmp_path, *filas):
    cfg = _cartera()
    _cache_cambio(str(tmp_path))
    plan = importar.preparar_portfolio(cfg, csv_pp(*filas), str(tmp_path))
    return cfg, plan


def movimientos(cfg, **criterios):
    return [m for m in cfg["movimientos"]
            if all(m.get(k) == v for k, v in criterios.items())]


def producto(cfg, nombre):
    return next(p for p in cfg["productos"] if p["nombre"] == nombre)


# ------------------------------------------------------------- lectura
def test_reconoce_el_export_y_pide_sus_columnas():
    filas, error = importar.leer_portfolio(csv_pp(TESLA_COMPRA))
    assert error is None and len(filas) == 1
    assert importar.es_portfolio_performance(CAB)

    _, error = importar.leer_portfolio("fecha;importe\n2025-01-01;10")
    assert "Portfolio Performance" in error


def test_los_titulos_con_coma_decimal_no_se_leen_como_miles(tmp_path):
    """0,241 participaciones son 0,241 y no 241: el fallo que falseaba la cartera."""
    _, plan = prepara(tmp_path, FIDELITY_EURO, FIDELITY_JP_166, FIDELITY_JP_598, PLAN2040)
    assert not plan.errores
    unidades = sorted(m["unidades"] for m in plan.movimientos)
    assert unidades == pytest.approx([0.166, 0.241, 0.598, 2.296], abs=1e-9)
    assert all(u < 10 for u in unidades)          # ninguna se ha quedado en 241 o 2296


def test_importe_grande_con_punto_de_miles_y_coma_decimal(tmp_path):
    """USD 2.565,00 (Costco) son 2565 dólares, no 2,565."""
    cfg, plan = prepara(tmp_path, COSTCO_COMPRA)
    assert not plan.errores
    m = plan.movimientos[0]
    assert m["importeOriginal"] == pytest.approx(2565.0)
    assert m["monedaOriginal"] == "USD"
    assert m["importe"] == pytest.approx(2565.0 * 0.92)   # el cambio de la cache


# ------------------------------------------------------------- multi-moneda
def test_tesla_guarda_importe_original_moneda_y_tipo_de_cambio(tmp_path):
    """Antes salía 291,21 € sin decir de dónde venía: ahora está el USD 300,00."""
    cfg, plan = prepara(tmp_path, TESLA_COMPRA)
    assert not plan.errores
    m = plan.movimientos[0]
    assert m["importeOriginal"] == pytest.approx(300.0)
    assert m["monedaOriginal"] == "USD"
    assert m["tipoCambio"] == pytest.approx(0.92)
    assert m["importe"] == pytest.approx(276.0)
    assert m["unidades"] == pytest.approx(0.69915402)
    assert m["cuenta"] and m["contrapartida"]


def test_venta_con_comision_en_dolares(tmp_path):
    cfg, plan = prepara(tmp_path, TESLA_VENTA)
    m = plan.movimientos[0]
    assert m["tipo"] == "venta"
    assert m["importeOriginal"] == pytest.approx(344.0)
    assert m["monedaOriginal"] == "USD"
    assert m["comision"] == pytest.approx(0.01)        # 0,01 USD en euros, redondeado
    assert m["importe"] == pytest.approx(344.0 * 0.92)


# ------------------------------------------------------------- intereses e impuestos
def test_intereses_de_trade_republic_llevan_su_retencion(tmp_path):
    """Bruto 53,71 · retención 10,20 · entra en la cuenta 43,51."""
    cfg, plan = prepara(tmp_path, INTERESES_TR)
    assert not plan.errores
    m = plan.movimientos[0]
    assert m["tipo"] == "interes"
    assert m["importe"] == pytest.approx(43.51)
    assert m["impuestos"] == pytest.approx(10.20)
    assert not m.get("producto")              # va a la cuenta, no a un producto
    assert m["cuenta"] == "cuenta:1"

    cuenta = next(c for c in plan.cuentas if c["ref"] == "cuenta:1")
    assert cuenta["datos"]["nombre"] == "TRADE REPUBLIC"
    assert cuenta["datos"]["moneda"] == "EUR"

    importar.aplicar(cfg, plan)
    assert len(cfg["movimientos"]) == 1
    guardado = cfg["movimientos"][0]
    assert guardado["impuestos"] == pytest.approx(10.20)
    assert guardado["cuenta"] and not guardado.get("producto")


def test_impuestos_de_dividendos(tmp_path):
    cfg, plan = prepara(tmp_path, AGNC_DIVIDENDO, IMPUESTO_DIVIDENDO, QUALCOMM_COMO_COMISION)
    assert not plan.errores
    agnc = next(m for m in plan.movimientos if m["fecha"] == "2026-08-12")
    assert agnc["tipo"] == "dividendo"
    assert agnc["importeOriginal"] == pytest.approx(5.81)     # lo que entra, en dólares
    assert agnc["impuestos"] == pytest.approx(round(1.03 * 0.92, 2))   # retención, en euros
    assert agnc["monedaOriginal"] == "USD"
    assert agnc["importe"] == pytest.approx(round(5.81 * 0.92, 2))

    # Impuesto suelto, con producto y en dólares.
    imp = [m for m in plan.movimientos if m["tipo"] == "impuesto"][0]
    assert imp["importe"] == pytest.approx(round(0.52 * 0.92, 2))
    assert imp.get("producto")

    # PP metió la retención de este dividendo en «Comisiones»: se unifica en impuestos.
    qc = next(m for m in plan.movimientos if m["fecha"] == "2025-09-26")
    assert qc["tipo"] == "dividendo"
    assert qc["impuestos"] == pytest.approx(round(0.40 * 0.92, 2))
    assert not qc.get("comision")


# ------------------------------------------------------------- cuentas
def test_transferencias_entre_cuentas_propias_no_son_aportaciones(tmp_path):
    cfg, plan = prepara(tmp_path, TRANSFERENCIA, TRANSFERENCIA_COMPRA)
    assert not plan.errores
    assert all(m["tipo"] == "transferencia" for m in plan.movimientos)
    assert not any(m["tipo"] == "deposito" for m in plan.movimientos)

    importar.aplicar(cfg, plan)
    assert len(cfg["movimientos"]) == 2
    t = next(m for m in cfg["movimientos"] if m["fecha"] == "2025-12-21")
    nombres = {c["id"]: c["nombre"] for c in cfg["cuentas"]}
    assert nombres[t["cuenta"]] == "FREEDOM EURO"
    assert nombres[t["contrapartida"]] == "FREEDOM DOLAR"
    # Ni compras ni depósitos: no cuentan como dinero aportado.
    assert not any(m["tipo"] in ("compra", "deposito") for m in cfg["movimientos"])


def test_las_cuentas_de_gina_son_de_gina(tmp_path):
    cfg, plan = prepara(tmp_path, GINA_COMPRA, GINA_DEPOSITO)
    importar.aplicar(cfg, plan)
    nombres = {c["nombre"]: c for c in cfg["cuentas"]}
    assert nombres["REVOLUT GINA EUROS"]["propietario"] == "gina"
    assert nombres["REVOUT GINA USD"]["propietario"] == "gina"     # el typo real de PP
    assert nombres["REVOLUT GINA EUROS"]["moneda"] == "EUR"
    # Aunque el nombre diga USD: PP no escribe la moneda cuando la cantidad es en euros.
    assert nombres["REVOUT GINA USD"]["moneda"] == "EUR"
    compra = next(m for m in cfg["movimientos"] if m["tipo"] == "compra")
    assert compra["propietario"] == "gina"
    por_id = {c["id"]: c for c in cfg["cuentas"]}
    assert por_id[compra["cuenta"]]["propietario"] == "gina"


def test_las_cuentas_de_david_no_se_quedan_sin_propietario(tmp_path):
    cfg, plan = prepara(tmp_path, COSTCO_COMPRA, COSTCO_COMISION, INTERESES_TR, AGNC_DIVIDENDO)
    importar.aplicar(cfg, plan)
    for c in cfg["cuentas"]:
        assert c.get("propietario") in ("david", "gina", "compartido")
    nombres = {c["nombre"]: c for c in cfg["cuentas"]}
    assert nombres["TRADE REPUBLIC"]["moneda"] == "EUR"     # sin prefijo = euros
    assert nombres["FREEDOM DOLAR"]["moneda"] == "USD"      # con «USD …» = dólares
    assert nombres["FREEDOM EURO"]["moneda"] == "EUR"


# ------------------------------------------------------------- sin duplicar
def test_la_comision_que_va_en_su_propia_fila_no_se_cuenta_dos_veces(tmp_path):
    cfg, plan = prepara(tmp_path, COSTCO_COMPRA, COSTCO_COMISION)
    importar.aplicar(cfg, plan)
    compra = next(m for m in cfg["movimientos"] if m["tipo"] == "compra")
    assert not compra.get("comision")                     # la compra no la arrastra
    suelta = next(m for m in cfg["movimientos"] if m["tipo"] == "comision")
    assert suelta["importe"] == pytest.approx(1.75)


def test_reimportar_el_mismo_csv_no_duplica(tmp_path):
    cfg, plan = prepara(tmp_path, TESLA_COMPRA, COSTCO_COMPRA, INTERESES_TR)
    primera = importar.aplicar(cfg, plan)
    assert primera["añadidos"] == 3

    cfg2, plan2 = prepara(tmp_path, TESLA_COMPRA, COSTCO_COMPRA, INTERESES_TR)
    cfg2 = copy.deepcopy(cfg)
    segunda = importar.aplicar(cfg2, plan2)
    assert segunda["sustituidos"] == 3                    # sustituye los importados antes
    assert len(cfg2["movimientos"]) == 3                  # y no quedan duplicados


def test_vista_previa_no_toca_la_cartera(tmp_path):
    cfg, plan = prepara(tmp_path, TESLA_COMPRA, INTERESES_TR)
    antes = copy.deepcopy(cfg)
    previa = importar.vista_previa(cfg, plan)
    assert cfg == antes
    assert previa["totales"]["intereses"] == pytest.approx(43.51)
    real = importar.aplicar(cfg, plan)
    assert previa["añadidos"] == real["añadidos"]


def test_el_plan_ordena_las_fechas_de_menor_a_mayor(tmp_path):
    _, plan = prepara(tmp_path, TESLA_COMPRA, INTERESES_TR, GINA_DEPOSITO, PLAN2040)
    fechas = [m["fecha"] for m in plan.movimientos]
    assert fechas == sorted(fechas)
    assert fechas == ["2025-01-17", "2025-12-02", "2026-06-03", "2026-09-01"]


# ------------------------------------------------------------- entrega (escisión)
def test_entrega_entrante_se_importa_y_no_mueve_efectivo(tmp_path):
    """PP exporta las escisiones como «Entrega (entrante)» (Corteva -> Vylor): antes se
    descartaba por «tipo desconocido» y los títulos entregados desaparecían de la
    cartera. Y no puede contar como abono: el «valor neto» del CSV es el coste que se
    asigna a los títulos, así que el saldo de FREEDOM USD no sube."""
    cfg, plan = prepara(tmp_path, ENTREGA_VYLOR)
    assert not plan.errores
    assert len(plan.movimientos) == 1
    m = plan.movimientos[0]
    assert m["tipo"] == "entrega"
    assert m["unidades"] == pytest.approx(8.0)
    assert m["importeOriginal"] == pytest.approx(546.08)
    assert m["monedaOriginal"] == "USD"
    assert m["importe"] == pytest.approx(round(546.08 * 0.92, 2))   # cambio de la caché
    # Y la entrega no deja ninguna cuenta de efectivo con saldo
    assert not [p for p in plan.productos_nuevos if p["datos"].get("tipo") == "efectivo"]


def test_entrega_entrante_llega_a_la_cartera_sin_saldo_falso(tmp_path):
    cfg, plan = prepara(tmp_path, ENTREGA_VYLOR)
    informe = importar.aplicar(cfg, plan)
    assert informe["añadidos"] == 1
    movs = movimientos(cfg, tipo="entrega")
    assert len(movs) == 1
    assert movs[0]["unidades"] == pytest.approx(8.0)
    assert movs[0]["importe"] == pytest.approx(round(546.08 * 0.92, 2))
    # Ninguna cuenta de efectivo tiene saldo: no ha entrado dinero. (La valoración
    # que sí se crea es el coste del propio Vylor, que es lo correcto.)
    efectivo = [p["id"] for p in cfg["productos"] if p.get("tipo") == "efectivo"]
    assert not [v for v in cfg["valoraciones"]
                if v.get("producto") in efectivo and abs(float(v.get("valor") or 0)) > 0.005]


def test_todos_los_tipos_del_export_de_pp_se_entienden():
    """Guarda: si PP exporta un tipo que Rumbo no conoce, la fila se descarta en
    silencio (pasó con «Entrega (entrante)»). Aquí están todos los que aparecen en el
    export real más los habituales de PP."""
    for tipo in ("Compra", "Venta", "Entrega (entrante)", "Dividendo", "Intereses",
                 "Comisiones", "Impuestos", "Depósito", "Retirada",
                 "Transferencia (salida)", "Transferencia (entrada)",
                 "Traspaso (salida)", "Traspaso (entrada)", "Saldo", "Apertura",
                 "Cambio de divisa", "Cupón"):
        assert importar.sin_tildes(tipo).lower() in importar.PP_TIPOS, tipo


# ------------------------------------------------------------- productos que sí cotizan
def _datos_de(plan, nombre):
    return next(p["datos"] for p in plan.productos_nuevos if p["datos"]["nombre"] == nombre)


def test_los_codigos_de_los_que_cotizan_estan_en_el_catalogo():
    """Tickers comprobados contra los precios del propio export (el precio del CSV y el
    del ticker cuadran). Los cuatro ETF tenían el código vacío y se valoraban a coste:
    825 € de patrimonio que no se veían."""
    for nombre, tipo, codigo, moneda in (
            ("Amundi IBEX35 UCITS ETF Acc", "etf", "AMES.DE", "EUR"),
            ("Vanguard S&P 500 UCITS ETF Accumulating", "etf", "VUAA.DE", "EUR"),
            ("ISHARES MSCI WORLD SRI-EUR-A", "etf", "2B7K.DE", "EUR"),
            ("BNP Paribas Easy FTSE EPRA/NAREIT Eurozone Capped UCITS ETF Capitalisation",
             "etf", "EEA.PA", "EUR"),
            ("Vylor Inc", "accion", "VYLR", "USD")):
        ficha = importar.CATALOGO_PP.get(importar._normaliza(nombre))
        assert ficha == (tipo, "yahoo", codigo, moneda), (nombre, ficha)


def test_un_etf_del_catalogo_se_importa_con_codigo_y_sin_revision(tmp_path):
    _, plan = prepara(tmp_path, IBEX_ETF)
    datos = _datos_de(plan, "Amundi IBEX35 UCITS ETF Acc")
    assert (datos["fuente"], datos["codigo"]) == ("yahoo", "AMES.DE")
    assert not datos.get("revision")        # ya no se queda «a coste, pendiente de fijar»


def test_la_clase_al_final_del_nombre_reutiliza_el_codigo_de_vinci(tmp_path):
    """PP escribe «VINCI S.A.                    A»: sin esto se creaba un producto
    manual (y duplicado) en vez de reutilizar el Vinci que ya está en el catálogo."""
    _, plan = prepara(tmp_path, VINCI_CLASE_A)
    datos = _datos_de(plan, "VINCI S.A.                    A")
    assert (datos["fuente"], datos["codigo"]) == ("yahoo", "DG.PA")
    assert not datos.get("revision")


def test_el_codigo_morningstar_del_nombre_se_usa_directamente(tmp_path):
    """Algunos fondos llegan con su código de Morningstar como nombre (0P0001XF41.F):
    Yahoo lo sirve con ese mismo código, así que ya no hace falta dejarlos a coste."""
    cfg, plan = prepara(tmp_path, MORNINGSTAR)
    assert not plan.errores
    datos = _datos_de(plan, "0P0001XF41.F")
    assert (datos["fuente"], datos["codigo"]) == ("yahoo", "0P0001XF41.F")
    assert not datos.get("revision")
    importar.aplicar(cfg, plan)
    assert producto(cfg, "0P0001XF41.F")["codigo"] == "0P0001XF41.F"


# ------------------------------------------------- una cuenta que es un plan de pensiones
# Filas literales del export real: la aportación son DOS filas encadenadas (el
# depósito que mete el dinero en la cuenta y la compra de participaciones que lo saca).
PLAN_DEPOSITO = "2025-12-01 00:00:00;Depósito;;;;55,90;;;55,90;PLAN 2040 ING;;;"


def _saldo(cfg, cid):
    """Saldo de la cuenta de efectivo, con las mismas reglas que usa el motor."""
    from app import motor
    return round(sum(motor.efecto_de(m, cid) * float(m.get("importe") or 0)
                     for m in cfg["movimientos"]), 2)


def test_cuenta_del_plan_no_duplica_cuenta_ni_producto(tmp_path):
    """«PLAN 2040 ING» es una cuenta que en realidad es un plan de pensiones: al
    importar tiene que quedar UNA cuenta de efectivo (el monedero) y UN producto
    (el plan), sin duplicados, y ya enlazado a Yahoo."""
    cfg, plan = prepara(tmp_path, PLAN_DEPOSITO, PLAN2040)
    assert not plan.errores
    importar.aplicar(cfg, plan)

    cuentas = [c for c in cfg["cuentas"] if c["nombre"] == "PLAN 2040 ING"]
    assert len(cuentas) == 1
    assert cuentas[0]["tipo"] == "efectivo"        # la cuenta guarda el dinero

    planes = [p for p in cfg["productos"] if p.get("tipo") == "pension"]
    assert len(planes) == 1                        # un solo plan
    assert planes[0]["codigo"] == "0P00008571.F"   # ya trae el precio de Yahoo
    assert planes[0]["fuente"] == "yahoo"
    assert not planes[0].get("revision")

    efectivos = [p for p in cfg["productos"] if p.get("tipo") == "efectivo"]
    assert len(efectivos) == 1                     # una sola cuenta de efectivo
    assert efectivos[0]["cuenta"] == cuentas[0]["id"]


def test_el_plan_solo_tiene_compras_con_unidades(tmp_path):
    """En el plan de pensiones no puede haber ingresos sueltos: cada aportación es
    una compra de participaciones, y el ingreso se queda en la cuenta de efectivo."""
    cfg, plan = prepara(tmp_path, PLAN_DEPOSITO, PLAN2040)
    importar.aplicar(cfg, plan)
    pid = next(p["id"] for p in cfg["productos"] if p.get("tipo") == "pension")
    del_plan = movimientos(cfg, producto=pid)
    assert del_plan
    assert all(m["tipo"] == "compra" for m in del_plan)
    assert all(float(m["unidades"] or 0) > 0 for m in del_plan)
    ingresos = movimientos(cfg, tipo="deposito")
    assert ingresos and all(m.get("producto") is None for m in ingresos)


def test_la_cuenta_del_plan_no_queda_en_negativo(tmp_path):
    """PP a veces apunta la compra sin su depósito (o días después). La cuenta de
    efectivo no puede quedarse en negativo: se añade el ingreso que falta."""
    cfg, plan = prepara(tmp_path, PLAN2040)        # compra SIN su depósito
    informe = importar.aplicar(cfg, plan)
    cid = next(c["id"] for c in cfg["cuentas"] if c["nombre"] == "PLAN 2040 ING")
    assert _saldo(cfg, cid) == pytest.approx(0.0)
    assert any("sin su ingreso" in a for a in informe["avisos"])


def test_la_serie_de_saldo_de_la_cuenta_sube_con_los_ingresos_añadidos(tmp_path):
    """El saldo que enseña la app sale de la serie anotada que crea el importador: si
    se añade el ingreso que faltaba, la serie tiene que subir con él o la cuenta
    seguiría apareciendo en negativo."""
    cfg, plan = prepara(tmp_path, PLAN2040)        # compra SIN su depósito
    importar.aplicar(cfg, plan)
    efectivo = next(p for p in cfg["productos"]
                    if p.get("tipo") == "efectivo" and p["nombre"] == "PLAN 2040 ING")
    vals = sorted([v for v in cfg["valoraciones"] if v["producto"] == efectivo["id"]],
                  key=lambda v: v["fecha"])
    assert vals
    assert vals[-1]["valor"] == pytest.approx(0.0)
    assert all(float(v["valor"]) >= -0.005 for v in vals)


def test_la_vista_previa_no_duplica_los_ingresos_al_confirmar(tmp_path):
    """La vista previa y la confirmación llaman a aplicar(): los ingresos que faltan
    no pueden acumularse entre las dos llamadas."""
    cfg, plan = prepara(tmp_path, PLAN2040)
    p1 = importar.vista_previa(cfg, plan)
    p2 = importar.vista_previa(cfg, plan)
    assert p1["totales"]["depositos"] == p2["totales"]["depositos"]
    importar.aplicar(cfg, plan)
    assert len(movimientos(cfg, tipo="deposito")) == 1
    assert len(plan.movimientos) == 1              # el plan no se ha modificado


def test_la_vista_previa_ofrece_las_cuentas_detectadas(tmp_path):
    """El informe lleva las cuentas para poder cambiar su tipo antes de importar."""
    _, plan = prepara(tmp_path, PLAN_DEPOSITO, PLAN2040)
    inf = importar.vista_previa(_cartera(), plan)
    detectadas = {c["datos"]["nombre"]: c["datos"]["tipo"] for c in inf["cuentasNuevas"]}
    assert detectadas["PLAN 2040 ING"] == "pension"


def test_el_tipo_elegido_en_la_vista_previa_decide_si_es_cuenta_o_producto(tmp_path):
    """El tipo que se elija en la vista previa manda: «broker» deja la cuenta como
    cuenta de dinero; «pensión» la convierte (el monedero + el plan como producto)."""
    cfg1, plan1 = prepara(tmp_path, PLAN_DEPOSITO, PLAN2040)
    for c in plan1.cuentas:
        c["datos"]["tipo"] = "broker"
    importar.aplicar(cfg1, plan1)
    assert [c["tipo"] for c in cfg1["cuentas"]] == ["broker"]

    cfg2, plan2 = prepara(tmp_path, PLAN_DEPOSITO, PLAN2040)
    for c in plan2.cuentas:
        c["datos"]["tipo"] = "pension"
    importar.aplicar(cfg2, plan2)
    assert [c["tipo"] for c in cfg2["cuentas"]] == ["efectivo"]
    planes = [p for p in cfg2["productos"] if p.get("tipo") == "pension"]
    assert len(planes) == 1
    assert planes[0]["codigo"] == "0P00008571.F"


# ------------------------------------------- excluir cuentas y productos (Fase 2)

def _firma(cfg):
    """Huella de todos los movimientos, con nombres en vez de ids: así se puede
    comparar antes y después de reimportar aunque los ids se reasignen."""
    nom = {p["id"]: p["nombre"] for p in cfg["productos"]}
    cta = {c["id"]: c["nombre"] for c in cfg["cuentas"]}
    return Counter((m["fecha"], m["tipo"], round(float(m.get("importe") or 0), 2),
                    nom.get(m.get("producto"), m.get("producto")),
                    cta.get(m.get("cuenta"), m.get("cuenta")))
                   for m in cfg["movimientos"])


def _importa(tmp_path, cfg, *filas, excluir=None, tipos=None):
    _cache_cambio(str(tmp_path))
    return importar.aplicar(cfg, importar.preparar_portfolio(cfg, csv_pp(*filas), str(tmp_path)),
                            excluir=excluir, tipos=tipos)


def _ref_de_producto(plan, nombre):
    return next(p["ref"] for p in plan.productos_nuevos if p["datos"]["nombre"] == nombre)


def test_la_vista_previa_da_un_ref_a_cada_cuenta_y_producto(tmp_path):
    """Las casillas de la vista previa necesitan un identificador estable para cada
    entidad (por ref, no por índice: el orden de la tabla puede cambiar)."""
    _, plan = prepara(tmp_path, PLAN_DEPOSITO, PLAN2040, TESLA_COMPRA)
    inf = importar.vista_previa(_cartera(), plan)
    assert inf["cuentasNuevas"] and all(c["ref"] for c in inf["cuentasNuevas"])
    assert inf["productosNuevos"] and all(p["ref"] for p in inf["productosNuevos"])
    assert inf["excluidas"] == {"cuentas": [], "productos": []}


def test_excluir_un_producto_no_lo_importa_ni_trae_sus_movimientos(tmp_path):
    cfg, plan = prepara(tmp_path, TESLA_COMPRA, COSTCO_COMPRA)
    ref = _ref_de_producto(plan, "Tesla Inc.")
    importar.aplicar(cfg, plan, excluir={"productos": [ref]})
    assert not any(p["nombre"] == "Tesla Inc." for p in cfg["productos"])
    # Solo queda la compra de COSTCO: la de Tesla no se ha traído.
    assert len([m for m in cfg["movimientos"] if m.get("tipo") == "compra"]) == 1
    # El otro producto sí entra: excluir uno no arrastra a los demás.
    assert any(p["nombre"].startswith("COSTCO") for p in cfg["productos"])


def test_excluir_una_cuenta_se_lleva_sus_productos_por_cascada(tmp_path):
    """Sin la cuenta no hay de dónde salga el dinero: los productos que dependen de
    ella se excluyen solos (la cuenta de efectivo y el plan)."""
    cfg, plan = prepara(tmp_path, PLAN2040)
    assert len(plan.cuentas) == 1
    ref_cuenta = plan.cuentas[0]["ref"]
    dependientes = {p["ref"] for p in plan.productos_nuevos
                    if p["datos"].get("cuenta") == ref_cuenta}
    assert len(dependientes) == 2                    # la cuenta de efectivo y el plan
    inf = importar.vista_previa(_cartera(), plan, excluir={"cuentas": [ref_cuenta]})
    assert set(inf["excluidas"]["productos"]) == dependientes
    importar.aplicar(cfg, plan, excluir={"cuentas": [ref_cuenta]})
    assert not cfg["cuentas"]
    assert not [p for p in cfg["productos"] if "2040" in p["nombre"].upper()]
    assert not cfg["movimientos"]


def test_la_vista_previa_baja_los_totales_al_excluir(tmp_path):
    """El recálculo del servidor sirve para ver el impacto de verdad, no un contador
    del navegador: los movimientos y lo invertido tienen que bajar."""
    cfg, plan = prepara(tmp_path, TESLA_COMPRA, COSTCO_COMPRA)
    todo = importar.vista_previa(cfg, plan)
    ref = _ref_de_producto(plan, "Tesla Inc.")
    menos = importar.vista_previa(cfg, plan, excluir={"productos": [ref]})
    assert menos["añadidos"] < todo["añadidos"]
    assert menos["totales"]["compras"] < todo["totales"]["compras"]
    assert len(menos["filas"]) < len(todo["filas"])


def test_reimportar_excluyendo_no_borra_lo_que_ya_habia(tmp_path):
    """EXCLUIR ES «NO LO IMPORTES AHORA», NUNCA «BÓRRALO». El barrido de
    `reemplazarTodo` borra los movimientos del origen «portfolio» y los reescribe:
    sin protegerlo, reimportar con una entidad excluida la borraría de la cartera."""
    cfg = _cartera()
    _cache_cambio(str(tmp_path))
    csv = csv_pp(TESLA_COMPRA, COSTCO_COMPRA)
    importar.aplicar(cfg, importar.preparar_portfolio(cfg, csv, str(tmp_path)))
    antes = _firma(cfg)
    assert antes and any(p["nombre"] == "Tesla Inc." for p in cfg["productos"])

    plan = importar.preparar_portfolio(cfg, csv, str(tmp_path))
    ref = _ref_de_producto(plan, "Tesla Inc.")
    importar.aplicar(cfg, importar.preparar_portfolio(cfg, csv, str(tmp_path)),
                     excluir={"productos": [ref]})

    assert _firma(cfg) == antes                        # ni un movimiento perdido
    assert any(p["nombre"] == "Tesla Inc." for p in cfg["productos"])   # ni el producto


def test_reimportar_excluyendo_una_cuenta_conserva_sus_movimientos(tmp_path):
    cfg = _cartera()
    _cache_cambio(str(tmp_path))
    csv = csv_pp(PLAN_DEPOSITO, PLAN2040)
    importar.aplicar(cfg, importar.preparar_portfolio(cfg, csv, str(tmp_path)))
    antes = _firma(cfg)
    cid = cfg["cuentas"][0]["id"]
    movs_cuenta = sum(1 for m in cfg["movimientos"] if m.get("cuenta") == cid)
    assert movs_cuenta

    plan = importar.preparar_portfolio(cfg, csv, str(tmp_path))
    importar.aplicar(cfg, importar.preparar_portfolio(cfg, csv, str(tmp_path)),
                     excluir={"cuentas": [plan.cuentas[0]["ref"]]})

    assert _firma(cfg) == antes
    assert any(c["id"] == cid for c in cfg["cuentas"])
    assert sum(1 for m in cfg["movimientos"] if m.get("cuenta") == cid) == movs_cuenta


def test_los_tipos_elegidos_no_tocan_el_plan(tmp_path):
    """La vista previa se recalcula cada vez que el usuario toca algo: si `aplicar`
    modificara el plan, el segundo cálculo daría otro resultado."""
    _, plan = prepara(tmp_path, PLAN_DEPOSITO, PLAN2040)
    ref = plan.cuentas[0]["ref"]
    inf = importar.vista_previa(_cartera(), plan, tipos={ref: "broker"})
    assert plan.cuentas[0]["datos"]["tipo"] == "pension"     # el plan sigue igual
    assert [c["datos"]["tipo"] for c in inf["cuentasNuevas"]] == ["pension"]  # el informe sí lo refleja


# ------------------------------------- vincular un precio en la vista previa (Fase 3)
# Un activo que NO está en el catálogo: así el código solo puede venir del vínculo.
INVENTADO = ("2025-03-03 00:00:00;Compra;INVENTADO SA;10;10,00;100,00;;;100,00;"
             "REVOLUT_EUR;REVOLUT_EUROS;;")
FINCA = ("2025-04-01 00:00:00;Compra;FINCA DEL PUEBLO;1;90000,00;90000,00;;;90000,00;"
         "REVOLUT_EUR;REVOLUT_EUROS;;")


def test_vincular_un_producto_le_pone_codigo_fuente_y_nombre(tmp_path):
    """Lo que el usuario vincula en la vista previa manda: el producto nace ya con
    ese código y esa fuente, y sin el aviso de «valor a coste»."""
    cfg, plan = prepara(tmp_path, INVENTADO)
    ref = _ref_de_producto(plan, "INVENTADO SA")
    importar.aplicar(cfg, plan, vinculos={ref: {
        "fuente": "yahoo", "codigo": "INV.MC", "nombre": "Inventado, S.A.",
        "moneda": "EUR", "identificador": "ES0000000001", "tipo": "accion"}})
    p = producto(cfg, "Inventado, S.A.")
    assert (p["fuente"], p["codigo"]) == ("yahoo", "INV.MC")
    assert p["identificador"] == "ES0000000001"
    assert not p.get("revision")


def test_vincular_guarda_el_nombre_del_csv_en_la_descripcion(tmp_path):
    """Al tomar el nombre canónico, el del CSV no se pierde: queda en la descripción
    del producto, que se puede leer y editar en su ficha."""
    cfg, plan = prepara(tmp_path, INVENTADO)
    ref = _ref_de_producto(plan, "INVENTADO SA")
    importar.aplicar(cfg, plan, vinculos={ref: {
        "fuente": "yahoo", "codigo": "INV.MC", "nombre": "Inventado, S.A."}})
    assert "INVENTADO SA" in producto(cfg, "Inventado, S.A.").get("papel", "")


def test_vincular_no_duplica_si_el_nombre_canonico_ya_existe(tmp_path):
    """El nombre canónico entra en el deduplicado por familia de la Fase 2: si en la
    cartera ya hay un producto con ese nombre, se reutiliza en vez de crear otro."""
    cfg = _cartera()
    _cache_cambio(str(tmp_path))
    existente, _ = almacen.guarda_producto(cfg, {
        "nombre": "Inventado, S.A.", "corto": "Inventado", "tipo": "accion",
        "fuente": "yahoo", "codigo": "INV.MC", "moneda": "EUR"})
    antes = len(cfg["productos"])
    plan = importar.preparar_portfolio(cfg, csv_pp(INVENTADO), str(tmp_path))
    ref = _ref_de_producto(plan, "INVENTADO SA")
    importar.aplicar(cfg, plan, vinculos={ref: {
        "fuente": "yahoo", "codigo": "INV.MC", "nombre": "Inventado, S.A."}})
    iguales = [p for p in cfg["productos"] if p["nombre"] == "Inventado, S.A."]
    assert len(iguales) == 1                                   # no se ha creado otro
    assert iguales[0]["id"] == existente["id"]
    assert len(cfg["productos"]) == antes + 2                  # solo las cuentas de efectivo


def test_los_productos_sin_vincular_conservan_su_codigo(tmp_path):
    """Vincular uno no toca a los demás: el plan de pensiones sigue naciendo con el
    código del catálogo."""
    cfg, plan = prepara(tmp_path, PLAN_DEPOSITO, PLAN2040, INVENTADO)
    ref = _ref_de_producto(plan, "INVENTADO SA")
    importar.aplicar(cfg, plan, vinculos={ref: {
        "fuente": "yahoo", "codigo": "INV.MC", "nombre": "Inventado, S.A."}})
    assert producto(cfg, "PLAN2040 ING")["codigo"] == "0P00008571.F"
    assert producto(cfg, "Inventado, S.A.")["codigo"] == "INV.MC"


def test_un_vinculo_sin_codigo_no_cambia_nada(tmp_path):
    """Sin código no es un vínculo: el producto se queda como estaba."""
    cfg, plan = prepara(tmp_path, INVENTADO)
    ref = _ref_de_producto(plan, "INVENTADO SA")
    importar.aplicar(cfg, plan, vinculos={ref: {"nombre": "Otro nombre"}})
    assert not any(p["nombre"] == "Otro nombre" for p in cfg["productos"])
    assert any(p["nombre"] == "INVENTADO SA" for p in cfg["productos"])


def test_la_vista_previa_con_vinculos_no_toca_el_plan(tmp_path):
    """La vista previa se recalcula cada vez que el usuario vincula algo: si `aplicar`
    modificara el plan, el segundo cálculo daría otro resultado."""
    _, plan = prepara(tmp_path, INVENTADO)
    ref = _ref_de_producto(plan, "INVENTADO SA")
    antes = copy.deepcopy(plan.productos_nuevos)
    importar.vista_previa(_cartera(), plan, vinculos={ref: {
        "fuente": "yahoo", "codigo": "INV.MC", "nombre": "Inventado, S.A."}})
    assert plan.productos_nuevos == antes
