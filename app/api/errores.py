"""Traducción de errores del dominio a respuestas HTTP con un único formato.

| código                        | HTTP |
|-------------------------------|------|
| solicitud_mal_formada         | 400  |
| entrada_invalida              | 422  |
| limite_solicitudes_excedido   | 429  |
| respuesta_no_interpretable    | 502  |
| fuente_no_disponible          | 503  |
| tiempo_agotado                | 504  |
| error_interno                 | 500  |
"""

import logging
from collections.abc import Collection
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.errores import ErrorConsulta

logger = logging.getLogger(__name__)

ESTADOS_HTTP = {
    "sin_resultados": 404,
    "consulta_ambigua": 409,
    "entrada_invalida": 422,
    "respuesta_no_interpretable": 502,
    "fuente_no_disponible": 503,
    "tiempo_agotado": 504,
    "limite_solicitudes_excedido": 429,
}


class ErrorRespuesta(BaseModel):
    codigo: str = Field(description="Código estable del error.")
    mensaje: str
    fuente: str | None = Field(default=None, description="Fuente que originó el error, si aplica.")
    detalles: list[dict[str, Any]] = Field(default_factory=list)


def estado_http(error: ErrorConsulta) -> int:
    for clase in type(error).__mro__:
        codigo = getattr(clase, "codigo", None)
        if codigo in ESTADOS_HTTP:
            return ESTADOS_HTTP[codigo]
    return 500


def _respuesta(estado: int, error: ErrorRespuesta, request: Request) -> JSONResponse:
    return JSONResponse(status_code=estado, content=error.model_dump(mode="json"))


async def _error_consulta(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, ErrorConsulta)
    cuerpo = ErrorRespuesta(
        codigo=error.codigo, mensaje=error.mensaje, fuente=error.fuente, detalles=error.detalles
    )
    return _respuesta(estado_http(error), cuerpo, request)


async def _error_validacion(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, RequestValidationError)
    detalles = [
        {"campo": ".".join(str(p) for p in e["loc"][1:]) or "cuerpo", "motivo": e["msg"]}
        for e in error.errors()
    ]
    if any(e["type"] == "json_invalid" for e in error.errors()):
        cuerpo = ErrorRespuesta(
            codigo="solicitud_mal_formada",
            mensaje="El cuerpo no es JSON válido.",
            detalles=detalles,
        )
        return _respuesta(400, cuerpo, request)
    cuerpo = ErrorRespuesta(
        codigo="entrada_invalida", mensaje="La solicitud no cumple el esquema.", detalles=detalles
    )
    return _respuesta(422, cuerpo, request)


async def _error_inesperado(request: Request, error: Exception) -> JSONResponse:
    logger.exception("Error no controlado", exc_info=error)
    respuesta = _respuesta(
        500, ErrorRespuesta(codigo="error_interno", mensaje="Error interno."), request
    )
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        respuesta.headers["X-Request-ID"] = request_id
    return respuesta


def registrar_manejadores(app: FastAPI) -> None:
    app.add_exception_handler(ErrorConsulta, _error_consulta)
    app.add_exception_handler(RequestValidationError, _error_validacion)
    app.add_exception_handler(Exception, _error_inesperado)


def _error(
    codigo: str,
    mensaje: str,
    *,
    fuente: str | None = None,
    detalles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {"codigo": codigo, "mensaje": mensaje, "fuente": fuente, "detalles": detalles or []}


def _detalle(campo: str, motivo: str) -> list[dict[str, str]]:
    return [{"campo": campo, "motivo": motivo}]


# Ejemplos estáticos con los mensajes que produce el código; no son respuestas
# capturadas de las fuentes. Cada ejemplo se publica en el estado HTTP de su código.
EJEMPLOS_ERROR: dict[str, dict[str, Any]] = {
    "json_invalido": {
        "summary": "El cuerpo no es JSON válido",
        "description": "`campo` indica la posición del cuerpo donde falló la lectura.",
        "value": _error(
            "solicitud_mal_formada",
            "El cuerpo no es JSON válido.",
            detalles=_detalle("8", "JSON decode error"),
        ),
    },
    "limite_solicitudes_excedido": {
        "summary": "Se alcanzó la cuota o el cupo de trabajo",
        "value": _error(
            "limite_solicitudes_excedido",
            "Se alcanzó el límite de peticiones. Reintentá más tarde.",
            detalles=[{"limite": "ip"}],
        ),
    },
    "sin_resultados": {
        "summary": "Sin coincidencias",
        "value": _error("sin_resultados", "No se encontraron coincidencias."),
    },
    "varias_personas": {
        "summary": "Varias personas posibles",
        "value": _error(
            "consulta_ambigua",
            "La consulta tiene varias coincidencias posibles; consultar por CUIT.",
        ),
    },
    "datos_contradictorios": {
        "summary": "Datos contradictorios para la misma persona",
        "value": _error(
            "consulta_ambigua", "La fuente informa datos contradictorios para la misma persona."
        ),
    },
    "numero_con_separadores": {
        "summary": "Número con puntos (no cumple el esquema)",
        "description": 'Respuesta a `{"tipo": "dni", "numero": "30.111.222"}`.',
        "value": _error(
            "entrada_invalida",
            "La solicitud no cumple el esquema.",
            detalles=_detalle("numero", "String should match pattern '^[0-9]+$'"),
        ),
    },
    "verificador_incorrecto": {
        "summary": "Dígito verificador incorrecto",
        "description": 'Respuesta a `{"tipo": "cuit", "numero": "20301112221"}`.',
        "value": _error(
            "entrada_invalida",
            "El dígito verificador del CUIT no es correcto.",
            detalles=_detalle("numero", "El dígito verificador del CUIT no es correcto."),
        ),
    },
    "respuesta_no_interpretable": {
        "summary": "La fuente respondió algo que no se puede interpretar",
        "value": _error(
            "respuesta_no_interpretable",
            "pag_web1 devolvió un formato inesperado.",
            fuente="pag_web1",
        ),
    },
    "sin_fuentes": {
        "summary": "Sin fuentes habilitadas",
        "value": _error("fuente_no_disponible", "No hay fuentes configuradas para consultar DNI."),
    },
    "fuentes_caidas": {
        "summary": "Ninguna fuente pudo consultarse",
        "value": _error(
            "fuente_no_disponible",
            "Ninguna fuente pudo confirmar el resultado.",
            detalles=[
                {
                    "fuente": "pag_web1",
                    "codigo": "fuente_no_disponible",
                    "mensaje": "pag_web1 falló al consultar.",
                },
                {
                    "fuente": "pag_web2",
                    "codigo": "fuente_no_disponible",
                    "mensaje": "pag_web2 falló al consultar.",
                },
            ],
        ),
    },
    "tiempo_agotado": {
        "summary": "La fuente no respondió a tiempo",
        "value": _error("tiempo_agotado", "pag_web2 no respondió a tiempo.", fuente="pag_web2"),
    },
}
_CODIGOS_POR_ESTADO = {**ESTADOS_HTTP, "solicitud_mal_formada": 400}


def respuestas_error(
    *estados: int, excluir: Collection[str] = ()
) -> dict[int | str, dict[str, Any]]:
    """Documentación OpenAPI de los errores de un endpoint, con ejemplos por estado.

    `excluir` quita ejemplos de `EJEMPLOS_ERROR` que no aplican al endpoint.
    """
    respuestas: dict[int | str, dict[str, Any]] = {}
    for estado in estados:
        codigos = [c for c, e in _CODIGOS_POR_ESTADO.items() if e == estado]
        ejemplos = {
            nombre: ejemplo
            for nombre, ejemplo in EJEMPLOS_ERROR.items()
            if ejemplo["value"]["codigo"] in codigos and nombre not in excluir
        }
        respuestas[estado] = {
            "model": ErrorRespuesta,
            "description": ", ".join(
                dict.fromkeys(e["value"]["codigo"] for e in ejemplos.values())
            ),
            "content": {"application/json": {"examples": ejemplos}},
        }
        if estado == 429:
            respuestas[estado]["headers"] = {
                "Retry-After": {
                    "description": "Segundos que se deben esperar antes de reintentar.",
                    "schema": {"type": "integer", "minimum": 1},
                }
            }
    return respuestas
