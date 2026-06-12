"""
filters/keywords.py
Filtro por palabras clave: primer descarte, gratis e instantáneo.

FASE 1.

Antes de gastar un solo token de IA, este filtro decide si un post es
*candidato* a concurso. Es la primera capa de la cascada:

    post -> ¿pasa keywords? -> (Fase 2) ¿la IA confirma? -> alerta

Reglas:
  - Es candidato si el texto contiene ALGUNA palabra de `incluir`
    y NINGUNA de `excluir`.
  - La comparación ignora mayúsculas/minúsculas y tildes, porque los captions
    colombianos mezclan ambas ("dinamica"/"dinámica", "T&C"/"t&c").

Nota de diseño: la comparación es por subcadena (substring), no por palabra
exacta. Es simple y suficiente para Fase 1; puede dejar pasar algún falso
positivo (p. ej. "gana" dentro de otra palabra). Eso es intencional: el filtro
de keywords está pensado para ser permisivo y barato, y la IA de la Fase 2 es
la que afina la precisión. Mejor dejar pasar de más aquí que perder un concurso.
"""

from __future__ import annotations

import unicodedata


def normalizar(texto: str) -> str:
    """
    Devuelve el texto en minúsculas y sin tildes, para comparar de forma robusta.
    Ej: "Participá YA — Dinámica" -> "participa ya — dinamica".

    Quita los diacríticos descomponiendo cada carácter (NFD) y eliminando las
    marcas combinantes. Así "á"->"a", "ñ"->"n", "ü"->"u".
    """
    if not texto:
        return ""
    texto = texto.lower()
    descompuesto = unicodedata.normalize("NFD", texto)
    sin_tildes = "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")
    return sin_tildes


def es_candidato(texto: str, incluir: list[str], excluir: list[str]) -> bool:
    """
    Devuelve True si el texto contiene alguna palabra de `incluir` y ninguna
    de `excluir`, comparando de forma normalizada (sin mayúsculas ni tildes).

    Si el texto está vacío, no es candidato. Si tiene una palabra de exclusión,
    se descarta aunque también tenga palabras de inclusión.
    """
    texto_norm = normalizar(texto)
    if not texto_norm:
        return False

    # Normalizamos también las keywords para comparar en igualdad de condiciones.
    incluir_norm = [normalizar(k) for k in incluir if k]
    excluir_norm = [normalizar(k) for k in excluir if k]

    # Si aparece cualquier palabra de exclusión, se descarta de inmediato.
    if any(palabra in texto_norm for palabra in excluir_norm):
        return False

    # Es candidato si aparece al menos una palabra de inclusión.
    return any(palabra in texto_norm for palabra in incluir_norm)
