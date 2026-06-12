"""
power.py
Evita que Windows entre en suspensión (modo reposo) mientras el sistema corre.

El problema: por defecto, Windows suspende el equipo tras unos minutos de
inactividad. Si eso pasa, el proceso de Concurso Radar se congela y deja de
buscar y avisar hasta que el PC despierta.

La solución: al arrancar, le pedimos a Windows mantener el SISTEMA activo con
la API SetThreadExecutionState. Importante: NO mantenemos la pantalla encendida
(se puede apagar para ahorrar energía); solo evitamos que el equipo se suspenda.

Nota: esto evita la suspensión por inactividad. No evita una suspensión forzada
por el usuario (cerrar la tapa de un portátil, botón de suspender). Para esos
casos, el scheduler está configurado para correr un ciclo al despertar.

Es código específico de Windows. En otros sistemas, las funciones no hacen nada.
"""

from __future__ import annotations

import logging
import sys

log = logging.getLogger("concurso_radar")

# Flags de la API de Windows (SetThreadExecutionState).
ES_CONTINUOUS = 0x80000000       # el estado se mantiene hasta el próximo llamado
ES_SYSTEM_REQUIRED = 0x00000001  # impide que el sistema se suspenda por inactividad


def mantener_despierto() -> bool:
    """
    Pide a Windows no suspender el equipo mientras el proceso viva.
    Devuelve True si se aplicó, False si no es Windows o si falló.
    """
    if sys.platform != "win32":
        log.info("No es Windows: se omite 'mantener despierto'.")
        return False
    try:
        resultado = ctypes_kernel32().SetThreadExecutionState(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        )
        if not resultado:
            log.warning("No se pudo activar 'mantener despierto'.")
            return False
        log.info(
            "Modo 'mantener despierto' activado: el PC no se suspenderá por "
            "inactividad mientras el sistema corra (la pantalla sí puede apagarse)."
        )
        return True
    except Exception as error:  # noqa: BLE001
        log.warning("Error al activar 'mantener despierto': %s", error)
        return False


def liberar() -> None:
    """
    Libera el bloqueo: Windows vuelve a su comportamiento normal de reposo.
    Se llama al detener el sistema.
    """
    if sys.platform != "win32":
        return
    try:
        ctypes_kernel32().SetThreadExecutionState(ES_CONTINUOUS)
        log.info("Modo 'mantener despierto' liberado.")
    except Exception as error:  # noqa: BLE001
        log.warning("Error al liberar 'mantener despierto': %s", error)


def ctypes_kernel32():
    """Devuelve la interfaz a kernel32 de Windows. Solo se llama en Windows."""
    import ctypes

    return ctypes.windll.kernel32
