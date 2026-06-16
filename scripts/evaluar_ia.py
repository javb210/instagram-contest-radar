r"""
scripts/evaluar_ia.py
Evalúa el clasificador de IA (Fase 2) contra el GOLD SET real: la tabla `concursos`
de la base de datos, que guarda los captions exactos que pasaron keywords y se
alertaron en producción (ver docs/AI_CONTEXT.md §7.2).

NO consulta Apify (costo cero por ese lado). SÍ consume crédito de Anthropic: una
llamada por concurso histórico. Úsalo para ver, ANTES de soltar la Fase 2, cuáles
de las alertas pasadas habría descartado la IA (p. ej. el falso positivo de El Corral).

Cuando el cliente etiquete esas alertas como relevante / no_relevante, pásale el CSV
con --etiquetas ruta.csv (columnas: url,etiqueta) y el script calcula los aciertos
contra la etiqueta humana (criterio de aceptación en docs/HANDOFF.md §Paso E).

Uso (desde la raíz del proyecto, con el venv activado y settings.yaml con api_key):
    python scripts\evaluar_ia.py
    python scripts\evaluar_ia.py --etiquetas etiquetas.csv
"""

from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from scheduler import cargar_config, construir_clasificador  # noqa: E402


def _leer_concursos(ruta_db: str) -> list[dict]:
    """Lee el historial de concursos (el gold set) ordenado por detección."""
    conexion = sqlite3.connect(ruta_db)
    conexion.row_factory = sqlite3.Row
    try:
        filas = conexion.execute(
            "SELECT cuenta, caption, url FROM concursos ORDER BY fecha_deteccion"
        ).fetchall()
    finally:
        conexion.close()
    return [dict(fila) for fila in filas]


def _leer_etiquetas(ruta_csv: str) -> dict[str, bool]:
    """
    Carga el etiquetado humano desde un CSV con columnas 'url' y 'etiqueta'.
    'etiqueta' se interpreta como relevante si vale: relevante / si / sí / 1 / true.
    """
    positivos = {"relevante", "si", "sí", "1", "true", "verdadero"}
    etiquetas: dict[str, bool] = {}
    with open(ruta_csv, encoding="utf-8") as archivo:
        for fila in csv.DictReader(archivo):
            url = (fila.get("url") or "").strip()
            valor = (fila.get("etiqueta") or "").strip().lower()
            if url:
                etiquetas[url] = valor in positivos
    return etiquetas


def main() -> None:
    etiquetas_csv = None
    args = sys.argv[1:]
    if "--etiquetas" in args:
        etiquetas_csv = args[args.index("--etiquetas") + 1]

    config = cargar_config()
    clasificador = construir_clasificador(config)
    if clasificador is None:
        sys.exit(
            "No hay api_key de Anthropic en config/settings.yaml.\n"
            "Pega la key bajo 'anthropic: api_key:' para poder evaluar la IA."
        )

    concursos = _leer_concursos(config["base_datos"]["ruta"])
    if not concursos:
        sys.exit(
            "La tabla 'concursos' está vacía: todavía no hay gold set que evaluar.\n"
            "Corre el sistema en producción para que acumule alertas, o carga datos."
        )

    etiquetas = _leer_etiquetas(etiquetas_csv) if etiquetas_csv else {}

    print(f"Evaluando {len(concursos)} concursos del historial con el modelo "
          f"{clasificador.modelo}...\n")
    print("=" * 78)
    print(f"{'IA':<10} | {'CUENTA':<18} | PREMIO / MECÁNICA")
    print("-" * 78)

    aciertos = relevantes = errores = 0
    for c in concursos:
        try:
            r = clasificador.analizar(c["caption"])
        except Exception as error:
            errores += 1
            print(f"{'[ERROR]':<10} | {c['cuenta']:<18} | {error}")
            continue

        veredicto = "RELEVANTE" if r["relevante"] else "descartado"
        relevantes += int(r["relevante"])
        detalle = f"{r['premio']} / {r['mecanica']}"
        linea = f"{veredicto:<10} | {c['cuenta']:<18} | {detalle}"

        # Si hay etiqueta humana para esta url, marcar acierto/fallo.
        if c["url"] in etiquetas:
            esperado = etiquetas[c["url"]]
            ok = esperado == r["relevante"]
            aciertos += int(ok)
            linea += f"   [{'OK' if ok else 'FALLO'}: humano={'rel' if esperado else 'no'}]"
        print(linea)

    print("=" * 78)
    print(f"Total: {len(concursos)} | IA relevantes: {relevantes} | "
          f"IA descartados: {len(concursos) - relevantes - errores} | errores: {errores}")
    if etiquetas:
        evaluados = sum(1 for c in concursos if c["url"] in etiquetas)
        if evaluados:
            print(f"Concordancia con el etiquetado humano: {aciertos}/{evaluados} "
                  f"({100 * aciertos / evaluados:.0f}%)")
    else:
        print("Sin etiquetas humanas: revisa a ojo los 'descartado' (¿eran falsos "
              "positivos?). Para medir, pasa --etiquetas con un CSV url,etiqueta.")


if __name__ == "__main__":
    main()
