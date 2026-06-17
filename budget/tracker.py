"""
budget/tracker.py
Control de gasto por servicio — la red de seguridad contra sustos de factura.

FASE 1.

Apify cobra por resultado devuelto. Este módulo estima el costo de cada corrida,
lo acumula en la base (tabla gasto_diario) y permite saber si ya se alcanzó el
techo diario configurado. Quien orquesta el ciclo usa `supera_limite` para
pausar las búsquedas por el resto del día y avisar por Telegram.

Trabaja sobre una instancia de BaseDatos (storage/database.py).

Nota: en la tabla gasto_diario, el campo `llamadas` se usa aquí para acumular
el número de resultados facturados en el día (la métrica que mueve el costo en
Apify), no el número de corridas.
"""

from __future__ import annotations

from datetime import date

from storage.database import BaseDatos


class ControlPresupuesto:
    """Estima, registra y vigila el gasto diario por servicio."""

    def __init__(
        self,
        db: BaseDatos,
        limite_diario_usd: float,
        costo_por_mil_resultados_usd: float,
    ) -> None:
        self.db = db
        self.limite_diario_usd = float(limite_diario_usd)
        self.costo_por_mil_resultados_usd = float(costo_por_mil_resultados_usd)

    def estimar_costo(self, num_resultados: int) -> float:
        """Estima el costo en USD de traer `num_resultados` desde el actor."""
        return (num_resultados / 1000.0) * self.costo_por_mil_resultados_usd

    def registrar(self, servicio: str, num_resultados: int) -> None:
        """Calcula el costo de la corrida y lo acumula en gasto_diario."""
        costo = self.estimar_costo(num_resultados)
        self.db.registrar_gasto(servicio, costo, llamadas=num_resultados)

    def gasto_hoy(
        self, servicio: str | None = None, fecha: date | None = None
    ) -> float:
        """Devuelve el gasto acumulado de un día (de un servicio o de todos).

        Por defecto usa el día local (hoy). Se acepta `fecha` para que el resumen
        de fin de día pueda consultar el día correcto cuando la tarea se recupera
        pasada la medianoche.
        """
        return self.db.gasto_del_dia(servicio, fecha)

    def supera_limite(self, servicio: str | None = None) -> bool:
        """Devuelve True si el gasto de hoy ya alcanzó o superó el techo diario."""
        return self.db.gasto_del_dia(servicio) >= self.limite_diario_usd
