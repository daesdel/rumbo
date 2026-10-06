# -*- coding: utf-8 -*-
"""
seguro.py  ·  Copias de seguridad cifradas con contraseña
==========================================================
La copia descargada sigue siendo un archivo JSON legible, pero si eliges
contraseña su contenido va cifrado con Fernet y una clave derivada de la frase
de paso con PBKDF2-SHA256 (sal aleatoria de 16 bytes y 390.000 iteraciones).
La frase no se guarda en ningún sitio: si la pierdes, la copia no se puede
leer. No protege con la app abierta (entonces los datos tienen que estar en
claro para funcionar), solo el archivo quieto en tu nube, tu USB o tu disco.
"""

import base64
import hashlib
import json
import os

FORMATO = "rumbo-copia"
VERSION = 1
KDF = "pbkdf2_sha256"
ITERACIONES = 390_000
ITER_MIN, ITER_MAX = 10_000, 2_000_000   # tope por si el archivo lo manda otro
SAL_TAM = 16


class ErrorSeguro(Exception):
    """La frase no es la correcta, falta la librería o el archivo está dañado."""


def _fernet(clave):
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        raise ErrorSeguro("Esta app no tiene la librería de cifrado: "
                          "instala «cryptography» (pip install cryptography).")
    return Fernet(clave)


def _deriva(frase, sal, iteraciones):
    bruta = hashlib.pbkdf2_hmac("sha256", frase.encode("utf-8"), sal, iteraciones, dklen=32)
    return base64.urlsafe_b64encode(bruta)


def es_cifrada(crudo):
    """¿Este archivo es una copia cifrada por esta app?"""
    if isinstance(crudo, str):
        crudo = crudo.encode("utf-8", "replace")
    try:
        env = json.loads(crudo.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        return False
    return isinstance(env, dict) and env.get("formato") == FORMATO


def cifra(datos, frase):
    """Copia en claro -> envoltorio JSON con el contenido cifrado."""
    frase = (frase or "").strip()
    if not frase:
        raise ErrorSeguro("La frase de paso no puede estar vacía.")
    sal = os.urandom(SAL_TAM)
    env = {
        "formato": FORMATO,
        "version": VERSION,
        "kdf": KDF,
        "iteraciones": ITERACIONES,
        "sal": base64.b64encode(sal).decode("ascii"),
        "cifrado": _fernet(_deriva(frase, sal, ITERACIONES)).encrypt(datos).decode("ascii"),
    }
    return json.dumps(env, ensure_ascii=False, indent=1).encode("utf-8")


def descifra(crudo, frase):
    """Envoltorio JSON -> copia en claro. Si la frase no es, ErrorSeguro."""
    if isinstance(crudo, str):
        crudo = crudo.encode("utf-8", "replace")
    try:
        env = json.loads(crudo.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        raise ErrorSeguro("Ese archivo no es una copia cifrada de esta app.")
    if not isinstance(env, dict) or env.get("formato") != FORMATO:
        raise ErrorSeguro("Ese archivo no es una copia cifrada de esta app.")
    if env.get("kdf") != KDF or env.get("version") != VERSION:
        raise ErrorSeguro("La copia usa un cifrado que esta app no entiende.")
    try:
        iteraciones = int(env["iteraciones"])
        sal = base64.b64decode(env["sal"], validate=True)
        texto = env["cifrado"].encode("ascii")
    except (KeyError, TypeError, ValueError):
        raise ErrorSeguro("El archivo de la copia está dañado.")
    if not (ITER_MIN <= iteraciones <= ITER_MAX) or len(sal) != SAL_TAM:
        raise ErrorSeguro("El archivo de la copia está dañado.")
    fn = _fernet(_deriva((frase or "").strip(), sal, iteraciones))   # falla aquí sin la librería
    from cryptography.fernet import InvalidToken
    try:
        return fn.decrypt(texto)
    except InvalidToken:
        raise ErrorSeguro("La frase de paso no es correcta (o la copia está dañada).")
