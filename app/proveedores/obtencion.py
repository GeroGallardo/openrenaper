"""Obtención de contenido: HTTP directo o navegador, con fallos clasificados.

El navegador puede esperar el renderizado específico de una fuente.
Los fallos se clasifican por tipo de excepción y por código HTTP; nunca por
el texto de un mensaje. Los logs no incluyen URL, HTML ni identificadores.
"""

from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Any, Protocol

import httpx
from playwright.async_api import Error as ErrorPlaywright
from playwright.async_api import TimeoutError as TiempoAgotadoPlaywright

from app.proveedores.errores import (
    AccesoRestringido,
    FormatoDesconocido,
    FuenteTemporalmenteCaida,
    TiempoAgotadoFuente,
)
from app.proveedores.resultados import PaginaObtenida

AGENTE_HTTP = "OpenRENAPER/0.1 (proyecto academico; +https://github.com/GeroGallardo/openrenaper)"

_ACCESO_RESTRINGIDO = frozenset({401, 403, 407, 451})
_TRANSITORIOS = frozenset({408, 425, 429})


class ObtenedorContenido(Protocol):
    async def obtener(self, url: str, *, tiempo_limite: float) -> PaginaObtenida: ...


def verificar_estado(fuente: str, estado_http: int) -> None:
    """Lanza el fallo que corresponde a un código HTTP distinto de 2xx."""
    if 200 <= estado_http < 300:
        return
    if estado_http in _ACCESO_RESTRINGIDO:
        raise AccesoRestringido(f"{fuente} rechazó el acceso (HTTP {estado_http}).", fuente=fuente)
    if estado_http in _TRANSITORIOS or estado_http >= 500:
        raise FuenteTemporalmenteCaida(
            f"{fuente} no está disponible (HTTP {estado_http}).", fuente=fuente
        )
    raise FormatoDesconocido(
        f"{fuente} respondió HTTP {estado_http}, que no corresponde a una búsqueda.",
        fuente=fuente,
    )


class ObtenedorHttp:
    """Descarga con un cliente HTTP compartido. Se inicia y cierra explícitamente."""

    def __init__(self, fuente: str, *, transporte: httpx.AsyncBaseTransport | None = None) -> None:
        self._fuente = fuente
        self._transporte = transporte
        self._cliente: httpx.AsyncClient | None = None

    async def iniciar(self) -> None:
        if self._cliente is None:
            self._cliente = httpx.AsyncClient(
                transport=self._transporte,
                follow_redirects=True,
                headers={"User-Agent": AGENTE_HTTP, "Accept-Language": "es-AR,es;q=0.9"},
            )

    async def cerrar(self) -> None:
        cliente, self._cliente = self._cliente, None
        if cliente is not None:
            await cliente.aclose()

    async def obtener(self, url: str, *, tiempo_limite: float) -> PaginaObtenida:
        if self._cliente is None:
            raise FuenteTemporalmenteCaida(
                f"El cliente HTTP de {self._fuente} no está iniciado.", fuente=self._fuente
            )
        try:
            respuesta = await self._cliente.get(url, timeout=tiempo_limite)
        except httpx.TimeoutException:
            raise TiempoAgotadoFuente(
                f"{self._fuente} no respondió a tiempo.", fuente=self._fuente
            ) from None
        except httpx.TransportError:
            raise FuenteTemporalmenteCaida(
                f"No se pudo conectar con {self._fuente}.", fuente=self._fuente
            ) from None
        verificar_estado(self._fuente, respuesta.status_code)
        return PaginaObtenida(
            url=str(respuesta.url), estado_http=respuesta.status_code, html=respuesta.text
        )


# Abre un contexto aislado del navegador y devuelve (contexto, página).
AbrirPagina = Callable[[], Awaitable[tuple[Any, Any]]]
EsperarContenido = Callable[[Any, float], Awaitable[None]]


class ObtenedorNavegador:
    """Descarga con una página nueva por consulta, en un contexto aislado.

    La página y el contexto se cierran siempre, también cuando la consulta falla.
    La administración del navegador (inicio, cierre, concurrencia) queda fuera.
    """

    def __init__(
        self,
        fuente: str,
        abrir_pagina: AbrirPagina,
        *,
        esperar_contenido: EsperarContenido | None = None,
    ) -> None:
        self._fuente = fuente
        self._abrir_pagina = abrir_pagina
        self._esperar_contenido = esperar_contenido

    async def obtener(self, url: str, *, tiempo_limite: float) -> PaginaObtenida:
        try:
            contexto, pagina = await self._abrir_pagina()
        except ErrorPlaywright:
            raise FuenteTemporalmenteCaida(
                f"No se pudo abrir el navegador para {self._fuente}.", fuente=self._fuente
            ) from None
        try:
            return await self._navegar(pagina, url, tiempo_limite)
        finally:
            await _cerrar_silencioso(pagina)
            await _cerrar_silencioso(contexto)

    async def _navegar(self, pagina: Any, url: str, tiempo_limite: float) -> PaginaObtenida:
        vencimiento = monotonic() + tiempo_limite
        try:
            respuesta = await pagina.goto(
                url, timeout=tiempo_limite * 1000, wait_until="domcontentloaded"
            )
            if respuesta is None:
                raise FuenteTemporalmenteCaida(
                    f"{self._fuente} no devolvió respuesta.", fuente=self._fuente
                )
            verificar_estado(self._fuente, respuesta.status)
            if self._esperar_contenido is not None:
                restante = vencimiento - monotonic()
                if restante <= 0:
                    raise TiempoAgotadoPlaywright("Plazo de navegación agotado")
                await self._esperar_contenido(pagina, restante)
            html = await pagina.content()
        except TiempoAgotadoPlaywright:
            raise TiempoAgotadoFuente(
                f"{self._fuente} no respondió a tiempo.", fuente=self._fuente
            ) from None
        except ErrorPlaywright:
            raise FuenteTemporalmenteCaida(
                f"El navegador no pudo cargar {self._fuente}.", fuente=self._fuente
            ) from None
        return PaginaObtenida(url=pagina.url, estado_http=respuesta.status, html=html)


async def _cerrar_silencioso(recurso: Any) -> None:
    """Cierra sin ocultar el error original de la consulta."""
    try:
        await recurso.close()
    except Exception:  # noqa: BLE001 - un fallo al cerrar no reemplaza al de la consulta
        pass
