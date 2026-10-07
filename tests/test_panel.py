# -*- coding: utf-8 -*-
"""
test_panel.py  ·  El pegamento entre el HTML y el JS
====================================================
El panel es HTML + JS sin compilación: si un id deja de existir (o se escribe
distinto en un sitio y en otro), el gráfico simplemente no sale y no hay test
que lo cace. Aquí se comprueba esa unión: cada `$("#algo")` del JS tiene que
existir como id en el HTML o crearse en una plantilla del propio JS.
"""
import os
import re

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(RAIZ, "app", "web")
JS = ["app.js", "editor.js", "graficos.js", "canal.js"]


def _lee(nombre):
    with open(os.path.join(WEB, nombre), "r", encoding="utf-8") as f:
        return f.read()


def _ids_usados(fuente):
    """Ids que el JS busca de verdad: $(«#id»), sin construcciones dinámicas."""
    return set(re.findall(r"""\$\(\s*["']#([A-Za-z0-9_-]+)["']\s*\)""", fuente))


def _ids_declarados(fuente):
    """Ids que existen: en el HTML o dentro de las plantillas del JS."""
    return set(re.findall(r"""\bid=["']([A-Za-z0-9_-]+)["']""", fuente))


def test_todos_los_ids_que_usa_el_js_existen():
    declarados = _ids_declarados(_lee("index.html"))
    usados = set()
    for n in JS:
        fuente = _lee(n)
        declarados |= _ids_declarados(fuente)      # los que crea el propio JS
        usados |= _ids_usados(fuente)
    faltan = sorted(usados - declarados)
    assert not faltan, "El JS busca ids que no existen en ninguna parte: " + ", ".join(faltan)


def test_los_graficos_de_cada_pestana_tienen_su_sitio():
    """Los contenedores de los gráficos y los mandos de zoom tienen que existir:
    en el HTML fijo o en la plantilla que los crea (la ficha de un producto se
    monta desde el JS)."""
    en_html = ["grafPrincipal", "segRango", "grafMesDia", "grafMesHist",
               "grafPeriodo", "grafAnual", "segRangoAnual", "grafComparacion",
               "segRangoCompara", "grafComparador", "segRangoComp"]
    en_plantilla = ["grafFondo", "segRangoFondo"]
    html = _lee("index.html")
    fuente_js = "\n".join(_lee(n) for n in JS)
    for ident in en_html:
        assert f'id="{ident}"' in html, f"falta #{ident} en index.html"
    for ident in en_plantilla:
        assert f'id="{ident}"' in fuente_js, f"falta #{ident} en la plantilla del JS"


def test_el_zoom_no_se_recuerda_entre_secciones():
    """El zoom de los gráficos es de la visita, no del usuario: se reinicia al
    entrar en cada sección (y el rango del periodo libre de «Periodo», en
    cambio, sí se guarda: ese es el periodo que el usuario elige)."""
    app = _lee("app.js")
    assert "function reiniciaZoom()" in app
    assert "reiniciaZoom();" in app.split("function irA(tab)", 1)[1][:600], \
        "irA() tiene que reiniciar el zoom de los gráficos al cambiar de sección"
    # El zoom nunca se guarda en localStorage (el periodo de la pestaña Periodo sí).
    for k in ["patrimonio.rango", "patrimonio.rangoFondo", "patrimonio.rangoAnual",
              "patrimonio.rangoCompara", "patrimonio.rangoComp"]:
        assert k not in app, f"{k} no debe guardarse: el zoom no se recuerda"
