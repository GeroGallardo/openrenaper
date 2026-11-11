"""Concurrencia, intervalo, reintentos y ciclo de vida del navegador (sin Chromium real)."""

import asyncio

import pytest

from app.errores import FuenteNoDisponible
from app.proveedores.ejecucion import Limitador, reintentar
from app.proveedores.errores import (
    AccesoRestringido,
    FormatoDesconocido,
    FuenteTemporalmenteCaida,
    TiempoAgotadoFuente,
)
from app.proveedores.navegador import NavegadorCompartido


class RelojFalso:
    """Reloj que solo avanza cuando alguien duerme."""

    def __init__(self) -> None:
        self.ahora = 0.0
        self.esperas: list[float] = []

    def __call__(self) -> float:
        return self.ahora

    async def dormir(self, segundos: float) -> None:
        self.esperas.append(segundos)
        self.ahora += segundos


# --- Limitador ----------------------------------------------------------------


def test_limita_consultas_simultaneas() -> None:
    async def ejecutar() -> int:
        limitador = Limitador(max_concurrentes=2, intervalo_minimo=0)
        activas = maximo = 0

        async def tarea() -> None:
            nonlocal activas, maximo
            async with limitador.turno():
                activas += 1
                maximo = max(maximo, activas)
                await asyncio.sleep(0.01)
                activas -= 1

        await asyncio.gather(*(tarea() for _ in range(6)))
        return maximo

    assert asyncio.run(ejecutar()) == 2


def test_respeta_el_intervalo_entre_solicitudes() -> None:
    reloj = RelojFalso()

    async def ejecutar() -> None:
        limitador = Limitador(
            max_concurrentes=3, intervalo_minimo=2.0, dormir=reloj.dormir, reloj=reloj
        )
        for _ in range(3):
            async with limitador.turno():
                pass

    asyncio.run(ejecutar())
    assert reloj.esperas == [2.0, 2.0]


def test_limitador_rechaza_configuracion_invalida() -> None:
    with pytest.raises(ValueError):
        Limitador(max_concurrentes=0, intervalo_minimo=0)


# --- Reintentos ---------------------------------------------------------------


def ejecutar_con_reintentos(fallos: list[Exception], **opciones) -> tuple[object, list, RelojFalso]:
    reloj = RelojFalso()
    limites: list[float] = []

    async def operacion(tiempo_limite: float) -> str:
        limites.append(tiempo_limite)
        if fallos:
            raise fallos.pop(0)
        return "ok"

    parametros = {
        "fuente": "fuente",
        "intentos": 3,
        "tiempo_solicitud": 5.0,
        "tiempo_total": 30.0,
        "espera_base": 1.0,
        "dormir": reloj.dormir,
        "reloj": reloj,
    } | opciones

    async def ejecutar() -> object:
        try:
            return await reintentar(operacion, **parametros)
        except Exception as error:
            return error

    return asyncio.run(ejecutar()), limites, reloj


def test_reintenta_transitorios_con_espera_progresiva() -> None:
    fallos = [FuenteTemporalmenteCaida("x"), TiempoAgotadoFuente("x")]
    resultado, limites, reloj = ejecutar_con_reintentos(fallos)
    assert resultado == "ok"
    assert len(limites) == 3
    assert reloj.esperas == [1.0, 2.0]


@pytest.mark.parametrize(
    "error",
    [AccesoRestringido("x"), FormatoDesconocido("x"), FuenteNoDisponible("x"), ValueError("x")],
)
def test_no_reintenta_fallos_permanentes(error: Exception) -> None:
    resultado, limites, reloj = ejecutar_con_reintentos([error])
    assert resultado is error
    assert len(limites) == 1
    assert reloj.esperas == []


def test_respeta_la_cantidad_de_intentos() -> None:
    fallos = [FuenteTemporalmenteCaida(str(i)) for i in range(5)]
    resultado, limites, _ = ejecutar_con_reintentos(fallos, intentos=2)
    assert isinstance(resultado, FuenteTemporalmenteCaida)
    assert str(resultado) == "1"
    assert len(limites) == 2


def test_no_espera_si_supera_el_tiempo_total() -> None:
    fallos = [FuenteTemporalmenteCaida("x"), FuenteTemporalmenteCaida("y")]
    resultado, limites, reloj = ejecutar_con_reintentos(fallos, tiempo_total=1.5, espera_base=2.0)
    assert str(resultado) == "x"
    assert reloj.esperas == []
    assert limites == [1.5]


def test_cada_intento_usa_el_tiempo_restante() -> None:
    fallos = [FuenteTemporalmenteCaida("x")]
    resultado, limites, _ = ejecutar_con_reintentos(
        fallos, tiempo_solicitud=10.0, tiempo_total=12.0, espera_base=4.0
    )
    assert resultado == "ok"
    assert limites == [10.0, 8.0]


def test_tiempo_total_incluye_la_espera_del_limitador() -> None:
    async def ejecutar() -> None:
        limitador = Limitador(max_concurrentes=1, intervalo_minimo=60)
        async with limitador.turno():
            pass
        obteniendo = False

        async def operacion(tiempo_limite: float) -> None:
            nonlocal obteniendo
            async with limitador.turno():
                obteniendo = True

        with pytest.raises(TiempoAgotadoFuente):
            await asyncio.wait_for(
                reintentar(
                    operacion,
                    fuente="sintetica",
                    intentos=1,
                    tiempo_solicitud=1,
                    tiempo_total=0.03,
                    espera_base=0,
                ),
                timeout=1,
            )
        assert not obteniendo

    asyncio.run(ejecutar())


def test_interrumpe_un_intento_lento_y_reintenta() -> None:
    async def ejecutar() -> None:
        intentos = 0
        cancelado = False

        async def operacion(tiempo_limite: float) -> str:
            nonlocal intentos, cancelado
            intentos += 1
            if intentos == 1:
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelado = True
            return "ok"

        respuesta = await reintentar(
            operacion,
            fuente="sintetica",
            intentos=2,
            tiempo_solicitud=0.03,
            tiempo_total=1,
            espera_base=0,
        )
        assert respuesta == "ok"
        assert intentos == 2
        assert cancelado

    asyncio.run(ejecutar())


def test_una_cancelacion_externa_no_se_convierte_en_reintento() -> None:
    async def ejecutar() -> None:
        iniciado = asyncio.Event()
        intentos = 0

        async def operacion(tiempo_limite: float) -> None:
            nonlocal intentos
            intentos += 1
            iniciado.set()
            await asyncio.Event().wait()

        tarea = asyncio.create_task(
            reintentar(
                operacion,
                fuente="sintetica",
                intentos=3,
                tiempo_solicitud=10,
                tiempo_total=30,
                espera_base=0,
            )
        )
        await iniciado.wait()
        tarea.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarea
        assert intentos == 1

    asyncio.run(ejecutar())


# --- Navegador compartido -----------------------------------------------------


class NavegadorFalso:
    def __init__(self) -> None:
        self.conectado = True
        self.cerrado = False
        self.contextos: list[ContextoFalso] = []

    def is_connected(self) -> bool:
        return self.conectado

    async def new_context(self, **_: object) -> "ContextoFalso":
        contexto = ContextoFalso()
        self.contextos.append(contexto)
        return contexto

    async def close(self) -> None:
        self.cerrado = True
        self.conectado = False


class ContextoFalso:
    def __init__(self) -> None:
        self.cerrado = False

    async def new_page(self) -> object:
        return object()

    async def close(self) -> None:
        self.cerrado = True


class PlaywrightFalso:
    def __init__(self) -> None:
        self.detenido = False

    async def stop(self) -> None:
        self.detenido = True


class Lanzador:
    def __init__(self) -> None:
        self.lanzados: list[tuple[PlaywrightFalso, NavegadorFalso]] = []

    async def __call__(self) -> tuple[PlaywrightFalso, NavegadorFalso]:
        par = (PlaywrightFalso(), NavegadorFalso())
        self.lanzados.append(par)
        return par


def test_inicio_idempotente_y_cierre_libera_todo() -> None:
    lanzador = Lanzador()

    async def ejecutar() -> None:
        navegador = NavegadorCompartido("fuente", lanzar=lanzador)
        await navegador.iniciar()
        await navegador.iniciar()
        await navegador.cerrar()

    asyncio.run(ejecutar())
    [(playwright, navegador)] = lanzador.lanzados
    assert navegador.cerrado and playwright.detenido


def test_cierre_espera_las_consultas_activas() -> None:
    lanzador = Lanzador()
    eventos: list[str] = []

    async def ejecutar() -> None:
        navegador = NavegadorCompartido("fuente", lanzar=lanzador)
        await navegador.iniciar()
        en_curso = asyncio.Event()

        async def consulta() -> None:
            async with navegador.consulta():
                await navegador.abrir_pagina()
                en_curso.set()
                await asyncio.sleep(0.02)
                eventos.append("consulta terminada")

        tarea = asyncio.create_task(consulta())
        await en_curso.wait()
        await navegador.cerrar()
        eventos.append("navegador cerrado")
        await tarea

    asyncio.run(ejecutar())
    assert eventos == ["consulta terminada", "navegador cerrado"]


def test_no_acepta_consultas_mientras_cierra() -> None:
    async def ejecutar() -> None:
        navegador = NavegadorCompartido("fuente", lanzar=Lanzador())
        await navegador.iniciar()
        await navegador.cerrar()
        async with navegador.consulta():
            pass  # pragma: no cover

    with pytest.raises(FuenteTemporalmenteCaida):
        asyncio.run(ejecutar())


def test_sin_iniciar_no_abre_paginas() -> None:
    navegador = NavegadorCompartido("fuente", lanzar=Lanzador())
    with pytest.raises(FuenteTemporalmenteCaida):
        asyncio.run(navegador.abrir_pagina())


def test_relanza_solo_un_navegador_desconectado() -> None:
    lanzador = Lanzador()

    async def ejecutar() -> None:
        navegador = NavegadorCompartido("fuente", lanzar=lanzador)
        await navegador.iniciar()
        await navegador.abrir_pagina()
        assert len(lanzador.lanzados) == 1  # conectado: se reutiliza
        lanzador.lanzados[0][1].conectado = False
        await navegador.abrir_pagina()
        await navegador.cerrar()

    asyncio.run(ejecutar())
    (pw_viejo, _), (pw_nuevo, nav_nuevo) = lanzador.lanzados
    assert pw_viejo.detenido
    assert nav_nuevo.cerrado and pw_nuevo.detenido


def test_cuenta_consultas_activas_aun_con_errores() -> None:
    async def ejecutar() -> int:
        navegador = NavegadorCompartido("fuente", lanzar=Lanzador())
        await navegador.iniciar()
        with pytest.raises(RuntimeError):
            async with navegador.consulta():
                raise RuntimeError("fallo")
        activas = navegador.activas
        await navegador.cerrar()
        return activas

    assert asyncio.run(ejecutar()) == 0
