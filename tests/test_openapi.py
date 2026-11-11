"""El contrato OpenAPI documenta endpoints, estados y errores, sin autenticación."""

from typing import Any

import pytest

from app.consultas.modelos import ConsultaSolicitud, PersonaConsulta
from app.consultas.router import EJEMPLOS_RESPUESTA, EJEMPLOS_SOLICITUD
from app.main import DESCRIPCION, INTEGRANTES, crear_app

ESQUEMA = crear_app(proveedores=[]).openapi()


def operacion(ruta: str) -> dict[str, Any]:
    return ESQUEMA["paths"][ruta]["post"]


def test_documenta_los_endpoints() -> None:
    assert set(ESQUEMA["paths"]) == {
        "/health",
        "/api/v1/consultas",
    }


def test_no_declara_autenticacion() -> None:
    assert "securitySchemes" not in ESQUEMA.get("components", {})
    assert "security" not in ESQUEMA
    for metodos in ESQUEMA["paths"].values():
        for definicion in metodos.values():
            assert "security" not in definicion
            nombres = {p["name"].lower() for p in definicion.get("parameters", [])}
            assert not nombres & {"authorization", "x-api-key", "api_key", "token"}


@pytest.mark.parametrize(
    ("ruta", "estados"),
    [
        ("/api/v1/consultas", {"200", "400", "404", "409", "422", "429", "502", "503", "504"}),
    ],
)
def test_documenta_los_errores(ruta: str, estados: set[str]) -> None:
    respuestas = operacion(ruta)["responses"]
    assert set(respuestas) == estados
    for estado in estados - {"200"}:
        contenido = respuestas[estado]["content"]["application/json"]
        assert contenido["schema"]["$ref"].endswith("/ErrorRespuesta")
        assert contenido["examples"]


def test_documenta_solo_los_seis_campos_y_los_dos_tipos_de_entrada() -> None:
    campos = ESQUEMA["components"]["schemas"]["PersonaConsulta"]["properties"]
    assert set(campos) == {"nombre", "dni", "cuit", "edad", "sexo", "provincia_ubicacion"}
    solicitud = ESQUEMA["components"]["schemas"]["ConsultaSolicitud"]["properties"]
    assert solicitud["tipo"]["enum"] == ["dni", "cuit"]
    assert solicitud["numero"]["pattern"] == "^[0-9]+$"


def test_presentacion_del_proyecto() -> None:
    info = ESQUEMA["info"]
    assert info["title"] == "OpenRENAPER"
    assert info["description"].startswith("## TFI PAD\n\n")
    assert DESCRIPCION == (
        "Proyecto académico independiente. No pertenece a RENAPER ni acredita identidad. "
        "API orientada a consultar y contrastar datos personales publicados en fuentes "
        "públicas a partir de un DNI o un CUIT/CUIL."
    )
    assert DESCRIPCION in info["description"]
    for nombre in INTEGRANTES:
        assert nombre in info["description"]


def test_documenta_espera_de_rate_limit() -> None:
    for ruta in ("/api/v1/consultas",):
        assert operacion(ruta)["responses"]["429"]["headers"]["Retry-After"]["schema"] == {
            "type": "integer",
            "minimum": 1,
        }


def _sin_calculados(valor: Any) -> Any:
    if isinstance(valor, dict):
        return {k: _sin_calculados(v) for k, v in valor.items() if k != "desconocidos"}
    if isinstance(valor, list):
        return [_sin_calculados(v) for v in valor]
    return valor


@pytest.mark.parametrize("nombre", list(EJEMPLOS_RESPUESTA))
def test_ejemplos_de_respuesta_cumplen_el_modelo(nombre: str) -> None:
    ejemplo = EJEMPLOS_RESPUESTA[nombre]["value"]
    modelo = PersonaConsulta.model_validate(_sin_calculados(ejemplo))
    assert modelo.model_dump(mode="json") == ejemplo


@pytest.mark.parametrize("nombre", list(EJEMPLOS_SOLICITUD))
def test_ejemplos_de_solicitud_cumplen_el_modelo(nombre: str) -> None:
    ConsultaSolicitud.model_validate(EJEMPLOS_SOLICITUD[nombre]["value"])
