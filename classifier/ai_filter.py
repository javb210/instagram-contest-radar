"""
classifier/ai_filter.py
Clasificación y resumen con IA (Claude Haiku, vía API de Anthropic).

FASE 2 — segunda capa de la cascada que ahorra costo:

    post -> ¿pasa keywords? -> ¿la IA confirma que es concurso relevante? -> resumen -> alerta

Solo se invoca sobre los posts que YA pasaron el filtro de keywords, para gastar
IA únicamente en lo que vale la pena. Resuelve lo que las keywords no pueden:
  - Descartar falsos positivos (publicidad sin mecánica, empleos, webinars, etc.).
  - Filtrar por valor del premio (criterio del cliente, ver `criterio_relevancia`).
  - Extraer un resumen estructurado para la alerta de Telegram.

Decisión de diseño: UNA sola llamada por caption devuelve relevancia + resumen en
un JSON (mitad de costo/latencia frente a dos llamadas). Los métodos
`es_concurso_relevante` y `resumir` se conservan como envoltorios sobre esa llamada.

La cuenta de Anthropic la paga el cliente y es SEPARADA de Apify (no cuenta contra
el tope de $5/mes). El `import anthropic` es perezoso (dentro de `__init__`): así
este módulo se puede importar aunque el paquete no esté instalado, y la Fase 1
sigue corriendo intacta mientras no haya `api_key`.
"""

from __future__ import annotations

import json

# Criterio por defecto de "qué cuenta como concurso relevante". Se sobrescribe con
# `anthropic.criterio_relevancia` de la config, que se afina con el cliente a partir
# del etiquetado del gold set (ver docs/AI_CONTEXT.md §7.3).
CRITERIO_POR_DEFECTO = (
    "Es relevante un concurso o sorteo real donde el usuario debe participar, comprar "
    "o interactuar para ganar un premio concreto. NO es relevante: publicidad sin "
    "mecánica de participación, ofertas o descuentos, empleos, webinars o cursos, ni "
    "dinámicas de muy bajo valor."
)

MODELO_POR_DEFECTO = "claude-haiku-4-5-20251001"

# Claves del resumen estructurado que consume notifier/telegram.py:formatear_alerta.
_CLAVES_RESUMEN = ("marca", "premio", "mecanica", "fecha_limite")


class ClasificadorIA:
    """Encapsula las llamadas a Claude Haiku para clasificar y resumir posts."""

    def __init__(
        self,
        api_key: str,
        modelo: str = MODELO_POR_DEFECTO,
        criterio_relevancia: str | None = None,
    ) -> None:
        if not api_key:
            raise ValueError(
                "ClasificadorIA requiere una api_key de Anthropic. Déjala vacía en la "
                "config para desactivar la IA (el sistema corre solo con keywords)."
            )
        # Import perezoso: solo se necesita el paquete cuando hay key configurada.
        import anthropic  # noqa: PLC0415

        self.cliente = anthropic.Anthropic(api_key=api_key)
        self.modelo = modelo or MODELO_POR_DEFECTO
        self.criterio = criterio_relevancia or CRITERIO_POR_DEFECTO

    def _prompt_sistema(self) -> str:
        """Instrucciones fijas del clasificador, con el criterio del cliente inyectado."""
        return (
            "Eres un clasificador de publicaciones de Instagram de marcas colombianas. "
            "Recibes el texto (caption) de UNA publicación y debes decidir si es un "
            "concurso relevante y, si lo es, resumirlo.\n\n"
            f"Criterio de relevancia:\n{self.criterio}\n\n"
            "Responde ÚNICAMENTE con un objeto JSON válido, sin texto adicional ni "
            "bloques de código, con exactamente estas claves:\n"
            '  "relevante": true o false,\n'
            '  "marca": nombre de la marca o cuenta,\n'
            '  "premio": el premio en juego ("No especificado" si no está claro),\n'
            '  "mecanica": cómo participar, máximo 15 palabras ("No especificada" si no está clara),\n'
            '  "fecha_limite": hasta cuándo participar ("No especificada" si no está clara).\n'
            "Si \"relevante\" es false, igual completa las demás claves con lo que puedas "
            "o con \"No especificado\"."
        )

    def analizar(self, caption: str) -> dict:
        """
        Clasifica y resume un caption en UNA sola llamada a la IA.

        Devuelve un dict con las claves:
            {"relevante": bool, "marca", "premio", "mecanica", "fecha_limite"}

        Lanza excepción si la llamada o el parseo del JSON fallan; quien orquesta la
        captura para aplicar el comportamiento "fail-open" (avisar igual sin resumen).
        """
        respuesta = self.cliente.messages.create(
            model=self.modelo,
            max_tokens=300,
            temperature=0,
            system=self._prompt_sistema(),
            messages=[{"role": "user", "content": caption or "(sin texto)"}],
        )
        texto = "".join(
            bloque.text for bloque in respuesta.content if bloque.type == "text"
        ).strip()
        return self._parsear(texto)

    @staticmethod
    def _parsear(texto: str) -> dict:
        """
        Extrae el objeto JSON de la respuesta del modelo de forma defensiva: toma
        desde el primer '{' hasta el último '}' por si el modelo agrega texto o
        cercas de código. Normaliza las claves al formato que espera la alerta.
        """
        inicio = texto.find("{")
        fin = texto.rfind("}")
        if inicio == -1 or fin == -1 or fin < inicio:
            raise ValueError(f"La IA no devolvió un JSON reconocible: {texto!r}")
        datos = json.loads(texto[inicio : fin + 1])

        resultado = {"relevante": bool(datos.get("relevante", False))}
        for clave in _CLAVES_RESUMEN:
            valor = datos.get(clave)
            resultado[clave] = str(valor).strip() if valor else "No especificado"
        return resultado

    def es_concurso_relevante(self, caption: str) -> bool:
        """
        Devuelve True si el post es un concurso real Y relevante según el criterio
        del cliente. Envoltorio sobre `analizar` (interfaz histórica del §3).
        """
        return self.analizar(caption)["relevante"]

    def resumir(self, caption: str) -> dict:
        """
        Extrae el resumen estructurado del concurso:
            {"marca": ..., "premio": ..., "mecanica": ..., "fecha_limite": ...}
        Envoltorio sobre `analizar` (interfaz histórica del §3).
        """
        analisis = self.analizar(caption)
        return {clave: analisis[clave] for clave in _CLAVES_RESUMEN}
