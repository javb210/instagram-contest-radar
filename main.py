"""
main.py
Punto de entrada del sistema Concurso Radar.

Ejecuta UNA corrida completa y termina (scheduler.correr_una_vez):
  1. Carga la configuración desde config/settings.yaml.
  2. Inicializa la base de datos.
  3. Corre un ciclo: buscar -> dedup -> filtrar -> avisar -> contabilizar gasto.
  4. Manda el heartbeat diario si es la primera corrida del día.

El horario (2 corridas/día a horas fijas) lo controla el Programador de Tareas de
Windows, no este proceso. Ver `install.py`.

Uso (desde la raíz del proyecto, con el venv activado y settings.yaml listo):
    python main.py
"""

import sys

from scheduler import correr_una_vez


def main() -> None:
    resumen = correr_una_vez()
    # Código de salida distinto de cero si la búsqueda falló, para que el
    # Programador de Tareas registre el fallo y aplique su reintento.
    if resumen["estado"] == "error_busqueda":
        sys.exit(1)


if __name__ == "__main__":
    main()
