"""La admisión limita trabajo real, no confía en cabeceras de clientes y siempre libera cupos."""

import asyncio
from unittest.mock import Mock

import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.api.limites import ControlSolicitudes, LimiteSolicitudesMiddleware
from app.config import Configuracion, ConfiguracionLimites
from app.main import crear_app


def control(**opciones):
    reloj = Mock(return_value=100.0)
    return ControlSolicitudes(ConfiguracionLimites(**opciones), reloj=reloj), reloj


def test_ip_ventana_deslizante_y_retry_after() -> None:
    limite, reloj = control(por_ip=2, total=10)
    assert limite.admitir("a") is None
    limite.terminar()
    reloj.return_value = 110.0
    assert limite.admitir("a") is None
    limite.terminar()
    reloj.return_value = 120.0
    rechazo = limite.admitir("a")
    assert rechazo.motivo == "ip"
    assert rechazo.reintentar_en == 40
    assert limite.admitir("b") is None
    limite.terminar()
    reloj.return_value = 160.0
    assert limite.admitir("a") is None
    limite.terminar()
    assert limite.admitir("a").reintentar_en == 10


def test_limite_total_entre_ips_y_cupo_en_curso() -> None:
    limite, reloj = control(total=2, max_en_curso=1)
    assert limite.admitir("a") is None
    assert limite.admitir("b").motivo == "en_curso"
    limite.terminar()
    assert limite.admitir("b") is None
    limite.terminar()
    assert limite.admitir("c").motivo == "total"
    reloj.return_value = 160.0
    assert limite.admitir("c") is None
    limite.terminar()


def test_memoria_acotada_sin_evictar_cupos_vigentes() -> None:
    reloj = Mock(return_value=100.0)
    limite = ControlSolicitudes(ConfiguracionLimites(total=100), reloj=reloj, max_clientes=2)
    for ip in ("a", "b"):
        assert limite.admitir(ip) is None
        limite.terminar()
    assert limite.admitir("c").motivo == "clientes"
    # El rechazo no extiende la ventana ni resetea los contadores de las IP existentes.
    reloj.return_value = 160.0
    assert limite.admitir("c") is None
    limite.terminar()


@pytest.mark.parametrize(
    "opciones",
    [
        {"por_ip": 0},
        {"total": -1},
        {"max_en_curso": 0},
        {"ventana_segundos": 0},
        {"ventana_segundos": float("nan")},
        {"ventana_segundos": float("inf")},
    ],
)
def test_rechaza_limites_invalidos(opciones) -> None:
    with pytest.raises(ValueError):
        ConfiguracionLimites(**opciones)


def test_http_429_entre_endpoints_e_independencia_de_documentacion() -> None:
    app = crear_app(
        proveedores=[], configuracion=Configuracion(limites=ConfiguracionLimites(por_ip=1))
    )
    cliente = TestClient(app)
    assert cliente.post("/api/v1/consultas", json={}).status_code == 422
    respuesta = cliente.post("/api/v1/consultas", content=b"no debe procesarse")
    assert respuesta.status_code == 429
    assert respuesta.json()["codigo"] == "limite_solicitudes_excedido"
    assert int(respuesta.headers["Retry-After"]) >= 1
    assert respuesta.headers["Cache-Control"] == "no-store"
    for ruta in ("/health", "/docs", "/openapi.json"):
        assert cliente.get(ruta).status_code == 200


async def correcto(scope, receive, send):
    await JSONResponse({"ok": True})(scope, receive, send)


@pytest.mark.anyio
async def test_rechaza_sin_leer_el_cuerpo_ni_invocar_el_endpoint() -> None:
    limite, _ = control(por_ip=1)
    middleware = LimiteSolicitudesMiddleware(correcto, limite)
    assert limite.admitir("a") is None
    limite.terminar()
    enviados = []

    async def recibir():
        raise AssertionError("No debe leer el upload bloqueado")

    async def enviar(mensaje):
        enviados.append(mensaje)

    await middleware(
        {
            "type": "http",
            "path": "/api/v1/consultas",
            "method": "POST",
            "client": ("a", 1),
        },
        recibir,
        enviar,
    )
    assert enviados[0]["status"] == 429


@pytest.mark.anyio
async def test_no_confia_en_xff_de_un_cliente_directo_y_si_en_el_proxy_autorizado() -> None:
    limite, _ = control(por_ip=1, total=10)
    app = ProxyHeadersMiddleware(
        LimiteSolicitudesMiddleware(correcto, limite), trusted_hosts=["192.0.2.10"]
    )
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("192.0.2.1", 1234)), base_url="http://test"
    ) as cliente:
        assert (
            await cliente.post("/api/test", headers={"X-Forwarded-For": "198.51.100.1"})
        ).status_code == 200
        assert (
            await cliente.post("/api/test", headers={"X-Forwarded-For": "198.51.100.2"})
        ).status_code == 429
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("192.0.2.10", 1234)), base_url="http://test"
    ) as cliente:
        for ip in ("198.51.100.3", "198.51.100.4"):
            assert (
                await cliente.post("/api/test", headers={"X-Forwarded-For": ip})
            ).status_code == 200


@pytest.mark.anyio
async def test_concurrencia_real_y_liberacion_al_cancelar() -> None:
    limite, _ = control(max_en_curso=1)
    iniciado = asyncio.Event()
    bloqueo = asyncio.Event()

    async def lento(scope, receive, send):
        iniciado.set()
        await bloqueo.wait()
        await correcto(scope, receive, send)

    app = LimiteSolicitudesMiddleware(lento, limite)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as cliente:
        primera = asyncio.create_task(cliente.post("/api/test"))
        await asyncio.wait_for(iniciado.wait(), 1)
        try:
            assert (await cliente.post("/api/test")).status_code == 429
            primera.cancel()
            with pytest.raises(asyncio.CancelledError):
                await primera
            bloqueo.set()
            assert (await cliente.post("/api/test")).status_code == 200
        finally:
            primera.cancel()
            await asyncio.gather(primera, return_exceptions=True)


@pytest.mark.anyio
async def test_libera_cupo_ante_excepcion() -> None:
    limite, _ = control(max_en_curso=1)

    async def roto(scope, receive, send):
        raise RuntimeError("fallo simulado")

    async with AsyncClient(
        transport=ASGITransport(app=LimiteSolicitudesMiddleware(roto, limite)),
        base_url="http://test",
    ) as cliente:
        with pytest.raises(RuntimeError):
            await cliente.post("/api/test")
    assert limite.admitir("otra") is None
    limite.terminar()


def test_desactivacion_por_configuracion() -> None:
    app = crear_app(
        proveedores=[],
        configuracion=Configuracion(limites=ConfiguracionLimites(habilitado=False, por_ip=1)),
    )
    cliente = TestClient(app)
    for _ in range(3):
        assert cliente.post("/api/v1/consultas", json={}).status_code == 422


def test_configuracion_desde_entorno(monkeypatch) -> None:
    monkeypatch.setenv("OPENRENAPER_RATE_LIMIT_POR_IP", "3")
    monkeypatch.setenv("OPENRENAPER_RATE_LIMIT_TOTAL", "7")
    monkeypatch.setenv("OPENRENAPER_RATE_LIMIT_VENTANA_SEGUNDOS", "20")
    monkeypatch.setenv("OPENRENAPER_RATE_LIMIT_MAX_EN_CURSO", "2")
    config = Configuracion.desde_entorno().limites
    assert (config.por_ip, config.total, config.ventana_segundos, config.max_en_curso) == (
        3,
        7,
        20,
        2,
    )
