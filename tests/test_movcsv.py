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
import datetime as dt
import json
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
    assert r.get_json()["informe"] == {"anadidos": 3, "fallos": [], "borrados": 3, "moneda": "EUR"}
    cfg = almacen.carga(os.path.join(s.DATOS, "cartera.json"))
    assert len(_movs_de(cfg, pid)) == 3
    assert _movs_de(cfg, cliente.otro["id"]) == []


# ------------------------------------------------------------------ la moneda
def _cache_usd(carpeta, valor=0.90, desde="2024-01-01", hasta="2026-12-31"):
    """USDEUR diario en la caché (0,90 € por dólar): así no se sale a internet."""
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


def _guardado(pid):
    cfg = almacen.carga(os.path.join(s.DATOS, "cartera.json"))
    return _movs_de(cfg, pid)


def test_sin_moneda_se_asume_euro(cliente):
    """El que no manda moneda (una app vieja, un script) se comporta como siempre."""
    pid = cliente.producto["id"]
    r = cliente.post(f"/api/productos/{pid}/movimientos/csv/importar", json={"texto": TRES})
    assert r.status_code == 200
    assert r.get_json()["informe"]["moneda"] == "EUR"


def test_en_euros_los_campos_de_moneda_quedan_vacios(cliente):
    """SIN REGRESIÓN: con EUR no se guarda original ni cambio, igual que en V1.04."""
    pid = cliente.producto["id"]
    cliente.post(f"/api/productos/{pid}/movimientos/csv/importar",
                 json={"texto": TRES, "moneda": "EUR"})
    movs = _guardado(pid)
    assert len(movs) == 3
    for m in movs:
        assert m.get("monedaOriginal") in ("", None)
        assert m.get("importeOriginal") in ("", None)
        assert m.get("tipoCambio") in ("", None)
    assert movs[0]["importe"] == pytest.approx(1000.00, abs=0.01)      # tal cual el CSV


def test_importar_en_dolares_guarda_el_original_y_el_cambio(cliente):
    """En USD: importeOriginal en dólares, importe en euros y tipoCambio del día."""
    _cache_usd(s.DATOS, 0.90)
    pid = cliente.producto["id"]
    r = cliente.post(f"/api/productos/{pid}/movimientos/csv/importar",
                     json={"texto": _csv("2026-10-01,compra,10,1000.00,0,0,en dolares"),
                           "moneda": "USD"})
    assert r.status_code == 200
    assert r.get_json()["informe"]["moneda"] == "USD"
    mov = _guardado(pid)[0]
    assert mov["monedaOriginal"] == "USD"
    assert float(mov["importeOriginal"]) == pytest.approx(1000.00, abs=0.01)
    assert float(mov["importe"]) == pytest.approx(900.00, abs=0.01)  # 1000 USD × 0,90
    assert float(mov["tipoCambio"]) == pytest.approx(0.90, abs=1e-6)


def test_en_dolares_tambien_se_convierte_la_comision(cliente):
    _cache_usd(s.DATOS, 0.50)
    pid = cliente.producto["id"]
    cliente.post(f"/api/productos/{pid}/movimientos/csv/importar",
                 json={"texto": _csv("2026-10-01,compra,10,1000.00,10,0,comision en dolares"),
                       "moneda": "USD"})
    mov = _guardado(pid)[0]
    assert float(mov["comision"]) == pytest.approx(5.00, abs=0.01)     # 10 USD × 0,50
    assert float(mov["importe"]) == pytest.approx(500.00, abs=0.01)


def test_la_previsualizacion_devuelve_la_moneda_y_los_importes_originales(cliente):
    _cache_usd(s.DATOS, 0.90)
    pid = cliente.producto["id"]
    r = cliente.post(f"/api/productos/{pid}/movimientos/csv/previsualizar",
                     json={"texto": TRES, "moneda": "USD"})
    j = r.get_json()
    assert j["ok"] and j["moneda"] == "USD" and j["validos"] == 3
    primera = j["filas"][0]
    assert primera["monedaOriginal"] == "USD"
    assert float(primera["importeOriginal"]) == pytest.approx(1000.00, abs=0.01)
    assert float(primera["importe"]) == pytest.approx(900.00, abs=0.01)
    # Y no ha tocado nada: sigue siendo un ensayo.
    assert _guardado(pid) == []


def test_una_moneda_invalida_da_un_error_claro(cliente):
    pid = cliente.producto["id"]
    r = cliente.post(f"/api/productos/{pid}/movimientos/csv/importar",
                     json={"texto": TRES, "moneda": "DOLARES"})
    assert r.status_code == 400
    assert "moneda" in r.get_json()["errores"][0].lower()
    assert _guardado(pid) == []


def test_sin_cambio_disponible_no_se_importa_nada(cliente, monkeypatch):
    """Sin cambio del día no se inventa nada: cada fila se reporta y no entra ninguna."""
    monkeypatch.setattr(s.motor, "serie_cambio", lambda moneda, carpeta: {})
    monkeypatch.setattr(s.motor, "descargar_serie", lambda *a, **k: {})
    pid = cliente.producto["id"]
    r = cliente.post(f"/api/productos/{pid}/movimientos/csv/importar",
                     json={"texto": TRES, "moneda": "USD"})
    j = r.get_json()
    assert r.status_code == 200 and j["ok"]
    assert j["informe"]["anadidos"] == 0
    assert len(j["informe"]["fallos"]) == 3
    assert all("cambio" in f["motivo"] for f in j["informe"]["fallos"])
    assert _guardado(pid) == []


def test_sin_cambio_en_sustituir_tampoco_borra(cliente, monkeypatch):
    pid = cliente.producto["id"]
    cliente.post(f"/api/productos/{pid}/movimientos/csv/importar",
                 json={"texto": TRES, "moneda": "EUR"})
    antes = [m["id"] for m in _guardado(pid)]
    assert len(antes) == 3
    monkeypatch.setattr(s.motor, "serie_cambio", lambda moneda, carpeta: {})
    monkeypatch.setattr(s.motor, "descargar_serie", lambda *a, **k: {})
    r = cliente.post(f"/api/productos/{pid}/movimientos/csv/importar",
                     json={"texto": TRES, "modo": "sustituir", "moneda": "USD"})
    assert r.status_code == 400
    assert "no se ha sustituido nada" in " ".join(r.get_json()["errores"]).lower()
    assert [m["id"] for m in _guardado(pid)] == antes      # los de euros siguen


def test_sustituir_cambiando_de_moneda_no_mezcla(cliente):
    _cache_usd(s.DATOS, 0.90)
    pid = cliente.producto["id"]
    cliente.post(f"/api/productos/{pid}/movimientos/csv/importar",
                 json={"texto": TRES, "modo": "anadir", "moneda": "EUR"})
    assert all(m.get("monedaOriginal") in ("", None) for m in _guardado(pid))
    r = cliente.post(f"/api/productos/{pid}/movimientos/csv/importar",
                     json={"texto": TRES, "modo": "sustituir", "moneda": "USD"})
    assert r.get_json()["informe"]["borrados"] == 3
    movs = _guardado(pid)
    assert len(movs) == 3
    assert all(m["monedaOriginal"] == "USD" for m in movs)   # sin mezcla
    assert all(float(m["tipoCambio"]) == pytest.approx(0.90, abs=1e-6) for m in movs)
    assert _guardado(cliente.otro["id"]) == []               # el testigo, intacto


def test_una_cuenta_en_dolares_no_cambia_el_signo_del_efectivo(cliente):
    """El saldo de efectivo se mueve en euros: la compra resta el importe ya convertido."""
    _cache_usd(s.DATOS, 0.90)
    pid = cliente.producto["id"]
    cliente.post(f"/api/productos/{pid}/movimientos/csv/importar",
                 json={"texto": _csv("2026-10-01,compra,10,1000.00,0,0,en dolares"),
                       "moneda": "USD"})
    cfg = almacen.carga(os.path.join(s.DATOS, "cartera.json"))
    ef = almacen.producto_efectivo_de(cfg, cliente.producto["cuenta"])
    vals = {v["fecha"]: v["valor"] for v in cfg["valoraciones"] if v["producto"] == ef["id"]}
    assert vals["2026-10-01"] == pytest.approx(-900.00, abs=0.01)


# ------------------------------------------------------------------ fechas
def _csv_fechas(*fechas, tipo="compra"):
    return "\n".join(["fecha,tipo,unidades,importe,comision,impuestos,nota"]
                     + [f"{f},{tipo},1,10,0,0,n" for f in fechas]) + "\n"


@pytest.mark.parametrize("crudo,esperado", [
    ("2026-10-05", "2026-10-05"),                 # ISO
    ("2026-10-05 00:00:00", "2026-10-05"),        # ISO con hora (formato de PP)
    ("2026-10-05 14:30", "2026-10-05"),           # ISO con hora corta
    ("2026-10-05T00:00:00", "2026-10-05"),        # ISO con T
    ("25/10/2026", "2026-10-25"),                 # DD/MM sin ambigüedad
    ("25/10/2026 08:15", "2026-10-25"),           # DD/MM con hora
    ("25-10-2026", "2026-10-25"),                 # DD-MM
    ("25-10-2026 08:15", "2026-10-25"),
    ("10/25/2026", "2026-10-25"),                 # MM/DD sin ambigüedad
    ("10/25/2026 0:00", "2026-10-25"),
    ("2026/10/05", "2026-10-05"),                 # año primero con barras
    ("2026.10.05", "2026-10-05"),                 # año primero con puntos
    ("25.10.2026", "2026-10-25"),                 # día primero con puntos
])
def test_formatos_de_fecha_aceptados(crudo, esperado):
    filas, errores = movcsv.lee(_csv_fechas(crudo))
    assert errores == [], errores
    assert filas[0]["fecha"] == esperado


@pytest.mark.parametrize("crudo", [
    "2026-13-45", "31/02/2026", "25/13/2026", "13/13/2026",
    "hola", "", "2026-10-05 99", "05/10", "2026-10",
])
def test_fechas_invalidas_dan_error_con_los_formatos(crudo):
    filas, errores = movcsv.lee(_csv_fechas(crudo))
    assert filas == []
    assert len(errores) == 1
    motivo = errores[0]["motivo"]
    assert motivo.startswith("Fecha inválida")
    assert "Formatos aceptados" in motivo
    for trozo in ("AAAA-MM-DD", "HH:MM:SS", "DD/MM/AAAA", "MM/DD/AAAA", "DD-MM-AAAA"):
        assert trozo in motivo


def test_una_fecha_ambigua_sola_se_lee_dia_primero_y_avisa():
    avisos = []
    filas, errores = movcsv.lee(_csv_fechas("10/05/2026"), avisos)
    assert errores == []
    assert filas[0]["fecha"] == "2026-05-10"          # 10 de mayo (DD/MM)
    assert len(avisos) == 1
    assert "ambigua" in avisos[0] and "línea 2" in avisos[0]
    assert "reformatea el CSV a ISO" in avisos[0]


def test_sin_avisos_si_no_se_pide_la_lista():
    """Compatibilidad: quien llame como antes sigue recibiendo dos valores."""
    filas, errores = movcsv.lee(_csv_fechas("10/05/2026"))
    assert errores == [] and filas[0]["fecha"] == "2026-05-10"


def test_el_fichero_delata_el_orden_dia_primero():
    """Una fecha con el día > 12 decide por todas: 10/05/2026 -> 10 de mayo."""
    avisos = []
    filas, errores = movcsv.lee(_csv_fechas("25/10/2026", "10/05/2026"), avisos)
    assert errores == []
    assert [f["fecha"] for f in filas] == ["2026-10-25", "2026-05-10"]
    assert avisos == []                     # ya no hay nada que adivinar


def test_el_fichero_delata_el_orden_mes_primero():
    """10/25/2026 delata que va mes primero: 10/5/2026 -> 5 de octubre, sin aviso."""
    avisos = []
    filas, errores = movcsv.lee(_csv_fechas("10/25/2026 0:00", "10/5/2026 0:00"), avisos)
    assert errores == []
    assert [f["fecha"] for f in filas] == ["2026-10-25", "2026-10-05"]
    assert avisos == []


def test_si_el_fichero_se_contradice_no_se_impone_nada():
    avisos = []
    filas, errores = movcsv.lee(_csv_fechas("25/10/2026", "10/25/2026", "10/05/2026"), avisos)
    assert errores == []
    assert [f["fecha"] for f in filas] == ["2026-10-25", "2026-10-25", "2026-05-10"]
    assert len(avisos) == 1 and "ambigua" in avisos[0]


def test_las_fechas_con_hora_de_excel_se_importan_de_verdad():
    """El caso real: Excel convierte 2026-10-05 en 10/5/2026 0:00 (MM/DD)."""
    texto = ("fecha,tipo,unidades,importe,comision,impuestos,nota\n"
             "10/5/2026 0:00,compra,10,1000.00,0,0,Aporte\n"
             "10/25/2026 0:00,compra,5,520.50,0,0,Otra\n")
    avisos = []
    filas, errores = movcsv.lee(texto, avisos)
    assert errores == [] and avisos == []
    assert [f["fecha"] for f in filas] == ["2026-10-05", "2026-10-25"]


# ------------------------------------------- el formato de fecha que elige el usuario
def test_el_formato_mdy_convierte_las_ambiguas_en_mes_primero():
    """El falso positivo de «3/12/2026»: con MM/DD es 12 de marzo, no 3 de diciembre."""
    avisos = []
    filas, errores = movcsv.lee(_csv_fechas("3/12/2026"), avisos, formato="mdy")
    assert errores == [] and filas[0]["fecha"] == "2026-03-12"
    assert avisos == []


def test_el_formato_dmy_convierte_las_ambiguas_en_dia_primero():
    filas, errores = movcsv.lee(_csv_fechas("3/12/2026"), formato="dmy")
    assert errores == [] and filas[0]["fecha"] == "2026-12-03"


def test_el_formato_gana_a_lo_que_delate_el_fichero():
    """Si el usuario dice MM/DD, manda él aunque otra fila sugiera lo contrario."""
    filas, errores = movcsv.lee(_csv_fechas("10/12/2026", "3/12/2026"), formato="mdy")
    assert errores == []
    assert [f["fecha"] for f in filas] == ["2026-10-12", "2026-03-12"]


def test_forzar_mes_primero_con_un_mes_imposible_lo_explica():
    filas, errores = movcsv.lee(_csv_fechas("25/10/2026"), formato="mdy")
    assert filas == []
    assert "MM/DD/AAAA" in errores[0]["motivo"] and "mes sería 25" in errores[0]["motivo"]
    assert "Formato de fecha" in errores[0]["motivo"]


def test_con_iso_las_fechas_a_la_espanola_se_rechazan():
    filas, errores = movcsv.lee(_csv_fechas("10/05/2026"), formato="iso")
    assert filas == []
    assert "AAAA-MM-DD (ISO)" in errores[0]["motivo"]


def test_iso_funciona_con_cualquier_formato_elegido():
    for fmt in (None, "auto", "dmy", "mdy", "iso"):
        filas, errores = movcsv.lee(_csv_fechas("2026-10-05 00:00:00"), formato=fmt)
        assert errores == [], (fmt, errores)
        assert filas[0]["fecha"] == "2026-10-05", fmt


def test_auto_sigue_avisando_de_la_ambiguedad():
    avisos = []
    filas, errores = movcsv.lee(_csv_fechas("3/12/2026"), avisos, formato="auto")
    assert errores == [] and filas[0]["fecha"] == "2026-12-03"
    assert len(avisos) == 1 and "Formato de fecha" in avisos[0]


# ------------------------------------------- el CSV de Portfolio Performance tal cual
PP = (
    "Fecha;Tipo;Activo;Títulos;Precio;Cantidad;Comisiones;Impuestos;"
    "Valor neto de transacción;Cuenta;Cuenta de contrapartida;Nota;Fuente\n"
    "2026-10-05 00:00:00;Compra;Tesla Inc.;10;250,00;;2,50;0;2.502,50;Revolut USD;;;Yahoo\n"
    "2026-03-12 00:00:00;Dividendo;Tesla Inc.;; ;;;3,10;25,00;Revolut USD;;Cupón;Yahoo\n"
    "2026-04-01 00:00:00;Compra;Bitcoin;1;50000,00;;0;0;50000,00;Revolut;;;CoinGecko\n"
)
TESLA = {"id": "tesla_inc", "nombre": "Tesla Inc.", "corto": "Tesla Inc."}


def test_el_csv_de_pp_se_lee_tal_cual_y_se_filtra_por_producto():
    avisos = []
    filas, errores = movcsv.lee(PP, avisos, producto=TESLA)
    assert errores == []
    assert len(filas) == 2                       # solo las de Tesla
    assert {f["tipo"] for f in filas} == {"compra", "dividendo"}
    fila_c = next(f for f in filas if f["tipo"] == "compra")
    assert fila_c["fecha"] == "2026-10-05"
    assert fila_c["unidades"] == 10.0
    assert fila_c["importe"] == 2502.50          # «Valor neto de transacción»
    assert fila_c["comision"] == 2.50
    fila_d = next(f for f in filas if f["tipo"] == "dividendo")
    assert fila_d["importe"] == 25.00 and fila_d["impuestos"] == 3.10
    assert fila_d["nota"] == "Cupón"
    assert any("Portfolio Performance" in a for a in avisos)


def test_si_el_producto_no_esta_en_el_csv_lo_dice_claro():
    filas, errores = movcsv.lee(PP, producto={"id": "x", "nombre": "Amundi", "corto": "Amundi"})
    assert filas == []
    assert "no tiene movimientos" in errores[0]["motivo"]
    assert "Tesla Inc." in errores[0]["motivo"]      # pista de qué trae el fichero


def test_el_csv_de_pp_sin_filtro_trae_todos_los_activos():
    filas, errores = movcsv.lee(PP)
    assert errores == [] and len(filas) == 3


def test_el_csv_de_pp_con_un_tipo_raro_avisa_de_esa_fila():
    texto = PP.replace(";Compra;Bitcoin", ";Traspaso raro;Bitcoin")
    filas, errores = movcsv.lee(texto)
    assert len(filas) == 2
    assert len(errores) == 1 and "no reconocido" in errores[0]["motivo"]


def test_el_csv_normal_de_siete_columnas_sigue_funcionando():
    """Regresión: el formato de casa no se ha tocado."""
    filas, errores = movcsv.lee(TRES)
    assert errores == [] and len(filas) == 3


# ----------------------------------- el CSV de PP con una fecha que no va en ISO
def test_pp_con_una_fecha_reescrita_no_se_adivina_el_orden():
    """«3/12/2026» en un CSV de PP: no se lee como diciembre (daría fecha futura)."""
    texto = PP.replace("2026-03-12 00:00:00", "3/12/2026")
    filas, errores = movcsv.lee(texto, producto=TESLA)
    assert [f["fecha"] for f in filas] == ["2026-10-05"]      # la buena sí entra
    assert len(errores) == 1 and errores[0]["linea"] == 3
    assert "ISO" in errores[0]["motivo"]


def test_pp_respeta_las_fechas_iso_con_cualquier_formato_elegido():
    for fmt in (None, "auto", "dmy", "mdy", "iso"):
        filas, errores = movcsv.lee(PP, formato=fmt, producto=TESLA)
        assert errores == [], (fmt, errores)
        assert [f["fecha"] for f in filas] == ["2026-03-12", "2026-10-05"], fmt


def test_pp_sin_match_avisa_y_dice_que_trae():
    """`sin_match` es lo que la previsualización usa para ofrecer elegir destino."""
    filas, errores = movcsv.lee(PP, producto={"id": "x", "nombre": "Naranja 2040 PP"})
    assert filas == []
    assert errores[0].get("sin_match") is True
    assert errores[0]["activos"] == ["Bitcoin", "Tesla Inc."]
    assert "Naranja 2040 PP" in errores[0]["motivo"]


def test_es_pp_distingue_los_dos_formatos():
    assert movcsv.es_pp(PP) is True
    assert movcsv.es_pp(TRES) is False


# --------------------------------------------------- importar en una CUENTA
def _cartera_con_cuenta():
    cfg = _cartera()
    almacen.guarda_cuenta(cfg, {"nombre": "Cuenta Banco", "tipo": "banco", "moneda": "EUR"})
    cta = next(c for c in cfg["cuentas"] if c["nombre"] == "Cuenta Banco")
    return cfg, cta


def test_la_plantilla_de_cuenta_trae_tipos_de_cuenta():
    texto = movcsv.plantilla("cuenta")
    lineas = [l for l in texto.strip().split("\n") if l.strip()]
    assert lineas[0] == ",".join(movcsv.COLUMNAS)
    filas, errores = movcsv.lee(texto)
    assert errores == []
    assert [f["tipo"] for f in filas] == ["deposito", "interes", "retirada"]
    assert all(f["unidades"] is None for f in filas)   # una cuenta no tiene unidades


def test_una_cuenta_suma_y_resta_en_el_saldo():
    cfg, cta = _cartera_con_cuenta()
    texto = _csv("2026-10-01,deposito,,1000.00,0,0,Entrada",
                 "2026-10-02,retirada,,200.00,0,0,Salida",
                 "2026-10-03,interes,,12.35,0,1.85,Intereses")
    filas, errores = movcsv.lee(texto)
    hechos, fallos = s._aplica_movs_cuenta(cfg, cta, filas, [], "EUR")
    assert fallos == [] and len(hechos) == 3
    assert all(m["cuenta"] == cta["id"] for m in hechos)
    assert all("producto" not in m for m in hechos)     # no son de producto
    ef = almacen.producto_efectivo_de(cfg, cta["id"])
    vals = {v["fecha"]: v["valor"] for v in cfg["valoraciones"] if v["producto"] == ef["id"]}
    assert vals["2026-10-01"] == pytest.approx(1000.00, abs=0.01)
    assert vals["2026-10-02"] == pytest.approx(800.00, abs=0.01)
    assert vals["2026-10-03"] == pytest.approx(812.35, abs=0.01)


def test_compra_y_venta_se_rechazan_en_una_cuenta():
    cfg, cta = _cartera_con_cuenta()
    filas, _ = movcsv.lee(_csv("2026-10-01,compra,10,1000.00,0,0,Compra",
                               "2026-10-02,venta,5,500.00,0,0,Venta",
                               "2026-10-03,deposito,,50.00,0,0,Buena"))
    hechos, fallos = s._aplica_movs_cuenta(cfg, cta, filas, [], "EUR")
    assert len(hechos) == 1 and hechos[0]["tipo"] == "deposito"
    assert [f["linea"] for f in fallos] == [2, 3]
    assert "movimientos de producto" in fallos[0]["motivo"]
    assert "ficha del producto" in fallos[0]["motivo"]


def test_transferencia_y_cambio_divisa_se_rechazan_con_su_motivo():
    cfg, cta = _cartera_con_cuenta()
    filas, _ = movcsv.lee(_csv("2026-10-01,transferencia,,100.00,0,0,x",
                               "2026-10-02,cambio_divisa,,100.00,0,0,y"))
    hechos, fallos = s._aplica_movs_cuenta(cfg, cta, filas, [], "EUR")
    assert hechos == [] and len(fallos) == 2
    assert "contrapartida" in fallos[0]["motivo"]


def test_unidades_en_una_cuenta_se_rechazan_con_mensaje_claro():
    cfg, cta = _cartera_con_cuenta()
    filas, _ = movcsv.lee(_csv("2026-10-01,deposito,10,1000.00,0,0,con unidades"))
    hechos, fallos = s._aplica_movs_cuenta(cfg, cta, filas, [], "EUR")
    assert hechos == []
    assert "no tiene unidades" in fallos[0]["motivo"]


def test_otros_tipos_no_valen_en_una_cuenta():
    cfg, cta = _cartera_con_cuenta()
    filas, _ = movcsv.lee(_csv("2026-10-01,dividendo,,10.00,0,0,div"))
    hechos, fallos = s._aplica_movs_cuenta(cfg, cta, filas, [], "EUR")
    assert hechos == []
    assert "no es un movimiento de cuenta" in fallos[0]["motivo"]


def test_importar_en_una_cuenta_no_toca_ningun_producto():
    cfg, cta = _cartera_con_cuenta()
    p = almacen.guarda_producto(cfg, {"nombre": "Otro", "tipo": "fondo",
                                      "fuente": "manual", "moneda": "EUR"})[0]
    antes = list(cfg["movimientos"])
    filas, _ = movcsv.lee(_csv("2026-10-01,deposito,,100.00,0,0,x"))
    s._aplica_movs_cuenta(cfg, cta, filas, [], "EUR")
    assert [m["id"] for m in antes] == [m["id"] for m in cfg["movimientos"][:len(antes)]]
    assert not [m for m in cfg["movimientos"] if m.get("producto") == p["id"]]


# ------------------------------------------------------- las rutas de cuenta
@pytest.fixture
def cliente_cuenta(monkeypatch):
    cfg, cta = _cartera_con_cuenta()
    ruta = os.path.join(s.DATOS, "cartera.json")
    previo = open(ruta, encoding="utf-8").read() if os.path.exists(ruta) else None
    almacen.guarda(ruta, cfg)
    monkeypatch.setattr(s, "modo", lambda: "propio")
    monkeypatch.setattr(s, "recalcula", lambda descargar: {"avisos": []})
    c = s.app.test_client()
    c.cuenta_id = cta["id"]
    yield c
    if previo is None:
        os.remove(ruta)
    else:
        open(ruta, "w", encoding="utf-8").write(previo)


def test_la_plantilla_de_cuenta_se_descarga(cliente_cuenta):
    r = cliente_cuenta.get("/api/movimientos/plantilla.csv?para=cuenta")
    assert r.status_code == 200
    assert "deposito" in r.get_data(as_text=True)


def test_ruta_importar_en_una_cuenta(cliente_cuenta):
    cid = cliente_cuenta.cuenta_id
    r = cliente_cuenta.post(f"/api/cuentas/{cid}/movimientos/csv/importar",
                            json={"texto": _csv("2026-10-01,deposito,,100.00,0,0,x")})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["informe"]["anadidos"] == 1
    cfg = almacen.carga(os.path.join(s.DATOS, "cartera.json"))
    movs = [m for m in cfg["movimientos"] if m.get("cuenta") == cid]
    assert len(movs) == 1 and "producto" not in movs[0]


def test_ruta_previsualizar_en_una_cuenta_no_toca_nada(cliente_cuenta):
    cid = cliente_cuenta.cuenta_id
    r = cliente_cuenta.post(f"/api/cuentas/{cid}/movimientos/csv/previsualizar",
                            json={"texto": _csv("2026-10-01,compra,10,100,0,0,x",
                                                "2026-10-02,deposito,,50,0,0,y")})
    j = r.get_json()
    assert r.status_code == 200 and j["validos"] == 1 and j["errores_totales"] == 1
    assert "movimientos de producto" in j["errores"][0]["motivo"]
    cfg = almacen.carga(os.path.join(s.DATOS, "cartera.json"))
    assert [m for m in cfg["movimientos"] if m.get("cuenta") == cid] == []
