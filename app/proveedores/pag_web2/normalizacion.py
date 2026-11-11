"""Conversión de registros crudos de pag_web2 en `DatosPersona`.

- El CUIT/CUIL se valida con `app.identificadores`; uno inválido indica que se
  interpretó mal la página (`FormatoDesconocido`), no se corrige.
- El DNI queda en `None`: la fuente no lo muestra y no se deriva del CUIT/CUIL.
- `tipo_persona` se toma solo del rótulo de la fuente, nunca del prefijo.
  Un rótulo desconocido queda en `adicionales["tipo_persona_fuente"]`.
- El resto de los atributos pasa sin normalizar a `adicionales`.
"""

import unicodedata

from app.consultas.modelos import DatosPersona, TipoPersona
from app.errores import EntradaInvalida
from app.identificadores import TipoIdentificador, normalizar
from app.proveedores.errores import FormatoDesconocido
from app.proveedores.pag_web2.parser import FUENTE
from app.proveedores.resultados import RegistroFuente

_TIPOS = {
    "persona fisica": TipoPersona.FISICA,
    "persona juridica": TipoPersona.JURIDICA,
}


def a_datos_persona(registro: RegistroFuente) -> DatosPersona:
    adicionales = dict(registro.atributos)
    tipo = _tipo_persona(registro.tipo_persona)
    if registro.tipo_persona is not None and tipo is None:
        adicionales["tipo_persona_fuente"] = registro.tipo_persona
    return DatosPersona(
        dni=None,
        cuit_cuil=_cuit(registro.cuit),
        nombre=registro.denominacion,
        tipo_persona=tipo,
        adicionales=adicionales,
    )


def _cuit(texto: str | None) -> str | None:
    if texto is None:
        return None
    try:
        return normalizar(TipoIdentificador.CUIT, texto).numero
    except EntradaInvalida:
        raise FormatoDesconocido(
            "pag_web2 mostró un CUIT/CUIL que no supera la validación.", fuente=FUENTE
        ) from None


def _tipo_persona(texto: str | None) -> TipoPersona | None:
    if texto is None:
        return None
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFKD", texto.casefold()) if not unicodedata.combining(c)
    )
    for prefijo, tipo in _TIPOS.items():
        if sin_tildes == prefijo or sin_tildes.startswith(f"{prefijo} "):
            return tipo
    return None
