r"""
scripts/probar_telegram.py
Prueba el notificador de Telegram enviando mensajes reales a tu chat.

Hace tres cosas:
  1. Verifica que el bot_token es válido (getMe).
  2. Envía un heartbeat de prueba.
  3. Envía una alerta de prueba con un post de ejemplo.

Requisito previo: haberle escrito al bot desde tu Telegram al menos una vez
(si no, Telegram no permite que el bot te escriba) y tener bot_token y chat_id
en config/settings.yaml.

Uso (desde la raíz del proyecto):
    python scripts\probar_telegram.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from notifier.telegram import NotificadorTelegram  # noqa: E402
from scheduler import _destinatarios_telegram  # noqa: E402

RUTA_CONFIG = RAIZ / "config" / "settings.yaml"


def main() -> None:
    if not RUTA_CONFIG.exists():
        sys.exit(
            f"No se encontró {RUTA_CONFIG}.\n"
            "Copia config/settings.example.yaml a config/settings.yaml."
        )

    config = yaml.safe_load(RUTA_CONFIG.read_text(encoding="utf-8")) or {}
    telegram = config.get("telegram", {})
    bot_token = telegram.get("bot_token")
    destinatarios = _destinatarios_telegram(telegram)

    if not bot_token or not destinatarios:
        sys.exit("Falta telegram.bot_token o telegram.chat_id / chat_ids en config/settings.yaml.")

    print(f"Destinatarios configurados: {', '.join(destinatarios)}")
    notificador = NotificadorTelegram(bot_token, destinatarios)

    print("1. Verificando el bot (getMe)...")
    if not notificador.probar_conexion():
        sys.exit("   El bot_token no es válido o no hay conexión. Revisa el token.")
    print("   OK: el bot responde.")

    print("2. Enviando heartbeat de prueba...")
    ok_hb = notificador.enviar_heartbeat("✅ Prueba de Concurso Radar: heartbeat recibido.")
    print("   OK" if ok_hb else "   Falló (revisa el chat_id).")

    print("3. Enviando alerta de prueba...")
    post_ejemplo = {
        "cuenta": "falabella_co",
        "caption": "¡Compra y participa! Llévate una TV 4K. Aplican T&C. Sorteo el 30 de junio.",
        "url": "https://www.instagram.com/p/DZXv3EvjWi7/",
        "fecha": "2026-06-09T16:00:18.000Z",
        "imagen_url": "",
    }
    ok_alerta = notificador.enviar_alerta(post_ejemplo)
    print("   OK" if ok_alerta else "   Falló.")

    if ok_hb and ok_alerta:
        print("\nRevisa tu Telegram: deberías ver el heartbeat y la alerta de prueba.")
    else:
        print("\nAlgo falló. Lo más común: el chat_id es incorrecto, o no le has "
              "escrito al bot desde tu Telegram todavía.")


if __name__ == "__main__":
    main()
