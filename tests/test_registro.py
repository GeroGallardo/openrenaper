"""Registro de consultas, contadores, correlación y casos que no completan una respuesta."""

import asyncio
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.api.registro import RegistroSolicitudesMiddleware, configurar_logger, logger
from app.config import Configuracion, ConfiguracionLimites, ConfiguracionRegistro
from app.consultas.modelos import DatosPersona
from app.main import crear_app
from scripts.resumir_logs import resumir
from tests.falsos import ProveedorFalso


@pytest.fixture
def registros(caplog):
    logger.addHandler(caplog.handler)
    yield lambda: [json.loads(r.getMessage()) for r in caplog.records if r.name == logger.name]
    logger.removeHandler(caplog.handler)


def cliente(**config):
    proveedor = ProveedorFalso(registros=[DatosPersona(dni="30111222", nombre="PERSONA SINTETICA")])
    return TestClient(
        crear_app(proveedores=[proveedor], configuracion=Configuracion(**config)),
        raise_server_exceptions=False,
    )


def test_registra_dni_y_correlacion_sin_cabeceras_o_query_strings(registros) -> None:
    respuesta = cliente().post(
        "/api/v1/consultas?token=secreto_sintetico",
        json={"tipo": "dni", "numero": "30111222"},
        headers={"Authorization": "Bearer secreto_sintetico", "X-Request-ID": "id-no-confiable"},
    )
    assert respuesta.status_code == 200
    dato = registros()[0]
    assert dato["consulta"] == {"tipo": "dni", "numero": "30111222"}
    assert dato["ruta"] == "/api/v1/consultas"
    assert dato["estado"] == 200 and dato["resultado"] == "completada"
    assert dato["duracion_ms"] >= 0
    assert dato["request_id"] == respuesta.headers["X-Request-ID"]
    assert uuid.UUID(dato["request_id"])
    assert "secreto_sintetico" not in json.dumps(dato)
    assert "PERSONA SINTETICA" not in json.dumps(dato)


def test_rechazos_tambien_cuentan_y_no_leen_identificadores_bloqueados(registros) -> None:
    api = cliente(limites=ConfiguracionLimites(por_ip=1))
    for numero in ("30111222", "40222333"):
        api.post("/api/v1/consultas", json={"tipo": "dni", "numero": numero})
    primero, segundo = registros()
    assert primero["solicitudes_total"] == 1
    assert segundo["solicitudes_total"] == 2
    assert segundo["solicitudes_operacion"] == 2
    assert segundo["rechazadas_429_total"] == 1
    assert segundo["estado"] == 429 and segundo["limite"] == "ip"
    assert "consulta" not in segundo


def test_no_registra_path_libre_con_datos_y_omite_health(registros) -> None:
    api = cliente()
    assert api.get("/health").status_code == 200
    assert registros() == []
    assert api.get("/api/personas/40222333?clave=privada").status_code == 404
    dato = registros()[0]
    assert dato["ruta"] == "(no_reconocida)"
    assert "40222333" not in json.dumps(dato)
    assert "privada" not in json.dumps(dato)


def test_configuracion_desactiva_logs_o_incluye_health(registros, monkeypatch) -> None:
    api = cliente(registro=ConfiguracionRegistro(habilitado=False))
    assert api.get("/docs").status_code == 200
    assert registros() == []
    api = cliente(registro=ConfiguracionRegistro(incluir_health=True))
    assert api.get("/health").status_code == 200
    assert registros()[0]["ruta"] == "/health"
    monkeypatch.setenv("OPENRENAPER_LOG_SOLICITUDES", "false")
    monkeypatch.setenv("OPENRENAPER_LOG_HEALTH", "true")
    config = Configuracion.desde_entorno().registro
    assert config.habilitado is False and config.incluir_health is True


def test_no_duplica_handlers_del_logger() -> None:
    configurar_logger()
    cantidad = len(logger.handlers)
    configurar_logger()
    assert len(logger.handlers) == cantidad


def test_error_500_conserva_correlacion_y_se_registra_una_vez(registros) -> None:
    app = crear_app(proveedores=[])

    @app.get("/fallo")
    async def fallo():
        raise RuntimeError("fallo sintético")

    api = TestClient(app, raise_server_exceptions=False)
    respuesta = api.get("/fallo")
    assert respuesta.status_code == 500
    assert len(registros()) == 1
    assert registros()[0]["estado"] == 500
    assert registros()[0]["request_id"] == respuesta.headers["X-Request-ID"]


@pytest.mark.anyio
async def test_cancelacion_se_registra_sin_inventar_estado_http(registros) -> None:
    iniciado = asyncio.Event()

    async def lento(scope, receive, send):
        iniciado.set()
        await asyncio.Event().wait()

    app = RegistroSolicitudesMiddleware(lento, ConfiguracionRegistro(), frozenset({"/lento"}))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
        tarea = asyncio.create_task(api.get("/lento"))
        await asyncio.wait_for(iniciado.wait(), 1)
        tarea.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarea
    assert registros()[0]["resultado"] == "cancelada"
    assert registros()[0]["estado"] is None


@pytest.mark.anyio
async def test_respuesta_incompleta_no_figura_como_completada(registros) -> None:
    async def rota(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"parcial", "more_body": True})
        raise RuntimeError("corte simulado")

    app = RegistroSolicitudesMiddleware(rota, ConfiguracionRegistro(), frozenset({"/stream"}))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
        with pytest.raises(RuntimeError):
            await api.get("/stream")
    assert registros()[0]["estado"] == 200
    assert registros()[0]["resultado"] == "interrumpida"


def test_resumen_cuenta_lineas_del_intervalo_sin_imprimir_dni() -> None:
    filas = [
        "INFO: inicio",
        "{}",
        json.dumps(
            {
                "evento": "solicitud_http",
                "metodo": "POST",
                "ruta": "/api/v1/consultas",
                "estado": 200,
                "consulta": {"numero": "30111222"},
            }
        ),
    ]
    resumen = resumir(filas)
    assert resumen["solicitudes_en_logs"] == 1
    assert resumen["por_estado"] == {"200": 1}
    assert resumen["por_operacion"][0]["cantidad"] == 1
    assert "30111222" not in json.dumps(resumen)
