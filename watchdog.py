"""
watchdog.py
Proceso independiente que vigila que main.py siga vivo.

FASE POSTERIOR (robustez, cerca de la entrega).

En una máquina desatendida de un usuario no técnico, si el proceso principal
se cae, nadie lo reinicia. Este watchdog hace ping periódico al sistema y, si
no responde, lo reinicia y avisa por Telegram.

Nota: Windows Task Scheduler ya cubre el reinicio si el proceso muere por
completo. El watchdog cubre el caso más sutil de "el proceso vive pero quedó
colgado". Se decide en su fase si vale la complejidad o basta con Task Scheduler.
"""

from __future__ import annotations


def vigilar() -> None:
    """Hace ping al proceso principal cada cierto tiempo y lo reinicia si no responde."""
    raise NotImplementedError("Se implementa en una fase posterior (robustez).")
