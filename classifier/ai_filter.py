"""
classifier/ai_filter.py
Clasificación y resumen con IA (Claude Haiku, vía API de Anthropic).

FASE 2 — no se implementa todavía.

Solo se invoca sobre los posts que YA pasaron el filtro de keywords, para
gastar IA únicamente en lo que vale la pena. Resuelve lo que las keywords
no pueden:
  - Descartar falsos positivos (ofertas de empleo, webinars, etc.).
  - Filtrar por valor del premio (el cliente solo quiere premios relevantes:
    boletas, TVs; no regalías pequeñas).
  - Extraer un resumen estructurado para la alerta de Telegram.
"""

from __future__ import annotations


class ClasificadorIA:
    """Encapsula las llamadas a Claude Haiku para clasificar y resumir posts."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        # TODO (Fase 2): inicializar el cliente de Anthropic.

    def es_concurso_relevante(self, caption: str) -> bool:
        """
        Devuelve True si el post es un concurso real Y el premio es relevante
        según el criterio del cliente. False en caso contrario.
        """
        raise NotImplementedError("Se implementa en la Fase 2 (clasificación con IA).")

    def resumir(self, caption: str) -> dict:
        """
        Extrae un resumen estructurado del concurso:
            {"marca": ..., "premio": ..., "mecanica": ..., "fecha_limite": ...}
        """
        raise NotImplementedError("Se implementa en la Fase 2 (clasificación con IA).")
