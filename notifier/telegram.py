"""
notifier/telegram.py
Envío de alertas y heartbeat por Telegram.

FASE 1 — alertas y heartbeat.
Fase posterior — comandos interactivos (/pausar, /activar, /buscar, /estado).

Decisión técnica: para *enviar* mensajes usamos la API HTTP de Telegram
directamente con `requests` (síncrono y simple), en vez de python-telegram-bot,
que desde la v20 es asíncrono y añade complejidad innecesaria para esto.
python-telegram-bot se reservará para la fase de comandos, donde sí hay que
*recibir* mensajes.

Es el único canal de salida del sistema: por eso el envío captura los errores
y devuelve True/False en vez de lanzar excepción, para que un fallo de red no
tumbe el ciclo. Quien orquesta decide si reintenta o lo registra.
"""

from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone

import requests

API_BASE = "https://api.telegram.org"
TIMEOUT = 15  # segundos para las peticiones HTTP
ZONA_COLOMBIA = timezone(timedelta(hours=-5))  # Colombia es UTC-5 fijo (sin horario de verano)


def _fecha_legible(iso: str) -> str:
    """
    Convierte un timestamp ISO en UTC (ej. "2026-06-09T16:00:18.000Z") a hora
    de Colombia, legible. Si no se puede parsear, devuelve el texto original.
    """
    if not iso:
        return "fecha desconocida"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(ZONA_COLOMBIA).strftime("%Y-%m-%d %H:%M") + " (hora Col.)"
    except (ValueError, TypeError):
        return iso


def formatear_alerta(post: dict, resumen: dict | None = None) -> str:
    """
    Arma el texto de la alerta en formato HTML de Telegram.

    - Fase 1 (resumen=None): usa los datos crudos del post (cuenta, texto, fecha).
    - Fase 2 (resumen dado): usa el resumen estructurado de la IA
      (marca, premio, mecánica, fecha límite).

    Todo el contenido dinámico se escapa con html.escape para que captions con
    caracteres como < > & no rompan el formato.
    """
    cuenta = html.escape(post.get("cuenta", ""))
    url = post.get("url", "")
    fecha = _fecha_legible(post.get("fecha", ""))

    if resumen:
        marca = html.escape(str(resumen.get("marca") or cuenta))
        premio = html.escape(str(resumen.get("premio") or "No especificado"))
        mecanica = html.escape(str(resumen.get("mecanica") or "No especificada"))
        fecha_limite = html.escape(str(resumen.get("fecha_limite") or "No especificada"))
        lineas = [
            f"🏆 <b>{marca}</b> — Concurso detectado",
            "",
            f"🎁 <b>Premio:</b> {premio}",
            f"📝 <b>Qué hacer:</b> {mecanica}",
            f"⏳ <b>Válido hasta:</b> {fecha_limite}",
            f"📅 Publicado: {fecha}",
        ]
    else:
        caption = (post.get("caption") or "").strip()
        if len(caption) > 350:
            caption = caption[:350] + "…"
        caption = html.escape(caption) if caption else "(sin texto)"
        lineas = [
            f"🏆 <b>Posible concurso</b> — @{cuenta}",
            "",
            caption,
            "",
            f"📅 Publicado: {fecha}",
        ]

    if url:
        lineas.append(f'🔗 <a href="{html.escape(url, quote=True)}">Ver publicación</a>')
    return "\n".join(lineas)


class NotificadorTelegram:
    """Encapsula el envío de mensajes a Telegram mediante el bot."""

    def __init__(self, bot_token: str, chat_id: str) -> None:
        if not bot_token or not chat_id:
            raise ValueError("Se requieren 'bot_token' y 'chat_id' de Telegram.")
        self.bot_token = bot_token
        self.chat_id = str(chat_id)

    def _url(self, metodo: str) -> str:
        return f"{API_BASE}/bot{self.bot_token}/{metodo}"

    def _enviar_texto(self, texto: str) -> bool:
        """Envía un mensaje. Devuelve True si Telegram lo aceptó, False si falló."""
        payload = {
            "chat_id": self.chat_id,
            "text": texto,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,  # mensajes limpios; el link sigue clickeable
        }
        try:
            respuesta = requests.post(self._url("sendMessage"), json=payload, timeout=TIMEOUT)
        except requests.RequestException as error:
            print(f"[telegram] Error de red al enviar: {error}")
            return False
        if respuesta.status_code != 200:
            print(f"[telegram] Telegram respondió {respuesta.status_code}: {respuesta.text}")
            return False
        return True

    def enviar_alerta(self, post: dict, resumen: dict | None = None) -> bool:
        """Envía la alerta de un concurso detectado."""
        return self._enviar_texto(formatear_alerta(post, resumen))

    def enviar_heartbeat(self, mensaje: str | None = None) -> bool:
        """Envía el mensaje de 'sigo activo' para confirmar que el sistema vive."""
        texto = mensaje or "✅ Concurso Radar sigue activo. Sin novedades por ahora."
        return self._enviar_texto(texto)

    def probar_conexion(self) -> bool:
        """Verifica que el bot_token es válido consultando getMe."""
        try:
            respuesta = requests.get(self._url("getMe"), timeout=TIMEOUT)
        except requests.RequestException as error:
            print(f"[telegram] Error de red en getMe: {error}")
            return False
        return respuesta.status_code == 200 and respuesta.json().get("ok", False)
