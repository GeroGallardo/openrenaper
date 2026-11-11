"""Obtención de contenido con transportes y navegadores falsos (sin red)."""

import asyncio

import httpx
import pytest
from playwright.async_api import Error as ErrorPlaywright
from playwright.async_api import TimeoutError as TiempoAgotadoPlaywright

from app.proveedores.errores import (
    AccesoRestringido,
    FormatoDesconocido,
    FuenteTemporalmenteCaida,
    TiempoAgotadoFuente,
)
from app.proveedores.obtencion import ObtenedorHttp, ObtenedorNavegador, verificar_estado

URL = "https://fuente.invalid/buscar?q=30111222"


@pytest.mark.parametrize("estado", [200, 204])
def test_estados_exitosos(estado: int) -> None:
    verificar_estado("fuente", estado)


@pytest.mark.parametrize(
    ("estado", "error"),
    [
        (403, AccesoRestringido),
        (451, AccesoRestringido),
        (429, FuenteTemporalmenteCaida),
        (500, FuenteTemporalmenteCaida),
        (503, FuenteTemporalmenteCaida),
        (404, FormatoDesconocido),
    ],
)
def test_estados_fallidos_se_clasifican(estado: int, error: type[Exception]) -> None:
    with pytest.raises(error):
        verificar_estado("fuente", estado)


# --- HTTP directo -----------------------------------------------------------


def obtener_http(manejador) -> object:
    async def ejecutar():
        obtenedor = ObtenedorHttp("fuente", transporte=httpx.MockTransport(manejador))
        await obtenedor.iniciar()
        try:
            return await obtenedor.obtener(URL, tiempo_limite=1)
        finally:
            await obtenedor.cerrar()

    return asyncio.run(ejecutar())


def test_http_devuelve_la_pagina() -> None:
    pagina = obtener_http(lambda request: httpx.Response(200, text="<html>ok</html>"))
    assert (pagina.estado_http, pagina.html) == (200, "<html>ok</html>")


def test_http_envia_un_agente_identificable_sin_credenciales() -> None:
    recibidas: list[httpx.Request] = []

    def manejador(request: httpx.Request) -> httpx.Response:
        recibidas.append(request)
        return httpx.Response(200, text="")

    obtener_http(manejador)
    [request] = recibidas
    assert request.headers["User-Agent"].startswith("OpenRENAPER/")
    assert "authorization" not in request.headers
    assert "cookie" not in request.headers


def test_http_timeout() -> None:
    def manejador(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("lento", request=request)

    with pytest.raises(TiempoAgotadoFuente):
        obtener_http(manejador)


def test_http_fallo_de_red() -> None:
    def manejador(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin red", request=request)

    with pytest.raises(FuenteTemporalmenteCaida):
        obtener_http(manejador)


def test_http_acceso_restringido() -> None:
    with pytest.raises(AccesoRestringido):
        obtener_http(lambda request: httpx.Response(403, text="captcha"))


def test_http_sin_iniciar_no_consulta() -> None:
    obtenedor = ObtenedorHttp("fuente")
    with pytest.raises(FuenteTemporalmenteCaida):
        asyncio.run(obtenedor.obtener(URL, tiempo_limite=1))


# --- Navegador ----------------------------------------------------------------


class RespuestaFalsa:
    def __init__(self, status: int) -> None:
        self.status = status


class PaginaFalsa:
    def __init__(self, *, status: int = 200, html: str = "<html/>", error=None) -> None:
        self.status = status
        self.html = html
        self.error = error
        self.url = URL
        self.cerrada = False

    async def goto(self, url: str, *, timeout: float, wait_until: str):
        if self.error is not None:
            raise self.error
        return RespuestaFalsa(self.status)

    async def content(self) -> str:
        return self.html

    async def close(self) -> None:
        self.cerrada = True


class ContextoFalso:
    def __init__(self, *, falla_al_cerrar: bool = False) -> None:
        self.cerrado = False
        self.falla_al_cerrar = falla_al_cerrar

    async def close(self) -> None:
        self.cerrado = True
        if self.falla_al_cerrar:
            raise ErrorPlaywright("cierre")


def obtener_navegador(pagina: PaginaFalsa, contexto: ContextoFalso | None = None):
    contexto = contexto or ContextoFalso()

    async def abrir():
        return contexto, pagina

    obtenedor = ObtenedorNavegador("fuente", abrir)
    return contexto, asyncio.run(obtenedor.obtener(URL, tiempo_limite=1))


def test_navegador_devuelve_html_y_cierra_recursos() -> None:
    pagina = PaginaFalsa(html="<html>resultado</html>")
    contexto, obtenida = obtener_navegador(pagina)
    assert obtenida.html == "<html>resultado</html>"
    assert pagina.cerrada and contexto.cerrado


@pytest.mark.parametrize("restringido", [False, True])
def test_espera_renderizado_antes_de_leer_y_libera_recursos(restringido: bool) -> None:
    pagina = PaginaFalsa(html="ofuscado")
    contexto = ContextoFalso()

    async def abrir():
        return contexto, pagina

    async def esperar(p, restante):
        assert 0 < restante <= 1
        assert p.html == "ofuscado"
        if restringido:
            raise AccesoRestringido("No habilitado", fuente="fuente")
        p.html = "nombre real"

    obtenedor = ObtenedorNavegador("fuente", abrir, esperar_contenido=esperar)
    if restringido:
        with pytest.raises(AccesoRestringido):
            asyncio.run(obtenedor.obtener(URL, tiempo_limite=1))
    else:
        assert asyncio.run(obtenedor.obtener(URL, tiempo_limite=1)).html == "nombre real"
    assert pagina.cerrada and contexto.cerrado


@pytest.mark.parametrize(
    ("pagina", "error"),
    [
        (PaginaFalsa(error=TiempoAgotadoPlaywright("lento")), TiempoAgotadoFuente),
        (PaginaFalsa(error=ErrorPlaywright("net::ERR")), FuenteTemporalmenteCaida),
        (PaginaFalsa(status=403), AccesoRestringido),
        (PaginaFalsa(status=503), FuenteTemporalmenteCaida),
    ],
)
def test_navegador_cierra_recursos_ante_errores(
    pagina: PaginaFalsa, error: type[Exception]
) -> None:
    contexto = ContextoFalso()

    async def abrir():
        return contexto, pagina

    with pytest.raises(error):
        asyncio.run(ObtenedorNavegador("fuente", abrir).obtener(URL, tiempo_limite=1))
    assert pagina.cerrada and contexto.cerrado


def test_fallo_al_cerrar_no_oculta_el_resultado() -> None:
    pagina = PaginaFalsa()
    contexto, obtenida = obtener_navegador(pagina, ContextoFalso(falla_al_cerrar=True))
    assert obtenida.estado_http == 200
    assert contexto.cerrado


def test_navegador_que_no_abre_es_fallo_transitorio() -> None:
    async def abrir():
        raise ErrorPlaywright("navegador cerrado")

    with pytest.raises(FuenteTemporalmenteCaida):
        asyncio.run(ObtenedorNavegador("fuente", abrir).obtener(URL, tiempo_limite=1))
