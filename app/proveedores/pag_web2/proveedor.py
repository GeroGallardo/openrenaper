"""Proveedor de pag_web2: une obtención, parsing y normalización.

Pertinencia de los resultados (la búsqueda de la fuente es por texto y puede
devolver registros de otros identificadores):

- CUIT/CUIL: se conservan los registros con ese CUIT/CUIL exacto.
- DNI: se conservan todos los registros cuyo CUIT/CUIL es de persona física y
  contiene ese DNI en las posiciones 3 a 10. Puede haber varios: no se supone
  una correspondencia única y se devuelven todos como candidatos. El campo
  `dni` queda en `None` porque la fuente no lo informa por separado.
- Un registro sin CUIT/CUIL no permite confirmar la correspondencia y no se
  devuelve.

Cero registros pertinentes en una página interpretada es "sin resultados".
Los fallos de la fuente se propagan como errores, nunca como lista vacía.
"""

import logging

from app.config import ConfiguracionPagWeb2, ModoObtencion
from app.consultas.modelos import DatosPersona
from app.identificadores import PREFIJOS_CUIL, Identificador, TipoIdentificador
from app.proveedores.ejecucion import Limitador, reintentar
from app.proveedores.errores import AccesoRestringido, FormatoDesconocido
from app.proveedores.navegador import NavegadorCompartido
from app.proveedores.obtencion import ObtenedorContenido, ObtenedorHttp, ObtenedorNavegador
from app.proveedores.pag_web2.normalizacion import a_datos_persona
from app.proveedores.pag_web2.parser import FUENTE, interpretar
from app.proveedores.pag_web2.renderizado import esperar_resultados
from app.proveedores.resultados import PaginaResultados
from app.proveedores.urls import url_busqueda

logger = logging.getLogger(__name__)


class ProveedorPagWeb2:
    nombre = FUENTE
    tipos = frozenset(TipoIdentificador)

    def __init__(
        self,
        configuracion: ConfiguracionPagWeb2,
        *,
        obtenedor: ObtenedorContenido | None = None,
        navegador: NavegadorCompartido | None = None,
        limitador: Limitador | None = None,
        tiempo_maximo: float | None = None,
    ) -> None:
        self._configuracion = configuracion
        self._navegador = navegador
        if obtenedor is None:
            if configuracion.modo is ModoObtencion.NAVEGADOR:
                self._navegador = navegador or NavegadorCompartido(FUENTE)
                obtenedor = ObtenedorNavegador(
                    FUENTE, self._navegador.abrir_pagina, esperar_contenido=esperar_resultados
                )
            else:
                obtenedor = ObtenedorHttp(FUENTE)
        self._obtenedor = obtenedor
        self._limitador = limitador or Limitador(
            max_concurrentes=configuracion.max_concurrentes,
            intervalo_minimo=configuracion.intervalo_minimo,
        )
        # El proveedor termina antes que el límite que impone ConsultaService.
        self._tiempo_total = min(configuracion.tiempo_total, tiempo_maximo or float("inf"))
        self._disponible = False

    async def iniciar(self) -> None:
        """Inicia el navegador o el cliente HTTP. Si falla, la fuente queda no disponible."""
        try:
            if self._navegador is not None:
                await self._navegador.iniciar()
            iniciar = getattr(self._obtenedor, "iniciar", None)
            if iniciar is not None:
                await iniciar()
        except Exception:
            logger.exception(
                "No se pudo iniciar %s; las consultas responderán fuente no disponible. "
                "Con modo navegador, instalar Chromium: `playwright install chromium`.",
                FUENTE,
            )
            return
        self._disponible = True

    async def cerrar(self) -> None:
        """Espera las consultas activas y libera navegador y cliente HTTP."""
        self._disponible = False
        cerrar = getattr(self._obtenedor, "cerrar", None)
        if cerrar is not None:
            await cerrar()
        if self._navegador is not None:
            await self._navegador.cerrar()

    async def consultar(self, identificador: Identificador) -> list[DatosPersona]:
        if not self._disponible:
            raise AccesoRestringido(f"{FUENTE} no está iniciada en este proceso.", fuente=FUENTE)
        url = url_busqueda(self._configuracion.url, identificador)

        async def intento(tiempo_limite: float) -> PaginaResultados:
            async with self._limitador.turno():
                if self._navegador is not None:
                    async with self._navegador.consulta():
                        pagina = await self._obtenedor.obtener(url, tiempo_limite=tiempo_limite)
                else:
                    pagina = await self._obtenedor.obtener(url, tiempo_limite=tiempo_limite)
            return interpretar(pagina.html)

        pagina = await reintentar(
            intento,
            fuente=FUENTE,
            intentos=self._configuracion.intentos,
            tiempo_solicitud=self._configuracion.tiempo_solicitud,
            tiempo_total=self._tiempo_total,
            espera_base=self._configuracion.espera_base,
        )
        registros = [a_datos_persona(r) for r in pagina.registros]
        if any(r.cuit_cuil is None for r in registros):
            raise FormatoDesconocido(
                "pag_web2 listó un resultado sin CUIT/CUIL; "
                "no se puede confirmar su correspondencia.",
                fuente=FUENTE,
            )
        return pertinentes(identificador, registros)


def pertinentes(identificador: Identificador, registros: list[DatosPersona]) -> list[DatosPersona]:
    if identificador.tipo is TipoIdentificador.DNI:
        dni = identificador.numero.zfill(8)
        return [
            r
            for r in registros
            if r.cuit_cuil is not None
            and r.cuit_cuil[:2] in PREFIJOS_CUIL
            and r.cuit_cuil[2:10] == dni
        ]
    return [r for r in registros if r.cuit_cuil == identificador.numero]
