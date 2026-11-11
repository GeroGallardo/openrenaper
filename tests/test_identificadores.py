"""Reglas de normalización y validación de DNI, CUIT y CUIL (datos sintéticos)."""

import pytest

from app.errores import EntradaInvalida
from app.identificadores import Identificador, TipoIdentificador, digito_verificador, normalizar

DNI = TipoIdentificador.DNI
CUIT = TipoIdentificador.CUIT
CUIL = TipoIdentificador.CUIL


@pytest.mark.parametrize(
    ("tipo", "entrada", "esperado"),
    [
        (DNI, "30111222", "30111222"),
        (DNI, "30.111.222", "30111222"),
        (DNI, " 30 111 222 ", "30111222"),
        (DNI, "1234567", "1234567"),
        ("dni", "30111222", "30111222"),
        (CUIL, "20301112220", "20301112220"),
        (CUIL, "20-30111222-0", "20301112220"),
        (CUIL, "27-30111222-5", "27301112225"),
        (CUIT, "30-71234567-1", "30712345671"),
        (CUIT, "20 30111222 0", "20301112220"),
    ],
)
def test_normaliza_identificadores_validos(
    tipo: TipoIdentificador | str, entrada: str, esperado: str
) -> None:
    assert normalizar(tipo, entrada) == Identificador(TipoIdentificador(tipo), esperado)


def test_conserva_ceros_significativos_del_cuit() -> None:
    identificador = normalizar(CUIT, "20-01234567-5")
    assert identificador.numero == "20012345675"
    assert isinstance(identificador.numero, str)


@pytest.mark.parametrize(
    ("tipo", "entrada", "motivo"),
    [
        (DNI, "", "Solo se admiten"),
        (DNI, "   ", "Solo se admiten"),
        (DNI, "30111222a", "Solo se admiten"),
        (DNI, "３0111222", "Solo se admiten"),
        (DNI, "٣0111222", "Solo se admiten"),
        (DNI, "+30111222", "Solo se admiten"),
        (DNI, "30-111-222", "no admite guiones"),
        (DNI, "123456", "7 u 8 dígitos"),
        (DNI, "123456789", "7 u 8 dígitos"),
        (DNI, "01234567", "no puede comenzar con 0"),
        (DNI, "...", "7 u 8 dígitos"),
        (CUIT, "2030111222", "11 dígitos"),
        (CUIT, "203011122201", "11 dígitos"),
        (CUIT, "10-30111222-0", "prefijo 10"),
        (CUIL, "30-71234567-1", "prefijo 30"),
        (CUIT, "20-30111222-1", "dígito verificador"),
        (CUIL, "27-30111222-0", "dígito verificador"),
        ("pasaporte", "30111222", "tipo debe ser"),
    ],
)
def test_rechaza_formatos_invalidos(
    tipo: TipoIdentificador | str, entrada: str, motivo: str
) -> None:
    with pytest.raises(EntradaInvalida, match=motivo) as error:
        normalizar(tipo, entrada)
    assert error.value.detalles[0]["campo"] in {"tipo", "numero"}


@pytest.mark.parametrize(
    ("base", "digito"),
    [("2030111222", 0), ("2730111222", 5), ("3071234567", 1), ("2001234567", 5)],
)
def test_digito_verificador_modulo_11(base: str, digito: int) -> None:
    assert digito_verificador(base) == digito


def test_base_sin_digito_verificador_posible_se_rechaza_siempre() -> None:
    assert digito_verificador("2010000005") is None
    for digito in range(10):
        with pytest.raises(EntradaInvalida):
            normalizar(CUIT, f"2010000005{digito}")
