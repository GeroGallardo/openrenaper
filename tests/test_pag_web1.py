"""pag_web1 y dos fuentes con respuestas sintéticas; sin red ni datos personales reales."""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Configuracion, ConfiguracionPagWeb1
from app.consultas.modelos import DatosPersona
from app.errores import TiempoAgotado
from app.identificadores import normalizar
from app.main import crear_app
from app.proveedores.errores import (
    AccesoRestringido,
    FormatoDesconocido,
    FuenteTemporalmenteCaida,
    ResultadosIncompletos,
)
from app.proveedores.pag_web1.parser import interpretar
from app.proveedores.pag_web1.proveedor import ProveedorPagWeb1
from app.proveedores.resultados import PaginaObtenida
from app.recursos import proveedores_predeterminados
from tests.falsos import ProveedorFalso

HTML = (Path(__file__).parent / "fixtures/pag_web1/un_resultado.html").read_text(encoding="utf-8")
CONSULTA = normalizar("dni", "30111222")
VACIO = (
    '<main><section class="about-transform-section">'
    '<h2 class="about-title"><strong>"30111222"</strong></h2>'
    '<p>Se encontraron 0 resultados</p></section><section class="about-features-section">'
    '<p class="text-muted">No se encontraron resultados para tu búsqueda.</p></section></main>'
)


def test_extrae_los_seis_campos_publicos_sin_informes() -> None:
    [datos] = interpretar(HTML, CONSULTA)
    assert (datos.nombre, datos.dni, datos.cuit_cuil) == ("PEREZ JUAN", "30111222", "20301112220")
    assert datos.adicionales == {}
    assert datos.tipo_persona is None
    assert datos.edad == 45
    assert datos.sexo == "Masculino"
    assert datos.provincia_ubicacion == "PROVINCIA SINTETICA"


@pytest.mark.parametrize("tipo", ["cuit", "cuil"])
def test_cuit_cuil_requiere_coincidencia_exacta(tipo) -> None:
    html = HTML.replace('<strong>"30111222"', '<strong>"20301112220"')
    assert len(interpretar(html, normalizar(tipo, "20301112220"))) == 1
    html = html.replace('<strong>"20301112220"', '<strong>"27301112225"')
    assert interpretar(html, normalizar(tipo, "27301112225")) == []


def test_acepta_cuit_pertinente_sin_inventar_dni() -> None:
    html = HTML.replace('class="text-muted">DNI', 'class="text-muted">Otro')
    [datos] = interpretar(html, CONSULTA)
    assert datos.dni is None
    assert datos.cuit_cuil == "20301112220"


def test_dni_de_siete_digitos_y_cero_en_cuit() -> None:
    html = HTML.replace("30111222", "03011122").replace("30.111.222", "3.011.122")
    html = html.replace("20-03011122-0", "20-03011122-3")
    html = html.replace('<strong>"03011122"', '<strong>"3011122"')
    assert interpretar(html, normalizar("dni", "3011122"))[0].cuit_cuil == "20030111223"


def test_no_devuelve_tarjeta_de_otro_dni() -> None:
    html = HTML.replace('<strong>"30111222"', '<strong>"30111223"')
    assert interpretar(html, normalizar("dni", "30111223")) == []


def test_conserva_todos_los_cuil_pertinentes_como_candidatos() -> None:
    otra_tarjeta = (
        '<div class="card"><div class="card-body"><h3>GOMEZ ANA</h3>'
        '<div class="col-6"><div class="text-muted">CUIL</div>'
        '<div class="fw-bold">27-30111222-5</div></div></div></div>'
    )
    html = HTML.replace("1 resultado", "2 resultados")
    html = html.replace("</section>\n<!--", otra_tarjeta + "</section>\n<!--")
    assert [d.cuit_cuil for d in interpretar(html, CONSULTA)] == ["20301112220", "27301112225"]


def test_cero_solo_con_aviso_y_total_explicitos() -> None:
    assert interpretar(VACIO, CONSULTA) == []


@pytest.mark.parametrize(
    "html",
    [
        "",
        "<h1>Verificación requerida</h1>",
        HTML.replace('"30111222"', '"30111223"'),
        HTML.replace("Se encontraron 1 resultado", "Se encontraron 0 resultados"),
        HTML.replace("20-30111222-0", "20-30111222-1"),
        HTML.replace("30.111.222", "30.111.223"),
        HTML.replace('class="text-muted">DNI', 'class="text-muted">Otro').replace(
            'class="text-muted">CUIL', 'class="text-muted">Otro'
        ),
        VACIO.replace("No se encontraron resultados", "Contenido pendiente"),
        HTML.replace("<h3>PEREZ JUAN</h3>", ""),
    ],
)
def test_cambios_o_datos_inconsistentes_no_son_ausencia(html) -> None:
    with pytest.raises(FormatoDesconocido) as error:
        interpretar(html, CONSULTA)
    assert error.value.fuente == "pag_web1"
    assert "30111222" not in str(error.value)


def test_no_presenta_primera_pagina_como_busqueda_completa() -> None:
    with pytest.raises(ResultadosIncompletos):
        interpretar(HTML.replace("1 resultado", "2 resultados"), CONSULTA)


def test_nombre_danado_se_conserva_literal_sin_marcas_ni_perder_identificadores() -> None:
    [datos] = interpretar(HTML.replace("PEREZ JUAN", "JUAN P\ufffdREZ"), CONSULTA)
    assert datos.nombre == "JUAN P\ufffdREZ"
    assert datos.dni == "30111222"
    assert datos.cuit_cuil == "20301112220"
    assert datos.adicionales == {}


@pytest.mark.parametrize("columna", ["col-4", "col-md-6", "otro-estilo"])
def test_identificadores_no_dependen_de_las_clases_de_distribucion(columna) -> None:
    [datos] = interpretar(HTML.replace("col-6", columna), CONSULTA)
    assert datos.cuit_cuil == "20301112220"


class ObtenedorFalso:
    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)
        self.urls = []

    async def obtener(self, url, *, tiempo_limite):
        self.urls.append(url)
        respuesta = self.respuestas.pop(0)
        if isinstance(respuesta, Exception):
            raise respuesta
        if callable(respuesta):
            await respuesta()
        return PaginaObtenida(url=url, estado_http=200, html=respuesta)


def proveedor(*respuestas):
    obtenedor = ObtenedorFalso(*respuestas)
    config = ConfiguracionPagWeb1(
        url="https://pag-web1.example/buscar?q={numero}",
        intervalo_minimo=0,
        tiempo_solicitud=0.1,
        tiempo_total=0.2,
        espera_base=0,
    )
    return ProveedorPagWeb1(config, obtenedor=obtenedor), obtenedor


@pytest.mark.parametrize(
    "fallo,esperado",
    [
        (None, 200),
        (AccesoRestringido("bloqueado", fuente="pag_web1"), 503),
    ],
)
def test_api_con_dos_fuentes_y_fallo_parcial(fallo, esperado) -> None:
    pag_web1, obtenedor = proveedor(fallo or HTML)
    pag_web2 = ProveedorFalso(
        "pag_web2", [DatosPersona(cuit_cuil="20301112220", nombre="PEREZ JUAN")], demora=0.01
    )
    with TestClient(crear_app(proveedores=[pag_web1, pag_web2])) as cliente:
        r = cliente.post("/api/v1/consultas", json={"tipo": "dni", "numero": "30111222"})
    assert r.status_code == 200
    assert obtenedor.urls == ["https://pag-web1.example/buscar?q=30111222"]
    assert set(r.json()) == {"nombre", "dni", "cuit", "edad", "sexo", "provincia_ubicacion"}
    if esperado == 200:
        assert r.json()["edad"] == 45
        assert pag_web2.consultas == []
    else:
        assert r.json()["edad"] is None
        assert len(pag_web2.consultas) == 1
        assert len(obtenedor.urls) == 1


def test_api_acepta_tarjeta_con_nombre_danado_sin_anadir_marcas() -> None:
    p, _ = proveedor(HTML.replace("PEREZ JUAN", "JUAN P\ufffdREZ"))
    with TestClient(crear_app(proveedores=[p])) as cliente:
        r = cliente.post("/api/v1/consultas", json={"tipo": "dni", "numero": "30111222"})
    assert r.status_code == 200
    assert r.json()["nombre"] == "JUAN P\ufffdREZ"
    assert set(r.json()) == {"nombre", "dni", "cuit", "edad", "sexo", "provincia_ubicacion"}


def test_fuente_transitoria_se_reintenta() -> None:
    p, obtenedor = proveedor(FuenteTemporalmenteCaida("caída", fuente="pag_web1"), HTML)

    async def ejecutar():
        await p.iniciar()
        try:
            return await p.consultar(CONSULTA)
        finally:
            await p.cerrar()

    assert asyncio.run(ejecutar())[0].nombre == "PEREZ JUAN"
    assert len(obtenedor.urls) == 2


def test_plazo_total_se_respeta_aunque_obtenedor_no_respete_timeout() -> None:
    async def lento():
        await asyncio.sleep(1)

    p, _ = proveedor(lento, lento)
    with TestClient(crear_app(proveedores=[p])) as cliente:
        r = cliente.post("/api/v1/consultas", json={"tipo": "dni", "numero": "30111222"})
    assert r.status_code == 504
    assert r.json()["codigo"] == TiempoAgotado.codigo


def test_registro_predeterminado_y_fuentes_configurables_por_separado(monkeypatch) -> None:
    # Sin URL configurada no se registra ninguna fuente.
    assert proveedores_predeterminados(Configuracion()) == []
    monkeypatch.setenv("OPENRENAPER_PAG_WEB1_URL", "https://pag-web1.example/buscar?q={numero}")
    monkeypatch.setenv("OPENRENAPER_PAG_WEB2_URL", "https://pag-web2.example/buscar/{numero}")
    config = Configuracion.desde_entorno()
    assert [p.nombre for p in proveedores_predeterminados(config)] == ["pag_web1", "pag_web2"]
    monkeypatch.setenv("OPENRENAPER_PAG_WEB1_HABILITADO", "false")
    config = Configuracion.desde_entorno()
    assert [p.nombre for p in proveedores_predeterminados(config)] == ["pag_web2"]
