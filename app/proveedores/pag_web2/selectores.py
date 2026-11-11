"""Selectores CSS de la página de búsqueda de pag_web2.

Concentran lo que depende del marcado de la fuente. Si la fuente cambia,
actualizar este archivo y los fixtures sintéticos.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Selectores:
    contenedor: str = "div.results"
    resultado: str = "div.hit"
    denominacion: str = "h2.denominacion"
    cuit: str = "span.cuit"
    facetas: str = "div.doc-facets"
    sin_resultados: str = ".no-results"
    total: str = ".results-count"
    contenido_restringido: str = ".paywalled-content.pigeon-blur"


SELECTORES = Selectores()
