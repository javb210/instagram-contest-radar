"""
searchers/web_search.py
Búsqueda web de concursos mediante la herramienta `web_search` de Anthropic.

FUENTE SECUNDARIA — piloto (no Fase 1). Reemplaza el viejo esqueleto
`brave_search.py`: Brave quitó su tier gratis (feb 2026) y Google Custom Search
cerró a nuevos clientes, así que la ruta elegida es la herramienta de búsqueda web
nativa de Claude. Ventaja: corre sobre la MISMA cuenta de Anthropic de la Fase 2
(separada del tope de Apify de $5/mes) y Claude busca Y clasifica en una sola
llamada, en vez de buscar + filtrar por keywords + clasificar por separado.

Automatiza el flujo que el cliente hace a mano en Google: hallar páginas de
"términos y condiciones" de concursos colombianos publicados hace poco. La web es
mucho más ruidosa que vigilar cuentas de Instagram conocidas (plantillas legales,
concursos vencidos, páginas sin fecha confiable), por eso el criterio de relevancia
es estricto y la fuente arranca apagada (`web.activo: false`).

Flujo:
  1. Una llamada a Claude con la herramienta servidor `web_search` activada y la
     ubicación fijada en Colombia, pidiéndole concursos VIGENTES con T&C recientes.
  2. Claude decide relevancia DENTRO de la búsqueda y devuelve un arreglo JSON de
     candidatos ya resumidos.
  3. Se normaliza cada candidato a la misma forma del resto del sistema
     ({cuenta, caption, url, fecha, imagen_url}) más un `resumen` para la alerta,
     de modo que dedup, notificador y base no distinguen la fuente.

El `import anthropic` es perezoso (igual que classifier/ai_filter.py): así el
módulo se importa aunque el paquete no esté instalado y la Fase 1 corre intacta
mientras la fuente web esté apagada.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

log = logging.getLogger("concurso_radar")

# Versión de la herramienta de búsqueda compatible con el modelo del clasificador
# (Haiku 4.5). La versión con filtrado dinámico (_20260209) no cubre Haiku, así que
# se usa la estable. El nombre debe ser exactamente "web_search".
HERRAMIENTA_BUSQUEDA = "web_search_20250305"

MODELO_POR_DEFECTO = "claude-haiku-4-5-20251001"

# Tope de continuaciones del bucle server-side: la herramienta de búsqueda corre un
# bucle propio en el servidor y puede devolver stop_reason="pause_turn". Se reanuda
# reenviando el contexto, con un tope para no quedar en un bucle infinito.
MAX_CONTINUACIONES = 4

# Claves del resumen estructurado que consume notifier/telegram.py:formatear_alerta.
_CLAVES_RESUMEN = ("marca", "premio", "mecanica", "fecha_limite")


class BuscadorWeb:
    """Encapsula la búsqueda web de concursos vía la herramienta `web_search`."""

    def __init__(
        self,
        api_key: str,
        modelo: str | None = None,
        consultas: list[str] | None = None,
        dias_recientes: int = 7,
        criterio: str | None = None,
        max_busquedas: int = 5,
        pais: str | None = None,
    ) -> None:
        if not api_key:
            raise ValueError(
                "BuscadorWeb requiere una api_key de Anthropic. Deja 'web.activo' en "
                "false para desactivar la fuente web (el resto del sistema corre igual)."
            )
        # Import perezoso: el paquete solo se necesita cuando la fuente está activa.
        import anthropic  # noqa: PLC0415

        self.cliente = anthropic.Anthropic(api_key=api_key)
        self.modelo = modelo or MODELO_POR_DEFECTO
        self.consultas = consultas or []
        self.dias_recientes = int(dias_recientes)
        self.criterio = (criterio or "").strip()
        self.max_busquedas = int(max_busquedas)
        # Código de país ISO para localizar la búsqueda. OJO: la herramienta solo
        # soporta algunos países (CO NO está soportado). Vacío = sin localización; el
        # enfoque colombiano lo dan igual el prompt, las consultas y el criterio.
        self.pais = (pais or "").strip().upper()
        # Métricas de la última corrida (insumo del gasto): búsquedas facturables y
        # tokens del modelo (Sonnet lee las páginas, así que los tokens pesan).
        self.ultimo_num_busquedas = 0
        self.ultimo_uso_entrada = 0
        self.ultimo_uso_salida = 0

    def _prompt(self) -> str:
        """Arma la instrucción de búsqueda con la fecha de hoy y el criterio inyectados."""
        hoy = datetime.now().strftime("%Y-%m-%d")
        lineas = [
            f"Hoy es {hoy}. Eres un asistente que busca en la web concursos y sorteos "
            f"VIGENTES de marcas en Colombia publicados en los últimos {self.dias_recientes} "
            "días, con sus términos y condiciones (T&C / bases).",
            "",
            "Usa la herramienta de búsqueda web para encontrarlos. Consultas sugeridas:",
        ]
        for c in self.consultas:
            lineas.append(f"  - {c}")
        lineas += [
            "",
            f"REGLA DE VIGENCIA: hoy es {hoy}. EXCLUYE únicamente los concursos cuya fecha "
            "de cierre ya PASÓ (es anterior a hoy). Si la fecha de cierre es hoy o posterior, "
            "inclúyelo. Si no logras determinar la fecha de cierre, inclúyelo igual pero "
            "intenta hallarla abriendo la página de T&C; pon la fecha en 'fecha_limite' en "
            "formato YYYY-MM-DD cuando la conozcas, así se puede verificar.",
        ]
        if self.criterio:
            lineas += ["", "Criterio de relevancia:", self.criterio]
        lineas += [
            "",
            "Cuando termines de buscar, responde ÚNICAMENTE con un arreglo JSON válido "
            "(sin texto adicional ni cercas de código). Incluye los concursos relevantes "
            "que no estén vencidos. Cada elemento debe tener exactamente estas claves:",
            '  "relevante": true,',
            '  "marca": nombre de la marca,',
            '  "premio": el premio en juego ("No especificado" si no está claro),',
            '  "mecanica": cómo participar, máximo 15 palabras,',
            '  "fecha_limite": fecha de cierre en formato YYYY-MM-DD si la conoces, o el '
            'texto tal cual ("No especificada" si no está clara),',
            '  "url": el enlace a la página del concurso o sus T&C,',
            '  "titulo": un título corto del concurso.',
            "Si no encuentras ninguno relevante, responde con un arreglo vacío: []",
        ]
        return "\n".join(lineas)

    def _herramienta(self) -> dict:
        """Bloque de la herramienta servidor `web_search`. Solo agrega `user_location`
        si hay un país configurado y soportado (CO no lo está) — el foco colombiano lo
        dan igual el prompt, las consultas y el criterio."""
        herramienta = {
            "type": HERRAMIENTA_BUSQUEDA,
            "name": "web_search",
            "max_uses": self.max_busquedas,
        }
        if self.pais:
            herramienta["user_location"] = {"type": "approximate", "country": self.pais}
        return herramienta

    def buscar(self) -> list[dict]:
        """
        Ejecuta la búsqueda web y devuelve candidatos normalizados.

        Cada candidato:
            {"cuenta": "web", "caption": ..., "url": ..., "fecha": <ISO>,
             "imagen_url": "", "resumen": {marca, premio, mecanica, fecha_limite}}

        Lanza RuntimeError si la llamada falla; quien orquesta lo captura para avisar
        sin tumbar el ciclo de Instagram (fail-soft).
        """
        herramientas = [self._herramienta()]
        mensajes: list[dict] = [{"role": "user", "content": self._prompt()}]
        self.ultimo_num_busquedas = 0
        self.ultimo_uso_entrada = 0
        self.ultimo_uso_salida = 0

        try:
            respuesta = self.cliente.messages.create(
                model=self.modelo,
                max_tokens=2000,
                messages=mensajes,
                tools=herramientas,
            )
            self.ultimo_num_busquedas += _contar_busquedas(respuesta)
            self._sumar_uso(respuesta)

            # Bucle server-side: si la herramienta pausó, reanudar reenviando el
            # contexto (NO se agrega un mensaje "continúa"; el SDK detecta el
            # server_tool_use pendiente y reanuda solo).
            continuaciones = 0
            while respuesta.stop_reason == "pause_turn" and continuaciones < MAX_CONTINUACIONES:
                mensajes.append({"role": "assistant", "content": respuesta.content})
                respuesta = self.cliente.messages.create(
                    model=self.modelo,
                    max_tokens=2000,
                    messages=mensajes,
                    tools=herramientas,
                )
                self.ultimo_num_busquedas += _contar_busquedas(respuesta)
                self._sumar_uso(respuesta)
                continuaciones += 1
        except Exception as error:  # red, auth, rate limit, etc.
            raise RuntimeError(f"Falló la búsqueda web con Anthropic: {error}") from error

        texto = "".join(
            bloque.text for bloque in respuesta.content if bloque.type == "text"
        ).strip()
        return self._normalizar(texto)

    def _sumar_uso(self, respuesta) -> None:
        """Acumula los tokens de una respuesta. Cuenta como 'entrada' los tokens de
        entrada y los de caché (lectura/creación), y como 'salida' los de salida; con
        eso se estima el costo de tokens del modelo en `scheduler.ejecutar_ciclo_web`."""
        uso = getattr(respuesta, "usage", None)
        if not uso:
            return
        self.ultimo_uso_entrada += (
            (getattr(uso, "input_tokens", 0) or 0)
            + (getattr(uso, "cache_read_input_tokens", 0) or 0)
            + (getattr(uso, "cache_creation_input_tokens", 0) or 0)
        )
        self.ultimo_uso_salida += getattr(uso, "output_tokens", 0) or 0

    @staticmethod
    def _normalizar(texto: str) -> list[dict]:
        """
        Extrae el arreglo JSON de la respuesta de forma defensiva (desde el primer
        '[' hasta el último ']', por si el modelo agrega texto o citas) y lo
        convierte a la forma uniforme del sistema. Descarta elementos sin URL.
        """
        inicio = texto.find("[")
        fin = texto.rfind("]")
        if inicio == -1 or fin == -1 or fin < inicio:
            log.warning("La búsqueda web no devolvió un arreglo JSON reconocible.")
            return []
        try:
            crudos = json.loads(texto[inicio : fin + 1])
        except json.JSONDecodeError as error:
            log.warning("No se pudo parsear el JSON de la búsqueda web: %s", error)
            return []

        ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        hoy = datetime.now().date()
        candidatos: list[dict] = []
        for item in crudos:
            if not isinstance(item, dict):
                continue
            # Respaldo de vigencia determinístico: si la fecha de cierre viene como
            # fecha ISO (YYYY-MM-DD) y ya pasó, se descarta sí o sí (no depende del
            # juicio del modelo). Las fechas desconocidas o en texto libre se conservan.
            if _fecha_ya_paso(item.get("fecha_limite"), hoy):
                log.info("Descartado por vencido (%s): %s", item.get("fecha_limite"), item.get("url"))
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue  # sin URL no hay dedup ni enlace; se descarta
            resumen = {
                clave: (str(item.get(clave)).strip() if item.get(clave) else "No especificado")
                for clave in _CLAVES_RESUMEN
            }
            titulo = str(item.get("titulo") or resumen["marca"] or "Concurso").strip()
            candidatos.append(
                {
                    "cuenta": "web",
                    "caption": f"{titulo} — {resumen['premio']}",
                    "url": url,
                    "fecha": ahora,  # la web no expone fecha de publicación confiable
                    "imagen_url": "",
                    "resumen": resumen,
                }
            )
        return candidatos


def _fecha_ya_paso(valor, hoy) -> bool:
    """True solo si `valor` es una fecha ISO (YYYY-MM-DD, con o sin hora) ANTERIOR a
    `hoy`. Texto libre o fechas desconocidas devuelven False (no se descartan): el
    descarte determinístico solo aplica cuando la fecha es inequívoca."""
    if not isinstance(valor, str):
        return False
    try:
        fecha = datetime.strptime(valor.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return False
    return fecha < hoy


def _contar_busquedas(respuesta) -> int:
    """Número de búsquedas web facturables en una respuesta. Es la métrica que mueve
    el costo en Anthropic ($10/1000). Usa el contador canónico
    `usage.server_tool_use.web_search_requests`; si no estuviera, cae a contar los
    bloques server_tool_use de 'web_search' (una búsqueda = un bloque)."""
    uso = getattr(respuesta, "usage", None)
    stu = getattr(uso, "server_tool_use", None)
    requests = getattr(stu, "web_search_requests", None)
    if isinstance(requests, int):
        return requests
    return sum(
        1
        for bloque in respuesta.content
        if getattr(bloque, "type", None) == "server_tool_use"
        and getattr(bloque, "name", None) == "web_search"
    )
