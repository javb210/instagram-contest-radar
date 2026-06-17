r"""
scripts/obtener_chat_ids.py
Averigua el chat_id de cada persona que le ha escrito al bot.

Telegram NO deja que el bot le escriba a alguien que no le haya escrito antes.
Por eso, para agregar a una persona nueva (ej. el cliente) hay que:

  1. Que esa persona abra Telegram, busque tu bot y le mande CUALQUIER mensaje
     (un "hola" o el botón Start).
  2. Correr este script. Lista los chats recientes con su nombre y su chat_id.
  3. Copiar el chat_id en config/settings.yaml dentro de telegram.chat_ids.

No envía nada ni gasta dinero: solo consulta getUpdates (los mensajes recientes
que ha recibido el bot).

OJO: Telegram solo guarda los updates de las últimas ~24 horas. Si no aparece
alguien, pídele que le vuelva a escribir al bot y corre el script de nuevo.

Uso (desde la raíz del proyecto, con el venv activo):
    python scripts\obtener_chat_ids.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests
import yaml

RAIZ = Path(__file__).resolve().parent.parent
RUTA_CONFIG = RAIZ / "config" / "settings.yaml"
API_BASE = "https://api.telegram.org"
TIMEOUT = 15


def main() -> None:
    if not RUTA_CONFIG.exists():
        sys.exit(
            f"No se encontro {RUTA_CONFIG}.\n"
            "Copia config/settings.example.yaml a config/settings.yaml."
        )

    config = yaml.safe_load(RUTA_CONFIG.read_text(encoding="utf-8")) or {}
    bot_token = (config.get("telegram") or {}).get("bot_token")
    if not bot_token:
        sys.exit("Falta telegram.bot_token en config/settings.yaml.")

    print("Consultando los mensajes recientes del bot (getUpdates)...\n")
    try:
        respuesta = requests.get(f"{API_BASE}/bot{bot_token}/getUpdates", timeout=TIMEOUT)
    except requests.RequestException as error:
        sys.exit(f"Error de red: {error}")

    if respuesta.status_code != 200:
        sys.exit(f"Telegram respondio {respuesta.status_code}: {respuesta.text}")

    updates = respuesta.json().get("result", [])
    if not updates:
        print("No hay mensajes recientes.")
        print("Pidele a la persona que le escriba CUALQUIER mensaje al bot y vuelve a correr esto.")
        return

    # Junta cada chat una sola vez (la persona pudo enviar varios mensajes).
    vistos: dict[str, str] = {}
    for upd in updates:
        msg = upd.get("message") or upd.get("edited_message") or {}
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            continue
        nombre = chat.get("title") or " ".join(
            filtro for filtro in [chat.get("first_name"), chat.get("last_name")] if filtro
        ) or chat.get("username") or "(sin nombre)"
        vistos[str(chat_id)] = nombre

    print("Chats que le han escrito al bot:\n")
    for chat_id, nombre in vistos.items():
        print(f"   {nombre}  ->  chat_id: {chat_id}")

    print("\nCopia el chat_id que necesites en config/settings.yaml, dentro de telegram.chat_ids:")
    print("   chat_ids:")
    for chat_id in vistos:
        print(f'     - "{chat_id}"')


if __name__ == "__main__":
    main()
