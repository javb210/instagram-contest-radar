r"""
scripts/probar_ciclo.py
Corre UN ciclo completo real, de punta a punta:
buscar (Apify) -> deduplicar -> filtrar -> avisar (Telegram) -> contabilizar.

Es la primera prueba integral con servicios reales. Para gastar poco, usa solo
las primeras 3 cuentas de la lista (el sistema completo usa todas). Si en los
posts recientes de esas cuentas hay un concurso, te llegará una alerta real.

Uso (desde la raíz del proyecto, con el venv activado y settings.yaml listo):
    python scripts\probar_ciclo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from scheduler import cargar_config, configurar_logging, ejecutar_ciclo  # noqa: E402
from storage.database import BaseDatos  # noqa: E402
from searchers.instagram_search import BuscadorInstagram  # noqa: E402
from notifier.telegram import NotificadorTelegram  # noqa: E402
from budget.tracker import ControlPresupuesto  # noqa: E402

CUENTAS_PRUEBA = 3  # usar pocas cuentas para que la prueba cueste poco


def main() -> None:
    config = cargar_config()
    configurar_logging(config.get("logs", {}).get("ruta", "logs/system.log"))

    # Limitar a unas pocas cuentas solo para esta prueba.
    config["cuentas"] = config["cuentas"][:CUENTAS_PRUEBA]

    db = BaseDatos(config["base_datos"]["ruta"])
    buscador = BuscadorInstagram(config["apify"]["token"], config["apify"]["actor_id"])
    notificador = NotificadorTelegram(
        config["telegram"]["bot_token"], config["telegram"]["chat_id"]
    )
    tracker = ControlPresupuesto(
        db,
        config["presupuesto"]["limite_diario_usd"],
        config["presupuesto"]["costo_por_mil_resultados_usd"],
    )

    print(f"Corriendo UN ciclo completo con {len(config['cuentas'])} cuentas: {config['cuentas']}")
    print("(buscar -> deduplicar -> filtrar -> avisar -> contabilizar)\n")

    resumen = ejecutar_ciclo(config, db, buscador, notificador, tracker)

    print("\n" + "=" * 60)
    print("RESUMEN DEL CICLO")
    print("=" * 60)
    print(f"  Posts traídos:     {resumen['posts']}")
    print(f"  Posts nuevos:      {resumen['nuevos']}")
    print(f"  Alertas enviadas:  {resumen['alertas']}")
    print(f"  Estado:            {resumen['estado']}")
    print(f"  Gasto de hoy:      ${tracker.gasto_hoy('apify'):.4f} USD")
    print("=" * 60)
    if resumen["alertas"]:
        print("Revisa tu Telegram: te llegó al menos una alerta.")
    else:
        print("No hubo concursos en los posts recientes de esas cuentas (normal).")
        print("Si quieres ver una alerta real, corre de nuevo cuando una de esas")
        print("cuentas tenga un concurso, o prueba scripts\\probar_telegram.py.")


if __name__ == "__main__":
    main()
