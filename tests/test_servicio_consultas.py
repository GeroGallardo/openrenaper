"""Estados y errores de ConsultaService con proveedores falsos."""

import asyncio

import pytest

from app.consultas.modelos import ConsultaRespuesta, DatosPersona, EstadoConsulta
from app.consultas.servicio import ConsultaService
from app.errores import (
    EntradaInvalida,
    ErrorConsulta,
    FuenteNoDisponible,
    RespuestaNoInterpretable,
    TiempoAgotado,
)
from app.identificadores import Identificador, TipoIdentificador
from tests.falsos import MOMENTO, ProveedorFalso

PERSONA = DatosPersona(dni="30111222", cuit_cuil="20301112220", nombre="PEREZ JUAN")
OTRA_PERSONA = DatosPersona(dni="30111222", cuit_cuil="27301112225", nombre="GOMEZ ANA")


def consultar(proveedores: list[ProveedorFalso], tipo: str, numero: str) -> ConsultaRespuesta:
    servicio = ConsultaService(proveedores, tiempo_limite=0.05, reloj=lambda: MOMENTO)
    return asyncio.run(servicio.consultar(tipo, numero))


def test_encontrado_identifica_fuente_y_momento() -> None:
    proveedor = ProveedorFalso("fuente-a", [PERSONA])
    respuesta = consultar([proveedor], "dni", "30.111.222")

    assert respuesta.estado is EstadoConsulta.ENCONTRADO
    assert respuesta.consulta.numero == "30111222"
    assert proveedor.consultas == [Identificador(TipoIdentificador.DNI, "30111222")]
    [resultado] = respuesta.resultados
    assert (resultado.fuente, resultado.consultado_en, resultado.candidato) == (
        "fuente-a",
        MOMENTO,
        1,
    )
    assert respuesta.advertencias == []


def test_misma_persona_en_varias_fuentes_no_es_ambigua() -> None:
    sin_cuit = DatosPersona(dni="30111222", nombre="Juan, Perez")
    respuesta = consultar(
        [ProveedorFalso("a", [PERSONA]), ProveedorFalso("b", [PERSONA, sin_cuit])],
        "dni",
        "30111222",
    )
    assert respuesta.estado is EstadoConsulta.ENCONTRADO
    assert [r.candidato for r in respuesta.resultados] == [1]
    assert [r.fuente for r in respuesta.resultados] == ["a"]


def test_sin_resultados_solo_si_todas_las_fuentes_lo_confirman() -> None:
    respuesta = consultar([ProveedorFalso("a"), ProveedorFalso("b")], "cuit", "20-30111222-0")
    assert respuesta.estado is EstadoConsulta.SIN_RESULTADOS
    assert respuesta.resultados == []


@pytest.mark.parametrize("primera", ["pag_web1", "pag_web2"])
def test_prioridad_fija_no_consulta_respaldo_si_primaria_encuentra(primera) -> None:
    primaria = ProveedorFalso(primera, [PERSONA], demora=0.01)
    respaldo = ProveedorFalso("respaldo", [OTRA_PERSONA])
    respuesta = consultar([primaria, respaldo], "dni", "30111222")
    assert [r.fuente for r in respuesta.resultados] == [primera]
    assert respaldo.consultas == []
    assert respuesta.advertencias == []


@pytest.mark.parametrize("resultado_rapido", [[], FuenteNoDisponible("caída")])
def test_respuesta_vacia_o_error_no_impide_consultar_la_segunda(resultado_rapido) -> None:
    rapido = (
        ProveedorFalso("rapida", error=resultado_rapido)
        if isinstance(resultado_rapido, Exception)
        else ProveedorFalso("rapida")
    )
    respuesta = consultar(
        [rapido, ProveedorFalso("segunda", [PERSONA], demora=0.01)], "dni", "30111222"
    )
    assert [r.fuente for r in respuesta.resultados] == ["segunda"]


def test_timeout_de_primaria_habilita_respaldo() -> None:
    primaria = ProveedorFalso("pag_web1", demora=1)
    respaldo = ProveedorFalso("pag_web2", [PERSONA])
    respuesta = consultar([primaria, respaldo], "dni", "30111222")
    assert [r.fuente for r in respuesta.resultados] == ["pag_web2"]
    assert respuesta.advertencias[0].codigo == "tiempo_agotado"


def test_varios_candidatos_dan_ambiguo_sin_elegir_el_primero() -> None:
    respuesta = consultar([ProveedorFalso("a", [PERSONA, OTRA_PERSONA])], "dni", "30111222")
    assert respuesta.estado is EstadoConsulta.AMBIGUO
    assert [r.candidato for r in respuesta.resultados] == [1, 2]
    assert respuesta.advertencias[0].codigo == "multiples_candidatos"


def test_registro_sin_cuit_ni_nombre_coincidente_es_otro_candidato() -> None:
    desconocido = DatosPersona(dni="30111222")
    respuesta = consultar([ProveedorFalso("a", [PERSONA, desconocido])], "dni", "30111222")
    assert respuesta.estado is EstadoConsulta.AMBIGUO


def test_entrada_invalida_no_consulta_proveedores() -> None:
    proveedor = ProveedorFalso("a", [PERSONA])
    with pytest.raises(EntradaInvalida):
        consultar([proveedor], "cuit", "20-30111222-1")
    assert proveedor.consultas == []


def test_no_infiere_cuit_desde_dni() -> None:
    solo_dni = ProveedorFalso("solo-dni", [PERSONA], tipos=frozenset({TipoIdentificador.DNI}))
    with pytest.raises(FuenteNoDisponible):
        consultar([solo_dni], "cuil", "20301112220")
    assert solo_dni.consultas == []


def test_sin_proveedores_configurados_es_fuente_no_disponible() -> None:
    with pytest.raises(FuenteNoDisponible):
        consultar([], "dni", "30111222")


@pytest.mark.parametrize(
    ("proveedor", "esperado"),
    [
        (ProveedorFalso(error=TiempoAgotado("lento")), TiempoAgotado),
        (ProveedorFalso(demora=1), TiempoAgotado),
        (ProveedorFalso(error=FuenteNoDisponible("caída")), FuenteNoDisponible),
        (ProveedorFalso(error=RespuestaNoInterpretable("html")), RespuestaNoInterpretable),
        (ProveedorFalso(error=RuntimeError("bug")), FuenteNoDisponible),
        (ProveedorFalso(error=EntradaInvalida("propia")), FuenteNoDisponible),
    ],
)
def test_fallo_de_proveedor_nunca_es_sin_resultados(
    proveedor: ProveedorFalso, esperado: type[ErrorConsulta]
) -> None:
    with pytest.raises(esperado) as error:
        consultar([proveedor], "dni", "30111222")
    assert type(error.value) is esperado
    assert error.value.fuente == proveedor.nombre


def test_fallo_parcial_sin_resultados_confirmados_es_error() -> None:
    with pytest.raises(TiempoAgotado) as error:
        consultar(
            [ProveedorFalso("a"), ProveedorFalso("b", error=TiempoAgotado("lento"))],
            "dni",
            "30111222",
        )
    assert error.value.fuente == "b"


def test_fallo_parcial_con_resultados_queda_como_advertencia() -> None:
    respuesta = consultar(
        [
            ProveedorFalso("b", error=FuenteNoDisponible("caída")),
            ProveedorFalso("a", [PERSONA]),
        ],
        "dni",
        "30111222",
    )
    assert respuesta.estado is EstadoConsulta.ENCONTRADO
    [advertencia] = respuesta.advertencias
    assert (advertencia.codigo, advertencia.fuente) == ("fuente_no_disponible", "b")


def test_varios_fallos_informan_el_mas_especifico_con_detalle() -> None:
    with pytest.raises(RespuestaNoInterpretable) as error:
        consultar(
            [
                ProveedorFalso("a", error=FuenteNoDisponible("caída")),
                ProveedorFalso("b", error=RespuestaNoInterpretable("html")),
            ],
            "dni",
            "30111222",
        )
    assert [d["fuente"] for d in error.value.detalles] == ["a", "b"]


def test_registro_de_otro_identificador_es_respuesta_no_interpretable() -> None:
    otro = DatosPersona(dni="30111223")
    with pytest.raises(RespuestaNoInterpretable):
        consultar([ProveedorFalso("a", [otro])], "dni", "30111222")
