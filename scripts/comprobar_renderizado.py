"""Prueba Chromium con respuestas sintéticas, sin consultar servicios externos.

Desde el repo: docker compose exec -T api python - < scripts/comprobar_renderizado.py
"""

import asyncio

from playwright.async_api import async_playwright

from app.identificadores import normalizar
from app.proveedores.errores import AccesoRestringido, TiempoAgotadoFuente
from app.proveedores.obtencion import ObtenedorNavegador
from app.proveedores.pag_web1.parser import interpretar as interpretar_pag_web1
from app.proveedores.pag_web1.renderizado import esperar_resultados as esperar_pag_web1
from app.proveedores.pag_web2.parser import interpretar
from app.proveedores.pag_web2.renderizado import esperar_resultados

URL = "https://fuente.invalid/search/30111222"
RESULTADO = (
    '<div class="hit"><a class="denominacion" '
    'href="detalle/20301112220/perez-juan.html"><h2 class="denominacion">PEREZ JUAN</h2></a>'
    '<span class="cuit">20-30111222-0</span></div>'
)
INICIAL = (
    '<div class="results"><div class="paywalled-content pigeon-blur">'
    '<div class="hit"><a class="denominacion"><h2 class="denominacion">OFUSCADO</h2></a>'
    '<span class="cuit">20-30111222-0</span></div></div></div>'
)


async def comprobar() -> None:
    async with async_playwright() as playwright:
        navegador = await playwright.chromium.launch(
            headless=True, args=["--disable-dev-shm-usage"]
        )
        try:

            async def obtener(html: str, tiempo: float = 2, esperar=esperar_resultados):
                async def abrir():
                    contexto = await navegador.new_context()
                    # Toda solicitud se resuelve localmente, incluso la del dominio ficticio.
                    await contexto.route(
                        "**/*",
                        lambda ruta: ruta.fulfill(
                            status=200, content_type="text/html; charset=utf-8", body=html
                        ),
                    )
                    return contexto, await contexto.new_page()

                return await ObtenedorNavegador(
                    "prueba-local", abrir, esperar_contenido=esperar
                ).obtener(URL, tiempo_limite=tiempo)

            # El JavaScript simula el reemplazo normal y demorado de la fuente.
            demorado = INICIAL + (
                '<script>setTimeout(() => {document.querySelector(".paywalled-content")'
                f".innerHTML = {RESULTADO!r};}}, 400);</script>"
            )
            pagina = await obtener(demorado)
            assert interpretar(pagina.html).registros[0].denominacion == "PEREZ JUAN"

            for bloqueado in (
                INICIAL,
                '<div class="results"><div class="paywalled-content pigeon-blur" '
                f'style="display:none">{RESULTADO}</div></div>',
                '<div class="results"><div class="paywalled-content pigeon-blur" '
                f'unselectable="on">{RESULTADO}</div></div>',
            ):
                try:
                    await obtener(bloqueado, tiempo=0.4)
                except AccesoRestringido:
                    pass
                else:
                    raise AssertionError("Se aceptó contenido ofuscado, oculto o restringido")

            pagina = await obtener('<div class="results"><div class="no-results">0</div></div>')
            assert interpretar(pagina.html).sin_resultados
            print("Chromium: renderizado demorado, ofuscado, oculto, restringido y vacío OK")

            pag_web1 = (
                '<main><section class="about-transform-section">'
                '<h2 class="about-title"><strong>"30111222"</strong></h2>'
                "<p>Se encontraron 1 resultado</p></section>"
                '<section class="about-features-section">'
                '<div class="card"><div class="card-body"><h3>JUAN <span>P�REZ</span></h3>'
                '<div class="col-md-6"><div class="text-muted">DNI</div>'
                '<div class="fw-bold">30111222</div></div>'
                '<div class="col-6"><div class="text-muted">CUIT</div>'
                '<div class="fw-bold">20301112220</div></div>'
                '<div class="col-6"><div class="text-muted">Edad</div>'
                '<div class="fw-bold">23 años</div></div>'
                '<div class="col-6"><div class="text-muted">Sexo</div>'
                '<div class="fw-bold">Masculino</div></div>'
                '<div class="col-12"><div class="text-muted">Provincia / Ubicación</div>'
                '<div class="fw-bold">PROVINCIA SINTETICA</div></div>'
                "</div></div></section></main>"
            )
            pagina = await obtener(pag_web1, esperar=esperar_pag_web1)
            [datos] = interpretar_pag_web1(pagina.html, normalizar("dni", "30111222"))
            assert datos.nombre == "JUAN P�REZ"
            assert datos.dni == "30111222"
            assert datos.cuit_cuil == "20301112220"
            assert datos.edad == 23
            assert datos.sexo == "Masculino"
            assert datos.provincia_ubicacion == "PROVINCIA SINTETICA"
            assert datos.adicionales == {}
            try:
                await obtener(
                    pag_web1.replace('class="card"', 'class="card" style="display:none"'),
                    tiempo=0.4,
                    esperar=esperar_pag_web1,
                )
            except TiempoAgotadoFuente:
                pass
            else:
                raise AssertionError("Se aceptó una tarjeta oculta de pag_web1")
            print("pag_web1: Chromium y Scrapling con contenido sintético OK")

            actual = (
                '<main><section class="results-hero">'
                '<h1 class="results-title"><strong>"30111222"</strong></h1></section>'
                '<section class="results-section"><div class="results-main">'
                '<div class="results-summary"><p class="count">'
                "Se encontraron <strong>1</strong> resultado</p></div>"
                '<div class="results-list"><article class="result-card">'
                '<div class="result-card-head"><h2 class="result-card-title">'
                'JUAN <span>P�REZ</span></h2></div><div class="result-card-body">'
                '<dl class="result-facts">'
                '<div class="result-fact"><dt>DNI</dt><dd>30111222</dd></div>'
                '<div class="result-fact"><dt>CUIT</dt><dd>20301112220</dd></div>'
                '<div class="result-fact"><dt>Edad</dt><dd>23 años</dd></div>'
                '<div class="result-fact"><dt>Sexo</dt><dd>Masculino</dd></div>'
                '<div class="result-fact"><dt>Provincia / Ubicación</dt>'
                '<dd><i aria-hidden="true"></i>CIUDAD SINTETICA</dd></div>'
                "</dl></div></article></div></div></section></main>"
            )
            pagina = await obtener(actual, esperar=esperar_pag_web1)
            [datos] = interpretar_pag_web1(pagina.html, normalizar("dni", "30111222"))
            assert datos.nombre == "JUAN P�REZ"
            assert datos.dni == "30111222" and datos.cuit_cuil == "20301112220"
            assert datos.edad == 23 and datos.sexo == "Masculino"
            assert datos.provincia_ubicacion == "CIUDAD SINTETICA"

            # Una tarjeta aún oculta debe esperar al renderizado antes de interpretarse.
            oculta = actual.replace(
                'class="result-card"', 'class="result-card" style="display:none"'
            )
            demorada = oculta + (
                '<script>setTimeout(() => {document.querySelector(".result-card")'
                '.style.display = "";}, 200);</script>'
            )
            pagina = await obtener(demorada, esperar=esperar_pag_web1)
            assert interpretar_pag_web1(pagina.html, normalizar("dni", "30111222"))[0].dni

            vacio = actual[: actual.index('<div class="results-list">')] + (
                '<div class="empty-state"><p>No se encontraron resultados para tu búsqueda.</p>'
                "</div></div></section></main>"
            )
            vacio = vacio.replace("<strong>1</strong>", "<strong>0</strong>")
            pagina = await obtener(vacio, esperar=esperar_pag_web1)
            assert interpretar_pag_web1(pagina.html, normalizar("dni", "30111222")) == []
            for incompleto in (
                oculta,
                vacio.replace("No se encontraron resultados", "Cargando"),
                actual.replace("<dd>30111222</dd>", '<dd style="display:none">30111222</dd>'),
            ):
                try:
                    await obtener(incompleto, tiempo=0.4, esperar=esperar_pag_web1)
                except TiempoAgotadoFuente:
                    pass
                else:
                    raise AssertionError("Se aceptó un resultado actual oculto o aún incompleto")
            print("pag_web1 actual: seis campos, renderizado demorado y cero explícito OK")
        finally:
            await navegador.close()


if __name__ == "__main__":
    asyncio.run(comprobar())
