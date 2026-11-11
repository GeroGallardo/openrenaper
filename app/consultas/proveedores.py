"""Contrato que implementan los proveedores de fuentes públicas (scraping).

Un proveedor:

- declara `nombre` (estable, aparece en cada resultado) y los `tipos` que consulta;
- en `consultar` devuelve los registros que la fuente informa para ese identificador;
- devuelve una lista vacía solo cuando la fuente confirmó que no hay resultados;
- ante fallos lanza `TiempoAgotado`, `FuenteNoDisponible` o
  `RespuestaNoInterpretable` (de `app.errores`), nunca una lista vacía;
- no infiere datos: lo que la fuente no muestra queda en `None`.

Si necesita recursos (navegador, cliente HTTP), implementa también `iniciar` y
`cerrar`; la aplicación los invoca una vez al arrancar y al terminar.
"""

from typing import Protocol, runtime_checkable

from app.consultas.modelos import DatosPersona
from app.identificadores import Identificador, TipoIdentificador


@runtime_checkable
class ProveedorConsulta(Protocol):
    nombre: str
    tipos: frozenset[TipoIdentificador]

    async def consultar(self, identificador: Identificador) -> list[DatosPersona]: ...


@runtime_checkable
class RecursoGestionado(Protocol):
    """Recurso con inicio y cierre explícitos (opcional para proveedores y extractores)."""

    async def iniciar(self) -> None: ...

    async def cerrar(self) -> None: ...
