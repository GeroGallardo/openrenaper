"""Proveedor independiente con plazos, concurrencia y contexto por consulta."""

import logging

from app.config import ConfiguracionPagWeb1
from app.consultas.modelos import DatosPersona
from app.identificadores import Identificador, TipoIdentificador
from app.proveedores.ejecucion import Limitador, reintentar
from app.proveedores.errores import AccesoRestringido
from app.proveedores.navegador import NavegadorCompartido
from app.proveedores.obtencion import ObtenedorContenido, ObtenedorNavegador
from app.proveedores.pag_web1.parser import FUENTE, interpretar
from app.proveedores.pag_web1.renderizado import esperar_resultados
from app.proveedores.urls import url_busqueda

logger = logging.getLogger(__name__)


class ProveedorPagWeb1:
    nombre = FUENTE
    tipos = frozenset(TipoIdentificador)

    def __init__(
        self,
        configuracion: ConfiguracionPagWeb1,
        *,
        obtenedor: ObtenedorContenido | None = None,
        navegador: NavegadorCompartido | None = None,
        tiempo_maximo: float | None = None,
    ) -> None:
        self._configuracion = configuracion
        self._navegador = navegador
        if obtenedor is None:
            self._navegador = navegador or NavegadorCompartido(FUENTE)
            obtenedor = ObtenedorNavegador(
                FUENTE, self._navegador.abrir_pagina, esperar_contenido=esperar_resultados
            )
        self._obtenedor = obtenedor
        self._limitador = Limitador(
            max_concurrentes=configuracion.max_concurrentes,
            intervalo_minimo=configuracion.intervalo_minimo,
        )
        self._tiempo_total = min(configuracion.tiempo_total, tiempo_maximo or float("inf"))
        self._disponible = False

    async def iniciar(self) -> None:
        try:
            if self._navegador is not None:
                await self._navegador.iniciar()
            if iniciar := getattr(self._obtenedor, "iniciar", None):
                await iniciar()
        except Exception:
            logger.exception("No se pudo iniciar el proveedor %s.", FUENTE)
            return
        self._disponible = True

    async def cerrar(self) -> None:
        self._disponible = False
        if cerrar := getattr(self._obtenedor, "cerrar", None):
            await cerrar()
        if self._navegador is not None:
            await self._navegador.cerrar()

    async def consultar(self, identificador: Identificador) -> list[DatosPersona]:
        if not self._disponible:
            raise AccesoRestringido("pag_web1 no está iniciada en este proceso.", fuente=FUENTE)
        url = url_busqueda(self._configuracion.url, identificador)

        async def intento(tiempo_limite: float) -> list[DatosPersona]:
            async with self._limitador.turno():
                if self._navegador is not None:
                    async with self._navegador.consulta():
                        pagina = await self._obtenedor.obtener(url, tiempo_limite=tiempo_limite)
                else:
                    pagina = await self._obtenedor.obtener(url, tiempo_limite=tiempo_limite)
            return interpretar(pagina.html, identificador)

        return await reintentar(
            intento,
            fuente=FUENTE,
            intentos=self._configuracion.intentos,
            tiempo_solicitud=self._configuracion.tiempo_solicitud,
            tiempo_total=self._tiempo_total,
            espera_base=self._configuracion.espera_base,
        )
