"""Diseños públicos reconocidos; compartidos por la espera y el parser."""

from dataclasses import dataclass


@dataclass(frozen=True)
class EstructuraBusqueda:
    cabecera: str
    total: str
    resultados: str
    tarjetas: str
    nombre: str
    rotulos: str
    valores: str
    aviso_vacio: str


ESTRUCTURAS = (
    EstructuraBusqueda(
        cabecera="main .results-hero h1.results-title strong",
        total="main .results-section .results-main .results-summary p.count",
        resultados="main .results-section .results-main",
        tarjetas=".results-list > article.result-card",
        nombre=".result-card-head h2.result-card-title",
        rotulos=".result-card-body dl.result-facts > .result-fact > dt",
        valores="following-sibling::dd",
        aviso_vacio=".empty-state p",
    ),
    EstructuraBusqueda(
        cabecera="main .about-transform-section h2.about-title strong",
        total="main .about-transform-section p",
        resultados="main .about-features-section",
        tarjetas=".card",
        nombre=".card-body h3",
        rotulos=".card-body .text-muted",
        valores=(
            "following-sibling::*[contains(concat(' ', normalize-space(@class), ' '), ' fw-bold ')]"
        ),
        aviso_vacio="p.text-muted",
    ),
)
