"""Resultados tipados de cada etapa de un proveedor.

- `PaginaObtenida`: contenido descargado, todavía sin interpretar.
- `RegistroFuente`: un resultado tal como lo muestra la fuente (textos crudos).
- `PaginaResultados`: lo que se pudo interpretar de una página de resultados.

`PaginaResultados` sin registros significa que la fuente mostró explícitamente
que no hay resultados; cualquier otra situación es un error.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PaginaObtenida:
    url: str
    estado_http: int
    html: str

    def __repr__(self) -> str:
        # El HTML puede contener datos personales: nunca forma parte del repr.
        return f"PaginaObtenida(estado_http={self.estado_http}, bytes={len(self.html)})"


@dataclass(frozen=True, slots=True)
class RegistroFuente:
    """Un resultado de la fuente. `None` significa que la fuente no mostró el dato."""

    denominacion: str | None
    cuit: str | None
    tipo_persona: str | None = None
    atributos: dict[str, str] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"RegistroFuente(atributos={sorted(self.atributos)})"


@dataclass(frozen=True, slots=True)
class PaginaResultados:
    registros: tuple[RegistroFuente, ...]
    total_informado: int | None = None

    @property
    def sin_resultados(self) -> bool:
        return not self.registros
