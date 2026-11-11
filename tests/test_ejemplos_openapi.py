"""Los ejemplos publicados en OpenAPI cumplen sus modelos y su código HTTP."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.errores import (
    _CODIGOS_POR_ESTADO,
    EJEMPLOS_ERROR,
    ErrorRespuesta,
)
from app.consultas.modelos import PersonaConsulta
from app.main import crear_app

ESQUEMA = crear_app(proveedores=[]).openapi()
MODELOS_200 = {
    "/api/v1/consultas": PersonaConsulta,
}


def _sin_calculados(valor: Any) -> Any:
    """Quita `desconocidos`, que el modelo calcula y no admite como entrada."""
    if isinstance(valor, dict):
        return {k: _sin_calculados(v) for k, v in valor.items() if k != "desconocidos"}
    if isinstance(valor, list):
        return [_sin_calculados(v) for v in valor]
    return valor


def _ejemplos(ruta: str, estado: str) -> dict[str, Any]:
    respuesta = ESQUEMA["paths"][ruta]["post"]["responses"][estado]
    return respuesta["content"]["application/json"]["examples"]


@pytest.mark.parametrize("ruta", list(MODELOS_200))
def test_ejemplos_exitosos_cumplen_el_modelo(ruta: str) -> None:
    ejemplos = _ejemplos(ruta, "200")
    assert ejemplos
    for ejemplo in ejemplos.values():
        valor = ejemplo["value"]
        modelo = MODELOS_200[ruta].model_validate(_sin_calculados(valor))
        assert modelo.model_dump(mode="json") == valor


@pytest.mark.parametrize("ruta", list(MODELOS_200))
def test_ejemplos_de_error_corresponden_a_su_estado(ruta: str) -> None:
    for estado, respuesta in ESQUEMA["paths"][ruta]["post"]["responses"].items():
        if estado == "200":
            continue
        ejemplos = respuesta["content"]["application/json"]["examples"]
        assert ejemplos, f"{ruta} {estado} sin ejemplos"
        for ejemplo in ejemplos.values():
            assert _CODIGOS_POR_ESTADO[ejemplo["value"]["codigo"]] == int(estado)


@pytest.mark.parametrize("nombre", list(EJEMPLOS_ERROR))
def test_ejemplos_de_error_cumplen_el_modelo(nombre: str) -> None:
    valor = EJEMPLOS_ERROR[nombre]["value"]
    assert ErrorRespuesta.model_validate(valor).model_dump(mode="json") == valor


@pytest.mark.parametrize(
    ("cuerpo", "nombre"),
    [
        ({"tipo": "dni", "numero": "30.111.222"}, "numero_con_separadores"),
        ({"tipo": "cuit", "numero": "20301112221"}, "verificador_incorrecto"),
    ],
)
def test_ejemplos_de_entrada_invalida_coinciden_con_la_respuesta_real(
    cuerpo: dict[str, str], nombre: str
) -> None:
    cliente = TestClient(crear_app(proveedores=[]))
    respuesta = cliente.post("/api/v1/consultas", json=cuerpo)
    assert respuesta.status_code == 422
    assert respuesta.json() == EJEMPLOS_ERROR[nombre]["value"]


def test_ejemplos_no_usan_nombres_de_personas_reales() -> None:
    texto = str(ESQUEMA)
    assert "PEREZ" not in texto and "JUAN" not in texto


def test_ejemplos_de_error_publicados_son_los_declarados() -> None:
    for ruta in MODELOS_200:
        for estado, respuesta in ESQUEMA["paths"][ruta]["post"]["responses"].items():
            if estado == "200":
                continue
            for nombre, ejemplo in respuesta["content"]["application/json"]["examples"].items():
                esperado = EJEMPLOS_ERROR[nombre]["value"]
                assert ejemplo["value"] == esperado
