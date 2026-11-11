"""Recursos compartidos por los routers y su ciclo de vida.

Los proveedores de scraping se registran en `proveedores_predeterminados`. Las
pruebas pasan sus propias implementaciones a `crear_app`.
"""

import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI

from app.config import Configuracion
from app.consultas.proveedores import ProveedorConsulta, RecursoGestionado
from app.consultas.servicio import ConsultaService

logger = logging.getLogger(__name__)


def proveedores_predeterminados(configuracion: Configuracion) -> list[ProveedorConsulta]:
    """Proveedores reales; se agregan aquí a medida que se integran.

    Construirlos no abre conexiones: el navegador y los clientes se inician en
    `ciclo_de_vida`.
    """
    proveedores: list[ProveedorConsulta] = []
    if configuracion.pag_web1.habilitado and configuracion.pag_web1.url:
        from app.proveedores.pag_web1.proveedor import ProveedorPagWeb1

        proveedores.append(
            ProveedorPagWeb1(
                configuracion.pag_web1,
                tiempo_maximo=configuracion.tiempo_limite_proveedor,
            )
        )
    if configuracion.pag_web2.habilitado and configuracion.pag_web2.url:
        from app.proveedores.pag_web2.proveedor import ProveedorPagWeb2

        proveedores.append(
            ProveedorPagWeb2(
                configuracion.pag_web2,
                tiempo_maximo=configuracion.tiempo_limite_proveedor,
            )
        )
    return proveedores


@dataclass(frozen=True, slots=True)
class Recursos:
    configuracion: Configuracion
    proveedores: tuple[ProveedorConsulta, ...]
    consultas: ConsultaService

    @classmethod
    def crear(
        cls,
        configuracion: Configuracion,
        proveedores: Sequence[ProveedorConsulta],
    ) -> "Recursos":
        return cls(
            configuracion=configuracion,
            proveedores=tuple(proveedores),
            consultas=ConsultaService(
                proveedores, tiempo_limite=configuracion.tiempo_limite_proveedor
            ),
        )

    def gestionados(self) -> list[RecursoGestionado]:
        candidatos = [*self.proveedores]
        return [r for r in candidatos if isinstance(r, RecursoGestionado)]


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI) -> AsyncIterator[None]:
    """Inicia los recursos al arrancar y cierra los iniciados, en orden inverso."""
    recursos: Recursos = app.state.recursos
    iniciados: list[RecursoGestionado] = []
    try:
        for recurso in recursos.gestionados():
            await recurso.iniciar()
            iniciados.append(recurso)
        yield
    finally:
        for recurso in reversed(iniciados):
            try:
                await recurso.cerrar()
            except Exception:
                logger.exception("No se pudo cerrar %r", recurso)
