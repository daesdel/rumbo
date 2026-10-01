# -*- coding: utf-8 -*-
"""
test_web_escape.py  ·  Guardas del escapado HTML (XSS)
======================================================
No hay navegador en estos tests, así que se vigilan los propios ficheros: la
única definición del escapado vive en graficos.js, app.js y editor.js la usan,
y no queda ninguna interpolación de nombres de usuario sin escapar.
"""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "app" / "web"


def _lee(nombre):
    return (WEB / nombre).read_text(encoding="utf-8")


def test_escapar_se_define_una_sola_vez_en_graficos():
    g = _lee("graficos.js")
    assert "global.escapar = escapar" in g
    # y solo ahí: ni app.js ni editor.js traen su propia implementación
    impl = re.compile(r"String\(s == null.*&amp;", re.S)
    assert not impl.search(_lee("app.js"))
    assert not impl.search(_lee("editor.js"))


def test_app_y_editor_usan_la_version_comun():
    a, e = _lee("app.js"), _lee("editor.js")
    assert "const esc = window.escapar" in a
    assert "const esc = window.escapar" in e


def test_los_puntos_de_texto_de_usuario_estan_escapados():
    a = _lee("app.js")
    # filtros, chips, selector de productos, tabla del mes y tabla anual
    assert "${esc(p.corto || p.nombre)}" in a
    assert "${esc(x.corto || x.nombre)}" in a
    assert "${esc(r.producto)}" in a
    assert "${esc(p.corto)}" in a
    # avisos (llevan nombres de producto), pie, ficha y comparador
    assert "<span>${esc(a)}</span>" in a
    assert "${esc(c.nombre)}" in a
    assert "${esc(l.nombre)}" in a
    assert "${esc(p.nombre)}</h2>" in a
    assert "${esc(c[0])}" in a and "${esc(c[1])}" in a
    # ningún nombre de producto suelto en innerHTML
    assert not re.search(r"\$\{(?!esc\()[a-z]+\.corto", a)
    assert not re.search(r"\$\{(?!esc\()[a-z]+\.nombre\b", a)
    assert not re.search(r"\$\{r\.producto\b", a)


def test_los_tooltips_de_graficos_escapan():
    g = _lee("graficos.js")
    for patrono in ("${escapar(s.nombre)}", "${escapar(d.nombre)}",
                    "${escapar(o.s.nombre)}", "${escapar(cfg.overlay.nombre)}",
                    "${escapar(e.texto)}"):
        assert patrono in g, patrono
    # ningún nombre de serie suelto
    assert not re.search(r"\$\{(?!escapar\()[a-z]+\.nombre\}", g)


def test_color_solo_admite_hex():
    """El color entra en atributos style: si no es hex, no se usa."""
    a = _lee("app.js")
    assert '/^#[0-9a-fA-F]{3,8}$/' in a
