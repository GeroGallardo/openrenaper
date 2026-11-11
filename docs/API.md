# API de consultas

Acceso directo: ningún endpoint requiere autenticación, claves, tokens ni
encabezados especiales. Los ejemplos usan datos sintéticos.

## Documentación interactiva

Todas las vistas leen el mismo contrato, generado por FastAPI en `/openapi.json`.

| Ruta            | Vista                                                          |
|-----------------|----------------------------------------------------------------|
| `/docs`         | Scalar: navegación por etiquetas, búsqueda, modelos y cliente. |
| `/swagger`      | Swagger UI.                                                    |
| `/redoc`        | ReDoc.                                                         |
| `/openapi.json` | Contrato OpenAPI.                                              |

Con Docker Compose local: http://127.0.0.1:8000/docs (o el puerto de
`OPENRENAPER_PORT`).

Scalar se integra con `scalar-fastapi` (ver `app/documentacion.py`):

- El navegador descarga `@scalar/api-reference@1.76.4` desde jsDelivr
  (`https://cdn.jsdelivr.net/npm/@scalar/api-reference@1.76.4`). Sin acceso a ese
  CDN la página no carga; `/swagger` y `/redoc` siguen disponibles. Para actualizarla,
  cambiar `SCALAR_JS_VERSION` y verificar la página.
- El cliente envía las solicitudes directamente a esta API, al mismo origen
  (host y puerto) desde el que se abrió `/docs`; no usa el proxy de Scalar.
- Agent, MCP y telemetría están desactivados. El contrato no declara
  autenticación; el cliente de Scalar muestra igualmente un selector de
  autenticación vacío y opcional, que no hace falta usar.
- Los ejemplos de la página son estáticos; el resultado de «Probar solicitud»
  es la respuesta real de la API. Una consulta válida consulta fuentes externas
  reales y puede demorar.
- Los ejemplos de código del cliente usan rutas relativas (`curl /api/v1/...`):
  anteponer el origen, por ejemplo `http://127.0.0.1:8000`.
Las respuestas registradas incluyen `X-Request-ID` para correlacionarlas con
los [logs del servicio](logs.md), que incluyen el identificador consultado.

## Límite de peticiones

Las rutas `/api/` comparten una ventana deslizante de 60 segundos: por defecto
admiten **15 peticiones por IP, 30 en total y hasta 4 en curso**. No se encolan
las peticiones que exceden el límite: se rechazan antes de leer el cuerpo o
invocar a los proveedores. Las solicitudes inválidas también consumen cuota;
las rechazadas por el limitador no extienden la ventana. OPTIONS queda exento.
`/health`, `/docs`, `/swagger`, `/redoc` y `/openapi.json` no consumen cuota.

La respuesta es HTTP **429**, con `Retry-After` (segundos de espera) y
`Cache-Control: no-store`:

```json
{
  "codigo": "limite_solicitudes_excedido",
  "mensaje": "Se alcanzó el límite de peticiones. Reintentá más tarde.",
  "fuente": null,
  "detalles": [{"limite": "ip"}]
}
```

`detalles.limite` puede indicar `ip`, `total`, `en_curso` o `clientes` (capacidad
acotada del registro en memoria). Para el cupo en curso se informa una espera
de un segundo, sin garantizar que el trabajo anterior termine en ese plazo.

Los contadores son **por proceso**, se reinician con la aplicación y no se
comparten entre workers o réplicas. La configuración del servidor comienza con
un worker. Para escalar manteniendo un único presupuesto, se necesita un
limitador compartido o en el proxy; no basta con aumentar `WEB_CONCURRENCY`.
No se usa el DNI ni el CUIT como clave, ni se registran las IP en logs del limitador.
La clave es la dirección del cliente resuelta por Uvicorn; no se aceptan
cabeceras de IP suministradas por clientes no confiables. Para usar un proxy inverso, declarar su IP en `OPENRENAPER_PROXIES_CONFIABLES`.

## Endpoints

| Método | Ruta                            | Uso                                              |
|--------|---------------------------------|--------------------------------------------------|
| GET    | `/health`                       | Estado del proceso; no consulta fuentes.         |
| POST   | `/api/v1/consultas`             | Consulta un DNI o CUIT.                    |

```sh
curl -X POST http://127.0.0.1:8000/api/v1/consultas \
  -H "Content-Type: application/json" \
  -d '{"tipo": "cuit", "numero": "20301112220"}'
```

## Entrada y respuesta de consulta JSON

`POST /api/v1/consultas` recibe únicamente `tipo` (`dni` o `cuit`) y `numero`
como texto solo con dígitos. No admite puntos, guiones, barras, espacios ni el
valor `cuil` como tipo; un CUIL se consulta con `tipo: "cuit"`.

```json
{"tipo": "dni", "numero": "30111222"}
```

La respuesta exitosa contiene exactamente seis campos:

```json
{
  "nombre": "PERSONA DE EJEMPLO",
  "dni": "30111222",
  "cuit": "20301112220",
  "edad": 45,
  "sexo": "Masculino",
  "provincia_ubicacion": "PROVINCIA DE EJEMPLO"
}
```

Los seis campos están siempre presentes y todos admiten `null`. `edad` es un
entero; los demás son texto.

Primero se consulta pag_web1. pag_web2 se consulta solo si pag_web1 falla,
agota su plazo o no encuentra coincidencias pertinentes. Si la primera fuente
encuentra datos válidos, no se consulta la segunda ni se combinan sus respuestas.

- Los campos que la fuente no publique se devuelven como `null`. No se calculan
  la edad ni el DNI a partir de otros datos, y no se infiere el sexo del CUIT.
- El nombre se devuelve tal como aparece, incluso si contiene caracteres dañados.
  No se sustituyen por letras supuestas ni se agregan marcas de calidad.
- La respuesta exitosa no contiene `estado`, `fuente`, `resultados`,
  `adicionales`, `desconocidos` ni `advertencias`.
- Sin resultados en todas las fuentes: HTTP 404. Varias personas posibles o datos
  contradictorios para la misma persona: HTTP 409; no se elige una arbitrariamente.
- Si no hay datos y alguna fuente falló, se conserva el error de fuente.
- Las fuentes externas pueden demorar; no hay un tiempo de respuesta garantizado.
  Cada fuente tiene un límite configurable (`OPENRENAPER_TIEMPO_LIMITE_PROVEEDOR`).

## Reglas de identificadores

La entrada JSON es estricta; internamente `app/identificadores.py` también
normaliza separadores publicados por las fuentes.

- DNI: 7 u 8 dígitos, sin cero inicial.
- CUIT: 11 dígitos, prefijos 20, 23, 24, 27, 30, 33 o 34 y módulo 11 válido.
- Un formato válido no acredita existencia ni identidad.

## Errores

Los errores usan el siguiente formato:

```json
{"codigo": "entrada_invalida", "mensaje": "...", "fuente": null, "detalles": []}
```

| Código                        | HTTP | Cuándo                                              |
|-------------------------------|------|-----------------------------------------------------|
| `solicitud_mal_formada`       | 400  | El cuerpo no es JSON válido.                        |
| `sin_resultados`            | 404  | Ninguna fuente encontró coincidencias.             |
| `consulta_ambigua`          | 409  | Hay varias personas posibles o datos contradictorios. |
| `entrada_invalida`            | 422  | Esquema o identificador inválido.                   |
| `limite_solicitudes_excedido` | 429  | Se agotó la cuota o el cupo de trabajo en curso.    |
| `respuesta_no_interpretable`  | 502  | La fuente respondió algo que no se puede interpretar. |
| `fuente_no_disponible`        | 503  | Fuente caída o sin fuentes configuradas.            |
| `tiempo_agotado`              | 504  | La fuente no respondió a tiempo.                    |

Un fallo de fuente nunca se informa como `sin_resultados`. Si fallan varias
fuentes, se informa el error más específico (502, luego 504, luego 503) y
`detalles` enumera cada fallo.

## Integración de proveedores

- Scraping: implementar `ProveedorConsulta` (`app/consultas/proveedores.py`) y
  registrarlo en `proveedores_predeterminados` (`app/recursos.py`).
- Si necesitan recursos (por ejemplo, un navegador), implementar `iniciar` y `cerrar`:
  la aplicación los llama al arrancar y al terminar.
- Las pruebas pasan implementaciones falsas a `crear_app` (`tests/falsos.py`);
  CI no consulta sitios reales. Las comprobaciones reales llevan la marca
  `real` y se ejecutan a mano con `uv run pytest -m real`.

## Configuración

Todas las variables, con su valor por defecto, están en `.env.example`. Las dos
fuentes se habilitan con su URL de búsqueda:

| Variable                     | Formato                                                    |
|------------------------------|------------------------------------------------------------|
| `OPENRENAPER_PAG_WEB1_URL`   | URL de búsqueda con el marcador `{numero}`; vacía = deshabilitada |
| `OPENRENAPER_PAG_WEB2_URL`   | URL de búsqueda con el marcador `{numero}`; vacía = deshabilitada |

`{numero}` se reemplaza por el DNI o CUIT/CUIL normalizado (solo dígitos).
