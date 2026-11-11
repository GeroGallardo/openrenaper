"""Proveedores de fuentes públicas (scraping).

Cada proveedor separa tres etapas:

1. obtención del contenido (HTTP directo o navegador),
2. interpretación del HTML en registros crudos de la fuente,
3. normalización de esos registros en `DatosPersona`.

Las rutas HTTP no conocen a los proveedores: los usa `ConsultaService`.
"""
