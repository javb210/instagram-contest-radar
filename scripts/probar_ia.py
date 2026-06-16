r"""
scripts/probar_ia.py
Prueba el clasificador de IA (Fase 2) sobre una batería de captions de ejemplo,
SIN tocar la base de datos ni Apify. Es la prueba de humo para confirmar, apenas
se pega la api_key, que la IA distingue un concurso real de publicidad/empleo y
que devuelve el resumen estructurado.

SÍ consume crédito de Anthropic: una llamada por ejemplo (centavos).

Lee la api_key, el modelo y el criterio_relevancia de config/settings.yaml (los
mismos que usará en producción), así que también sirve para ver cómo cambia el
comportamiento cuando ajustas `criterio_relevancia`.

Uso (desde la raíz del proyecto, con el venv activado y la api_key puesta):
    python scripts\probar_ia.py
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from scheduler import cargar_config, construir_clasificador  # noqa: E402

# Batería de ejemplos. Edítala para probar tus propios textos.
# Cada tupla: (qué esperamos, etiqueta del caso, texto del caption).
EJEMPLOS = [
    ("RELEVANTE", "Concurso compra y gana",
     "¡Compra y participa! Llévate una TV 4K Samsung. Aplican T&C. Sorteo el 30 de junio."),
    ("RELEVANTE", "Concurso comenta y gana",
     "Comenta con quién irías y gana 2 boletas para el concierto. Dinámica válida hasta el viernes."),
    ("RELEVANTE", "Concurso con tildes",
     "Participa por un viaje a San Andrés para dos personas. Términos y condiciones en la bio."),
    ("descartado", "Publicidad sin mecánica (caso El Corral)",
     "Nada como un Corralazo en familia 🍔 Pide el tuyo hoy por la app y disfruta."),
    ("descartado", "Oferta / descuento",
     "¡Solo este fin de semana! 30% de descuento en toda la tienda. No te lo pierdas."),
    ("descartado", "Empleo",
     "Únete a nuestro equipo. Buscamos asesor comercial, gana comisiones atractivas. Postúlate."),
]


def main() -> None:
    config = cargar_config()
    clasificador = construir_clasificador(config)
    if clasificador is None:
        sys.exit(
            "No hay api_key de Anthropic en config/settings.yaml.\n"
            "Pega la key bajo 'anthropic: api_key:' para poder probar la IA."
        )

    print(f"Probando el clasificador con el modelo {clasificador.modelo}.")
    print("Criterio de relevancia (de settings.yaml):")
    print(f"  {clasificador.criterio[:200]}")
    print("=" * 78)

    aciertos = 0
    for esperado, nombre, texto in EJEMPLOS:
        try:
            r = clasificador.analizar(texto)
        except Exception as error:
            print(f"[ERROR] {nombre}: {error}")
            continue

        veredicto = "RELEVANTE" if r["relevante"] else "descartado"
        ok = veredicto == esperado
        aciertos += int(ok)
        marca = "OK   " if ok else "REVISAR"
        print(f"[{marca}] {nombre}")
        print(f"         IA: {veredicto}  (esperado: {esperado})")
        print(f"         premio: {r['premio']} | mecánica: {r['mecanica']} | "
              f"hasta: {r['fecha_limite']}")
        print("-" * 78)

    print(f"Coincidencias con lo esperado: {aciertos}/{len(EJEMPLOS)}")
    print("Nota: 'REVISAR' no siempre es un error; el criterio se afina en "
          "config/settings.yaml (anthropic.criterio_relevancia).")


if __name__ == "__main__":
    main()
