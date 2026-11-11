from typing import Annotated

from fastapi import Depends, Request

from app.consultas.servicio import ConsultaService
from app.recursos import Recursos


def obtener_recursos(request: Request) -> Recursos:
    return request.app.state.recursos


def obtener_consultas(recursos: Annotated[Recursos, Depends(obtener_recursos)]) -> ConsultaService:
    return recursos.consultas


RecursosDep = Annotated[Recursos, Depends(obtener_recursos)]
ConsultaServiceDep = Annotated[ConsultaService, Depends(obtener_consultas)]
