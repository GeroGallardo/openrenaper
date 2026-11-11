"""Fallos de las fuentes, clasificados por tipo y no por el texto del mensaje.

Todos heredan de los errores del dominio (`app.errores`), de modo que la capa
HTTP y `ConsultaService` los traducen sin conocer a cada proveedor. El atributo
`reintentable` decide si conviene repetir la consulta:

| Error                        | Dominio                    | Reintentable |
|------------------------------|----------------------------|--------------|
| `TiempoAgotadoFuente`        | `TiempoAgotado`            | sí           |
| `FuenteTemporalmenteCaida`   | `FuenteNoDisponible`       | sí           |
| `AccesoRestringido`          | `FuenteNoDisponible`       | no           |
| `FormatoDesconocido`         | `RespuestaNoInterpretable` | no           |
| `ResultadosIncompletos`      | `RespuestaNoInterpretable` | no           |

Ninguno se convierte en "sin resultados": la ausencia solo la confirma una
página de resultados interpretada correctamente.
"""

from typing import ClassVar

from app.errores import ErrorConsulta, FuenteNoDisponible, RespuestaNoInterpretable, TiempoAgotado


class TiempoAgotadoFuente(TiempoAgotado):
    """La fuente no respondió dentro del tiempo de una solicitud."""

    reintentable: ClassVar[bool] = True


class FuenteTemporalmenteCaida(FuenteNoDisponible):
    """Fallo de red o respuesta 5xx/429: puede resolverse al reintentar."""

    reintentable: ClassVar[bool] = True


class AccesoRestringido(FuenteNoDisponible):
    """La fuente rechazó el acceso (403, desafío o CAPTCHA). No se intenta eludirlo."""

    reintentable: ClassVar[bool] = False


class FormatoDesconocido(RespuestaNoInterpretable):
    """La fuente respondió con un contenido que no coincide con el formato conocido."""

    reintentable: ClassVar[bool] = False


class ResultadosIncompletos(RespuestaNoInterpretable):
    """La fuente informa más resultados de los que se pudieron obtener.

    Se informa como error para no presentar un subconjunto como si fuera completo.
    """

    reintentable: ClassVar[bool] = False


def es_reintentable(error: BaseException) -> bool:
    """Solo se reintentan los fallos marcados explícitamente como transitorios."""
    return isinstance(error, ErrorConsulta) and getattr(error, "reintentable", False) is True
