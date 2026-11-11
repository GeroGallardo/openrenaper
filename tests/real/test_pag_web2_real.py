"""Comprobación real contra pag_web2. No corre en CI ni con `pytest` a secas.

Ejecutar a mano con Chromium (predeterminado):

    uv run pytest -m real

El modo navegador requiere `uv run playwright install chromium` fuera de Docker.

Usa el CUIT del Banco Nación (persona jurídica), no de una
persona. Para probar un DNI propio, exportar OPENRENAPER_REAL_DNI: el número no
se imprime y los resultados solo se comparan por cantidad y estructura.
No guardar ni pegar en issues el HTML ni los datos obtenidos.
"""

import asyncio
import os
import unicodedata

import pytest

from app.config import ConfiguracionPagWeb2
from app.consultas.modelos import EstadoConsulta
from app.consultas.servicio import ConsultaService
from app.proveedores.pag_web2.proveedor import ProveedorPagWeb2

pytestmark = pytest.mark.real

CUIT_ORGANISMO_PUBLICO = "30500010912"  # Banco de la Nación Argentina


def consultar(tipo: str, numero: str):
    async def ejecutar():
        proveedor = ProveedorPagWeb2(ConfiguracionPagWeb2.desde_entorno())
        await proveedor.iniciar()
        try:
            return await ConsultaService([proveedor], tiempo_limite=45).consultar(tipo, numero)
        finally:
            await proveedor.cerrar()

    return asyncio.run(ejecutar())


def test_cuit_de_organismo_publico() -> None:
    respuesta = consultar("cuit", CUIT_ORGANISMO_PUBLICO)
    assert respuesta.estado is EstadoConsulta.ENCONTRADO
    [resultado, *_] = respuesta.resultados
    assert resultado.datos.cuit_cuil == CUIT_ORGANISMO_PUBLICO
    nombre = unicodedata.normalize("NFKD", resultado.datos.nombre or "")
    nombre = "".join(c for c in nombre if not unicodedata.combining(c)).upper()
    assert {"BANCO", "NACION", "ARGENTINA"} <= set(nombre.split())


@pytest.mark.skipif("OPENRENAPER_REAL_DNI" not in os.environ, reason="sin DNI de prueba")
def test_dni_propio() -> None:
    respuesta = consultar("dni", os.environ["OPENRENAPER_REAL_DNI"])
    assert respuesta.estado in set(EstadoConsulta)
    for resultado in respuesta.resultados:
        assert resultado.fuente == "pag_web2"
        assert resultado.datos.cuit_cuil is not None
        assert resultado.datos.cuit_cuil[2:10] == os.environ["OPENRENAPER_REAL_DNI"].zfill(8)
        assert resultado.datos.dni is None
