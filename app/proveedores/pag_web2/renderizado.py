"""Espera el contenido que el JavaScript de la fuente habilita normalmente.

No altera estilos, permisos, cookies ni el contenido de la página. La versión
ofuscada carece de los enlaces de detalle que acompañan los nombres reales.
"""

from typing import Any

from playwright.async_api import TimeoutError as TiempoAgotadoPlaywright

from app.proveedores.errores import AccesoRestringido
from app.proveedores.pag_web2.parser import FUENTE
from app.proveedores.pag_web2.selectores import SELECTORES

CONTENIDO_LISTO = """() => {
    const visible = el => {
        if (!el || !el.getClientRects().length) return false;
        for (let e = el; e; e = e.parentElement) {
            const s = getComputedStyle(e);
            if (s.display === 'none' || s.visibility !== 'visible' ||
                s.filter !== 'none' || Number(s.opacity) === 0 ||
                e.hasAttribute('unselectable')) return false;
        }
        return true;
    };
    const zona = document.querySelector('div.results');
    if (!zona) return false;
    const items = [...zona.querySelectorAll('div.hit')];
    if (!items.length) {
        return !zona.querySelector('.paywalled-content.pigeon-blur') &&
            visible(zona.querySelector('.no-results'));
    }
    return items.every(item => {
        const nombre = item.querySelector('a.denominacion[href*="detalle/"] h2.denominacion');
        const cuit = item.querySelector('span.cuit');
        return visible(nombre) && nombre.textContent.trim() &&
            visible(cuit) && cuit.textContent.trim();
    });
}"""


async def esperar_resultados(pagina: Any, tiempo_limite: float) -> None:
    try:
        await pagina.wait_for_function(CONTENIDO_LISTO, timeout=tiempo_limite * 1000)
    except TiempoAgotadoPlaywright:
        if await pagina.locator(SELECTORES.contenido_restringido).count():
            raise AccesoRestringido(
                "pag_web2 no habilitó resultados visibles dentro del plazo.", fuente=FUENTE
            ) from None
        raise
