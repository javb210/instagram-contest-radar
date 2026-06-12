r"""
scripts/diagnostico_filtro.py
Diagnóstico: ¿el filtro de fecha trae solo posts recientes, o posts viejos?

Corre la búsqueda con la config REAL (skipPinnedPosts + onlyPostsNewerThan)
sobre las 12 cuentas, y para cada post traído muestra su fecha y si cae DENTRO
de la ventana esperada o si es un post VIEJO que no debería estar.

Si la mayoría son "VIEJOS", el actor está devolviendo el último post de cada
cuenta aunque no haya nada nuevo (y cobrándolo). Si casi todos están "DENTRO",
el costo es real y la palanca es la frecuencia.

Uso (desde la raíz del proyecto):
    python scripts\diagnostico_filtro.py
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from scheduler import cargar_config  # noqa: E402
from searchers.instagram_search import BuscadorInstagram  # noqa: E402


def ventana_a_minutos(texto: str) -> int:
    """Convierte '70 minutes', '2 hours', '1 day' a minutos. Default 70."""
    if not texto:
        return 70
    m = re.match(r"\s*(\d+)\s*(minute|hour|day|week)", texto.lower())
    if not m:
        return 70
    n, unidad = int(m.group(1)), m.group(2)
    factor = {"minute": 1, "hour": 60, "day": 1440, "week": 10080}[unidad]
    return n * factor


def main() -> None:
    config = cargar_config()
    cuentas = config["cuentas"]
    posts_por_cuenta = config["busqueda"]["posts_por_cuenta"]
    newer_than = config["busqueda"].get("solo_posts_mas_nuevos_que") or "70 minutes"
    saltar_fijados = config["busqueda"].get("saltar_posts_fijados", True)

    minutos = ventana_a_minutos(newer_than)
    limite = datetime.now(timezone.utc) - timedelta(minutes=minutos)

    print(f"Ventana esperada: últimos {minutos} min (desde {limite:%Y-%m-%d %H:%M} UTC)")
    print(f"Config: filtro={newer_than}, saltar_fijados={saltar_fijados}")
    print("Buscando en las 12 cuentas...\n")

    buscador = BuscadorInstagram(config["apify"]["token"], config["apify"]["actor_id"])
    posts = buscador.buscar(cuentas, posts_por_cuenta, newer_than=newer_than,
                            saltar_fijados=saltar_fijados)

    dentro = 0
    viejos = 0
    print(f"{'ESTADO':<8} | {'CUENTA':<18} | FECHA DEL POST")
    print("-" * 60)
    for post in sorted(posts, key=lambda p: p["fecha"], reverse=True):
        try:
            fecha = datetime.fromisoformat(post["fecha"].replace("Z", "+00:00"))
            es_reciente = fecha >= limite
        except (ValueError, TypeError):
            fecha, es_reciente = None, False
        estado = "DENTRO" if es_reciente else "VIEJO"
        if es_reciente:
            dentro += 1
        else:
            viejos += 1
        fecha_txt = fecha.strftime("%Y-%m-%d %H:%M UTC") if fecha else "?"
        print(f"{estado:<8} | {post['cuenta']:<18} | {fecha_txt}")

    print("-" * 60)
    print(f"Total: {len(posts)} posts -> {dentro} DENTRO de la ventana, {viejos} VIEJOS")
    print()
    if viejos > dentro:
        print("DIAGNÓSTICO: el actor trae mayormente posts VIEJOS pese al filtro.")
        print("Devuelve el último post de cada cuenta aunque no haya novedad, y lo")
        print("cobra. El filtro de fecha no basta; toca cambiar de actor o de táctica.")
    else:
        print("DIAGNÓSTICO: los posts son mayormente RECIENTES. El filtro funciona;")
        print("el costo es real y la palanca para bajarlo es la frecuencia.")


if __name__ == "__main__":
    main()
