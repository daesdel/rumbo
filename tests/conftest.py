# -*- coding: utf-8 -*-
"""
conftest.py  ·  Aislamiento de los tests
==========================================
Antes de importar cualquier módulo de la app: el servidor lee PATRIMONIO_DATOS
al arrancar, y los tests NUNCA deben tocar mis_datos reales. Siempre van a un
temporal.
"""
import os
import tempfile

os.environ["PATRIMONIO_DATOS"] = tempfile.mkdtemp(prefix="rumbo_tests_")
