"""Proveedor de pag_web2 de punta a punta con obtención falsa (sin red ni Chromium)."""

import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Configuracion, ConfiguracionPagWeb1, ConfiguracionPagWeb2, ModoObtencion
from app.consultas.modelos import DatosPersona, EstadoConsulta
from app.consultas.proveedores import ProveedorConsulta, RecursoGestionado
from app.consultas.servicio import ConsultaService
from app.identificadores import Identificador, TipoIdentificador, normalizar
from app.main import crear_app
from app.proveedores.ejecucion import Limitador
from app.proveedores.errores import (
    AccesoRestringido,
    FormatoDesconocido,
    FuenteTemporalmenteCaida,
    ResultadosIncompletos,
)
from app.proveedores.navegador import NavegadorCompartido
from app.proveedores.obtencion import ObtenedorNavegador
from app.proveedores.pag_web2.proveedor import ProveedorPagWeb2, pertinentes
from app.proveedores.resultados import PaginaObtenida
from app.proveedores.urls import url_busqueda
from app.recursos import proveedores_predeterminados

FIXTURES = Path(__file__).parent / "fixtures" / "pag_web2"
URL_PAG_WEB2 = "https://pag-web2.example/buscar/{numero}"
RAPIDA = ConfiguracionPagWeb2(
    url=URL_PAG_WEB2,
    modo=ModoObtencion.NAVEGADOR,
    intervalo_minimo=0,
    espera_base=0,
    tiempo_solicitud=1,
    tiempo_total=2,
)


def html(nombre: str) -> str:
    return (FIXTURES / nombre).read_text(encoding="utf-8")


class ObtenedorFalso:
    """Devuelve, en orden, páginas o errores."""

    def __init__(self, *respuestas: str | Exception) -> None:
        self.respuestas = list(respuestas)
        self.urls: list[str] = []
        self.iniciado = self.cerrado = False

    async def iniciar(self) -> None:
        self.iniciado = True

    async def cerrar(self) -> None:
        self.cerrado = True

    async def obtener(self, url: str, *, tiempo_limite: float) -> PaginaObtenida:
        self.urls.append(url)
        respuesta = self.respuestas.pop(0)
        if isinstance(respuesta, Exception):
            raise respuesta
        return PaginaObtenida(url=url, estado_http=200, html=respuesta)


def proveedor(*respuestas: str | Exception, **config) -> tuple[ProveedorPagWeb2, ObtenedorFalso]:
    obtenedor = ObtenedorFalso(*respuestas)
    configuracion = ConfiguracionPagWeb2(**(vars(RAPIDA) | config))
    p = ProveedorPagWeb2(
        configuracion,
        obtenedor=obtenedor,
        limitador=Limitador(max_concurrentes=1, intervalo_minimo=0),
    )
    return p, obtenedor


def consultar(p: ProveedorPagWeb2, tipo: str, numero: str):
    async def ejecutar():
        await p.iniciar()
        try:
            return await ConsultaService([p], tiempo_limite=5).consultar(tipo, numero)
        finally:
            await p.cerrar()

    return asyncio.run(ejecutar())


def test_cumple_los_contratos() -> None:
    p, _ = proveedor()
    assert isinstance(p, ProveedorConsulta)
    assert isinstance(p, RecursoGestionado)
    assert p.tipos == frozenset(TipoIdentificador)


@pytest.mark.parametrize(
    ("tipo", "entrada", "numero"),
    [
        ("dni", "30.111.222", "30111222"),
        ("dni", "3.011.122", "3011122"),
        ("cuit", "30-71234567-1", "30712345671"),
        ("cuil", "20-30111222-0", "20301112220"),
    ],
)
def test_url_de_busqueda_usa_el_numero_normalizado(tipo, entrada, numero) -> None:
    url = url_busqueda("https://pag-web2.example/buscar/{numero}", normalizar(tipo, entrada))
    assert url == f"https://pag-web2.example/buscar/{numero}"


def test_dni_con_varios_candidatos_es_ambiguo() -> None:
    p, obtenedor = proveedor(html("varios_resultados.html"))
    respuesta = consultar(p, "dni", "30.111.222")

    assert obtenedor.urls == ["https://pag-web2.example/buscar/30111222"]
    assert respuesta.estado is EstadoConsulta.AMBIGUO
    assert [(r.candidato, r.datos.cuit_cuil) for r in respuesta.resultados] == [
        (1, "20301112220"),
        (2, "27301112225"),
    ]
    for resultado in respuesta.resultados:
        assert resultado.fuente == "pag_web2"
        assert resultado.consultado_en.tzinfo is not None
        assert resultado.datos.dni is None  # no se inventa a partir del CUIT/CUIL


def test_dni_con_un_candidato() -> None:
    p, _ = proveedor(html("un_resultado.html"))
    respuesta = consultar(p, "dni", "30111222")
    assert respuesta.estado is EstadoConsulta.ENCONTRADO
    [resultado] = respuesta.resultados
    assert resultado.datos.nombre == "PEREZ JUAN"


def test_dni_de_siete_digitos() -> None:
    registros = [DatosPersona(cuit_cuil="20030111223"), DatosPersona(cuit_cuil="20301112220")]
    elegidos = pertinentes(Identificador(TipoIdentificador.DNI, "3011122"), registros)
    assert [r.cuit_cuil for r in elegidos] == ["20030111223"]


def test_dni_descarta_personas_juridicas_y_registros_sin_cuit() -> None:
    registros = [
        DatosPersona(cuit_cuil="30301112225"),
        DatosPersona(nombre="SIN CUIT"),
        DatosPersona(cuit_cuil="27301112225"),
    ]
    elegidos = pertinentes(Identificador(TipoIdentificador.DNI, "30111222"), registros)
    assert [r.cuit_cuil for r in elegidos] == ["27301112225"]


def test_cuil_conserva_solo_la_coincidencia_exacta() -> None:
    p, _ = proveedor(html("varios_resultados.html"))
    respuesta = consultar(p, "cuil", "27-30111222-5")
    assert respuesta.estado is EstadoConsulta.ENCONTRADO
    [resultado] = respuesta.resultados
    assert resultado.datos.nombre == "GOMEZ ANA"


def test_registros_del_mismo_cuit_son_un_candidato() -> None:
    pagina = (
        '<div class="results">'
        '<div class="hit"><span class="cuit">30-71234567-1</span></div>'
        '<div class="hit"><h2 class="denominacion">EMPRESA SINTETICA</h2>'
        '<span class="cuit">30-71234567-1</span></div></div>'
    )
    p, _ = proveedor(pagina)
    respuesta = consultar(p, "cuit", "30712345671")
    assert respuesta.estado is EstadoConsulta.ENCONTRADO
    assert [r.candidato for r in respuesta.resultados] == [1, 1]
    assert respuesta.resultados[0].datos.nombre is None


def test_sin_resultados_confirmado_por_la_fuente() -> None:
    p, _ = proveedor(html("sin_resultados.html"))
    assert consultar(p, "dni", "30111223").estado is EstadoConsulta.SIN_RESULTADOS


def test_resultados_no_pertinentes_dan_sin_resultados() -> None:
    p, _ = proveedor(html("un_resultado.html"))
    assert consultar(p, "dni", "40111222").estado is EstadoConsulta.SIN_RESULTADOS


@pytest.mark.parametrize("tipo", ["dni", "cuit", "cuil"])
@pytest.mark.parametrize("incluir_completo", [False, True])
def test_registro_sin_identificador_no_confirma_ausencia(tipo: str, incluir_completo: bool) -> None:
    incompleto = '<div class="hit"><h2 class="denominacion">PERSONA SINTETICA</h2></div>'
    completo = (
        '<div class="hit"><h2 class="denominacion">OTRA PERSONA SINTETICA</h2>'
        '<span class="cuit">20-30111222-0</span></div>'
    )
    registros = incompleto + (completo if incluir_completo else "")
    cantidad = 2 if incluir_completo else 1
    pagina = (
        f'<div class="results"><span class="results-count">{cantidad} resultados</span>'
        f"{registros}</div>"
    )
    p, obtenedor = proveedor(pagina)
    numero = "30111222" if tipo == "dni" else "20301112220"
    with pytest.raises(FormatoDesconocido):
        consultar(p, tipo, numero)
    assert len(obtenedor.urls) == 1


@pytest.mark.parametrize(
    ("respuesta", "error"),
    [
        (html("inesperado.html"), FormatoDesconocido),
        (html("incompleto.html"), ResultadosIncompletos),
        (html("cuit_invalido.html"), FormatoDesconocido),
        (AccesoRestringido("captcha", fuente="pag_web2"), AccesoRestringido),
    ],
)
def test_fallos_no_se_convierten_en_sin_resultados(respuesta, error: type[Exception]) -> None:
    p, obtenedor = proveedor(respuesta, html("un_resultado.html"))
    with pytest.raises(error):
        consultar(p, "dni", "30111222")
    assert len(obtenedor.urls) == 1  # no se reintenta un fallo permanente


def test_reintenta_fallos_transitorios() -> None:
    p, obtenedor = proveedor(
        FuenteTemporalmenteCaida("caída", fuente="pag_web2"), html("un_resultado.html")
    )
    assert consultar(p, "dni", "30111222").estado is EstadoConsulta.ENCONTRADO
    assert len(obtenedor.urls) == 2


def test_agota_los_intentos() -> None:
    caidas = [FuenteTemporalmenteCaida("caída", fuente="pag_web2") for _ in range(3)]
    p, obtenedor = proveedor(*caidas, intentos=2)
    with pytest.raises(FuenteTemporalmenteCaida):
        consultar(p, "dni", "30111222")
    assert len(obtenedor.urls) == 2


def test_sin_iniciar_no_consulta() -> None:
    p, obtenedor = proveedor(html("un_resultado.html"))
    with pytest.raises(AccesoRestringido):
        asyncio.run(p.consultar(Identificador(TipoIdentificador.DNI, "30111222")))
    assert obtenedor.urls == []


def test_inicio_y_cierre_del_obtenedor() -> None:
    p, obtenedor = proveedor()

    async def ejecutar() -> None:
        await p.iniciar()
        await p.cerrar()

    asyncio.run(ejecutar())
    assert obtenedor.iniciado and obtenedor.cerrado


def test_si_chromium_no_inicia_la_fuente_queda_no_disponible() -> None:
    async def lanzar_fallido():
        raise RuntimeError("Executable doesn't exist")

    p = ProveedorPagWeb2(RAPIDA, navegador=NavegadorCompartido("pag_web2", lanzar=lanzar_fallido))

    async def ejecutar() -> None:
        await p.iniciar()
        try:
            await p.consultar(Identificador(TipoIdentificador.DNI, "30111222"))
        finally:
            await p.cerrar()

    with pytest.raises(AccesoRestringido):
        asyncio.run(ejecutar())


def test_modo_navegador_libera_paginas_y_contextos_ante_errores() -> None:
    """Integra NavegadorCompartido + ObtenedorNavegador con objetos falsos."""
    cerrados: list[str] = []

    class Pagina:
        url = "https://pag-web2.example/"

        async def goto(self, *args, **kwargs):
            raise RuntimeError("fallo inesperado del sitio")

        async def close(self) -> None:
            cerrados.append("pagina")

    class Contexto:
        async def new_page(self) -> Pagina:
            return Pagina()

        async def close(self) -> None:
            cerrados.append("contexto")

    class Navegador:
        def is_connected(self) -> bool:
            return True

        async def new_context(self, **_):
            return Contexto()

        async def close(self) -> None:
            cerrados.append("navegador")

    class Playwright:
        async def stop(self) -> None:
            cerrados.append("playwright")

    async def lanzar():
        return Playwright(), Navegador()

    navegador = NavegadorCompartido("pag_web2", lanzar=lanzar)
    p = ProveedorPagWeb2(
        RAPIDA,
        obtenedor=ObtenedorNavegador("pag_web2", navegador.abrir_pagina),
        navegador=navegador,
    )

    async def ejecutar() -> None:
        await p.iniciar()
        try:
            await p.consultar(Identificador(TipoIdentificador.DNI, "30111222"))
        finally:
            assert navegador.activas == 0
            await p.cerrar()

    with pytest.raises(RuntimeError):
        asyncio.run(ejecutar())
    assert cerrados == ["pagina", "contexto", "navegador", "playwright"]


# --- Registro en la aplicación -------------------------------------------------


def test_registro_predeterminado_segun_configuracion() -> None:
    [p] = proveedores_predeterminados(
        Configuracion(
            pag_web1=ConfiguracionPagWeb1(habilitado=False),
            pag_web2=ConfiguracionPagWeb2(url=URL_PAG_WEB2),
        )
    )
    assert isinstance(p, ProveedorPagWeb2)
    deshabilitado = Configuracion(
        pag_web2=ConfiguracionPagWeb2(habilitado=False),
        pag_web1=ConfiguracionPagWeb1(habilitado=False),
    )
    assert proveedores_predeterminados(deshabilitado) == []


def test_modo_http_explicito_no_inicia_chromium(monkeypatch) -> None:
    cliente_http = httpx.AsyncClient
    solicitudes: list[httpx.Request] = []

    def responder(solicitud: httpx.Request) -> httpx.Response:
        solicitudes.append(solicitud)
        return httpx.Response(200, text=html("un_resultado.html"))

    def crear_cliente(**opciones):
        opciones["transport"] = httpx.MockTransport(responder)
        return cliente_http(**opciones)

    def no_iniciar_navegador(*args, **kwargs):
        pytest.fail("El modo HTTP explícito no debe necesitar Chromium")

    monkeypatch.setattr("app.proveedores.obtencion.httpx.AsyncClient", crear_cliente)
    monkeypatch.setattr(
        "app.proveedores.pag_web2.proveedor.NavegadorCompartido", no_iniciar_navegador
    )
    [p] = proveedores_predeterminados(
        Configuracion(
            pag_web2=ConfiguracionPagWeb2(url=URL_PAG_WEB2, modo=ModoObtencion.HTTP),
            pag_web1=ConfiguracionPagWeb1(habilitado=False),
        )
    )
    respuesta = consultar(p, "cuit", "20301112220")
    assert respuesta.estado is EstadoConsulta.ENCONTRADO
    assert len(solicitudes) == 1
    assert solicitudes[0].url.path == "/buscar/20301112220"
    assert not solicitudes[0].url.query


def test_el_tiempo_total_no_supera_el_del_servicio() -> None:
    p = ProveedorPagWeb2(
        ConfiguracionPagWeb2(url=URL_PAG_WEB2, tiempo_total=60, modo=ModoObtencion.HTTP),
        tiempo_maximo=20,
    )
    assert p._tiempo_total == 20


def test_configuracion_desde_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENRENAPER_PAG_WEB2_MODO", "HTTP")
    monkeypatch.setenv("OPENRENAPER_PAG_WEB2_HABILITADO", "false")
    monkeypatch.setenv("OPENRENAPER_PAG_WEB2_MAX_CONCURRENTES", "4")
    configuracion = ConfiguracionPagWeb2.desde_entorno()
    assert configuracion.modo is ModoObtencion.HTTP
    assert configuracion.habilitado is False
    assert configuracion.max_concurrentes == 4


def test_api_de_punta_a_punta_con_ciclo_de_vida() -> None:
    p, obtenedor = proveedor(html("varios_resultados.html"))
    app = crear_app(proveedores=[p], configuracion=Configuracion(tiempo_limite_proveedor=5))

    with TestClient(app) as cliente:
        respuesta = cliente.post("/api/v1/consultas", json={"tipo": "dni", "numero": "30111222"})
        assert obtenedor.iniciado

    assert obtenedor.cerrado
    assert respuesta.status_code == 409
    assert respuesta.json()["codigo"] == "consulta_ambigua"


def test_api_traduce_cambios_de_formato_a_502() -> None:
    p, _ = proveedor(html("inesperado.html"))
    app = crear_app(proveedores=[p], configuracion=Configuracion(tiempo_limite_proveedor=5))
    with TestClient(app) as cliente:
        respuesta = cliente.post("/api/v1/consultas", json={"tipo": "dni", "numero": "30111222"})
    assert respuesta.status_code == 502
    assert respuesta.json()["codigo"] == "respuesta_no_interpretable"
    assert respuesta.json()["fuente"] == "pag_web2"


def test_api_no_devuelve_datos_de_contenido_ofuscado() -> None:
    contenido = '<div class="paywalled-content pigeon-blur">' + html("un_resultado.html") + "</div>"
    p, _ = proveedor(contenido)
    app = crear_app(proveedores=[p], configuracion=Configuracion(tiempo_limite_proveedor=5))
    with TestClient(app) as cliente:
        respuesta = cliente.post("/api/v1/consultas", json={"tipo": "dni", "numero": "30111222"})
    assert respuesta.status_code == 503
    assert respuesta.json()["codigo"] == "fuente_no_disponible"
    assert "resultados" not in respuesta.json()


def test_los_logs_no_registran_identificadores(caplog: pytest.LogCaptureFixture) -> None:
    caidas = [FuenteTemporalmenteCaida("caída", fuente="pag_web2") for _ in range(3)]
    p, _ = proveedor(*caidas)
    with caplog.at_level("DEBUG"), pytest.raises(FuenteTemporalmenteCaida):
        consultar(p, "dni", "30111222")
    assert "30111222" not in caplog.text
