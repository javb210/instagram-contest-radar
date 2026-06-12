r"""
scripts/probar_filtro.py
Prueba el filtro de keywords (filters/keywords.py) SIN gastar en Apify.

Lee las keywords reales de config/settings.yaml y las aplica a una batería de
ejemplos: los 4 posts reales del test de Instagram (ninguno es concurso) y
varios concursos de verdad. Sirve para ver el comportamiento del filtro y para
calibrar las listas de inclusión/exclusión antes de conectarlo al pipeline.

Uso (desde la raíz del proyecto):
    python scripts\probar_filtro.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from filters.keywords import es_candidato  # noqa: E402

RUTA_CONFIG = RAIZ / "config" / "settings.yaml"

# Batería de ejemplos. Edítala libremente para probar tus propios textos.
EJEMPLOS = [
    ("REAL falabella (Día del Padre)",
     "💚 Para quien siempre ha estado ahí. Este Día del Padre, encuentra el regalo perfecto para papá."),
    ("REAL antioquenobog (pre-anuncio)",
     "El tío de toda una Nación está por llegar 🔜🔜 #nacionpalasquesea 🔥"),
    ("REAL falabella (tenis)",
     "Buscando el regalo perfecto para papá? Los tenis más virales están aquí. #FelizDiaPapa"),
    ("CONCURSO compra y gana",
     "¡Compra y participa! Llévate una TV 4K. Aplican T&C. Sorteo el 30 de junio."),
    ("CONCURSO comenta y gana",
     "Comenta y gana boletas para el concierto. Dinámica válida hasta agotar cupos."),
    ("CONCURSO con tildes",
     "Participá por un viaje. Términos y condiciones en la bio."),
    ("EMPLEO (debe descartarse)",
     "Únete a nuestro equipo. Vacante de asesor comercial: gana comisiones atractivas."),
]


def main() -> None:
    if not RUTA_CONFIG.exists():
        sys.exit(
            f"No se encontró {RUTA_CONFIG}.\n"
            "Copia config/settings.example.yaml a config/settings.yaml."
        )

    config = yaml.safe_load(RUTA_CONFIG.read_text(encoding="utf-8")) or {}
    keywords = config.get("keywords", {})
    incluir = keywords.get("incluir", [])
    excluir = keywords.get("excluir", [])

    print("Keywords de inclusión:", incluir)
    print("Keywords de exclusión:", excluir)
    print("=" * 70)
    print(f"{'VEREDICTO':<12} | CASO")
    print("-" * 70)
    for nombre, texto in EJEMPLOS:
        veredicto = "CANDIDATO" if es_candidato(texto, incluir, excluir) else "descartado"
        print(f"{veredicto:<12} | {nombre}")
    print("=" * 70)
    print(
        "Ajusta las listas 'incluir'/'excluir' en config/settings.yaml y vuelve "
        "a correr para ver cómo cambia el filtrado."
    )


if __name__ == "__main__":
    main()
