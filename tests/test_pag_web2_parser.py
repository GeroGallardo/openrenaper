"""Parsing y normalización de pag_web2 con HTML sintético (ver fixtures/pag_web2)."""

from pathlib import Path

import pytest

from app.consultas.modelos import TipoPersona
from app.proveedores.errores import AccesoRestringido, FormatoDesconocido, ResultadosIncompletos
from app.proveedores.pag_web2.normalizacion import a_datos_persona
from app.proveedores.pag_web2.parser import interpretar
from app.proveedores.resultados import RegistroFuente

FIXTURES = Path(__file__).parent / "fixtures" / "pag_web2"


def html(nombre: str) -> str:
    return (FIXTURES / nombre).read_text(encoding="utf-8")


def test_un_resultado_con_atributos() -> None:
    pagina = interpretar(html("un_resultado.html"))

    [registro] = pagina.registros
    assert pagina.total_informado == 1
    assert registro.denominacion == "PEREZ JUAN"
    assert registro.cuit == "20-30111222-0"
    assert registro.tipo_persona == "Persona Física (masculino)"
    assert registro.atributos == {"Ganancias": "No Inscripto", "IVA": "Responsable Monotributo"}


def test_rechaza_contenido_ofuscado_aunque_tenga_resultados_validos() -> None:
    contenido = '<div class="paywalled-content pigeon-blur">' + html("un_resultado.html") + "</div>"
    with pytest.raises(AccesoRestringido):
        interpretar(contenido)


def test_acepta_contenido_que_la_pagina_ya_habilito() -> None:
    contenido = '<div class="paywalled-content">' + html("un_resultado.html") + "</div>"
    assert interpretar(contenido).registros[0].denominacion == "PEREZ JUAN"


def test_contenido_renderizado_puede_conservar_la_clase_pigeon_blur() -> None:
    contenido = (
        '<div class="paywalled-content pigeon-blur"><div class="results"><div class="hit">'
        '<a class="denominacion" href="detalle/20301112220/perez-juan.html">'
        '<h2 class="denominacion">PEREZ JUAN</h2></a>'
        '<span class="cuit">20-30111222-0</span></div></div></div>'
    )
    assert interpretar(contenido).registros[0].denominacion == "PEREZ JUAN"
    with pytest.raises(AccesoRestringido):
        interpretar(
            contenido.replace(
                'class="paywalled-content', 'unselectable="on" class="paywalled-content'
            )
        )


def test_varios_resultados_conservan_el_orden() -> None:
    pagina = interpretar(html("varios_resultados.html"))

    assert [r.cuit for r in pagina.registros] == [
        "20-30111222-0",
        "27-30111222-5",
        "20-03011122-3",
    ]
    assert pagina.registros[1].atributos == {"Empleador": "No"}


def test_sin_resultados_explicito() -> None:
    pagina = interpretar(html("sin_resultados.html"))
    assert pagina.sin_resultados
    assert pagina.total_informado == 0


def test_campos_ausentes_quedan_en_none() -> None:
    sin_nombre, empresa, sin_cuit = interpretar(html("campos_ausentes.html")).registros

    assert sin_nombre.denominacion is None
    assert sin_nombre.tipo_persona is None
    assert sin_nombre.atributos == {}
    assert empresa.denominacion == "EMPRESA FICTICIA S.A."
    assert empresa.atributos == {}  # "Categoría:" sin valor no es un dato
    assert sin_cuit.cuit is None
    assert sin_cuit.atributos == {"otros": "Tipo desconocido por la fuente"}


@pytest.mark.parametrize(
    "contenido",
    [
        html("inesperado.html"),
        "",
        "<html><body><p>Mantenimiento</p></body></html>",
        # Contenedor sin resultados ni aviso de ausencia: no se asume que no hay datos.
        '<div class="results"></div>',
        # Contradicciones internas.
        '<div class="results"><div class="results-count">2</div>'
        '<div class="no-results">x</div></div>',
        '<div class="results"><div class="no-results">x</div><div class="hit"></div></div>',
        '<div class="results"><div class="results-count">sin cifra</div>'
        '<div class="hit"></div></div>',
    ],
)
def test_html_inesperado_es_formato_desconocido(contenido: str) -> None:
    with pytest.raises(FormatoDesconocido):
        interpretar(contenido)


def test_resultados_incompletos_no_se_presentan_como_completos() -> None:
    with pytest.raises(ResultadosIncompletos):
        interpretar(html("incompleto.html"))


def test_los_errores_no_incluyen_el_html() -> None:
    with pytest.raises(FormatoDesconocido) as error:
        interpretar(html("inesperado.html"))
    assert "sintetico" not in str(error.value)
    assert error.value.fuente == "pag_web2"


# --- Normalización ------------------------------------------------------------


def test_normaliza_persona_fisica_sin_inventar_dni() -> None:
    [registro] = interpretar(html("un_resultado.html")).registros
    datos = a_datos_persona(registro)

    assert datos.cuit_cuil == "20301112220"
    assert datos.nombre == "PEREZ JUAN"
    assert datos.tipo_persona is TipoPersona.FISICA
    assert datos.dni is None
    assert datos.desconocidos == ["dni"]
    assert datos.adicionales == {"Ganancias": "No Inscripto", "IVA": "Responsable Monotributo"}


def test_normaliza_persona_juridica() -> None:
    _, empresa, _ = interpretar(html("campos_ausentes.html")).registros
    datos = a_datos_persona(empresa)
    assert datos.tipo_persona is TipoPersona.JURIDICA
    assert datos.cuit_cuil == "30712345671"


def test_tipo_no_se_deduce_del_prefijo() -> None:
    datos = a_datos_persona(RegistroFuente(denominacion=None, cuit="30-71234567-1"))
    assert datos.tipo_persona is None
    assert set(datos.desconocidos) == {"dni", "nombre", "tipo_persona"}


def test_tipo_desconocido_se_conserva_como_adicional() -> None:
    registro = RegistroFuente(denominacion="X", cuit=None, tipo_persona="Persona Sucesión")
    datos = a_datos_persona(registro)
    assert datos.tipo_persona is None
    assert datos.adicionales == {"tipo_persona_fuente": "Persona Sucesión"}


def test_cuit_invalido_es_formato_desconocido() -> None:
    [registro] = interpretar(html("cuit_invalido.html")).registros
    with pytest.raises(FormatoDesconocido):
        a_datos_persona(registro)
