"""Logs privados de solicitudes e identificadores consultados, sin imágenes ni cuerpos completos."""

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import ConfiguracionRegistro

logger = logging.getLogger("openrenaper.solicitudes")
_configuracion_lock = threading.Lock()
_METODOS = frozenset(
    {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "CONNECT", "TRACE"}
)


def configurar_logger() -> None:
    with _configuracion_lock:
        if not logger.handlers:
            salida = logging.StreamHandler()
            salida.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(salida)
        logger.setLevel(logging.INFO)
        logger.propagate = False


def _numero_admitido(numero: object) -> bool:
    return (
        isinstance(numero, str) and 7 <= len(numero) <= 11 and numero.isascii() and numero.isdigit()
    )


def anotar_consulta(scope: Scope, tipo: str, numero: str) -> None:
    if tipo in {"dni", "cuit", "cuil"} and _numero_admitido(numero):
        scope.setdefault("state", {})["consulta_registro"] = {"tipo": tipo, "numero": numero}


def anotar_dni_extraido(scope: Scope, numero: str | None) -> None:
    if _numero_admitido(numero) and len(numero) in (7, 8) and not numero.startswith("0"):
        scope.setdefault("state", {})["dni_extraido_registro"] = numero


class RegistroSolicitudes:
    def __init__(self) -> None:
        self._total = 0
        self._rechazos = 0
        self._rutas: Counter[tuple[str, str]] = Counter()
        self._lock = threading.Lock()

    def contadores(self, metodo: str, ruta: str, estado: int | None) -> dict[str, int]:
        with self._lock:
            self._total += 1
            self._rutas[metodo, ruta] += 1
            self._rechazos += estado == 429
            return {
                "solicitudes_total": self._total,
                "solicitudes_operacion": self._rutas[metodo, ruta],
                "rechazadas_429_total": self._rechazos,
            }


class RegistroSolicitudesMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        configuracion: ConfiguracionRegistro,
        rutas: frozenset[str] | Callable[[], frozenset[str]],
    ) -> None:
        self.app = app
        self.configuracion = configuracion
        self.rutas = rutas() if callable(rutas) else rutas
        self.contador = RegistroSolicitudes()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or not self.configuracion.habilitado
            or (scope.get("path") == "/health" and not self.configuracion.incluir_health)
        ):
            await self.app(scope, receive, send)
            return

        inicio = time.perf_counter()
        request_id = uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        estado: int | None = None
        completa = False
        resultado = "completada"

        async def enviar(mensaje: Message) -> None:
            nonlocal estado, completa
            if mensaje["type"] == "http.response.start":
                estado = mensaje["status"]
                mensaje = dict(mensaje)
                mensaje["headers"] = [
                    (k, v) for k, v in mensaje.get("headers", []) if k.lower() != b"x-request-id"
                ] + [(b"x-request-id", request_id.encode("ascii"))]
            await send(mensaje)
            if mensaje["type"] == "http.response.body" and not mensaje.get("more_body", False):
                completa = True

        try:
            await self.app(scope, receive, enviar)
        except asyncio.CancelledError:
            resultado = "cancelada"
            raise
        except Exception:
            resultado = "interrumpida"
            if estado is None:
                estado = 500
            raise
        finally:
            # Registrar la plantilla de ruta; nunca el path libre con posibles datos personales.
            ruta_objeto = scope.get("route")
            ruta = getattr(ruta_objeto, "path", None)
            candidata = scope.get("path", "").rstrip("/") or "/"
            if candidata in self.rutas:
                ruta = candidata
            elif ruta not in self.rutas:
                ruta = "(no_reconocida)"
            metodo = scope.get("method", "")
            metodo = metodo if metodo in _METODOS else "OTRO"
            if not completa and resultado == "completada":
                resultado = "interrumpida"
            datos = {
                "evento": "solicitud_http",
                "fecha": datetime.now(UTC).isoformat(timespec="milliseconds"),
                "request_id": request_id,
                "pid": os.getpid(),
                "metodo": metodo,
                "ruta": ruta,
                "estado": estado,
                "resultado": resultado,
                "duracion_ms": round((time.perf_counter() - inicio) * 1000, 2),
                **self.contador.contadores(metodo, ruta, estado),
            }
            limite = scope.get("state", {}).get("limite_solicitudes")
            if limite in {"ip", "total", "en_curso", "clientes"}:
                datos["limite"] = limite
            consulta = scope.get("state", {}).get("consulta_registro")
            if (
                isinstance(consulta, dict)
                and consulta.get("tipo") in {"dni", "cuit", "cuil"}
                and _numero_admitido(consulta.get("numero"))
            ):
                datos["consulta"] = {"tipo": consulta["tipo"], "numero": consulta["numero"]}
            dni_extraido = scope.get("state", {}).get("dni_extraido_registro")
            if _numero_admitido(dni_extraido) and len(dni_extraido) in (7, 8):
                datos["dni_extraido"] = dni_extraido
            logger.info("%s", json.dumps(datos, ensure_ascii=True, separators=(",", ":")))
