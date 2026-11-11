# OpenRENAPER

Servicio HTTP para consultar datos públicos de una persona a partir de su **DNI** o
**CUIT/CUIL**. Lo levantás junto a tu backend y le hacés un `POST` con el número;
responde siempre los mismos seis campos.

> Proyecto académico del TFI de Programación de Aplicaciones Distribuidas (UTN FRT).
> **No pertenece al RENAPER ni a ningún organismo, y no acredita identidad.**

```http
POST /api/v1/consultas
Content-Type: application/json

{"tipo": "dni", "numero": "30111222"}
```

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

## Cómo funciona

El servicio consulta en el momento dos páginas web públicas, **pag_web1** y
**pag_web2**, con un navegador Chromium que ejecuta el JavaScript de cada página.
Primero intenta con pag_web1 y, si no encuentra a la persona o falla, con pag_web2.
No combina datos de las dos fuentes ni guarda lo que consulta.

Las direcciones de las fuentes **no están en el código**: se configuran en `.env`
(ver [Configurar las fuentes](#configurar-las-fuentes)).

## Levantarlo

### Con Docker Compose (recomendado)

No hace falta instalar Python ni Chromium.

```sh
git clone <url-de-este-repo> openrenaper
cd openrenaper
cp .env.example .env        # completá las URL de las fuentes
docker compose up --build -d
```

Queda en http://127.0.0.1:8000. Comprobá que responde con `GET /health`.

### Con Python y uv

Requisitos: Python 3.13 y [uv](https://docs.astral.sh/uv/getting-started/installation/).

```sh
uv sync --frozen
uv run playwright install chromium
export OPENRENAPER_PAG_WEB1_URL='...'   # ver .env.example
export OPENRENAPER_PAG_WEB2_URL='...'
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

## Configurar las fuentes

Cada fuente se habilita con su URL de búsqueda, que es una plantilla con el
marcador `{numero}`:

```sh
OPENRENAPER_PAG_WEB1_URL=https://<sitio-1>/<ruta-de-busqueda>?<parametro>={numero}
OPENRENAPER_PAG_WEB2_URL=https://<sitio-2>/<ruta-de-busqueda>/{numero}
```

Una fuente con la URL vacía queda deshabilitada; sin ninguna, las consultas
responden `503`. Las URL reales las pasa el equipo de OpenRENAPER. El resto de los
parámetros (plazos, reintentos, concurrencia, límite de peticiones) tienen valores
por defecto razonables y están explicados en `.env.example`.

## Integrarlo en tu backend

Llamalo por HTTP desde tu servidor como a cualquier otra API. Ejemplo en C#:

```csharp
using System.Net.Http.Json;

using var http = new HttpClient
{
    BaseAddress = new Uri("http://127.0.0.1:8000"),
    Timeout = TimeSpan.FromSeconds(60), // las fuentes pueden tardar varios segundos
};

var respuesta = await http.PostAsJsonAsync("/api/v1/consultas", new { tipo = "dni", numero = "30111222" });
var cuerpo = await respuesta.Content.ReadAsStringAsync();
// 200: persona encontrada · 404: sin resultados · 409: varias personas posibles
// 422: número inválido · 429: límite de peticiones · 502/503/504: fuente con problemas
```

Puntos a tener en cuenta:

- `numero` va **solo con dígitos**. Un CUIL se consulta con `"tipo": "cuit"`.
- Los campos que la fuente no publica llegan en `null`.
- Decidí por el campo `codigo` del error, no por el texto del mensaje.
- El límite por defecto es de **15 peticiones por minuto por IP**. Al superarlo,
  respondé al `429` esperando los segundos de `Retry-After`.

La documentación interactiva queda en `/docs` (Scalar), `/swagger` y `/redoc`.
El contrato completo, los códigos de error y las reglas de validación están en
[docs/API.md](docs/API.md). Los logs están descriptos en [docs/logs.md](docs/logs.md).

## Comprobar cambios

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest            # usa fuentes falsas, no consulta sitios reales
uv run pytest -m real    # contra las fuentes reales, con las URL configuradas
```

## Estructura

```text
app/consultas/      Endpoint, modelos y servicio que coordina las fuentes
app/proveedores/    Obtención (HTTP o Chromium), límites y las fuentes pag_web1 y pag_web2
app/api/            Errores, límite de peticiones y registro de solicitudes
tests/              Pruebas con HTML sintético; tests/real/ consulta las fuentes
docs/               Contrato de la API y logs
```

## Integrantes

- Ibañez Matias Agustin
- Gutierrez Andrés
- Gallardo Piorno Gerónimo
- Atilio Vergara

## Licencia

MIT. Ver [LICENSE](LICENSE).
