"""Clasificación de fallos y resultados tipados de los proveedores."""

import pytest

from app.api.errores import estado_http
from app.errores import FuenteNoDisponible, RespuestaNoInterpretable, TiempoAgotado
from app.proveedores.errores import (
    AccesoRestringido,
    FormatoDesconocido,
    FuenteTemporalmenteCaida,
    TiempoAgotadoFuente,
    es_reintentable,
)
from app.proveedores.resultados import PaginaObtenida, PaginaResultados, RegistroFuente


@pytest.mark.parametrize(
    ("error", "base", "codigo", "http", "reintentable"),
    [
        (TiempoAgotadoFuente("x"), TiempoAgotado, "tiempo_agotado", 504, True),
        (FuenteTemporalmenteCaida("x"), FuenteNoDisponible, "fuente_no_disponible", 503, True),
        (AccesoRestringido("x"), FuenteNoDisponible, "fuente_no_disponible", 503, False),
        (
            FormatoDesconocido("x"),
            RespuestaNoInterpretable,
            "respuesta_no_interpretable",
            502,
            False,
        ),
    ],
)
def test_fallos_se_traducen_a_errores_del_dominio(
    error: Exception, base: type, codigo: str, http: int, reintentable: bool
) -> None:
    assert isinstance(error, base)
    assert error.codigo == codigo
    assert estado_http(error) == http
    assert es_reintentable(error) is reintentable


def test_la_clasificacion_no_depende_del_mensaje() -> None:
    assert not es_reintentable(FormatoDesconocido("timeout temporal, reintentar"))
    assert es_reintentable(TiempoAgotadoFuente("formato desconocido"))


def test_errores_genericos_no_se_reintentan() -> None:
    assert not es_reintentable(FuenteNoDisponible("x"))
    assert not es_reintentable(ValueError("x"))


def test_sin_resultados_solo_cuando_no_hay_registros() -> None:
    assert PaginaResultados(registros=()).sin_resultados
    registro = RegistroFuente(denominacion="PEREZ JUAN", cuit="20-30111222-0")
    assert not PaginaResultados(registros=(registro,)).sin_resultados


def test_repr_no_expone_contenido_personal() -> None:
    pagina = PaginaObtenida(url="https://fuente/?q=30111222", estado_http=200, html="PEREZ JUAN")
    registro = RegistroFuente(denominacion="PEREZ JUAN", cuit="20301112220", atributos={"IVA": "x"})

    for texto in (repr(pagina), repr(registro)):
        assert "PEREZ" not in texto
        assert "30111222" not in texto
