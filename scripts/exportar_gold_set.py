r"""
scripts/exportar_gold_set.py
Vuelca la tabla `concursos` (el historial de alertas que pasaron keywords) a un
archivo CSV listo para que el cliente lo ETIQUETE: marca cada fila como relevante
o no relevante. Ese CSV etiquetado es el gold set contra el cual se mide la IA
(ver docs/AI_CONTEXT.md §7.2 y §8; lo consume scripts/evaluar_ia.py --etiquetas).

NO gasta nada (ni Apify ni Anthropic): solo lee la base de datos local.

El CSV sale con columnas:  url, cuenta, fecha_post, caption, etiqueta
La columna `etiqueta` queda VACÍA: el cliente la llena con  relevante  o  no_relevante.
Se escribe con BOM (utf-8-sig) para que Excel en Windows muestre bien las tildes.

Uso (desde la raíz del proyecto, con el venv activado):
    python scripts\exportar_gold_set.py
    python scripts\exportar_gold_set.py --salida etiquetas.csv
"""

from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from scheduler import cargar_config  # noqa: E402

SALIDA_POR_DEFECTO = "etiquetas.csv"
COLUMNAS = ["url", "cuenta", "fecha_post", "caption", "etiqueta"]


def main() -> None:
    args = sys.argv[1:]
    salida = args[args.index("--salida") + 1] if "--salida" in args else SALIDA_POR_DEFECTO

    config = cargar_config()
    ruta_db = config["base_datos"]["ruta"]

    conexion = sqlite3.connect(ruta_db)
    conexion.row_factory = sqlite3.Row
    try:
        filas = conexion.execute(
            "SELECT url, cuenta, fecha_post, caption FROM concursos "
            "ORDER BY fecha_deteccion"
        ).fetchall()
    finally:
        conexion.close()

    if not filas:
        sys.exit(
            "La tabla 'concursos' está vacía: todavía no hay historial que exportar.\n"
            "El sistema debe haber corrido en producción y detectado alertas antes."
        )

    ruta_salida = Path(salida)
    with open(ruta_salida, "w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS)
        escritor.writeheader()
        for fila in filas:
            escritor.writerow(
                {
                    "url": fila["url"],
                    "cuenta": fila["cuenta"],
                    "fecha_post": fila["fecha_post"],
                    "caption": (fila["caption"] or "").replace("\n", " ").strip(),
                    "etiqueta": "",  # la llena el cliente: relevante / no_relevante
                }
            )

    print(f"[OK] Exportadas {len(filas)} alertas a: {ruta_salida.resolve()}")
    print("Pasos siguientes:")
    print("  1. Abre el archivo (Excel/LibreOffice) y llena la columna 'etiqueta'")
    print("     con  relevante  o  no_relevante  en cada fila.")
    print("  2. Guarda el archivo en formato CSV (no .xlsx).")
    print("  3. Corre:  python scripts\\evaluar_ia.py --etiquetas " + str(ruta_salida))


if __name__ == "__main__":
    main()
