"""
searchers/instagram_search.py
Búsqueda de publicaciones en Instagram mediante un actor de Apify.

FASE 1 — núcleo del sistema.

Actor en uso: apify/instagram-post-scraper.
Tarifa real medida: $1.70/1000 eventos ($0.0017/evento). El actor cobra por
PERFIL CONSULTADO, no por post devuelto — una cuenta sin novedad igual genera
un evento facturado (stub vacío). La palanca de costo es la frecuencia de ciclos.

Este módulo aísla todo el contacto con Apify y normaliza cada post al formato
uniforme del sistema: {cuenta, caption, url, fecha, imagen_url}.

Si se cambia de actor, basta ajustar `_construir_input` (formato de entrada) y
`normalizar_post` (nombres de los campos de salida).
"""

from __future__ import annotations

from apify_client import ApifyClient


def _campo(objeto, *nombres):
    """
    Lee un campo de un objeto que, según la versión del SDK de Apify, puede ser
    un diccionario (versiones viejas) o un modelo pydantic (versiones nuevas).
    Prueba varios nombres y devuelve el primero que exista.
    """
    for nombre in nombres:
        if isinstance(objeto, dict):
            if nombre in objeto:
                return objeto[nombre]
        elif hasattr(objeto, nombre):
            return getattr(objeto, nombre)
    return None


def normalizar_post(post: dict) -> dict | None:
    """
    Convierte un post crudo del actor apify/instagram-post-scraper al formato
    uniforme del sistema. Devuelve None si el post no tiene URL.

    Mapeo (campo real del actor -> nuestro formato):
        ownerUsername -> cuenta
        caption       -> caption     (si viene None, queda "")
        url           -> url         (clave de deduplicación)
        timestamp     -> fecha       (ISO 8601)
        displayUrl    -> imagen_url
    """
    url = post.get("url")
    if not url:
        return None
    return {
        "cuenta": post.get("ownerUsername") or "",
        "caption": post.get("caption") or "",
        "url": url,
        "fecha": post.get("timestamp") or "",
        "imagen_url": post.get("displayUrl") or "",
    }


class BuscadorInstagram:
    """Encapsula las llamadas a Apify para traer posts recientes de Instagram."""

    def __init__(self, token: str, actor_id: str) -> None:
        if not token or not actor_id:
            raise ValueError("Se requieren 'token' y 'actor_id' de Apify.")
        self.actor_id = actor_id
        self._cliente = ApifyClient(token)

    def _construir_input(
        self,
        cuentas: list[str],
        posts_por_cuenta: int,
        newer_than: str | None = None,
        saltar_fijados: bool = True,
    ) -> dict:
        """
        Arma el input para el actor apify/instagram-post-scraper.

        - `username`: lista de usuarios (nombres planos o URLs de perfil).
        - `resultsLimit`: tope de posts por cuenta.
        - `onlyPostsNewerThan`: filtro de fecha; acepta ISO UTC o relativo ("1 day").
        - `skipPinnedPosts`: omite posts fijados (evita ruido y re-cobro).
        - `dataDetailLevel`: forzado a "basicData" para evitar cargos extra por
          datos adicionales que el sistema no usa (métricas, comentarios, etc.).
        """
        run_input: dict = {
            "username": list(cuentas),
            "resultsLimit": posts_por_cuenta,
            "skipPinnedPosts": saltar_fijados,
            "dataDetailLevel": "basicData",
        }
        if newer_than:
            run_input["onlyPostsNewerThan"] = newer_than
        return run_input

    def buscar(
        self,
        cuentas: list[str],
        posts_por_cuenta: int,
        newer_than: str | None = None,
        saltar_fijados: bool = True,
    ) -> list[dict]:
        """
        Trae hasta `posts_por_cuenta` posts recientes de cada cuenta de la lista
        y los devuelve normalizados. Con `newer_than` se limita por fecha.

        Lanza RuntimeError si la corrida de Apify falla o no devuelve dataset,
        para que quien orquesta el ciclo pueda registrarlo y avisar por Telegram
        en vez de fallar en silencio.
        """
        if not cuentas:
            return []

        run_input = self._construir_input(
            cuentas, posts_por_cuenta, newer_than, saltar_fijados
        )
        try:
            run = self._cliente.actor(self.actor_id).call(run_input=run_input)
        except Exception as error:
            raise RuntimeError(f"Falló la corrida de Apify: {error}") from error

        dataset_id = _campo(run, "defaultDatasetId", "default_dataset_id")
        if not dataset_id:
            raise RuntimeError(
                "Apify no devolvió dataset. Revisa el log de la corrida en la consola."
            )

        posts: list[dict] = []
        for item in self._cliente.dataset(dataset_id).iterate_items():
            normalizado = normalizar_post(item)
            if normalizado is not None:
                posts.append(normalizado)
        return posts
