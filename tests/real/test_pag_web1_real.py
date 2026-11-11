"""Prueba manual real con institución pública; excluida de las pruebas habituales."""

import asyncio
import unicodedata

import pytest

from app.config import Configuracion
from app.consultas.servicio import ConsultaService
from app.recursos import proveedores_predeterminados

pytestmark = pytest.mark.real
CUIT_BANCO_NACION = "30500010912"


def test_primera_fuente_devuelve_el_cuit_y_nombre_del_banco_nacion() -> None:
    async def ejecutar():
        proveedores = proveedores_predeterminados(Configuracion.desde_entorno())
        try:
            for proveedor in proveedores:
                await proveedor.iniciar()
            respuesta = await ConsultaService(proveedores, tiempo_limite=45).consultar(
                "cuit", CUIT_BANCO_NACION
            )
        finally:
            for proveedor in reversed(proveedores):
                await proveedor.cerrar()
        assert len(respuesta.resultados) == 1
        assert respuesta.resultados[0].fuente in {"pag_web2", "pag_web1"}
        assert {r.candidato for r in respuesta.resultados} == {1}
        assert not respuesta.advertencias
        for resultado in respuesta.resultados:
            assert resultado.datos.cuit_cuil == CUIT_BANCO_NACION
            nombre = unicodedata.normalize("NFKD", resultado.datos.nombre or "")
            nombre = "".join(c for c in nombre if not unicodedata.combining(c)).upper()
            assert {"BANCO", "NACION", "ARGENTINA"} <= set(nombre.split())

    asyncio.run(ejecutar())
