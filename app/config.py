"""Configuración por variables de entorno. Ninguna exige credenciales."""

import math
import os
from dataclasses import dataclass
from enum import StrEnum


class ModoObtencion(StrEnum):
    HTTP = "http"
    NAVEGADOR = "navegador"


@dataclass(frozen=True)
class ConfiguracionPagWeb2:
    habilitado: bool = True
    modo: ModoObtencion = ModoObtencion.NAVEGADOR
    url: str = ""  # plantilla con {numero}; ver .env.example
    max_concurrentes: int = 2
    intervalo_minimo: float = 2.0
    intentos: int = 3
    tiempo_solicitud: float = 30.0
    tiempo_total: float = 40.0
    espera_base: float = 0.5

    @classmethod
    def desde_entorno(cls) -> "ConfiguracionPagWeb2":
        prefijo = "OPENRENAPER_PAG_WEB2_"

        def leer(nombre: str, defecto: object) -> str:
            return os.environ.get(prefijo + nombre, str(defecto))

        return cls(
            habilitado=leer("HABILITADO", "true").strip().lower() in {"1", "true", "si", "sí"},
            modo=ModoObtencion(leer("MODO", cls.modo).strip().lower()),
            url=leer("URL", cls.url).strip(),
            max_concurrentes=int(leer("MAX_CONCURRENTES", cls.max_concurrentes)),
            intervalo_minimo=float(leer("INTERVALO_MINIMO", cls.intervalo_minimo)),
            intentos=int(leer("INTENTOS", cls.intentos)),
            tiempo_solicitud=float(leer("TIEMPO_SOLICITUD", cls.tiempo_solicitud)),
            tiempo_total=float(leer("TIEMPO_TOTAL", cls.tiempo_total)),
            espera_base=float(leer("ESPERA_BASE", cls.espera_base)),
        )


@dataclass(frozen=True)
class ConfiguracionPagWeb1:
    habilitado: bool = True
    url: str = ""  # plantilla con {numero}; ver .env.example
    max_concurrentes: int = 2
    intervalo_minimo: float = 2.0
    intentos: int = 2
    tiempo_solicitud: float = 30.0
    tiempo_total: float = 40.0
    espera_base: float = 0.5

    @classmethod
    def desde_entorno(cls) -> "ConfiguracionPagWeb1":
        def leer(nombre: str, defecto: object) -> str:
            return os.environ.get("OPENRENAPER_PAG_WEB1_" + nombre, str(defecto))

        return cls(
            habilitado=leer("HABILITADO", "true").strip().lower() in {"1", "true", "si", "sí"},
            url=leer("URL", cls.url).strip(),
            max_concurrentes=int(leer("MAX_CONCURRENTES", cls.max_concurrentes)),
            intervalo_minimo=float(leer("INTERVALO_MINIMO", cls.intervalo_minimo)),
            intentos=int(leer("INTENTOS", cls.intentos)),
            tiempo_solicitud=float(leer("TIEMPO_SOLICITUD", cls.tiempo_solicitud)),
            tiempo_total=float(leer("TIEMPO_TOTAL", cls.tiempo_total)),
            espera_base=float(leer("ESPERA_BASE", cls.espera_base)),
        )


@dataclass(frozen=True)
class ConfiguracionLimites:
    habilitado: bool = True
    por_ip: int = 15
    total: int = 30
    ventana_segundos: float = 60.0
    max_en_curso: int = 4

    def __post_init__(self) -> None:
        if min(self.por_ip, self.total, self.max_en_curso) < 1:
            raise ValueError("Los límites de peticiones deben ser positivos.")
        if not math.isfinite(self.ventana_segundos) or self.ventana_segundos <= 0:
            raise ValueError("La ventana del límite debe ser finita y positiva.")

    @classmethod
    def desde_entorno(cls) -> "ConfiguracionLimites":
        prefijo = "OPENRENAPER_RATE_LIMIT_"
        return cls(
            habilitado=os.environ.get(prefijo + "HABILITADO", "true").strip().lower()
            in {"1", "true", "si", "sí"},
            por_ip=int(os.environ.get(prefijo + "POR_IP", cls.por_ip)),
            total=int(os.environ.get(prefijo + "TOTAL", cls.total)),
            ventana_segundos=float(
                os.environ.get(prefijo + "VENTANA_SEGUNDOS", cls.ventana_segundos)
            ),
            max_en_curso=int(os.environ.get(prefijo + "MAX_EN_CURSO", cls.max_en_curso)),
        )


@dataclass(frozen=True)
class ConfiguracionRegistro:
    habilitado: bool = True
    incluir_health: bool = False

    @classmethod
    def desde_entorno(cls) -> "ConfiguracionRegistro":
        return cls(
            habilitado=os.environ.get("OPENRENAPER_LOG_SOLICITUDES", "true").strip().lower()
            in {"1", "true", "si", "sí"},
            incluir_health=os.environ.get("OPENRENAPER_LOG_HEALTH", "false").strip().lower()
            in {"1", "true", "si", "sí"},
        )


@dataclass(frozen=True)
class Configuracion:
    tiempo_limite_proveedor: float = 45.0
    pag_web2: ConfiguracionPagWeb2 = ConfiguracionPagWeb2()
    pag_web1: ConfiguracionPagWeb1 = ConfiguracionPagWeb1()
    limites: ConfiguracionLimites = ConfiguracionLimites()
    registro: ConfiguracionRegistro = ConfiguracionRegistro()

    @classmethod
    def desde_entorno(cls) -> "Configuracion":
        return cls(
            tiempo_limite_proveedor=float(
                os.environ.get("OPENRENAPER_TIEMPO_LIMITE_PROVEEDOR", cls.tiempo_limite_proveedor)
            ),
            pag_web2=ConfiguracionPagWeb2.desde_entorno(),
            pag_web1=ConfiguracionPagWeb1.desde_entorno(),
            limites=ConfiguracionLimites.desde_entorno(),
            registro=ConfiguracionRegistro.desde_entorno(),
        )
