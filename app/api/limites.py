"""Admisión ASGI antes de leer el cuerpo: ventana deslizante y trabajo en curso.

Los contadores son locales al proceso. No se aceptan IP de cabeceras directamente:
Uvicorn debe resolver los encabezados exclusivamente de los proxies configurados.
"""

import math
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass

from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.errores import ErrorRespuesta
from app.config import ConfiguracionLimites


@dataclass(frozen=True)
class Rechazo:
    motivo: str
    reintentar_en: int


class ControlSolicitudes:
    def __init__(
        self,
        configuracion: ConfiguracionLimites,
        *,
        reloj: Callable[[], float] = time.monotonic,
        max_clientes: int = 4096,
    ) -> None:
        if max_clientes < 1:
            raise ValueError("El máximo de clientes debe ser positivo.")
        self.configuracion = configuracion
        self._reloj = reloj
        self._max_clientes = max_clientes
        self._global: deque[float] = deque()
        # Ordenados por la última admisión, para eliminar entradas vencidas sin barrer el mapa.
        self._clientes: OrderedDict[str, deque[float]] = OrderedDict()
        self._en_curso = 0
        self._lock = threading.Lock()

    def admitir(self, cliente: str) -> Rechazo | None:
        with self._lock:
            ahora = self._reloj()
            corte = ahora - self.configuracion.ventana_segundos
            while self._global and self._global[0] <= corte:
                self._global.popleft()
            while self._clientes:
                _, fechas = next(iter(self._clientes.items()))
                if fechas[-1] > corte:
                    break
                self._clientes.popitem(last=False)

            fechas = self._clientes.get(cliente)
            if fechas is not None:
                while fechas and fechas[0] <= corte:
                    fechas.popleft()
                if len(fechas) >= self.configuracion.por_ip:
                    return self._rechazo("ip", fechas[0], ahora)
            if len(self._global) >= self.configuracion.total:
                return self._rechazo("total", self._global[0], ahora)
            if self._en_curso >= self.configuracion.max_en_curso:
                return Rechazo("en_curso", 1)
            if fechas is None:
                if len(self._clientes) >= self._max_clientes:
                    primeras = next(iter(self._clientes.values()))
                    return self._rechazo("clientes", primeras[-1], ahora)
                fechas = deque()
                self._clientes[cliente] = fechas

            fechas.append(ahora)
            self._clientes.move_to_end(cliente)
            self._global.append(ahora)
            self._en_curso += 1
            return None

    def terminar(self) -> None:
        with self._lock:
            self._en_curso -= 1

    def _rechazo(self, motivo: str, fecha: float, ahora: float) -> Rechazo:
        espera = math.ceil(fecha + self.configuracion.ventana_segundos - ahora)
        return Rechazo(motivo, max(1, espera))


class LimiteSolicitudesMiddleware:
    def __init__(self, app: ASGIApp, control: ControlSolicitudes) -> None:
        self.app = app
        self.control = control

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or not self.control.configuracion.habilitado
            or not scope.get("path", "").startswith("/api/")
            or scope.get("method") == "OPTIONS"
        ):
            await self.app(scope, receive, send)
            return

        direccion = scope.get("client")
        cliente = direccion[0] if direccion else "desconocido"
        rechazo = self.control.admitir(cliente)
        if rechazo is not None:
            scope.setdefault("state", {})["limite_solicitudes"] = rechazo.motivo
            cuerpo = ErrorRespuesta(
                codigo="limite_solicitudes_excedido",
                mensaje="Se alcanzó el límite de peticiones. Reintentá más tarde.",
                detalles=[{"limite": rechazo.motivo}],
            )
            respuesta = JSONResponse(
                status_code=429,
                content=cuerpo.model_dump(mode="json"),
                headers={"Retry-After": str(rechazo.reintentar_en), "Cache-Control": "no-store"},
            )
            await respuesta(scope, receive, send)
            return

        try:
            await self.app(scope, receive, send)
        finally:
            self.control.terminar()
