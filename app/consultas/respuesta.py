"""Convierte el resultado interno en una sola persona para la API pública."""

from app.consultas.modelos import ConsultaRespuesta, EstadoConsulta, PersonaConsulta
from app.errores import ConsultaAmbigua, SinResultados


def persona_encontrada(respuesta: ConsultaRespuesta) -> PersonaConsulta:
    if respuesta.estado is EstadoConsulta.SIN_RESULTADOS:
        raise SinResultados("No se encontraron coincidencias.")
    if respuesta.estado is EstadoConsulta.AMBIGUO:
        raise ConsultaAmbigua(
            "La consulta tiene varias coincidencias posibles; consultar por CUIT."
        )
    personas = [
        PersonaConsulta(
            nombre=r.datos.nombre,
            dni=r.datos.dni,
            cuit=r.datos.cuit_cuil,
            edad=r.datos.edad,
            sexo=r.datos.sexo,
            provincia_ubicacion=r.datos.provincia_ubicacion,
        )
        for r in respuesta.resultados
    ]
    if not personas:
        raise SinResultados("No se encontraron coincidencias.")
    if any(p != personas[0] for p in personas[1:]):
        raise ConsultaAmbigua("La fuente informa datos contradictorios para la misma persona.")
    return personas[0]
