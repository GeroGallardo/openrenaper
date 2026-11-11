"""Regresiones del frontend observado el 2026-11-09; todos los datos son sintéticos."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.consultas.modelos import DatosPersona
from app.identificadores import normalizar
from app.main import crear_app
from app.proveedores.errores import FormatoDesconocido, ResultadosIncompletos
from app.proveedores.pag_web1.parser import interpretar
from tests.falsos import ProveedorFalso
from tests.test_pag_web1 import proveedor

HTML = (Path(__file__).parent / "fixtures/pag_web1/un_resultado_actual.html").read_text(
    encoding="utf-8"
)
CONSULTA = normalizar("dni", "30111222")
TARJETA = HTML[
    HTML.index('      <article class="result-card result-row">') : HTML.index("      </article>")
    + len("      </article>")
]
VACIO = HTML.replace(TARJETA, "").replace("<strong>1</strong>", "<strong>0</strong>")
VACIO = VACIO.replace(
    '<div class="results-list">',
    '<div class="empty-state panel"><p>No se encontraron resultados para tu búsqueda.</p></div>'
    '<div class="results-list">',
)


def test_lee_tarjeta_actual_y_omite_filtros_publicidad_e_informes() -> None:
    [datos] = interpretar(HTML, CONSULTA)
    assert datos.nombre == "JUAN PEREZ"
    assert datos.dni == "30111222"
    assert datos.cuit_cuil == "20301112220"
    assert datos.edad == 45
    assert datos.sexo == "Masculino"
    assert datos.provincia_ubicacion == "CIUDAD SINTETICA, PROVINCIA SINTETICA"
    assert datos.adicionales == {}


@pytest.mark.parametrize("tipo", ["cuit", "cuil"])
def test_consulta_actual_por_cuit_cuil(tipo: str) -> None:
    html = HTML.replace('<strong>"30111222"', '<strong>"20301112220"')
    assert interpretar(html, normalizar(tipo, "20301112220"))[0].dni == "30111222"


def test_frontend_actual_no_inventa_dni_si_solo_publica_cuit() -> None:
    html = HTML.replace('<div class="result-fact"><dt>DNI</dt><dd>30111222</dd></div>', "")
    [datos] = interpretar(html, CONSULTA)
    assert datos.dni is None
    assert datos.cuit_cuil == "20301112220"


def test_empresa_actual_puede_publicar_solo_cuit_y_nombre() -> None:
    html = HTML.replace(
        TARJETA,
        TARJETA[: TARJETA.index('          <div class="result-card-body">')]
        + '<div class="result-card-body"><dl class="result-facts">'
        '<div class="result-fact"><dt>CUIT</dt><dd>30301112226</dd></div>'
        "</dl></div></div></article>",
    )
    html = html.replace('<strong>"30111222"', '<strong>"30301112226"')
    [datos] = interpretar(html, normalizar("cuit", "30301112226"))
    assert datos.dni is datos.edad is datos.sexo is datos.provincia_ubicacion is None


def test_cero_actual_requiere_aviso_y_total() -> None:
    assert interpretar(VACIO, CONSULTA) == []
    with pytest.raises(FormatoDesconocido):
        interpretar(VACIO.replace("No se encontraron resultados", "Cargando"), CONSULTA)


@pytest.mark.parametrize(
    "html",
    [
        HTML.replace('"30111222"', '"30111223"'),
        HTML.replace("<dd>20301112220</dd>", "<dd>20301112221</dd>"),
        HTML.replace("<dd>30111222</dd>", "<dd>30111223</dd>"),
        HTML.replace("<dd>30111222</dd>", "<dd>30111222</dd><dd>30111223</dd>"),
        HTML.replace("<dt>DNI</dt><dd>30111222</dd>", "<dt>DNI</dt><dd></dd>"),
        HTML.replace(
            '<h2 class="result-card-title">JUAN <span class="result-card-sub">PEREZ</span></h2>', ""
        ),
        HTML.replace("<strong>1</strong>", "<strong>0</strong>"),
        HTML.replace('<p class="count">', '<p class="otro">'),
        HTML.replace(
            '<div class="results-main">',
            '<div class="results-main"></div><div class="results-main">',
        ),
        HTML.replace(
            '<div class="results-summary">',
            '<div class="results-summary"><p class="count">Se encontraron 1 resultado</p>',
        ),
    ],
)
def test_frontend_actual_rechaza_identificadores_y_estructura_inconsistentes(html: str) -> None:
    with pytest.raises(FormatoDesconocido):
        interpretar(html, CONSULTA)


def test_no_confunde_paginacion_actual_con_resultado_completo() -> None:
    with pytest.raises(ResultadosIncompletos):
        interpretar(HTML.replace("<strong>1</strong>", "<strong>20</strong>"), CONSULTA)


def test_preserva_candidatos_y_nombre_danado_del_frontend_actual() -> None:
    otra = TARJETA.replace("20301112220", "27301112225").replace("JUAN", "ANA")
    html = HTML.replace(TARJETA, TARJETA + otra).replace("<strong>1</strong>", "<strong>2</strong>")
    assert len(interpretar(html, CONSULTA)) == 2
    assert interpretar(HTML.replace("PEREZ", "P\ufffdREZ"), CONSULTA)[0].nombre == "JUAN P\ufffdREZ"


def test_api_actual_no_recurre_al_respaldo_tras_resultado_valido() -> None:
    pag_web1, _ = proveedor(HTML)
    respaldo = ProveedorFalso("pag_web2", [DatosPersona(dni="30111222")])
    with TestClient(crear_app(proveedores=[pag_web1, respaldo])) as cliente:
        respuesta = cliente.post("/api/v1/consultas", json={"tipo": "dni", "numero": "30111222"})
    assert respuesta.status_code == 200
    assert respuesta.json()["edad"] == 45
    assert respaldo.consultas == []
