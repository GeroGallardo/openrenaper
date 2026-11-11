"""Endpoints HTTP, traducción de errores y ciclo de vida, sin credenciales ni sitios reales."""

import pytest
from fastapi.testclient import TestClient

from app.config import Configuracion
from app.consultas.modelos import DatosPersona
from app.errores import (
    FuenteNoDisponible,
    RespuestaNoInterpretable,
    TiempoAgotado,
)
from app.main import crear_app
from tests.falsos import ProveedorFalso

PERSONA = DatosPersona(dni="30111222", cuit_cuil="20301112220", nombre="PEREZ JUAN")


def cliente(proveedores=None, **configuracion) -> TestClient:
    app = crear_app(
        proveedores=[] if proveedores is None else proveedores,
        configuracion=Configuracion(tiempo_limite_proveedor=0.05, **configuracion),
    )
    return TestClient(app, raise_server_exceptions=False)


def test_health_no_consulta_fuentes() -> None:
    proveedor = ProveedorFalso(error=FuenteNoDisponible("caída"))
    respuesta = cliente([proveedor]).get("/health")
    assert respuesta.status_code == 200
    assert respuesta.json() == {"status": "ok"}
    assert proveedor.consultas == []


def test_consulta_encontrada_sin_credenciales() -> None:
    respuesta = cliente([ProveedorFalso("fuente-a", [PERSONA])]).post(
        "/api/v1/consultas", json={"tipo": "cuit", "numero": "20301112220"}
    )
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo == {
        "nombre": "PEREZ JUAN",
        "dni": "30111222",
        "cuit": "20301112220",
        "edad": None,
        "sexo": None,
        "provincia_ubicacion": None,
    }


def test_sin_resultados_responde_404() -> None:
    respuesta = cliente([ProveedorFalso()]).post(
        "/api/v1/consultas", json={"tipo": "dni", "numero": "30111222"}
    )
    assert respuesta.status_code == 404
    assert respuesta.json()["codigo"] == "sin_resultados"


@pytest.mark.parametrize(
    ("cuerpo", "estado", "codigo"),
    [
        ({"tipo": "dni", "numero": "30111222x"}, 422, "entrada_invalida"),
        ({"tipo": "cuit", "numero": "20-30111222-1"}, 422, "entrada_invalida"),
        ({"tipo": "pasaporte", "numero": "30111222"}, 422, "entrada_invalida"),
        ({"tipo": "dni", "numero": 30111222}, 422, "entrada_invalida"),
        ({"tipo": "dni"}, 422, "entrada_invalida"),
        ({"tipo": "dni", "numero": "30111222", "extra": 1}, 422, "entrada_invalida"),
        ({"tipo": "cuil", "numero": "20301112220"}, 422, "entrada_invalida"),
        ({"tipo": "dni", "numero": "30.111.222"}, 422, "entrada_invalida"),
        ({"tipo": "dni", "numero": "30111222 "}, 422, "entrada_invalida"),
        ({"tipo": "dni", "numero": "30/111/222"}, 422, "entrada_invalida"),
        ({"tipo": "cuit", "numero": "20-30111222-0"}, 422, "entrada_invalida"),
    ],
)
def test_entrada_invalida(cuerpo: dict, estado: int, codigo: str) -> None:
    respuesta = cliente([ProveedorFalso()]).post("/api/v1/consultas", json=cuerpo)
    assert respuesta.status_code == estado
    assert respuesta.json()["codigo"] == codigo
    assert respuesta.json()["detalles"]


def test_json_mal_formado_es_400() -> None:
    respuesta = cliente([ProveedorFalso()]).post(
        "/api/v1/consultas", content=b"{no es json", headers={"content-type": "application/json"}
    )
    assert respuesta.status_code == 400
    assert respuesta.json()["codigo"] == "solicitud_mal_formada"


@pytest.mark.parametrize(
    ("proveedor", "estado", "codigo"),
    [
        (ProveedorFalso(demora=1), 504, "tiempo_agotado"),
        (ProveedorFalso(error=TiempoAgotado("lento")), 504, "tiempo_agotado"),
        (ProveedorFalso(error=FuenteNoDisponible("caída")), 503, "fuente_no_disponible"),
        (ProveedorFalso(error=RespuestaNoInterpretable("html")), 502, "respuesta_no_interpretable"),
    ],
)
def test_errores_de_proveedor(proveedor: ProveedorFalso, estado: int, codigo: str) -> None:
    respuesta = cliente([proveedor]).post(
        "/api/v1/consultas", json={"tipo": "dni", "numero": "30111222"}
    )
    assert respuesta.status_code == estado
    assert respuesta.json()["codigo"] == codigo
    assert respuesta.json()["fuente"] == proveedor.nombre


def test_sin_proveedores_es_503() -> None:
    respuesta = cliente([]).post("/api/v1/consultas", json={"tipo": "dni", "numero": "30111222"})
    assert respuesta.status_code == 503


def test_ciclo_de_vida_inicia_y_cierra_recursos() -> None:
    proveedor = ProveedorFalso()
    with cliente([proveedor]) as c:
        assert proveedor.iniciado and not proveedor.cerrado
        assert c.get("/health").status_code == 200
    assert proveedor.cerrado


def test_error_no_controlado_usa_el_formato_comun() -> None:
    prueba = cliente([ProveedorFalso()])

    async def roto(*_):
        raise RuntimeError("bug")

    prueba.app.state.recursos.consultas.consultar = roto
    respuesta = prueba.post("/api/v1/consultas", json={"tipo": "dni", "numero": "30111222"})
    assert respuesta.status_code == 500
    assert respuesta.json()["codigo"] == "error_interno"
