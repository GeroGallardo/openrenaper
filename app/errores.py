"""Errores del dominio compartidos por consultas y proveedores.

Cada error tiene un código estable. La capa HTTP los traduce a estados
(ver `app.api.errores`); el dominio no conoce HTTP.
"""

from typing import Any, ClassVar


class ErrorConsulta(Exception):
    """Base de los errores esperables al consultar datos."""

    codigo: ClassVar[str] = "error_consulta"

    def __init__(
        self,
        mensaje: str,
        *,
        fuente: str | None = None,
        detalles: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.fuente = fuente
        self.detalles = detalles or []


class EntradaInvalida(ErrorConsulta):
    """El identificador recibido no cumple el formato exigido."""

    codigo = "entrada_invalida"


class SinResultados(ErrorConsulta):
    """Las fuentes consultadas no encontraron coincidencias."""

    codigo = "sin_resultados"


class ConsultaAmbigua(ErrorConsulta):
    """No se puede representar la consulta como una única persona."""

    codigo = "consulta_ambigua"


class TiempoAgotado(ErrorConsulta):
    """La fuente no respondió dentro del tiempo permitido."""

    codigo = "tiempo_agotado"


class FuenteNoDisponible(ErrorConsulta):
    """La fuente no pudo consultarse (caída, bloqueo, sin proveedores configurados)."""

    codigo = "fuente_no_disponible"


class RespuestaNoInterpretable(ErrorConsulta):
    """La fuente respondió, pero su contenido no pudo interpretarse con seguridad."""

    codigo = "respuesta_no_interpretable"
