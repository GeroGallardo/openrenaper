"""Reglas de consulta: validar, consultar proveedores y decidir el estado.

- Se consultan los proveedores en orden de prioridad. El primero con datos
  válidos responde; los siguientes solo se usan si hubo ausencia o fallo.
- Un registro cuyo identificador contradice el consultado invalida la respuesta
  de ese proveedor (`respuesta_no_interpretable`): nunca se descarta en silencio.
- Si ningún proveedor respondió, se informa el error y no `sin_resultados`.
  Si alguno falló pero otro aportó resultados, el fallo queda como advertencia.
  Si los que respondieron no hallaron nada pero alguno falló, también es error:
  la ausencia no está confirmada.
- Los registros se agrupan en candidatos. Más de un candidato da `ambiguo`;
  nunca se elige el primero.
"""

import asyncio
import logging
import unicodedata
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from app.consultas.modelos import (
    Advertencia,
    ConsultaEfectuada,
    ConsultaRespuesta,
    DatosPersona,
    EstadoConsulta,
    Resultado,
)
from app.consultas.proveedores import ProveedorConsulta
from app.errores import (
    ErrorConsulta,
    FuenteNoDisponible,
    RespuestaNoInterpretable,
    TiempoAgotado,
)
from app.identificadores import Identificador, TipoIdentificador, normalizar

logger = logging.getLogger(__name__)

# Cuando todas las fuentes fallan se informa el error más específico.
_PRIORIDAD_ERRORES: tuple[type[ErrorConsulta], ...] = (
    RespuestaNoInterpretable,
    TiempoAgotado,
    FuenteNoDisponible,
)


class ConsultaService:
    def __init__(
        self,
        proveedores: Sequence[ProveedorConsulta],
        *,
        tiempo_limite: float = 20.0,
        reloj: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._proveedores = tuple(proveedores)
        self._tiempo_limite = tiempo_limite
        self._reloj = reloj

    async def consultar(self, tipo: TipoIdentificador | str, numero: str) -> ConsultaRespuesta:
        identificador = normalizar(tipo, numero)
        proveedores = [p for p in self._proveedores if identificador.tipo in p.tipos]
        if not proveedores:
            raise FuenteNoDisponible(
                f"No hay fuentes configuradas para consultar {identificador.tipo.value.upper()}."
            )

        fallos: list[tuple[str, ErrorConsulta]] = []
        for proveedor in proveedores:
            respuesta = await self._consultar_proveedor(proveedor, identificador)
            if isinstance(respuesta, ErrorConsulta):
                fallos.append((proveedor.nombre, respuesta))
            else:
                momento, registros = respuesta
                if registros:
                    return self._respuesta(
                        identificador, [(proveedor.nombre, momento, r) for r in registros], fallos
                    )
        if fallos:
            raise _error_agregado(fallos)
        return self._respuesta(identificador, [], [])

    def _respuesta(
        self,
        identificador: Identificador,
        resultados: list[tuple[str, datetime, DatosPersona]],
        fallos: list[tuple[str, ErrorConsulta]],
    ) -> ConsultaRespuesta:

        candidatos = _agrupar_candidatos([datos for _, _, datos in resultados])
        estado = {0: EstadoConsulta.SIN_RESULTADOS, 1: EstadoConsulta.ENCONTRADO}.get(
            max(candidatos, default=0), EstadoConsulta.AMBIGUO
        )
        advertencias = [
            Advertencia(codigo=error.codigo, mensaje=error.mensaje, fuente=fuente)
            for fuente, error in fallos
        ]
        if estado is EstadoConsulta.AMBIGUO:
            advertencias.insert(
                0,
                Advertencia(
                    codigo="multiples_candidatos",
                    mensaje=f"Las fuentes informan {max(candidatos)} personas distintas.",
                ),
            )
        return ConsultaRespuesta(
            consulta=ConsultaEfectuada(tipo=identificador.tipo, numero=identificador.numero),
            estado=estado,
            resultados=[
                Resultado(fuente=fuente, consultado_en=momento, candidato=candidato, datos=datos)
                for (fuente, momento, datos), candidato in zip(resultados, candidatos, strict=True)
            ],
            advertencias=advertencias,
        )

    async def _consultar_proveedor(
        self, proveedor: ProveedorConsulta, identificador: Identificador
    ) -> tuple[datetime, list[DatosPersona]] | ErrorConsulta:
        nombre = proveedor.nombre
        try:
            async with asyncio.timeout(self._tiempo_limite):
                registros = await proveedor.consultar(identificador)
        except _PRIORIDAD_ERRORES as error:
            error.fuente = error.fuente or nombre
            return error
        except TimeoutError:
            return TiempoAgotado(f"{nombre} no respondió a tiempo.", fuente=nombre)
        except Exception:
            logger.exception("Fallo inesperado del proveedor %s", nombre)
            return FuenteNoDisponible(f"{nombre} falló al consultar.", fuente=nombre)

        if not isinstance(registros, list) or not all(
            isinstance(r, DatosPersona) for r in registros
        ):
            return RespuestaNoInterpretable(
                f"{nombre} devolvió un formato inesperado.", fuente=nombre
            )
        if any(not _coincide(identificador, r) for r in registros):
            return RespuestaNoInterpretable(
                f"{nombre} devolvió registros de otro identificador.", fuente=nombre
            )
        return self._reloj(), registros


def _coincide(identificador: Identificador, datos: DatosPersona) -> bool:
    campo = datos.dni if identificador.tipo is TipoIdentificador.DNI else datos.cuit_cuil
    return campo is None or campo == identificador.numero


def _agrupar_candidatos(registros: list[DatosPersona]) -> list[int]:
    """Asigna a cada registro el número de candidato (desde 1).

    Dos registros son la misma persona si comparten CUIT/CUIL. Un registro sin
    CUIT/CUIL se une al único candidato con igual nombre; si no lo hay, es un
    candidato propio (no se presume que sea la misma persona).
    """
    asignados = [0] * len(registros)
    por_cuit: dict[str, int] = {}
    por_nombre: dict[str, set[int]] = {}
    total = 0

    def registrar_nombre(datos: DatosPersona, candidato: int) -> None:
        if datos.nombre:
            por_nombre.setdefault(_clave_nombre(datos.nombre), set()).add(candidato)

    for i, datos in enumerate(registros):
        if datos.cuit_cuil is None:
            continue
        if datos.cuit_cuil not in por_cuit:
            total += 1
            por_cuit[datos.cuit_cuil] = total
        asignados[i] = por_cuit[datos.cuit_cuil]
        registrar_nombre(datos, asignados[i])

    for i, datos in enumerate(registros):
        if datos.cuit_cuil is not None:
            continue
        coincidentes = por_nombre.get(_clave_nombre(datos.nombre)) if datos.nombre else None
        if coincidentes and len(coincidentes) == 1:
            asignados[i] = next(iter(coincidentes))
        else:
            total += 1
            asignados[i] = total
            registrar_nombre(datos, total)
    return asignados


def _clave_nombre(nombre: str) -> str:
    """Compara nombres sin distinguir mayúsculas, tildes, comas ni orden de palabras."""
    texto = "".join(
        c for c in unicodedata.normalize("NFKD", nombre.casefold()) if not unicodedata.combining(c)
    )
    return " ".join(sorted(texto.replace(",", " ").split()))


def _error_agregado(fallos: list[tuple[str, ErrorConsulta]]) -> ErrorConsulta:
    if len(fallos) == 1:
        return fallos[0][1]
    clase = next(c for c in _PRIORIDAD_ERRORES if any(isinstance(e, c) for _, e in fallos))
    return clase(
        "Ninguna fuente pudo confirmar el resultado.",
        detalles=[
            {"fuente": fuente, "codigo": error.codigo, "mensaje": error.mensaje}
            for fuente, error in fallos
        ],
    )
