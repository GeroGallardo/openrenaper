"""Resume las líneas JSON disponibles en stdin; no imprime identificadores consultados."""

import json
import sys
from collections import Counter
from collections.abc import Iterable


def resumir(lineas: Iterable[str]) -> dict:
    estados = Counter()
    operaciones = Counter()
    total = 0
    for linea in lineas:
        try:
            dato = json.loads(linea)
        except (ValueError, TypeError):
            continue
        if not isinstance(dato, dict) or dato.get("evento") != "solicitud_http":
            continue
        metodo, ruta = dato.get("metodo"), dato.get("ruta")
        if not isinstance(metodo, str) or not isinstance(ruta, str):
            continue
        total += 1
        estados[str(dato.get("estado"))] += 1
        operaciones[metodo, ruta] += 1
    return {
        "solicitudes_en_logs": total,
        "por_estado": dict(sorted(estados.items())),
        "por_operacion": [
            {"metodo": metodo, "ruta": ruta, "cantidad": cantidad}
            for (metodo, ruta), cantidad in sorted(operaciones.items())
        ],
    }


if __name__ == "__main__":
    print(json.dumps(resumir(sys.stdin), ensure_ascii=False, indent=2))
