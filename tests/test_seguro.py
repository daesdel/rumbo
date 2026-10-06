# -*- coding: utf-8 -*-
"""
test_seguro.py  ·  Copias de seguridad cifradas con contraseña
==============================================================
El envoltorio JSON, la frase correcta, la incorrecta y los archivos tocados:
ninguna de estas rutas puede romper la app ni dejar datos en claro.
"""
import json

import pytest

from app import seguro


def _datos():
    return b'{"productos": [{"nombre": "Oro"}], "movimientos": []}'


def test_cifra_y_descifra_con_la_misma_frase():
    env = seguro.cifra(_datos(), "una frase cualquiera")
    assert seguro.es_cifrada(env)
    env_json = json.loads(env)
    assert env_json["formato"] == "rumbo-copia"
    assert env_json["kdf"] == "pbkdf2_sha256"
    assert env_json["iteraciones"] == seguro.ITERACIONES
    # el contenido no aparece ni por asomo en el archivo
    assert b"Oro" not in env and b"productos" not in env
    assert seguro.descifra(env, "una frase cualquiera") == _datos()


def test_frase_distinta_no_abre_la_copia():
    env = seguro.cifra(_datos(), "correcta")
    with pytest.raises(seguro.ErrorSeguro) as e:
        seguro.descifra(env, "otra")
    assert "frase de paso" in str(e.value)


def test_frase_vacia_no_cifra():
    with pytest.raises(seguro.ErrorSeguro):
        seguro.cifra(_datos(), "   ")


def test_un_json_normal_no_parece_cifrada():
    assert not seguro.es_cifrada(b'{"productos": [], "movimientos": []}')
    assert not seguro.es_cifrada(b"esto no es ni json")
    with pytest.raises(seguro.ErrorSeguro):
        seguro.descifra(b'{"productos": []}', "la que sea")


def test_archivo_tocado_no_tira_de_la_cpu_ni_da_excepciones_raras():
    env = json.loads(seguro.cifra(_datos(), "frase"))
    env["iteraciones"] = 10 ** 9                       # nadie manda la CPU de tu equipo
    with pytest.raises(seguro.ErrorSeguro):
        seguro.descifra(json.dumps(env).encode("utf-8"), "frase")

    env = json.loads(seguro.cifra(_datos(), "frase"))
    env["cifrado"] = "~~~~no-es-un-token~~~~"
    with pytest.raises(seguro.ErrorSeguro):
        seguro.descifra(json.dumps(env).encode("utf-8"), "frase")

    env = json.loads(seguro.cifra(_datos(), "frase"))
    env["kdf"] = "quantum"
    with pytest.raises(seguro.ErrorSeguro):
        seguro.descifra(json.dumps(env).encode("utf-8"), "frase")


def test_acepta_una_frase_con_espacios_de_mas_por_teclado():
    """Se recortan los espacios al principio y al final en las dos direcciones."""
    env = seguro.cifra(_datos(), "  mi frase  ")
    assert seguro.descifra(env, "mi frase") == _datos()
