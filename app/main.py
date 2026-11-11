"""Punto de entrada de la API: registro de routers, errores y recursos compartidos."""

from collections.abc import Sequence

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel

from app.api.errores import registrar_manejadores
from app.api.limites import ControlSolicitudes, LimiteSolicitudesMiddleware
from app.api.registro import RegistroSolicitudesMiddleware, configurar_logger
from app.config import Configuracion
from app.consultas.proveedores import ProveedorConsulta
from app.consultas.router import router as consultas_router
from app.documentacion import conservar_nulos_en_ejemplos, registrar_scalar
from app.recursos import (
    Recursos,
    ciclo_de_vida,
    proveedores_predeterminados,
)

DESCRIPCION = (
    "Proyecto académico independiente. No pertenece a RENAPER ni acredita identidad. "
    "API orientada a consultar y contrastar datos personales publicados en fuentes "
    "públicas a partir de un DNI o un CUIT/CUIL."
)
INTEGRANTES = (
    "Ibañez Matias Agustin",
    "Gutierrez Andrés",
    "Gallardo Piorno Gerónimo",
    "Atilio Vergara",
)
DOCUMENTACION = (
    "## TFI PAD\n\n"
    + DESCRIPCION
    + "\n\n### Integrantes\n\n"
    + "\n".join(f"- {nombre}" for nombre in INTEGRANTES)
)

ETIQUETAS = [
    {
        "name": "consultas",
        "description": "Consulta de un DNI o CUIT/CUIL en fuentes públicas.",
    },
    {
        "name": "operación",
        "description": "Estado del servicio. No consulta fuentes.",
    },
]


class HealthResponse(BaseModel):
    status: str


def crear_app(
    *,
    proveedores: Sequence[ProveedorConsulta] | None = None,
    configuracion: Configuracion | None = None,
) -> FastAPI:
    """Crea la aplicación. Sin argumentos usa los proveedores registrados."""
    app = FastAPI(
        title="OpenRENAPER",
        version="0.1.0",
        description=DOCUMENTACION,
        openapi_tags=ETIQUETAS,
        docs_url="/swagger",
        lifespan=ciclo_de_vida,
    )
    configuracion = configuracion or Configuracion.desde_entorno()
    app.state.recursos = Recursos.crear(
        configuracion,
        proveedores_predeterminados(configuracion) if proveedores is None else proveedores,
    )
    registrar_manejadores(app)
    app.state.control_solicitudes = ControlSolicitudes(configuracion.limites)
    app.add_middleware(LimiteSolicitudesMiddleware, control=app.state.control_solicitudes)

    @app.get("/health", response_model=HealthResponse, tags=["operación"])
    def health() -> HealthResponse:
        """Estado del proceso. No consulta fuentes."""
        return HealthResponse(status="ok")

    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(consultas_router)
    app.include_router(api_v1)
    conservar_nulos_en_ejemplos(app)
    registrar_scalar(app)
    if configuracion.registro.habilitado:
        configurar_logger()
    app.add_middleware(
        RegistroSolicitudesMiddleware,
        configuracion=configuracion.registro,
        rutas=lambda: (
            frozenset(app.openapi()["paths"])
            | frozenset(r.path for r in app.routes if hasattr(r, "path"))
        ),
    )
    return app


app = crear_app()
