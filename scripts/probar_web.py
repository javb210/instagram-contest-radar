r"""
scripts/probar_web.py
Prueba la fuente WEB (piloto) sin tocar la base de datos ni Telegram. Corre una
búsqueda real con la herramienta web_search de Anthropic e imprime los candidatos
que devuelve, para MEDIR la precisión/ruido del piloto antes de confiarle alertas.

SÍ consume crédito de Anthropic: una llamada con varias búsquedas web (~$10/1000
búsquedas, así que centavos por corrida). Es la cuenta de Anthropic, APARTE de Apify.

Lee 'web' y 'anthropic' de config/settings.yaml (los mismos que usará producción),
así que también sirve para afinar 'web.consultas' y 'web.criterio'. La fuente debe
estar encendida: pon 'web.activo: true' y una 'anthropic.api_key' válida.

Uso (desde la raíz del proyecto, con el venv activado):
    python scripts\probar_web.py
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from scheduler import cargar_config, construir_buscador_web  # noqa: E402


def main() -> None:
    config = cargar_config()
    buscador = construir_buscador_web(config)
    if buscador is None:
        sys.exit(
            "La fuente web está apagada o sin api_key.\n"
            "Pon 'web.activo: true' y una 'anthropic.api_key' válida en "
            "config/settings.yaml para probarla."
        )

    print(f"Buscando concursos en la web con el modelo {buscador.modelo}.")
    print(f"Ventana: ultimos {buscador.dias_recientes} dias. Max busquedas: {buscador.max_busquedas}.")
    print("=" * 78)

    try:
        candidatos = buscador.buscar()
    except RuntimeError as error:
        sys.exit(f"[ERROR] La busqueda web fallo: {error}")

    print(f"Busquedas web ejecutadas (facturables): {buscador.ultimo_num_busquedas}")
    print(f"Candidatos relevantes devueltos: {len(candidatos)}")
    print("-" * 78)

    for i, post in enumerate(candidatos, 1):
        r = post["resumen"]
        print(f"[{i}] {r['marca']}")
        print(f"     premio: {r['premio']} | mecanica: {r['mecanica']} | hasta: {r['fecha_limite']}")
        print(f"     url: {post['url']}")
        print("-" * 78)

    print(
        "Nota: revisa a mano que sean concursos colombianos VIGENTES reales. Si hay "
        "mucho ruido, ajusta 'web.criterio' o 'web.consultas' antes de poner la fuente "
        "en produccion (correr_una_vez)."
    )


if __name__ == "__main__":
    main()
