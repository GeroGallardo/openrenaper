"""Modelos públicos de las consultas por DNI, CUIT o CUIL."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.identificadores import TipoIdentificador


class EstadoConsulta(StrEnum):
    ENCONTRADO = "encontrado"
    SIN_RESULTADOS = "sin_resultados"
    AMBIGUO = "ambiguo"


class TipoPersona(StrEnum):
    FISICA = "fisica"
    JURIDICA = "juridica"


CAMPOS_PRINCIPALES = ("dni", "cuit_cuil", "nombre", "tipo_persona")


class DatosPersona(BaseModel):
    """Datos que una fuente informa sobre una persona.

    Lo que la fuente no informa queda en `null` y se enumera en `desconocidos`;
    nunca se completa con valores inferidos. Los identificadores van solo con dígitos.
    """

    model_config = ConfigDict(extra="forbid")

    dni: str | None = Field(default=None, pattern=r"^[0-9]+$")
    cuit_cuil: str | None = Field(default=None, pattern=r"^[0-9]{11}$")
    nombre: str | None = Field(
        default=None, description="Nombre completo o razón social, tal como lo informa la fuente."
    )
    tipo_persona: TipoPersona | None = None
    edad: int | None = Field(default=None, ge=0)
    sexo: str | None = None
    provincia_ubicacion: str | None = None
    adicionales: dict[str, str] = Field(
        default_factory=dict, description="Datos propios de la fuente, sin normalizar."
    )

    @computed_field(description="Campos principales que la fuente no informó.")
    @property
    def desconocidos(self) -> list[str]:
        return [campo for campo in CAMPOS_PRINCIPALES if getattr(self, campo) is None]


class Resultado(BaseModel):
    fuente: str = Field(description="Nombre del proveedor que informó el dato.")
    consultado_en: datetime = Field(description="Momento (UTC) en que respondió la fuente.")
    candidato: int = Field(
        ge=1,
        description="Persona candidata a la que corresponde; varios resultados pueden compartirla.",
    )
    datos: DatosPersona


class Advertencia(BaseModel):
    codigo: str
    mensaje: str
    fuente: str | None = None


class ConsultaSolicitud(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tipo: Literal["dni", "cuit"] = Field(
        description="`dni` o `cuit`. Un CUIL se consulta con `cuit`; `cuil` no se admite."
    )
    numero: str = Field(
        min_length=7,
        max_length=11,
        pattern=r"^[0-9]+$",
        strict=True,
        description="DNI o CUIT como texto, solo dígitos, sin puntos, guiones, barras ni espacios.",
    )


class ConsultaEfectuada(BaseModel):
    tipo: TipoIdentificador
    numero: str = Field(description="Número normalizado: solo dígitos.")


class ConsultaRespuesta(BaseModel):
    consulta: ConsultaEfectuada
    estado: EstadoConsulta
    resultados: list[Resultado]
    advertencias: list[Advertencia]


class PersonaConsulta(BaseModel):
    """Respuesta pública de la consulta JSON: únicamente los seis campos acordados.

    Todos los campos pueden ser `null` cuando la fuente elegida no los publica.
    """

    model_config = ConfigDict(extra="forbid")

    nombre: str | None = Field(
        default=None,
        description="Nombre o razón social tal como lo publica la fuente, sin corregir.",
    )
    dni: str | None = Field(default=None, description="DNI publicado, solo dígitos.")
    cuit: str | None = Field(
        default=None, description="CUIT o CUIL publicado, 11 dígitos sin separadores."
    )
    edad: int | None = Field(
        default=None, ge=0, description="Edad en años publicada por la fuente; no se calcula."
    )
    sexo: str | None = Field(
        default=None,
        description="Texto publicado por la fuente (por ejemplo, Masculino); no se infiere.",
    )
    provincia_ubicacion: str | None = Field(
        default=None, description="Provincia o ubicación tal como la publica la fuente."
    )
