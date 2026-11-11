from typing import Annotated, Any

from fastapi import APIRouter, Body, Request

from app.api.dependencias import ConsultaServiceDep
from app.api.errores import respuestas_error
from app.api.registro import anotar_consulta
from app.consultas.modelos import ConsultaSolicitud, PersonaConsulta
from app.consultas.respuesta import persona_encontrada

router = APIRouter(prefix="/consultas", tags=["consultas"])

# Ejemplos estáticos con identificadores sintéticos que cumplen las validaciones
# (incluido el dígito verificador). No son respuestas reales de las fuentes.
EJEMPLOS_SOLICITUD: dict[str, Any] = {
    "dni": {"summary": "DNI", "value": {"tipo": "dni", "numero": "30111222"}},
    "cuil": {
        "summary": "CUIL (se consulta con tipo cuit)",
        "value": {"tipo": "cuit", "numero": "20301112220"},
    },
    "cuit": {
        "summary": "CUIT de persona jurídica",
        "value": {"tipo": "cuit", "numero": "30712345671"},
    },
}
EJEMPLOS_RESPUESTA: dict[str, Any] = {
    "completa": {
        "summary": "La fuente publica los seis campos",
        "value": {
            "nombre": "PERSONA DE EJEMPLO",
            "dni": "30111222",
            "cuit": "20301112220",
            "edad": 45,
            "sexo": "Masculino",
            "provincia_ubicacion": "PROVINCIA DE EJEMPLO",
        },
    },
    "campos_no_publicados": {
        "summary": "La fuente no publica edad, sexo ni provincia",
        "description": "Lo que la fuente elegida no publica se devuelve como null.",
        "value": {
            "nombre": "PERSONA DE EJEMPLO",
            "dni": "30111222",
            "cuit": "20301112220",
            "edad": None,
            "sexo": None,
            "provincia_ubicacion": None,
        },
    },
    "nombre_con_caracteres_danados": {
        "summary": "Nombre con caracteres dañados en la fuente",
        "description": "El nombre se devuelve tal como lo publica la fuente, sin corregirlo.",
        "value": {
            "nombre": "PERSONA DE EJ�MPLO",
            "dni": "30111222",
            "cuit": "20301112220",
            "edad": None,
            "sexo": None,
            "provincia_ubicacion": None,
        },
    },
    "persona_juridica": {
        "summary": "CUIT de persona jurídica",
        "value": {
            "nombre": "EMPRESA DE EJEMPLO S.A.",
            "dni": None,
            "cuit": "30712345671",
            "edad": None,
            "sexo": None,
            "provincia_ubicacion": None,
        },
    },
}

DESCRIPCION = """Consulta un DNI o un CUIT/CUIL en fuentes públicas y devuelve una sola persona.

**Entrada.** `tipo` admite únicamente `dni` o `cuit`; un CUIL se consulta con
`tipo: "cuit"`. `numero` es una cadena de dígitos ASCII, sin puntos, guiones,
barras ni espacios (7 a 11 caracteres). Además, un DNI tiene 7 u 8 dígitos sin
cero inicial, y un CUIT/CUIL tiene 11 dígitos, prefijo 20, 23, 24, 27, 30, 33
o 34 y dígito verificador correcto. Un formato válido no acredita que el
número exista.

**Respuesta exitosa (200).** Únicamente `nombre`, `dni`, `cuit`, `edad`,
`sexo` y `provincia_ubicacion`. Todos admiten `null`: lo que la fuente elegida
no publica queda en `null` y no se calcula ni se infiere. El nombre y el sexo
conservan el texto publicado, incluso con caracteres dañados. La respuesta no
incluye estado, fuente, resultados, advertencias ni otros envoltorios.

**Errores.** 404 sin coincidencias; 409 si hay varias personas posibles o datos
contradictorios; 422 si la entrada no cumple el esquema o las reglas del
identificador; 400 si el cuerpo no es JSON. Un fallo de fuente nunca se informa
como 404: 502 si la respuesta no se pudo interpretar, 503 si la fuente no está
disponible o no hay fuentes habilitadas, 504 si no respondió a tiempo. Si fallan
varias fuentes se informa el error más específico (502, luego 504, luego 503) y
`detalles` enumera cada fallo.

**Límite de peticiones.** Por defecto admite 15 peticiones por minuto por IP.
Si se alcanza la cuota o el cupo de trabajo en curso, devuelve 429 con el
encabezado `Retry-After`, que indica cuántos segundos esperar antes de reintentar.

**Tiempo.** Las fuentes externas pueden demorar; no hay un tiempo de respuesta
garantizado. Cada fuente tiene un límite configurable (45 s por defecto).

No requiere autenticación. Los ejemplos son estáticos y usan datos ficticios.
"""


@router.post(
    "",
    response_model=PersonaConsulta,
    summary="Consultar un DNI o CUIT",
    description=DESCRIPCION,
    response_description="Persona encontrada: exactamente seis campos, null si no se publican.",
    responses={
        200: {"content": {"application/json": {"examples": EJEMPLOS_RESPUESTA}}},
        **respuestas_error(
            400,
            404,
            409,
            422,
            429,
            502,
            503,
            504,
        ),
    },
)
async def consultar(
    solicitud: Annotated[ConsultaSolicitud, Body(openapi_examples=EJEMPLOS_SOLICITUD)],
    consultas: ConsultaServiceDep,
    request: Request,
):
    anotar_consulta(request.scope, solicitud.tipo, solicitud.numero)
    respuesta = await consultas.consultar(solicitud.tipo, solicitud.numero)
    return persona_encontrada(respuesta)
