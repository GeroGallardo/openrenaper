"""Interpretación de la página de búsqueda de pag_web2.

Devuelve registros crudos (textos tal como los muestra la fuente) o lanza:

- `FormatoDesconocido` si la página no es una búsqueda reconocible
  (desafío, CAPTCHA, rediseño) o si sus partes se contradicen;
- `ResultadosIncompletos` si la fuente informa más resultados que los listados.

Cero resultados solo se acepta cuando la página lo indica explícitamente.
"""

import re

from bs4 import BeautifulSoup, Tag

from app.proveedores.errores import AccesoRestringido, FormatoDesconocido, ResultadosIncompletos
from app.proveedores.pag_web2.selectores import SELECTORES, Selectores
from app.proveedores.resultados import PaginaResultados, RegistroFuente

FUENTE = "pag_web2"

_ETIQUETAS_IDENTIFICADOR = frozenset({"cuit", "cuil"})
_TIPO_PERSONA = re.compile(r"^persona\s", re.IGNORECASE)
_VINETAS = "•·  \t"
_DIGITOS = re.compile(r"\d+")


def interpretar(html: str, selectores: Selectores = SELECTORES) -> PaginaResultados:
    sopa = BeautifulSoup(html, "html.parser")
    protegidos = sopa.select(selectores.contenido_restringido)
    if any(
        zona.has_attr("unselectable")
        or not zona.select(selectores.resultado)
        or any(
            resultado.select_one('a.denominacion[href*="detalle/"] h2.denominacion') is None
            for resultado in zona.select(selectores.resultado)
        )
        for zona in protegidos
    ):
        raise AccesoRestringido(
            "pag_web2 no habilitó el contenido; no se devuelven datos ofuscados.", fuente=FUENTE
        )
    contenedor = sopa.select_one(selectores.contenedor)
    if contenedor is None:
        raise FormatoDesconocido(
            "La página de pag_web2 no tiene el formato de búsqueda esperado.", fuente=FUENTE
        )

    resultados = contenedor.select(selectores.resultado)
    total = _total_informado(contenedor, selectores)
    marca_sin_resultados = contenedor.select_one(selectores.sin_resultados) is not None

    if not resultados:
        if not marca_sin_resultados or (total is not None and total != 0):
            raise FormatoDesconocido(
                "pag_web2 no listó resultados ni indicó que no los hubiera.", fuente=FUENTE
            )
        return PaginaResultados(registros=(), total_informado=total)

    if marca_sin_resultados or total == 0:
        raise FormatoDesconocido(
            "pag_web2 listó resultados e indicó a la vez que no los hay.", fuente=FUENTE
        )
    if total is not None and total > len(resultados):
        raise ResultadosIncompletos(
            f"pag_web2 informa {total} resultados pero lista {len(resultados)}.",
            fuente=FUENTE,
        )
    registros = tuple(_interpretar_resultado(r, selectores) for r in resultados)
    return PaginaResultados(registros=registros, total_informado=total)


def _total_informado(contenedor: Tag, selectores: Selectores) -> int | None:
    elemento = contenedor.select_one(selectores.total)
    if elemento is None:
        return None
    numeros = _DIGITOS.findall(elemento.get_text())
    if len(numeros) != 1:
        raise FormatoDesconocido(
            "No se pudo interpretar la cantidad de resultados de pag_web2.", fuente=FUENTE
        )
    return int(numeros[0])


def _interpretar_resultado(resultado: Tag, selectores: Selectores) -> RegistroFuente:
    tipo_persona: str | None = None
    atributos: dict[str, str] = {}
    otros: list[str] = []

    facetas = resultado.select_one(selectores.facetas)
    for linea in _lineas(facetas) if facetas is not None else []:
        etiqueta, separador, valor = linea.partition(":")
        etiqueta, valor = etiqueta.strip(), _texto(valor)
        if separador and etiqueta.casefold() in _ETIQUETAS_IDENTIFICADOR:
            continue  # el identificador se toma de su propio elemento
        if separador and etiqueta:
            if valor:  # una etiqueta sin valor no es un dato
                atributos[etiqueta] = valor
        elif _TIPO_PERSONA.match(linea):
            tipo_persona = linea
        else:
            otros.append(linea)
    if otros:
        atributos["otros"] = "; ".join(otros)

    return RegistroFuente(
        denominacion=_texto_de(resultado.select_one(selectores.denominacion)),
        cuit=_texto_de(resultado.select_one(selectores.cuit)),
        tipo_persona=tipo_persona,
        atributos=atributos,
    )


def _lineas(facetas: Tag) -> list[str]:
    """Separa las facetas por `<br>` y quita viñetas y espacios."""
    for salto in facetas.find_all("br"):
        salto.replace_with("\n")
    lineas = (_texto(linea.strip(_VINETAS)) for linea in facetas.get_text().split("\n"))
    return [linea for linea in lineas if linea]


def _texto_de(elemento: Tag | None) -> str | None:
    return _texto(elemento.get_text()) if elemento is not None else None


def _texto(valor: str) -> str | None:
    limpio = " ".join(valor.replace(" ", " ").split())
    return limpio or None
