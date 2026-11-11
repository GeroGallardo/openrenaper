"""Proveedores falsos: las pruebas nunca consultan sitios reales."""

import asyncio
from datetime import UTC, datetime

from app.consultas.modelos import DatosPersona
from app.identificadores import Identificador, TipoIdentificador

MOMENTO = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
TODOS = frozenset(TipoIdentificador)


class ProveedorFalso:
    """Devuelve registros fijos, lanza un error o demora más que el límite."""

    def __init__(
        self,
        nombre: str = "fuente-a",
        registros: list[DatosPersona] | None = None,
        *,
        error: Exception | None = None,
        demora: float = 0,
        tipos: frozenset[TipoIdentificador] = TODOS,
    ) -> None:
        self.nombre = nombre
        self.tipos = tipos
        self.registros = registros or []
        self.error = error
        self.demora = demora
        self.consultas: list[Identificador] = []
        self.iniciado = False
        self.cerrado = False

    async def consultar(self, identificador: Identificador) -> list[DatosPersona]:
        self.consultas.append(identificador)
        if self.demora:
            await asyncio.sleep(self.demora)
        if self.error is not None:
            raise self.error
        return list(self.registros)

    async def iniciar(self) -> None:
        self.iniciado = True

    async def cerrar(self) -> None:
        self.cerrado = True
