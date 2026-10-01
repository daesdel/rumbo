# -*- coding: utf-8 -*-
"""
test_exportar.py  ·  El panel exportado como web
=================================================
Dos promesas del README: con «ocultar importes» no se cuela ninguna cifra
absoluta, y el HTML de un solo archivo no se puede romper con datos maliciosos.
"""
import copy
from pathlib import Path

import pytest

from app import exportar

WEB = Path(__file__).resolve().parent.parent / "app" / "web"

DATOS = {
    "titular": "Prueba",
    "total": {"patrimonio": 12345.67, "aportado": 10000.0, "plusvalia": 2345.67,
              "hitos": [25000], "serie": [100.0, 200.0], "serieAportado": [50.0, 80.0]},
    "objetivo": {"activo": True, "importe": 50000, "etiqueta": "Próximo"},
    "productos": [{"id": "p1", "nombre": "Fondo", "valor": 10000.0, "aportado": 8000.0,
                   "flujos": [["2025-01-01", -8000.0]],
                   "snapshots": [["2025-01-01", 10000.0]],
                   "aportaciones": [{"fecha": "2025-01-01", "importe": 8000.0}]}],
    "vivo": {"titulos": 0.5, "coin": "bitcoin"},
}


def test_ocultar_importes_escala_con_un_factor_y_quita_lo_absoluto():
    out = exportar.sin_importes(copy.deepcopy(DATOS))
    k = out["total"]["patrimonio"] / DATOS["total"]["patrimonio"]
    assert 0.37 <= k <= 2.9

    # todos los importes escalan con EL MISMO factor (se conservan las proporciones)
    assert out["total"]["aportado"] == pytest.approx(10000.0 * k, abs=0.02)
    assert out["productos"][0]["valor"] == pytest.approx(10000.0 * k, abs=0.02)
    assert out["vivo"]["titulos"] == pytest.approx(0.5 * k, abs=1e-4)

    # las cifras absolutas que delatarían el patrimonio, fuera
    assert out["total"]["hitos"] == []
    assert out["objetivo"] is None
    assert out["productos"][0]["aportaciones"] == [] or \
        out["productos"][0]["aportaciones"][0].get("importe") in (None, pytest.approx(8000.0 * k, abs=0.02))

    # los textos y las fechas no se tocan
    assert out["titular"] == "Prueba"
    assert out["productos"][0]["nombre"] == "Fondo"


def test_pagina_exportada_es_un_solo_html_funcional():
    html = exportar.pagina(str(WEB), copy.deepcopy(DATOS), ocultar=False, titulo="Prueba")
    assert "window.DATOS" in html
    assert "window.ESTATICO = true" in html
    assert "<meta name=\"robots\" content=\"noindex, nofollow\">" in html
    assert "data:image/png;base64," in html          # el icono va dentro


def test_un_nombre_con_cierre_de_script_no_rompe_el_html():
    datos = copy.deepcopy(DATOS)
    datos["titular"] = "Tito </script><script>window.__xss=1</script>"
    html = exportar.pagina(str(WEB), datos, ocultar=False, titulo="Prueba")
    # el corte queda neutralizado dentro del JS: no hay un </script> suelto que
    # cierre el bloque y abra otro
    assert "</script><script>window.__xss=1" not in html
    assert "<\\/script><script>window.__xss=1" in html
