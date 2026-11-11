"""Armado de la URL de búsqueda de cada fuente a partir de su plantilla.

Las direcciones de las fuentes no están en el código: se configuran por entorno
(ver `.env.example`) como una plantilla con el marcador `{numero}`.
"""

from urllib.parse import quote

from app.identificadores import Identificador

MARCADOR = "{numero}"


def url_busqueda(plantilla: str, identificador: Identificador) -> str:
    """Reemplaza `{numero}` por el número normalizado, codificado para URL."""
    if MARCADOR not in plantilla:
        raise ValueError(f"La URL de búsqueda debe incluir {MARCADOR}.")
    return plantilla.replace(MARCADOR, quote(identificador.numero, safe=""))
