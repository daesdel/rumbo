# -*- coding: utf-8 -*-
"""
test_importar.py  ·  Los tres caminos de importación
=====================================================
Fechas y números de la plantilla, lectura de CSV/Excel/texto de IA, y la
promesa clave: la vista previa no toca la cartera y devuelve exactamente lo
que se guardará después.
"""
import copy
import datetime as dt
import io

import pytest

from app import importar


# ------------------------------------------------------------- lectura

def test_lee_fecha_los_formatos_de_siempre():
    assert importar.lee_fecha("10/03/2025") == "2025-03-10"
    assert importar.lee_fecha("2025-03-10") == "2025-03-10"
    assert importar.lee_fecha("10-03-25") == "2025-03-10"
    assert importar.lee_fecha(dt.date(2025, 3, 10)) == "2025-03-10"
    assert importar.lee_fecha("10.03.2025 12:00") == "2025-03-10"
    assert importar.lee_fecha("31/02/2025") is None      # no existe
    assert importar.lee_fecha("no sé") is None


def test_lee_numero_convierte_y_normaliza_a_positivo():
    assert importar.lee_numero("1.234,56") == pytest.approx(1234.56)
    assert importar.lee_numero("1234.5") == pytest.approx(1234.5)
    assert importar.lee_numero(-5) == 5.0                # importes en positivo
    assert importar.lee_numero("€ 900") == pytest.approx(900.0)
    assert importar.lee_numero("") is None
    assert importar.lee_numero(None) is None
    assert importar.lee_numero("esto no es un número") == "error"


def test_leer_tabla_csv_del_texto_que_devuelve_una_ia():
    texto = ("```csv\n"
             "fecha;identificador;tipo_movimiento;importe\n"
             "2025-03-10;IE00BYX5NX33;compra;900\n"
             "10/03/2025;AAPL;compra;1050\n"
             "```\n")
    filas, error = importar.leer_tabla("pegado.csv", texto)
    assert error is None
    assert len(filas) == 2
    _, f = filas[0]
    assert f["fecha"] == "2025-03-10"
    assert f["identificador"] == "IE00BYX5NX33"
    assert f["importe"] == "900"


def test_leer_tabla_pide_las_columnas_basicas():
    filas, error = importar.leer_tabla("mal.csv", "foo;bar\n1;2")
    assert filas == []
    assert "fecha" in error and "importe" in error


def test_leer_tabla_solo_cabecera():
    filas, error = importar.leer_tabla("vacio.csv", "fecha;importe\n")
    assert filas == []
    assert "cabecera" in error


def test_leer_tabla_excel_de_la_plantilla():
    from openpyxl import Workbook
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Movimientos"
    hoja.append(importar.COLUMNAS)
    hoja.append([dt.date(2025, 3, 10), "IE00BYX5NX33", "Fidelity MSCI World",
                 "fondo", "compra", 62.5, 900, "EUR", None, "Aportación"])
    buf = io.BytesIO()
    libro.save(buf)

    filas, error = importar.leer_tabla("plantilla.xlsx", buf.getvalue())
    assert error is None
    assert len(filas) == 1
    _, f = filas[0]
    # openpyxl devuelve datetime; la fecha se normaliza al leer el movimiento
    assert importar.lee_fecha(f["fecha"]) == "2025-03-10"
    assert f["importe"] == 900
    assert f["unidades"] == 62.5


# ------------------------------------------------------------- el plan

def _cartera():
    return {
        "productos": [{"id": "cuenta", "nombre": "Cuenta del banco", "corto": "Cuenta",
                       "tipo": "efectivo", "fuente": "manual"}],
        "movimientos": [], "valoraciones": [],
    }


def test_vista_previa_no_toca_la_cartera_y_dice_lo_que_se_guarda(tmp_path):
    cfg = _cartera()
    filas = [(2, {"fecha": "2025-03-10", "nombre": "Cuenta del banco",
                  "tipo_producto": "efectivo", "tipo_movimiento": "saldo",
                  "importe": "2500"})]
    plan = importar.preparar_tabla(cfg, filas, str(tmp_path))
    assert not plan.errores

    antes = copy.deepcopy(cfg)
    previa = importar.vista_previa(cfg, plan)
    assert cfg == antes                       # la vista previa no escribe nada
    assert previa["saldos"] == 1
    assert len(cfg["valoraciones"]) == 0      # nada guardado todavía

    real = importar.aplicar(cfg, plan)
    assert previa == real                     # lo que ves es lo que se guarda
    assert len(cfg["valoraciones"]) == 1


def test_fila_sin_importe_es_error_fila_a_fila(tmp_path):
    cfg = _cartera()
    filas = [(7, {"fecha": "2025-03-10", "nombre": "Cuenta del banco",
                  "tipo_movimiento": "compra", "importe": ""})]
    plan = importar.preparar_tabla(cfg, filas, str(tmp_path))
    assert plan.errores and plan.errores[0]["fila"] == 7
    assert "importe" in plan.errores[0]["mensaje"]


def test_producto_sin_identificador_ni_nombre_es_error(tmp_path):
    cfg = _cartera()
    filas = [(3, {"fecha": "2025-03-10", "tipo_movimiento": "compra", "importe": "100"})]
    plan = importar.preparar_tabla(cfg, filas, str(tmp_path))
    assert any("identificador" in e["mensaje"] for e in plan.errores)


def test_aplicar_no_duplica_la_misma_fila_dos_veces(tmp_path):
    cfg = _cartera()
    filas = [(2, {"fecha": "2025-03-10", "nombre": "Cuenta del banco",
                  "tipo_movimiento": "saldo", "importe": "2500"})]
    plan = importar.preparar_tabla(cfg, filas, str(tmp_path))
    importar.aplicar(cfg, plan)
    importar.aplicar(cfg, plan)               # misma planificación otra vez
    assert len(cfg["valoraciones"]) == 1      # «Un solo valor por producto y día»
