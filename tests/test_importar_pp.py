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
