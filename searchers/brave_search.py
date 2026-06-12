"""
searchers/brave_search.py
Búsqueda web mediante la API de Brave Search.

FUENTE SECUNDARIA — fase posterior (no Fase 1).

Cubre el flujo de Google que hace el cliente manualmente: buscar páginas de
"términos y condiciones", "campaña", boleterías que reabren cupos, etc. No
sirve para detectar posts nuevos de Instagram en tiempo real (de eso se
encarga instagram_search.py vía Apify); es un complemento para hallazgos web.

Flujo previsto:
  1. Para cada consulta configurada, llamar a la API de Brave Search.
  2. Normalizar los resultados a la misma forma de diccionario que usa el resto
     del sistema, para que el filtro y el notificador no distingan la fuente.
"""

from __future__ import annotations


class BuscadorBrave:
    """Encapsula las llamadas a la API de Brave Search."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def buscar(self, consultas: list[str], max_resultados: int = 5) -> list[dict]:
        """
        Ejecuta cada consulta y devuelve resultados normalizados:
            {"cuenta": "web", "caption": <título+resumen>, "url": ..., "fecha": ..., "imagen_url": ""}
        """
        raise NotImplementedError("Fuente secundaria; se implementa en una fase posterior.")
