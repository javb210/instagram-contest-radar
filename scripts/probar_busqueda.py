r"""
scripts/probar_busqueda.py
Prueba el módulo searchers/instagram_search.py de punta a punta.

Trae posts de 2 cuentas usando el BuscadorInstagram y los muestra YA
normalizados al formato del sistema ({cuenta, caption, url, fecha, imagen_url}).
Sirve para confirmar que el módulo entrega datos limpios antes de conectarlo
al filtro de keywords y al notificador.

Uso (desde la raíz del proyecto, con el venv activado y settings.yaml listo):
    python scripts\probar_busqueda.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))  # permite importar el paquete searchers/

from searchers.instagram_search import BuscadorInstagram  # noqa: E402

RUTA_CONFIG = RAIZ / "config" / "settings.yaml"
CUENTAS_PRUEBA = 2  # cuántas cuentas de la lista usar en la prueba


def main() -> None:
    if not RUTA_CONFIG.exists():
        sys.exit(
            f"No se encontró {RUTA_CONFIG}.\n"
            "Copia config/settings.example.yaml a config/settings.yaml y "
            "pega tu token y actor_id de Apify."
        )

    config = yaml.safe_load(RUTA_CONFIG.read_text(encoding="utf-8")) or {}
    token = config.get("apify", {}).get("token")
    actor_id = config.get("apify", {}).get("actor_id")
    cuentas = config.get("cuentas", [])[:CUENTAS_PRUEBA]
    posts_por_cuenta = config.get("busqueda", {}).get("posts_por_cuenta", 2)

    if not token or not actor_id:
        sys.exit("Falta apify.token o apify.actor_id en config/settings.yaml.")

    print(f"Buscando {posts_por_cuenta} post(s) por cuenta de: {cuentas}")
    print("Lanzando corrida en Apify (puede tardar entre 30 s y 2 min)...\n")

    buscador = BuscadorInstagram(token, actor_id)
    try:
        posts = buscador.buscar(cuentas, posts_por_cuenta)
    except RuntimeError as error:
        sys.exit(str(error))

    print(f"Posts normalizados recibidos: {len(posts)}")
    print("=" * 70)
    for i, post in enumerate(posts, 1):
        caption = post["caption"].replace("\n", " ")
        if len(caption) > 140:
            caption = caption[:140] + "..."
        imagen = post["imagen_url"]
        if len(imagen) > 80:
            imagen = imagen[:80] + "..."
        print(f"[{i}] {post['cuenta']}  |  {post['fecha']}")
        print(f"    url:    {post['url']}")
        print(f"    imagen: {imagen}")
        print(f"    texto:  {caption or '(sin texto)'}")
        print("-" * 70)

    print(
        "\nSi ves los posts con su cuenta, fecha, url y texto, el módulo de "
        "Instagram quedó funcionando. Pégame la salida para seguir con el filtro de keywords."
    )


if __name__ == "__main__":
    main()
