# Logs de solicitudes

Cada petición HTTP registrada genera una línea JSON con método, plantilla de
ruta, estado HTTP, duración, resultado y un `request_id`. Las consultas incluyen
el **DNI o CUIT/CUIL enviado**, tal como solicitó el propietario. La respuesta
HTTP incluye `X-Request-ID` para correlacionarla con su registro.

Ejemplo con identificador sintético:

```json
{
  "evento": "solicitud_http",
  "fecha": "2026-11-05T12:00:00.000+00:00",
  "request_id": "5795e9f522bb4ee08ef1299fbc0c8be6",
  "pid": 1,
  "metodo": "POST",
  "ruta": "/api/v1/consultas",
  "consulta": {"tipo": "dni", "numero": "30111222"},
  "estado": 200,
  "resultado": "completada",
  "duracion_ms": 8950.2,
  "solicitudes_total": 12,
  "solicitudes_operacion": 8,
  "rechazadas_429_total": 2
}
```

Las fechas están en UTC. Los contadores corresponden al proceso indicado por
`pid` y se reinician con él. `solicitudes_operacion` cuenta ese método y ruta;
`solicitudes_total` cuenta las peticiones HTTP registradas, incluyendo errores
y rechazos, no solo las que terminaron con éxito.

## Ver en tiempo real

Desde el checkout local:

```bash
docker compose logs --follow --tail 100 api
```

No se requiere publicar un endpoint de logs ni habilitar un panel público.
Los identificadores completos permanecen en los logs privados del contenedor;
no copiar registros reales a commits, issues, capturas públicas o fixtures.

## Contar solicitudes en un intervalo

El script resume los registros disponibles sin volver a imprimir los DNI:

```bash
docker compose logs --no-log-prefix --since 1h api 2>&1 | python3 scripts/resumir_logs.py
```

En Windows puede usarse `python` en lugar de `python3`.

El resumen muestra cantidad de peticiones, distribución por estado y cantidad
por método/ruta. Cuenta solo las líneas presentes en el intervalo consultado;
no es una base histórica permanente ni recupera logs ya rotados o pertenecientes
a contenedores eliminados. No usar `--timestamps` ni prefijos de Compose en la
entrada del resumen, porque el script espera una línea JSON por evento.

## Qué se registra

- `/api/v1/consultas`: el `tipo` y `numero` que superaron la validación de esquema,
  incluso si la consulta termina con un error de fuente o sin resultados.
- HTTP 429: se incluye `limite` (`ip`, `total`, `en_curso` o `clientes`). El cuerpo
  se rechaza antes de leerlo, por lo que esos eventos no contienen el DNI enviado.
- JSON o identificadores que no superan la validación de esquema: se registra
  el error HTTP sin copiar la entrada inválida al log.
- Las respuestas personales de las fuentes, cabeceras, tokens, cookies
  y query strings no se vuelcan. Las rutas no reconocidas se agrupan como
  `(no_reconocida)` para evitar registrar datos insertados en un path arbitrario.
- Una petición cancelada se marca `cancelada`; si todavía no se habían enviado
  cabeceras, su estado HTTP es `null`. Una respuesta cortada se marca `interrumpida`.

`/health` se omite por defecto para que los healthchecks no inflen los contadores.
`OPENRENAPER_LOG_HEALTH=true` lo incluye. `OPENRENAPER_LOG_SOLICITUDES=false`
desactiva este registro. El contenedor usa `--no-access-log` para evitar duplicar
las líneas con el log de acceso crudo de Uvicorn.

Compose limita los logs del contenedor mediante `json-file`: archivos de hasta
10 MB y un máximo de tres archivos, rotados por Docker. La configuración se
aplica al recrear OpenRENAPER y no cambia el daemon ni otros contenedores.
