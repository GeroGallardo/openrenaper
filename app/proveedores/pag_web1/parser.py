"""Interpreta los seis campos de las tarjetas públicas de búsqueda.

No sigue enlaces a informes ni extrae datos de contacto, domicilio o financieros.
Los selectores son explícitos: el modo adaptativo de Scrapling queda desactivado
para que un cambio de estructura no seleccione silenciosamente otro campo.
"""

import re
import unicodedata

from scrapling import Selector

from app.consultas.modelos import DatosPersona
from app.errores import EntradaInvalida
from app.identificadores import PREFIJOS_CUIL, Identificador, TipoIdentificador, normalizar
from app.proveedores.errores import FormatoDesconocido, ResultadosIncompletos
from app.proveedores.pag_web1.estructura import ESTRUCTURAS, EstructuraBusqueda

FUENTE = "pag_web1"
_TOTAL = re.compile(r"^Se encontraron ([0-9]+) resultados?$", re.IGNORECASE)


def _texto(elemento: Selector) -> str:
    return " ".join(elemento.get_all_text(separator=" ", strip=True).split())


def _fallo() -> FormatoDesconocido:
    return FormatoDesconocido(
        "pag_web1 no mostró una búsqueda completa con identificadores verificables.", fuente=FUENTE
    )


def _etiqueta(texto: str) -> str:
    texto = "".join(
        c for c in unicodedata.normalize("NFKD", texto.upper()) if not unicodedata.combining(c)
    )
    return re.sub(r"\s*/\s*", "/", texto.rstrip(":"))


def interpretar(html: str, consulta: Identificador) -> list[DatosPersona]:
    pagina = Selector(html, adaptive=False)
    disenos = [e for e in ESTRUCTURAS if pagina.css(e.cabecera)]
    if len(disenos) != 1:
        raise _fallo()
    estructura = disenos[0]
    cabeceras = pagina.css(estructura.cabecera)
    if len(cabeceras) != 1 or _texto(cabeceras[0]).strip('"“”') != consulta.numero:
        raise _fallo()
    totales = [
        coincidencia
        for p in pagina.css(estructura.total)
        if (coincidencia := _TOTAL.fullmatch(_texto(p)))
    ]
    contenedores = pagina.css(estructura.resultados)
    if len(totales) != 1 or len(contenedores) != 1:
        raise _fallo()
    total = int(totales[0][1])
    tarjetas = contenedores[0].css(estructura.tarjetas)
    if total > len(tarjetas):
        raise ResultadosIncompletos(
            "pag_web1 informa más resultados que las tarjetas disponibles.", fuente=FUENTE
        )
    if total != len(tarjetas):
        raise _fallo()
    if total == 0:
        avisos = contenedores[0].css(estructura.aviso_vacio)
        if not any(_texto(p).startswith("No se encontraron resultados") for p in avisos):
            raise _fallo()
        return []
    registros = [_tarjeta(tarjeta, estructura) for tarjeta in tarjetas]
    return [datos for datos in registros if _pertinente(consulta, datos)]


def _tarjeta(tarjeta: Selector, estructura: EstructuraBusqueda) -> DatosPersona:
    nombres = tarjeta.css(estructura.nombre)
    if len(nombres) != 1 or not (nombre := _texto(nombres[0])):
        raise _fallo()
    campos: dict[str, str] = {}
    complementarios: dict[str, str | int] = {}
    for rotulo in tarjeta.css(estructura.rotulos):
        etiqueta = _etiqueta(_texto(rotulo))
        if etiqueta not in {
            "DNI",
            "CUIT",
            "CUIL",
            "CUIT/CUIL",
            "EDAD",
            "SEXO",
            "PROVINCIA",
            "PROVINCIA/UBICACION",
        }:
            continue
        valores = rotulo.xpath(estructura.valores)
        if etiqueta in {"EDAD", "SEXO", "PROVINCIA", "PROVINCIA/UBICACION"}:
            if len(valores) == 1 and (valor := _texto(valores[0])):
                if etiqueta == "EDAD":
                    if coincidencia := re.fullmatch(
                        r"([0-9]{1,3})(?:\s+a[nñ]os?)?", valor, re.IGNORECASE
                    ):
                        complementarios["edad"] = int(coincidencia[1])
                else:
                    campo_extra = "sexo" if etiqueta == "SEXO" else "provincia_ubicacion"
                    complementarios[campo_extra] = valor
            continue
        campo = "dni" if etiqueta == "DNI" else "cuit_cuil"
        if len(valores) != 1 or campo in campos:
            raise _fallo()
        try:
            tipo = TipoIdentificador.DNI if campo == "dni" else TipoIdentificador.CUIT
            campos[campo] = normalizar(tipo, _texto(valores[0])).numero
        except EntradaInvalida:
            raise _fallo() from None
    if not campos:
        raise _fallo()
    dni, cuit = campos.get("dni"), campos.get("cuit_cuil")
    if dni and cuit and (cuit[:2] not in PREFIJOS_CUIL or cuit[2:10] != dni.zfill(8)):
        raise _fallo()
    return DatosPersona(nombre=nombre, **campos, **complementarios)


def _pertinente(consulta: Identificador, datos: DatosPersona) -> bool:
    if consulta.tipo is not TipoIdentificador.DNI:
        return datos.cuit_cuil == consulta.numero
    if datos.dni is not None:
        return datos.dni == consulta.numero
    cuit = datos.cuit_cuil
    return cuit is not None and cuit[:2] in PREFIJOS_CUIL and cuit[2:10] == consulta.numero.zfill(8)
