r"""
scripts/probar_newerthan.py
Experimento: medir si el filtro onlyPostsNewerThan reduce el costo real.

Corre el actor DOS veces sobre las mismas cuentas:
  A) sin filtro de fecha       -> trae los N posts más recientes por cuenta
  B) con filtro "2 hours"      -> debería traer solo posts de las últimas 2 horas

Si B devuelve muchos menos posts que A (idealmente casi cero, porque las marcas
no postean cada par de horas), el filtro está recortando resultados. Para
confirmar que además recorta el COSTO, hay que mirar el dashboard de Apify y
comparar el costo de las dos corridas (ver instrucciones al final).

Usa pocas cuentas para gastar poco. Uso (desde la raíz del proyecto):
    python scripts\probar_newerthan.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from searchers.instagram_search import BuscadorInstagram  # noqa: E402

RUTA_CONFIG = RAIZ / "config" / "settings.yaml"
CUENTAS_PRUEBA = 3
POSTS_POR_CUENTA = 2
VENTANA = "2 hours"  # filtro de fecha a probar


def main() -> None:
    if not RUTA_CONFIG.exists():
        sys.exit(f"No se encontró {RUTA_CONFIG}.")

    config = yaml.safe_load(RUTA_CONFIG.read_text(encoding="utf-8")) or {}
    token = config.get("apify", {}).get("token")
    actor_id = config.get("apify", {}).get("actor_id")
    cuentas = config.get("cuentas", [])[:CUENTAS_PRUEBA]

    if not token or not actor_id:
        sys.exit("Falta apify.token o apify.actor_id en config/settings.yaml.")

    buscador = BuscadorInstagram(token, actor_id)

    print(f"Cuentas de prueba: {cuentas}")
    print("=" * 70)

    print(f"\nCORRIDA A — SIN filtro de fecha (trae {POSTS_POR_CUENTA} por cuenta)...")
    posts_a = buscador.buscar(cuentas, POSTS_POR_CUENTA)
    print(f"   Posts devueltos: {len(posts_a)}")

    print(f"\nCORRIDA B — CON filtro 'onlyPostsNewerThan = {VENTANA}'...")
    posts_b = buscador.buscar(cuentas, POSTS_POR_CUENTA, newer_than=VENTANA)
    print(f"   Posts devueltos: {len(posts_b)}")

    print("\n" + "=" * 70)
    print("RESULTADO")
    print("=" * 70)
    print(f"  Sin filtro:  {len(posts_a)} posts")
    print(f"  Con filtro:  {len(posts_b)} posts")
    if len(posts_b) < len(posts_a):
        print("  -> El filtro SÍ recorta los posts devueltos. Buena señal.")
    else:
        print("  -> El filtro NO recortó (devolvió igual o más). Puede ser que")
        print("     las cuentas postearon en las últimas 2 horas, o que el actor")
        print("     no respeta el filtro. Repite cuando no haya posts recientes.")
    print("=" * 70)
    print("PASO CLAVE — confirmar el ahorro de COSTO:")
    print("  1. Abre el dashboard de Apify -> sección 'Runs' (o 'Actor runs').")
    print("  2. Busca las dos corridas que acabas de hacer (las más recientes).")
    print("  3. Compara el costo de cada una.")
    print("     - Si la corrida B costó bastante menos que la A -> el filtro AHORRA.")
    print("     - Si costaron casi igual -> el filtro no reduce el cobro en este")
    print("       actor, y tocaría pasar al actor de respaldo (khadinakbar).")
    print("  Pégame ambos costos y decidimos.")


if __name__ == "__main__":
    main()
