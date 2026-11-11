"""Un Chromium por proceso, compartido por las consultas de ese proceso.

Interfaz para la aplicación:

- `iniciar()`: lanza Playwright y Chromium. Idempotente.
- `cerrar()`: deja de aceptar consultas, espera a que terminen las activas
  (hasta `espera_cierre` segundos) y recién entonces cierra el navegador.
- `consulta()`: contexto que marca una consulta como activa.
- `abrir_pagina()`: contexto de navegador aislado y página nuevos para una
  consulta; quien los usa debe cerrarlos (ver `ObtenedorNavegador`).

Un navegador conectado nunca se cierra ni se reinicia con consultas activas.
Solo se relanza si se desconectó (por ejemplo, si el proceso de Chromium murió).
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from app.proveedores.errores import FuenteTemporalmenteCaida

logger = logging.getLogger(__name__)

# Devuelve (playwright, navegador). Reemplazable en pruebas.
Lanzador = Callable[[], Awaitable[tuple[Any, Any]]]

# --disable-dev-shm-usage evita fallos por /dev/shm reducido dentro de Docker.
ARGUMENTOS_CHROMIUM = ("--disable-dev-shm-usage",)


async def lanzar_chromium() -> tuple[Any, Any]:
    from playwright.async_api import async_playwright

    playwright = await async_playwright().start()
    try:
        navegador = await playwright.chromium.launch(headless=True, args=list(ARGUMENTOS_CHROMIUM))
    except BaseException:
        await playwright.stop()
        raise
    return playwright, navegador


class NavegadorCompartido:
    def __init__(
        self, fuente: str, *, lanzar: Lanzador = lanzar_chromium, espera_cierre: float = 30.0
    ) -> None:
        self._fuente = fuente
        self._lanzar = lanzar
        self._espera_cierre = espera_cierre
        self._playwright: Any = None
        self._navegador: Any = None
        self._bloqueo = asyncio.Lock()
        self._activas = 0
        self._sin_activas = asyncio.Event()
        self._sin_activas.set()
        self._cerrando = False

    @property
    def activas(self) -> int:
        return self._activas

    async def iniciar(self) -> None:
        async with self._bloqueo:
            self._cerrando = False
            if self._navegador is None:
                self._playwright, self._navegador = await self._lanzar()

    async def cerrar(self) -> None:
        self._cerrando = True
        try:
            await asyncio.wait_for(self._sin_activas.wait(), timeout=self._espera_cierre)
        except TimeoutError:
            logger.warning(
                "Se cierra el navegador de %s con %d consultas activas tras esperar %.0f s",
                self._fuente,
                self._activas,
                self._espera_cierre,
            )
        async with self._bloqueo:
            await self._detener()

    @asynccontextmanager
    async def consulta(self) -> AsyncIterator[None]:
        if self._cerrando:
            raise FuenteTemporalmenteCaida(
                f"El navegador de {self._fuente} se está cerrando.", fuente=self._fuente
            )
        self._activas += 1
        self._sin_activas.clear()
        try:
            yield
        finally:
            self._activas -= 1
            if self._activas == 0:
                self._sin_activas.set()

    async def abrir_pagina(self) -> tuple[Any, Any]:
        navegador = await self._navegador_conectado()
        contexto = await navegador.new_context(locale="es-AR")
        try:
            pagina = await contexto.new_page()
        except BaseException:
            await contexto.close()
            raise
        return contexto, pagina

    async def _navegador_conectado(self) -> Any:
        async with self._bloqueo:
            if self._cerrando or self._navegador is None:
                raise FuenteTemporalmenteCaida(
                    f"El navegador de {self._fuente} no está iniciado.", fuente=self._fuente
                )
            if not self._navegador.is_connected():
                # Desconectado: no tiene páginas vivas que interrumpir.
                logger.warning("Se relanza el navegador de %s (desconectado)", self._fuente)
                await self._detener()
                self._playwright, self._navegador = await self._lanzar()
            return self._navegador

    async def _detener(self) -> None:
        navegador, self._navegador = self._navegador, None
        playwright, self._playwright = self._playwright, None
        for recurso, cerrar in ((navegador, "close"), (playwright, "stop")):
            if recurso is None:
                continue
            try:
                await getattr(recurso, cerrar)()
            except Exception:
                logger.exception("No se pudo cerrar un recurso del navegador de %s", self._fuente)
