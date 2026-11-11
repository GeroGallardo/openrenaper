"""Contratos compartidos con los módulos de scraping."""

import pytest
from pydantic import ValidationError

from app.consultas.modelos import DatosPersona
from app.consultas.proveedores import ProveedorConsulta, RecursoGestionado
from app.identificadores import Identificador, TipoIdentificador


class ProveedorFalso:
    nombre = "falso"
    tipos = frozenset({TipoIdentificador.DNI})

    async def consultar(self, identificador: Identificador) -> list[DatosPersona]:
        return []


def test_implementaciones_cumplen_los_protocolos() -> None:
    assert isinstance(ProveedorFalso(), ProveedorConsulta)
    assert not isinstance(ProveedorFalso(), RecursoGestionado)


@pytest.mark.parametrize("campos", [{"dni": "30.111.222"}, {"cuit_cuil": "20-30111222-1"}])
def test_proveedores_entregan_identificadores_solo_con_digitos(campos: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        DatosPersona(**campos)


def test_datos_persona_rechaza_campos_no_declarados() -> None:
    with pytest.raises(ValidationError):
        DatosPersona(domicilio="Calle Falsa 123")
