r"""
scripts/probar_apify.py
Script de INSPECCIÓN (no es parte del sistema final).

Objetivo: hacer una corrida mínima del actor de Apify contra 2 cuentas y
volcar el JSON crudo que devuelve, para ver cómo se llaman de verdad los
campos (caption, url, fecha, etc.) en el actor elegido. Con esos nombres
confirmados se escribe el mapeo definitivo en searchers/instagram_search.py.

Cómo usarlo:
  1. Copiar config/settings.example.yaml a config/settings.yaml y pegar:
       - apify.token     (tu API token de Apify)
       - apify.actor_id  (sugerido para empezar: "apify/instagram-scraper")
  2. Activar el entorno virtual e instalar dependencias:
       pip install -r requirements.txt
  3. Desde la raíz del proyecto, correr:
       python scripts\probar_apify.py
  4. Pegar la salida completa en el chat para definir el mapeo.

Consume centavos: trae pocos posts de 2 cuentas.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml
from apify_client import ApifyClient

# Raíz del proyecto (este script vive en scripts/, subimos un nivel).
RAIZ = Path(__file__).resolve().parent.parent
RUTA_CONFIG = RAIZ / "config" / "settings.yaml"

# Parámetros de la prueba (deliberadamente pequeños para gastar poco).
CUENTAS_PRUEBA = 2     # cuántas cuentas de la lista usar en la inspección
POSTS_POR_CUENTA = 2   # cuántos posts traer por cuenta


def cargar_config(ruta: Path) -> dict:
    """Carga config/settings.yaml y valida que existan los datos mínimos."""
    if not ruta.exists():
        sys.exit(
            f"No se encontró {ruta}.\n"
            "Copia config/settings.example.yaml a config/settings.yaml y "
            "pega tu token y actor_id de Apify."
        )
    with open(ruta, "r", encoding="utf-8") as archivo:
        config = yaml.safe_load(archivo) or {}

    apify = config.get("apify", {})
    if not apify.get("token"):
        sys.exit("Falta apify.token en config/settings.yaml.")
    if not apify.get("actor_id"):
        sys.exit(
            "Falta apify.actor_id en config/settings.yaml.\n"
            'Para empezar, sugiero: actor_id: "apify/instagram-scraper"'
        )
    if not config.get("cuentas"):
        sys.exit("No hay cuentas en config/settings.yaml.")
    return config


def construir_input(cuentas: list[str], posts_por_cuenta: int) -> dict:
    """
    Arma el input para el actor OFICIAL apify/instagram-scraper.

    Si usas otro actor, este es el único bloque que hay que ajustar: cada
    actor nombra distinto sus campos de entrada. Para el oficial, lo esencial
    es la lista de URLs de perfil, el tipo de resultado y el límite por perfil.
    """
    return {
        "directUrls": [f"https://www.instagram.com/{u}/" for u in cuentas],
        "resultsType": "posts",
        "resultsLimit": posts_por_cuenta,
        "addParentData": False,
    }


def _campo(objeto, *nombres):
    """
    Lee un campo de `objeto`, que según la versión del SDK de Apify puede ser
    un diccionario (versiones viejas) o un modelo pydantic (versiones nuevas).
    Prueba varios nombres posibles (camelCase y snake_case) y devuelve el
    primero que exista. Así el script funciona sin importar la versión.
    """
    for nombre in nombres:
        if isinstance(objeto, dict):
            if nombre in objeto:
                return objeto[nombre]
        elif hasattr(objeto, nombre):
            return getattr(objeto, nombre)
    return None


def _recortar(valor, limite: int = 300):
    """Recorta strings largos para que el volcado sea legible en consola."""
    if isinstance(valor, str) and len(valor) > limite:
        return valor[:limite] + f"... [recortado, {len(valor)} caracteres]"
    if isinstance(valor, list):
        return f"[lista con {len(valor)} elementos]"
    if isinstance(valor, dict):
        return f"{{dict con claves: {sorted(valor.keys())}}}"
    return valor


def main() -> None:
    config = cargar_config(RUTA_CONFIG)
    token = config["apify"]["token"]
    actor_id = config["apify"]["actor_id"]
    cuentas = config["cuentas"][:CUENTAS_PRUEBA]

    run_input = construir_input(cuentas, POSTS_POR_CUENTA)

    print("=" * 70)
    print("INSPECCIÓN DE APIFY")
    print("=" * 70)
    print("Actor:    ", actor_id)
    print("Cuentas:  ", cuentas)
    print("Input enviado:")
    print(json.dumps(run_input, indent=2, ensure_ascii=False))
    print("-" * 70)
    print("Lanzando corrida (puede tardar entre 30 s y 2 min)...")

    cliente = ApifyClient(token)
    try:
        run = cliente.actor(actor_id).call(run_input=run_input)
    except Exception as error:
        sys.exit(
            f"\nFalló la corrida del actor: {error}\n"
            "Revisa que el token sea válido, que el actor_id exista y que "
            "tengas conexión a internet."
        )

    estado = _campo(run, "status")
    dataset_id = _campo(run, "defaultDatasetId", "default_dataset_id")
    print(f"Estado de la corrida: {estado}")

    if not dataset_id:
        sys.exit("La corrida no devolvió dataset. Revisa el log en la consola de Apify.")

    items = list(cliente.dataset(dataset_id).iterate_items())
    print(f"Posts devueltos: {len(items)}")
    print("=" * 70)

    if not items:
        print(
            "No vinieron posts. Posibles causas: las cuentas son privadas, el "
            "input no es el que espera este actor, o el actor no encontró posts.\n"
            "Revisa el log de la corrida en la consola de Apify."
        )
        return

    primero = items[0]
    print("CLAVES del primer post (estos son los nombres reales de los campos):")
    print(sorted(primero.keys()))
    print("-" * 70)
    print("MUESTRA del primer post (valores largos recortados):")
    muestra = {clave: _recortar(valor) for clave, valor in primero.items()}
    print(json.dumps(muestra, indent=2, ensure_ascii=False, default=str))
    print("=" * 70)
    print(
        "Listo. Copia TODO lo de arriba en el chat: con los nombres reales de "
        "los campos escribimos el mapeo definitivo de instagram_search.py."
    )


if __name__ == "__main__":
    main()