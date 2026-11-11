"""La documentación interactiva de Scalar usa el contrato local y no amplía la API."""

import json
import re
from typing import Any

from fastapi.testclient import TestClient

from app.documentacion import RUTA_SCALAR, SCALAR_JS_VERSION
from app.main import INTEGRANTES, crear_app


def _pagina() -> tuple[Any, str]:
    respuesta = TestClient(crear_app(proveedores=[])).get(RUTA_SCALAR)
    return respuesta, respuesta.text


def _configuracion(html: str) -> dict[str, Any]:
    coincidencia = re.search(r"createApiReference\(\"#app\", (\{.*\})\)", html)
    assert coincidencia, "La página debe inicializar Scalar con una configuración JSON."
    return json.loads(coincidencia.group(1))


def test_scalar_responde_html() -> None:
    respuesta, _ = _pagina()
    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith("text/html")
    assert RUTA_SCALAR == "/docs"


def test_descripcion_publica_no_enumera_proveedores() -> None:
    descripcion = crear_app(proveedores=[]).openapi()["paths"]["/api/v1/consultas"]["post"][
        "description"
    ]
    assert "pag_web1" not in descripcion.lower()
    assert "pag_web2" not in descripcion.lower()
    assert "Retry-After" in descripcion


def test_scalar_usa_el_openapi_local() -> None:
    _, html = _pagina()
    configuracion = _configuracion(html)
    assert configuracion["url"] == "/openapi.json"
    assert "content" not in configuracion and "sources" not in configuracion


def test_scalar_no_usa_proxy_ni_servidor_fijo() -> None:
    _, html = _pagina()
    configuracion = _configuracion(html)
    assert not configuracion.get("proxyUrl")
    assert "proxy.scalar.com" not in html
    # Sin servidores: el cliente usa rutas relativas al origen de la página.
    assert "servers" not in configuracion and "baseServerURL" not in configuracion
    assert "servers" not in crear_app(proveedores=[]).openapi()
    assert "localhost" not in html and "18080" not in html


def test_scalar_desactiva_agent_mcp_telemetria_y_autenticacion() -> None:
    _, html = _pagina()
    configuracion = _configuracion(html)
    assert configuracion["agent"] == {"disabled": True}
    assert configuracion["mcp"] == {"disabled": True}
    assert configuracion["telemetry"] is False
    assert "authentication" not in configuracion
    assert not configuracion.get("hideClientButton")
    assert not configuracion.get("hideTestRequestButton")
    assert not configuracion.get("hideModels")
    assert not configuracion.get("hideSearch")


def test_scalar_fija_la_version_del_cdn() -> None:
    _, html = _pagina()
    assert f"@scalar/api-reference@{SCALAR_JS_VERSION}" in html
    assert re.fullmatch(r"\d+\.\d+\.\d+", SCALAR_JS_VERSION)


def test_scalar_no_aparece_en_el_contrato_y_se_conservan_las_otras_vistas() -> None:
    cliente = TestClient(crear_app(proveedores=[]))
    esquema = cliente.get("/openapi.json").json()
    assert RUTA_SCALAR not in esquema["paths"]
    assert not any(ruta in esquema["paths"] for ruta in ("/docs", "/redoc", "/openapi.json"))
    for ruta in ("/swagger", "/redoc"):
        assert cliente.get(ruta).status_code == 200


def test_navegacion_por_etiquetas() -> None:
    esquema = crear_app(proveedores=[]).openapi()
    assert [t["name"] for t in esquema["tags"]] == ["consultas", "operación"]
    etiquetas = {
        etiqueta
        for metodos in esquema["paths"].values()
        for operacion in metodos.values()
        for etiqueta in operacion["tags"]
    }
    assert etiquetas == {"consultas", "operación"}


def test_ejemplos_publicados_conservan_los_null() -> None:
    esquema = crear_app(proveedores=[]).openapi()
    for metodos in esquema["paths"].values():
        for operacion in metodos.values():
            for respuesta in operacion["responses"].values():
                for contenido in respuesta.get("content", {}).values():
                    for ejemplo in contenido.get("examples", {}).values():
                        valor = ejemplo["value"]
                        if isinstance(valor, dict) and "codigo" in valor:
                            assert "fuente" in valor, "ErrorRespuesta siempre incluye fuente"
    respuesta = esquema["paths"]["/api/v1/consultas"]["post"]["responses"]["200"]
    ejemplos = respuesta["content"]["application/json"]["examples"]
    assert any(None in e["value"].values() for e in ejemplos.values())


def test_descripcion_incluye_al_equipo() -> None:
    descripcion = (
        TestClient(crear_app(proveedores=[])).get("/openapi.json").json()["info"]["description"]
    )
    assert "### Integrantes" in descripcion
    for nombre in INTEGRANTES:
        assert f"- {nombre}" in descripcion
