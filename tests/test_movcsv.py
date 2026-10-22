# -*- coding: utf-8 -*-
"""
test_movcsv.py  ·  Movimientos de UN producto desde un CSV
==========================================================
Dos capas:

- `app/movcsv.py` lee y valida el texto (sin tocar nada).
- `servidor._aplica_movs_csv()` lo anota en la cartera.

Aquí se prueba lo que de verdad importa: que **solo se toca el producto elegido**,
que "sustituir" no se lleva por delante nada más y que si el CSV es una porquería
no se borra lo que había.
"""
import os

import pytest

from app import almacen, movcsv
from app import servidor as s


# ------------------------------------------------------------------ utilidades
def _cartera():
    return {"version": 2, "titular": "Mi patrimonio",
            "propietarios": [dict(p) for p in almacen.PROPIETARIOS_BASE],
            "cuentas": [], "productos": [], "movimientos": [], "valoraciones": []}


def _con_dos_productos():
    """Una cartera con dos productos manuales, cada uno con su cuenta de efectivo."""
    cfg = _cartera()
    almacen.guarda_cuenta(cfg, {"nombre": "Cuenta A", "tipo": "banco", "moneda": "EUR"})
    almacen.guarda_cuenta(cfg, {"nombre": "Cuenta B", "tipo": "banco", "moneda": "EUR"})
    a = almacen.cuenta(cfg, next(c["id"] for c in cfg["cuentas"] if c["nombre"] == "Cuenta A"))
    b = almacen.cuenta(cfg, next(c["id"] for c in cfg["cuentas"] if c["nombre"] == "Cuenta B"))
    pa, _ = almacen.guarda_producto(cfg, {"nombre": "Producto A", "corto": "Prod A",
                                          "tipo": "fondo", "fuente": "manual",
                                          "moneda": "EUR", "cuenta": a["id"]})
    pb, _ = almacen.guarda_producto(cfg, {"nombre": "Producto B", "corto": "Prod B",
                                          "tipo": "fondo", "fuente": "manual",
                                          "moneda": "EUR", "cuenta": b["id"]})
    return cfg, pa, pb


def _csv(*filas, cabecera="fecha,tipo,unidades,importe,comision,impuestos,nota"):
    return "\n".join([cabecera, *filas]) + "\n"


TRES = _csv("2025-01-15,compra,10,1000.00,0,0,Aporte",
            "2025-02-20,compra,5,520.50,2.5,0,Segunda",
            "2025-06-30,dividendo,,25.00,0,5.10,Cupon")


def _movs_de(cfg, pid):
    return [m for m in cfg["movimientos"] if m.get("producto") == pid]


# ------------------------------------------------------------------ el parser
def test_la_plantilla_trae_cabecera_y_dos_ejemplos():
    texto = movcsv.plantilla()
    lineas = [l for l in texto.strip().split("\n") if l.strip()]
    assert lineas[0] == ",".join(movcsv.COLUMNAS)
    assert len(lineas) == 3
    filas, errores = movcsv.lee(texto)
    assert errores == []
    assert [f["tipo"] for f in filas] == ["compra", "dividendo"]


def test_lee_un_csv_correcto():
    filas, errores = movcsv.lee(TRES)
    assert errores == []
    assert [f["linea"] for f in filas] == [2, 3, 4]
    assert filas[0]["fecha"] == "2025-01-15"
    assert filas[0]["tipo"] == "compra"
    assert filas[0]["unidades"] == 10.0
    assert filas[0]["importe"] == 1000.0
    assert filas[0]["nota"] == "Aporte"
    assert filas[2]["unidades"] is None        # celda vacía -> None


def test_los_numeros_valen_con_punto_o_con_coma():
    filas, errores = movcsv.lee(_csv(
        '2025-01-15,compra,10,"1000.50",0,0,a',
        '2025-01-16,compra,10,"1000,50",0,0,b',
        '2025-01-17,compra,10,"1.000,50",0,0,c',
        '2025-01-18,compra,10,"1,000.50",0,0,d'))
    assert errores == []
    assert [f["importe"] for f in filas] == [1000.5, 1000.5, 1000.5, 1000.5]


def test_el_tipo_se_acepta_con_tildes_y_con_su_etiqueta():
    filas, errores = movcsv.lee(_csv(
        "2025-01-15,COMPRA,1,10,0,0,a",
        "2025-01-16,Interés,,5,0,0,b",
        "2025-01-17,Dividendo o cupón,,5,0,0,c",
        "2025-01-18,comisión,,5,0,0,d"))
    assert errores == []
    assert [f["tipo"] for f in filas] == ["compra", "interes", "dividendo", "comision"]


def test_sin_cabecera_es_un_error_de_todo_el_fichero():
    filas, errores = movcsv.lee("2025-01-15,compra,10,1000.00,0,0,x\n")
    assert filas == []
    assert len(errores) == 1 and errores[0]["linea"] == 1
    assert "cabecera" in errores[0]["motivo"].lower()


def test_un_fichero_vacio_es_un_error():
    filas, errores = movcsv.lee("   \n\n")
    assert filas == [] and errores and errores[0]["linea"] == 1


def test_las_filas_malas_se_cuentan_y_las_buenas_pasan():
    filas, errores = movcsv.lee(_csv(
        "2025-13-45,compra,1,10,0,0,fecha rota",
        "2025-01-16,inventado,1,10,0,0,tipo raro",
        "2025-01-17,compra,1,no-es-un-numero,0,0,importe roto",
        "2025-01-18,compra,1,10,0,0,buena"))
    assert len(filas) == 1 and filas[0]["nota"] == "buena"
    assert [e["linea"] for e in errores] == [2, 3, 4]
    assert "Fecha inválida" in errores[0]["motivo"]
    assert "Tipo desconocido" in errores[1]["motivo"]
    assert "ilegible" in errores[2]["motivo"]


def test_las_lineas_en_blanco_no_cuentan_como_error():
    filas, errores = movcsv.lee(_csv("2025-01-15,compra,1,10,0,0,a") + "\n\n")
    assert len(filas) == 1 and errores == []


# --------------------------------------------------------- anotar en la cartera
def test_anadir_mete_los_movimientos_en_su_producto():
    cfg, pa, pb = _con_dos_productos()
    filas, errores = movcsv.lee(TRES)
    hechos, fallos = s._aplica_movs_csv(cfg, pa, filas, "anadir", [])
    assert len(hechos) == 3 and fallos == []
    assert len(_movs_de(cfg, pa["id"])) == 3
    assert _movs_de(cfg, pb["id"]) == []            # el otro producto, intacto
    assert all(m["cuenta"] == pa["cuenta"] for m in _movs_de(cfg, pa["id"]))
    assert [m["tipo"] for m in _movs_de(cfg, pa["id"])] == ["compra", "compra", "dividendo"]


def test_anadir_no_toca_los_movimientos_que_ya_habia():
    cfg, pa, pb = _con_dos_productos()
    filas, _ = movcsv.lee(_csv("2025-01-10,compra,1,100,0,0,previo"))
    s._aplica_movs_csv(cfg, pa, filas, "anadir", [])
    antes = {m["id"] for m in cfg["movimientos"]}
    filas2, _ = movcsv.lee(TRES)
    s._aplica_movs_csv(cfg, pa, filas2, "anadir", [])
    despues = {m["id"] for m in cfg["movimientos"]}
    assert antes <= despues                          # los de antes siguen
    assert len(_movs_de(cfg, pa["id"])) == 4


def test_sustituir_borra_solo_los_de_ese_producto():
    cfg, pa, pb = _con_dos_productos()
    # Cada producto tiene sus movimientos de partida.
    s._aplica_movs_csv(cfg, pa, movcsv.lee(_csv("2025-01-01,compra,1,10,0,0,viejo A"))[0],
                       "anadir", [])
    s._aplica_movs_csv(cfg, pb, movcsv.lee(_csv("2025-01-01,compra,7,70,0,0,viejo B"))[0],
                       "anadir", [])
    b_antes = [m["id"] for m in _movs_de(cfg, pb["id"])]
    assert len(_movs_de(cfg, pa["id"])) == 1

    hechos, fallos = s._aplica_movs_csv(cfg, pa, movcsv.lee(TRES)[0], "sustituir", [])
    assert len(hechos) == 3 and fallos == []
    assert len(_movs_de(cfg, pa["id"])) == 3
    assert "viejo A" not in [m.get("nota") for m in _movs_de(cfg, pa["id"])]
    # El otro producto sigue exactamente igual.
    assert [m["id"] for m in _movs_de(cfg, pb["id"])] == b_antes


def test_una_fila_mala_no_impide_anotar_las_buenas():
    cfg, pa, _ = _con_dos_productos()
    filas, errores = movcsv.lee(_csv(
        "2025-01-15,compra,1,10,0,0,buena",
        "2025-13-45,compra,1,10,0,0,mala",
        "2025-01-17,compra,1,10,0,0,buena2"))
    assert len(filas) == 2 and len(errores) == 1
    hechos, fallos = s._aplica_movs_csv(cfg, pa, filas, "anadir", [])
    assert len(hechos) == 2 and fallos == []
    assert len(_movs_de(cfg, pa["id"])) == 2


def test_una_regla_de_la_app_que_falla_cuenta_como_fila_mala():
    """Un importe de 0 no vale para ninguna compra: cuenta como fila mala, no rompe."""
    cfg, pa, _ = _con_dos_productos()
    filas, _ = movcsv.lee(_csv(
        "2025-01-15,compra,1,0,0,0,importe cero",
        "2025-01-16,compra,2,20,0,0,compra buena"))
    hechos, fallos = s._aplica_movs_csv(cfg, pa, filas, "anadir", [])
    assert len(hechos) == 1 and hechos[0]["tipo"] == "compra"
    assert len(fallos) == 1 and fallos[0]["linea"] == 2
    assert "importe" in fallos[0]["motivo"]


def test_sustituir_sin_ninguna_fila_valida_no_borra_nada():
    cfg, pa, _ = _con_dos_productos()
    s._aplica_movs_csv(cfg, pa, movcsv.lee(_csv("2025-01-01,compra,1,10,0,0,viejo"))[0],
                       "anadir", [])
    antes = [m["id"] for m in _movs_de(cfg, pa["id"])]
    assert len(antes) == 1
    filas, _ = movcsv.lee(_csv("2025-01-15,compra,99,0,0,0,imposible"))
    with pytest.raises(almacen.ErrorValidacion):
        s._aplica_movs_csv(cfg, pa, filas, "sustituir", [])
    # La función lanza ANTES de que nadie guarde: los movimientos siguen ahí.
    assert [m["id"] for m in _movs_de(cfg, pa["id"])] == antes


def test_un_producto_sin_cuenta_no_se_toca():
    cfg, pa, _ = _con_dos_productos()
    pa["cuenta"] = ""
    filas, _ = movcsv.lee(TRES)
    with pytest.raises(almacen.ErrorValidacion) as e:
        s._aplica_movs_csv(cfg, pa, filas, "sustituir", [])
    assert "cuenta de efectivo" in " ".join(e.value.errores)
    assert _movs_de(cfg, pa["id"]) == []


def test_una_cuenta_que_ya_no_existe_no_se_crea_sola():
    cfg, pa, _ = _con_dos_productos()
    pa["cuenta"] = "cuenta_que_no_existe"
    filas, _ = movcsv.lee(TRES)
    with pytest.raises(almacen.ErrorValidacion) as e:
        s._aplica_movs_csv(cfg, pa, filas, "anadir", [])
    assert "ya no existe" in " ".join(e.value.errores)
    assert [c["id"] for c in cfg["cuentas"]].count("cuenta_que_no_existe") == 0


def test_el_saldo_de_efectivo_sigue_al_dia():
    """Una compra resta de la cuenta y un dividendo suma: el saldo del día se rehace.
    Lo anotado es el saldo ACUMULADO a esa fecha, no el movimiento del día."""
    cfg, pa, _ = _con_dos_productos()
    s._aplica_movs_csv(cfg, pa, movcsv.lee(TRES)[0], "anadir", [])
    ef = almacen.producto_efectivo_de(cfg, pa["cuenta"])
    vals = {v["fecha"]: v["valor"] for v in cfg["valoraciones"] if v["producto"] == ef["id"]}
    assert vals, "la cuenta debería tener su saldo anotado"
    # 15-ene: −1000 (compra) · 20-feb: −520,50 (compra) · 30-jun: +25 (dividendo)
    assert vals["2025-01-15"] == pytest.approx(-1000.00, abs=0.01)
    assert vals["2025-02-20"] == pytest.approx(-1520.50, abs=0.01)
    assert vals["2025-06-30"] == pytest.approx(-1495.50, abs=0.01)


def test_sustituir_rehace_el_saldo_de_los_dias_que_se_quedan_sin_movimientos():
    """Si el CSV quita movimientos de un día, el saldo automático de ese día se retira."""
    cfg, pa, _ = _con_dos_productos()
    s._aplica_movs_csv(cfg, pa, movcsv.lee(
        _csv("2025-01-15,compra,1,100,0,0,uno", "2025-03-03,compra,1,200,0,0,dos"))[0],
        "anadir", [])
    ef = almacen.producto_efectivo_de(cfg, pa["cuenta"])
    assert any(v["fecha"] == "2025-03-03" for v in cfg["valoraciones"]
               if v["producto"] == ef["id"])
    # El CSV nuevo no trae nada del 3-mar: ese día deja de tener saldo automático.
    s._aplica_movs_csv(cfg, pa, movcsv.lee(_csv("2025-01-15,compra,1,100,0,0,uno"))[0],
                       "sustituir", [])
    assert not any(v["fecha"] == "2025-03-03" for v in cfg["valoraciones"]
                   if v["producto"] == ef["id"])


# ------------------------------------------------------------------ las rutas
@pytest.fixture
def cliente(monkeypatch):
    """Cliente de Flask con una cartera de dos productos y el recálculo simulado
    (el motor necesita precios y aquí no hace falta)."""
    cfg, pa, pb = _con_dos_productos()
    ruta = os.path.join(s.DATOS, "cartera.json")
    previo = None
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as f:
            previo = f.read()
    almacen.guarda(ruta, cfg)
    monkeypatch.setattr(s, "modo", lambda: "propio")
    monkeypatch.setattr(s, "recalcula", lambda descargar: {"avisos": []})
    c = s.app.test_client()
    c.producto = pa
    c.otro = pb
    yield c
    if previo is None:
        os.remove(ruta)
    else:
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(previo)


def test_la_plantilla_se_descarga(cliente):
    r = cliente.get("/api/movimientos/plantilla.csv")
    assert r.status_code == 200
    assert "csv" in r.headers["Content-Type"]
    assert "movimientos.csv" in r.headers["Content-Disposition"]
    texto = r.get_data(as_text=True)
    assert texto.startswith(",".join(movcsv.COLUMNAS))
    assert len(texto.strip().split("\n")) == 3


def test_previsualizar_cuenta_validos_y_errores(cliente):
    r = cliente.post(f"/api/productos/{cliente.producto['id']}/movimientos/csv/previsualizar",
                     json={"texto": TRES})
    j = r.get_json()
    assert r.status_code == 200 and j["ok"]
    assert j["validos"] == 3 and j["errores_totales"] == 0
    assert j["producto"]["id"] == cliente.producto["id"]
    # Y no ha anotado nada: la vista previa es solo un ensayo.
    cfg = almacen.carga(os.path.join(s.DATOS, "cartera.json"))
    assert _movs_de(cfg, cliente.producto["id"]) == []


def test_previsualizar_detecta_la_fila_mala(cliente):
    r = cliente.post(f"/api/productos/{cliente.producto['id']}/movimientos/csv/previsualizar",
                     json={"texto": _csv("2025-01-15,compra,1,10,0,0,buena",
                                         "2025-13-45,compra,1,10,0,0,mala",
                                         "2025-01-17,compra,1,10,0,0,buena2")})
    j = r.get_json()
    assert j["validos"] == 2 and j["errores_totales"] == 1
    assert j["errores"][0]["linea"] == 3


def test_sin_cabecera_responde_400_y_no_importa(cliente):
    r = cliente.post(f"/api/productos/{cliente.producto['id']}/movimientos/csv/importar",
                     json={"texto": "2025-01-15,compra,1,10,0,0,x\n"})
    assert r.status_code == 400
    assert "cabecera" in r.get_json()["errores"][0].lower()
    cfg = almacen.carga(os.path.join(s.DATOS, "cartera.json"))
    assert _movs_de(cfg, cliente.producto["id"]) == []


def test_un_producto_que_no_existe_da_error(cliente):
    r = cliente.post("/api/productos/no_existe/movimientos/csv/importar",
                     json={"texto": TRES})
    assert r.status_code == 400
    assert "no existe" in r.get_json()["errores"][0].lower()


def test_importar_anadir_y_luego_sustituir(cliente):
    pid = cliente.producto["id"]
    r = cliente.post(f"/api/productos/{pid}/movimientos/csv/importar",
                     json={"texto": TRES, "modo": "anadir"})
    assert r.status_code == 200 and r.get_json()["ok"]
    assert r.get_json()["informe"]["anadidos"] == 3
    cfg = almacen.carga(os.path.join(s.DATOS, "cartera.json"))
    assert len(_movs_de(cfg, pid)) == 3
    assert _movs_de(cfg, cliente.otro["id"]) == []

    # El mismo CSV otra vez, sustituyendo: siguen siendo 3 (no 6).
    r = cliente.post(f"/api/productos/{pid}/movimientos/csv/importar",
                     json={"texto": TRES, "modo": "sustituir"})
    assert r.status_code == 200
    assert r.get_json()["informe"] == {"anadidos": 3, "fallos": [], "borrados": 3}
    cfg = almacen.carga(os.path.join(s.DATOS, "cartera.json"))
    assert len(_movs_de(cfg, pid)) == 3
    assert _movs_de(cfg, cliente.otro["id"]) == []
