"""Identificadores de personas aceptados por la API.

Este módulo es la única implementación de las reglas de identificadores y la
reutilizan las consultas y los proveedores (scraping).

Normalización (`normalizar`):

- El número se trata siempre como texto; nunca se convierte a entero, de modo
  que los ceros internos del CUIT/CUIL (por ejemplo `20-01234567-?`) se conservan.
- Se quitan los espacios exteriores y los separadores `.`, `-` y espacio. Solo se
  aceptan dígitos ASCII; cualquier otro carácter rechaza la entrada.
- DNI: 7 u 8 dígitos, sin cero inicial y sin guiones. Un cero inicial no se
  recorta en silencio: se rechaza para que quien consulta corrija el número.
  Quedan fuera los números menores a 1.000.000 (libretas antiguas).
- CUIT/CUIL: 11 dígitos con prefijo válido y dígito verificador (módulo 11).
  CUIL admite prefijos de persona física (20, 23, 24, 27); CUIT además los de
  persona jurídica (30, 33, 34).

Un formato válido no implica que el identificador exista: eso lo informan las
fuentes. Tampoco se deriva un CUIT/CUIL a partir de un DNI.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from app.errores import EntradaInvalida

PREFIJOS_CUIL = frozenset({"20", "23", "24", "27"})
PREFIJOS_CUIT = PREFIJOS_CUIL | {"30", "33", "34"}
PESOS_VERIFICADOR = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)

_CARACTERES_PERMITIDOS = re.compile(r"[0-9.\- ]+")
_SEPARADORES = re.compile(r"[.\- ]")


class TipoIdentificador(StrEnum):
    DNI = "dni"
    CUIT = "cuit"
    CUIL = "cuil"


@dataclass(frozen=True, slots=True)
class Identificador:
    """Identificador ya normalizado: `numero` contiene solo dígitos ASCII.

    Se conserva como texto para no perder ceros significativos.
    """

    tipo: TipoIdentificador
    numero: str


def digito_verificador(base: str) -> int | None:
    """Dígito verificador de los primeros 10 dígitos, o `None` si no existe.

    Cuando el cálculo da 10 no hay dígito posible: AFIP asigna otro prefijo.
    """
    resto = sum(int(d) * p for d, p in zip(base, PESOS_VERIFICADOR, strict=True)) % 11
    digito = 11 - resto
    if digito == 11:
        return 0
    if digito == 10:
        return None
    return digito


def normalizar(tipo: TipoIdentificador | str, numero: str) -> Identificador:
    """Valida y normaliza un identificador; lanza `EntradaInvalida` si no cumple."""
    try:
        tipo = TipoIdentificador(tipo)
    except ValueError:
        raise _invalido("tipo", "El tipo debe ser dni, cuit o cuil.") from None

    texto = numero.strip()
    if not texto or not _CARACTERES_PERMITIDOS.fullmatch(texto):
        raise _invalido("numero", "Solo se admiten dígitos y los separadores '.', '-' o espacio.")
    if tipo is TipoIdentificador.DNI and "-" in texto:
        raise _invalido("numero", "El DNI no admite guiones.")

    digitos = _SEPARADORES.sub("", texto)
    if tipo is TipoIdentificador.DNI:
        _validar_dni(digitos)
    else:
        _validar_cuit_cuil(tipo, digitos)
    return Identificador(tipo=tipo, numero=digitos)


def _validar_dni(digitos: str) -> None:
    if len(digitos) not in (7, 8):
        raise _invalido("numero", "El DNI debe tener 7 u 8 dígitos.")
    if digitos.startswith("0"):
        raise _invalido("numero", "El DNI no puede comenzar con 0.")


def _validar_cuit_cuil(tipo: TipoIdentificador, digitos: str) -> None:
    nombre = tipo.value.upper()
    if len(digitos) != 11:
        raise _invalido("numero", f"El {nombre} debe tener 11 dígitos.")
    prefijos = PREFIJOS_CUIL if tipo is TipoIdentificador.CUIL else PREFIJOS_CUIT
    if digitos[:2] not in prefijos:
        raise _invalido("numero", f"El prefijo {digitos[:2]} no corresponde a un {nombre}.")
    if digito_verificador(digitos[:10]) != int(digitos[10]):
        raise _invalido("numero", f"El dígito verificador del {nombre} no es correcto.")


def _invalido(campo: str, motivo: str) -> EntradaInvalida:
    return EntradaInvalida(motivo, detalles=[{"campo": campo, "motivo": motivo}])
