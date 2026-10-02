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


def _candidato_nvda():
    return {"fuente": "yahoo", "codigo": "NVDA", "nombre": "NVIDIA Corporation",
            "tipo": "accion", "identificador": "US6706661040", "vivo": None,
            "moneda": "USD", "precio": 100.0, "fecha": "2026-10-02", "mercado": "NasdaqGS"}


def _fila(fecha, ident, nombre="", unidades="4"):
    return {"fecha": fecha, "identificador": ident, "nombre": nombre,
            "tipo_producto": "accion", "tipo_movimiento": "compra",
            "unidades": unidades, "importe": "500", "moneda": "EUR", "comision": "0"}


def test_isin_no_indexado_se_resuelve_con_el_nombre_de_la_fila(monkeypatch, tmp_path):
    # US6706661040 (NVIDIA) no está en los buscadores: el nombre «NVIDIA» sí
    # lleva a NVDA, y el ISIN se conserva como identificador del producto.
    consultas = []

    def busca(q):
        consultas.append(q)
        return [_candidato_nvda()] if q == "NVIDIA" else []

    monkeypatch.setattr(importar.buscar, "buscar", busca)
    cfg = _cartera()
    plan = importar.preparar_tabla(cfg, [(2, _fila("2025-01-28", "US6706661040", "NVIDIA"))], str(tmp_path))
    assert not plan.errores
    nuevo = plan.productos_nuevos[0]["datos"]
    assert nuevo["codigo"] == "NVDA"
    assert nuevo["identificador"] == "US6706661040"
    assert "US6706661040" in consultas and "NVIDIA" in consultas


def test_el_nombre_solo_se_acepta_si_coincide_con_el_resultado(monkeypatch, tmp_path):
    # Un resultado que no lleva que ver con el nombre no se acepta.
    ajeno = {**_candidato_nvda(), "codigo": "OTRA", "nombre": "Otra Cosas S.A."}
    monkeypatch.setattr(importar.buscar, "buscar", lambda q: [] if q.startswith("US") else [ajeno])
    plan = importar.preparar_tabla(_cartera(), [(2, _fila("2025-01-28", "US6706661040", "NVIDIA"))],
                                   str(tmp_path))
    assert any("US6706661040" in e["mensaje"] for e in plan.errores)


def test_un_producto_no_encontrado_se_avisa_en_todas_sus_filas(monkeypatch, tmp_path):
    # Antes solo la primera fila avisaba: las demás se descartaban en silencio.
    monkeypatch.setattr(importar.buscar, "buscar", lambda q: [])
    filas = [(2, _fila("2025-01-28", "ZZZZNOEXISTE")), (9, _fila("2025-03-03", "ZZZZNOEXISTE"))]
    plan = importar.preparar_tabla(_cartera(), filas, str(tmp_path))
    assert [e["fila"] for e in plan.errores] == [2, 9]
    assert all("ZZZZNOEXISTE" in e["mensaje"] for e in plan.errores)


def test_fila_solo_con_nombre_se_busca_en_internet(monkeypatch, tmp_path):
    # Extractos sin columna de identificador: «Tesla Inc.» debe encontrar TSLA
    # en vez de crear un producto manual que luego no se valora en el panel.
    cand = {"fuente": "yahoo", "codigo": "TSLA", "nombre": "Tesla, Inc.", "tipo": "accion",
            "identificador": "TSLA", "vivo": None, "moneda": "USD",
            "precio": 300.0, "fecha": "2026-10-02", "mercado": "NasdaqGS"}
    consultas = []

    def busca(q):
        consultas.append(q)
        return [cand] if q == "Tesla Inc." else []

    monkeypatch.setattr(importar.buscar, "buscar", busca)
    fila = {"fecha": "2025-01-17", "identificador": "", "nombre": "Tesla Inc.",
            "tipo_producto": "accion", "tipo_movimiento": "compra",
            "unidades": "1", "importe": "300", "moneda": "EUR", "comision": ""}
    plan = importar.preparar_tabla(_cartera(), [(2, fila)], str(tmp_path))
    assert not plan.errores
    nuevo = plan.productos_nuevos[0]["datos"]
    assert nuevo["fuente"] == "yahoo" and nuevo["codigo"] == "TSLA"
    assert consultas == ["Tesla Inc."]          # se busca una sola vez


def test_fila_solo_con_nombre_sin_coincidencia_se_crea_manual(monkeypatch, tmp_path):
    # Nada que se le parezca: sigue siendo manual (un plan de pensiones, una cuenta...).
    monkeypatch.setattr(importar.buscar, "buscar", lambda q: [_candidato_nvda()])
    fila = {"fecha": "2025-01-17", "identificador": "", "nombre": "Plan 2040 del banco",
            "tipo_producto": "pension", "tipo_movimiento": "compra",
            "unidades": "100", "importe": "500", "moneda": "EUR", "comision": ""}
    plan = importar.preparar_tabla(_cartera(), [(2, fila)], str(tmp_path))
    assert not plan.errores
    nuevo = plan.productos_nuevos[0]["datos"]
    assert nuevo["fuente"] == "manual"


def test_las_cuentas_no_se_bucan_en_internet(monkeypatch, tmp_path):
    def no_llames(q):
        raise AssertionError("una cuenta es un saldo, no se busca")

    monkeypatch.setattr(importar.buscar, "buscar", no_llames)
    fila = {"fecha": "2025-01-17", "identificador": "", "nombre": "Cuenta del banco",
            "tipo_producto": "efectivo", "tipo_movimiento": "saldo",
            "unidades": "", "importe": "2500", "moneda": "EUR", "comision": ""}
    cfg = {"productos": [], "movimientos": [], "valoraciones": []}
    plan = importar.preparar_tabla(cfg, [(2, fila)], str(tmp_path))
    assert not plan.errores
    assert plan.productos_nuevos[0]["datos"]["fuente"] == "manual"
    assert plan.valoraciones


def test_fila_solo_con_nombre_y_sin_conexion_avisa_en_veces_de_crearlo_a_ciegas(monkeypatch, tmp_path):
    monkeypatch.setattr(importar.buscar, "FALLOS", [])

    def rota(q):
        importar.buscar.FALLOS.append("yahoo: timeout")
        return []

    monkeypatch.setattr(importar.buscar, "buscar", rota)
    fila = {"fecha": "2025-01-17", "identificador": "", "nombre": "Tesla Inc.",
            "tipo_producto": "accion", "tipo_movimiento": "compra",
            "unidades": "1", "importe": "300", "moneda": "EUR", "comision": ""}
    plan = importar.preparar_tabla(_cartera(), [(2, fila)], str(tmp_path))
    assert any("conexión" in e["mensaje"] for e in plan.errores)
    assert not plan.productos_nuevos            # no crea un producto manual a ciegas


def test_aplicar_no_duplica_la_misma_fila_dos_veces(tmp_path):
    cfg = _cartera()
    filas = [(2, {"fecha": "2025-03-10", "nombre": "Cuenta del banco",
                  "tipo_movimiento": "saldo", "importe": "2500"})]
    plan = importar.preparar_tabla(cfg, filas, str(tmp_path))
    importar.aplicar(cfg, plan)
    importar.aplicar(cfg, plan)               # misma planificación otra vez
    assert len(cfg["valoraciones"]) == 1      # «Un solo valor por producto y día»
