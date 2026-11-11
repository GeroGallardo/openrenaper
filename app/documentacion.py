"""Documentación interactiva con Scalar en `/docs`.

Scalar lee el contrato que genera FastAPI (`app.openapi_url`); no hay una copia
manual del esquema. Swagger está en `/swagger`; ReDoc y OpenAPI se conservan.

El JavaScript de Scalar se descarga del CDN jsDelivr en el navegador de quien
abre la página, con versión fijada en `SCALAR_JS_VERSION`. Como el contrato no
declara esquemas de seguridad, la referencia no pide credenciales; el cliente de
Scalar 1.76.4 igual muestra un selector de autenticación vacío y opcional, que
no puede ocultarse por configuración. La página no usa el proxy de Scalar (las
solicitudes van directo a esta API) y desactiva Agent, MCP y telemetría.
"""

from typing import Any

from fastapi import FastAPI, routing
from fastapi.encoders import jsonable_encoder
from scalar_fastapi import AgentScalarConfig, add_scalar_reference

RUTA_SCALAR = "/docs"
SCALAR_JS_VERSION = "1.76.4"
SCALAR_JS_URL = f"https://cdn.jsdelivr.net/npm/@scalar/api-reference@{SCALAR_JS_VERSION}"

# Ícono embebido para no depender de recursos de terceros además del script.
_FAVICON = (
    "data:image/svg+xml,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E"
    "%3Crect width='16' height='16' rx='3' fill='%23009485'/%3E%3C/svg%3E"
)


def registrar_scalar(app: FastAPI) -> None:
    """Agrega `GET /docs` (fuera del esquema OpenAPI) a la aplicación."""
    add_scalar_reference(
        app,
        route=RUTA_SCALAR,
        include_in_schema=False,
        openapi_url=app.openapi_url,
        title=f"{app.title} · Referencia de la API",
        scalar_js_url=SCALAR_JS_URL,
        scalar_favicon_url=_FAVICON,
        # Sin proxy: el cliente de Scalar envía las solicitudes directo a la API.
        scalar_proxy_url="",
        # Sin `servers`: el contrato no los declara y el cliente usa rutas relativas
        # (/api/v1/...), que el navegador resuelve contra el origen (host y puerto)
        # desde el que se abrió /docs. Un servidor "/" generaba URL con "//".
        hide_client_button=False,
        hide_test_request_button=False,
        hide_models=False,
        hide_search=False,
        default_open_all_tags=True,
        order_schema_properties_by="preserve",
        order_required_properties_first=False,
        show_developer_tools="never",
        with_default_fonts=False,
        telemetry=False,
        agent=AgentScalarConfig(disabled=True),
        overrides={
            "mcp": {"disabled": True},
            "localization": {"locale": "es"},
            "modelsSectionLabel": "Modelos",
        },
    )


def _rutas(app: FastAPI) -> list[Any]:
    """Rutas de la API, incluidas las de routers anidados.

    Desde FastAPI 0.162 los routers incluidos se recorren con `iter_route_contexts`.
    """
    iterar = getattr(routing, "iter_route_contexts", None)
    if iterar is None:
        return [r for r in app.routes if isinstance(r, routing.APIRoute)]
    return [
        contexto
        for contexto in iterar(app.routes)
        if isinstance(contexto.original_route, routing.APIRoute)
    ]


def conservar_nulos_en_ejemplos(app: FastAPI) -> None:
    """Publica los ejemplos de respuesta con sus `null`.

    FastAPI genera el contrato con `exclude_none=True`, lo que elimina los campos
    `null` de los ejemplos (por ejemplo, `edad` o `fuente`). Aquí se reponen los
    valores declarados en `responses=` de cada ruta. Solo cambia `/openapi.json`;
    las respuestas de la API no se modifican.
    """
    generar = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        esquema = generar()
        for ruta in _rutas(app):
            if not ruta.include_in_schema:
                continue
            operaciones = esquema["paths"].get(ruta.path_format, {})
            for metodo in ruta.methods:
                operacion = operaciones.get(metodo.lower())
                if operacion is None:
                    continue
                for estado, respuesta in ruta.responses.items():
                    for tipo, contenido in respuesta.get("content", {}).items():
                        publicados = operacion["responses"][str(estado)]["content"][tipo]
                        for nombre, ejemplo in contenido.get("examples", {}).items():
                            if "value" in ejemplo:
                                publicados["examples"][nombre]["value"] = jsonable_encoder(
                                    ejemplo["value"]
                                )
        return esquema

    app.openapi = openapi  # type: ignore[method-assign]
