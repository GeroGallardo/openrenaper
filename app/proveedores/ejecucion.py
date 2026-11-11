"""Límites de ejecución compartidos por los proveedores.

- `Limitador`: cantidad máxima de consultas simultáneas a una fuente y espera
  mínima entre solicitudes, para respetar el ritmo que admite cada fuente.
- `reintentar`: repite solo fallos transitorios, con espera progresiva, sin
  superar la cantidad de intentos ni el tiempo total.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from app.proveedores.errores import TiempoAgotadoFuente, es_reintentable

Dormir = Callable[[float], Awaitable[None]]
Reloj = Callable[[], float]


def _reloj_monotonico() -> float:
    return asyncio.get_running_loop().time()


class Limitador:
    def __init__(
        self,
        *,
        max_concurrentes: int,
        intervalo_minimo: float,
        dormir: Dormir = asyncio.sleep,
        reloj: Reloj = _reloj_monotonico,
    ) -> None:
        if max_concurrentes < 1:
            raise ValueError("max_concurrentes debe ser al menos 1")
        self._semaforo = asyncio.Semaphore(max_concurrentes)
        self._intervalo = intervalo_minimo
        self._dormir = dormir
        self._reloj = reloj
        self._turno = asyncio.Lock()
        self._ultima: float | None = None

    @asynccontextmanager
    async def turno(self) -> AsyncIterator[None]:
        """Ocupa un lugar y respeta el intervalo desde la solicitud anterior."""
        async with self._semaforo:
            async with self._turno:
                if self._ultima is not None:
                    espera = self._ultima + self._intervalo - self._reloj()
                    if espera > 0:
                        await self._dormir(espera)
                self._ultima = self._reloj()
            yield


async def reintentar[T](
    operacion: Callable[[float], Awaitable[T]],
    *,
    fuente: str,
    intentos: int,
    tiempo_solicitud: float,
    tiempo_total: float,
    espera_base: float,
    dormir: Dormir = asyncio.sleep,
    reloj: Reloj = _reloj_monotonico,
) -> T:
    """Ejecuta `operacion(tiempo_limite)` y la repite ante fallos transitorios.

    El plazo total incluye las esperas por concurrencia e intervalo, el trabajo
    de cada intento y el backoff. Cada intento también tiene su propio plazo.
    Si la próxima espera no entra en el tiempo total, se informa el último fallo.
    """
    if intentos < 1:
        raise ValueError("intentos debe ser al menos 1")
    vence = reloj() + tiempo_total
    try:
        async with asyncio.timeout(tiempo_total):
            for intento in range(intentos):
                restante = vence - reloj()
                if restante <= 0:
                    raise TiempoAgotadoFuente(f"{fuente} superó el tiempo total.", fuente=fuente)
                limite = min(tiempo_solicitud, restante)
                try:
                    async with asyncio.timeout(limite):
                        return await operacion(limite)
                except TimeoutError:
                    fallo: Exception = TiempoAgotadoFuente(
                        f"{fuente} superó el tiempo del intento.", fuente=fuente
                    )
                except Exception as error:
                    fallo = error
                espera = espera_base * 2**intento
                ultimo = intento == intentos - 1
                if not es_reintentable(fallo) or ultimo or reloj() + espera >= vence:
                    raise fallo
                await dormir(espera)
    except TimeoutError:
        raise TiempoAgotadoFuente(f"{fuente} superó el tiempo total.", fuente=fuente) from None
    raise AssertionError("inalcanzable")  # pragma: no cover
