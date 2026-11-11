"""Espera únicamente la sección pública de resultados, sin abrir informes."""

import json
from dataclasses import asdict
from typing import Any

from app.proveedores.pag_web1.estructura import ESTRUCTURAS

CONTENIDO_LISTO = r"""() => {
    const visible = el => {
        if (!el || !el.getClientRects().length) return false;
        for (let e = el; e; e = e.parentElement) {
            const s = getComputedStyle(e);
            if (s.display === 'none' || s.visibility !== 'visible' ||
                s.filter !== 'none' || Number(s.opacity) === 0) return false;
        }
        return true;
    };
    const disenos = __ESTRUCTURAS__;
    const conocidos = disenos.filter(e => document.querySelector(e.cabecera));
    if (conocidos.length !== 1) return false;
    const e = conocidos[0];
    const cabecera = document.querySelector(e.cabecera);
    const resultados = document.querySelector(e.resultados);
    if (!visible(cabecera) || !visible(resultados)) return false;
    const totales = [...document.querySelectorAll(e.total)].filter(el =>
        /^Se encontraron [0-9]+ resultados?$/i.test(el.textContent.trim().replace(/\s+/g, ' '))
    );
    if (totales.length !== 1 || !visible(totales[0])) return false;
    const tarjetas = [...resultados.querySelectorAll(e.tarjetas)];
    const total = Number(totales[0].textContent.match(/[0-9]+/)[0]);
    if (total === 0 && tarjetas.length === 0) {
        return [...resultados.querySelectorAll(e.aviso_vacio)].some(el => visible(el) &&
            el.textContent.trim().startsWith('No se encontraron resultados'));
    }
    if (!tarjetas.length) return false;
    return tarjetas.every(card => {
        if (!visible(card.querySelector(e.nombre))) return false;
        return [...card.querySelectorAll(e.rotulos)].every(rotulo => {
            const etiqueta = rotulo.textContent.trim().toUpperCase()
                .replace(/:$/, '').replace(/\s*\/\s*/g, '/');
            const valores = document.evaluate(e.valores, rotulo, null,
                XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
            return !['DNI', 'CUIT', 'CUIL', 'CUIT/CUIL'].includes(etiqueta) ||
                (valores.snapshotLength === 1 && visible(valores.snapshotItem(0)));
        });
    });
}""".replace("__ESTRUCTURAS__", json.dumps([asdict(e) for e in ESTRUCTURAS]))


async def esperar_resultados(pagina: Any, tiempo_limite: float) -> None:
    # El parser verifica después la consulta, el total y todos los identificadores.
    await pagina.wait_for_function(CONTENIDO_LISTO, timeout=tiempo_limite * 1000)
