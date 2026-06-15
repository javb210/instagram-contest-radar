"""
main.py
Punto de entrada del sistema Concurso Radar.

Dos modos, ambos corren una vez y terminan; el horario lo controla el Programador
de Tareas de Windows, no este proceso (ver `install.py`):

  python main.py            # CORRIDA: buscar -> dedup -> filtrar -> avisar -> gasto.
                            #   Manda el heartbeat en la primera corrida del día.
                            #   Lo disparan las tareas a horas fijas (tarea ConcursoRadar).
  python main.py --resumen  # RESUMEN: manda por Telegram el resumen del día
                            #   (posts revisados / alertas). NO consulta Apify (costo cero).
                            #   Lo dispara la tarea de fin de día (ConcursoRadarResumen).

Uso (desde la raíz del proyecto, con el venv activado y settings.yaml listo).
"""

import sys

from scheduler import correr_una_vez, enviar_resumen_diario


def main() -> None:
    if "--resumen" in sys.argv[1:]:
        enviar_resumen_diario()
        return

    resumen = correr_una_vez()
    # Código de salida distinto de cero si la búsqueda falló, para que el
    # Programador de Tareas registre el fallo y aplique su reintento.
    if resumen["estado"] == "error_busqueda":
        sys.exit(1)


if __name__ == "__main__":
    main()
