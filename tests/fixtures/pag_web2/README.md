# Fixtures de pag_web2

HTML **sintético**, escrito a mano para las pruebas. No proviene de respuestas
reales de la fuente y no contiene datos de personas reales: nombres y CUIT/CUIL
son ficticios (los CUIT tienen dígito verificador válido para ejercitar la
normalización).

La estructura replica la que se supone para la página de búsqueda
(`app/proveedores/pag_web2/selectores.py`). Si la fuente cambia, actualizar
primero los selectores con la comprobación real (`pytest -m real`) y después
estos fixtures, sin copiar HTML real ni datos personales.

| Archivo                  | Caso                                             |
|--------------------------|--------------------------------------------------|
| `un_resultado.html`      | Una persona física con atributos fiscales.       |
| `varios_resultados.html` | Varios CUIT/CUIL para la misma búsqueda.         |
| `sin_resultados.html`    | La fuente informa explícitamente cero resultados. |
| `campos_ausentes.html`   | Resultados sin denominación, tipo o atributos.    |
| `incompleto.html`        | La fuente informa más resultados que los listados. |
| `inesperado.html`        | Página 200 que no es una búsqueda (desafío).      |
| `cuit_invalido.html`     | Resultado con un CUIT que no supera la validación. |
