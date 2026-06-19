"""
storage/database.py
Capa de acceso a la base de datos SQLite del sistema Concurso Radar.

Responsabilidades de este módulo:
- Crear el esquema de la base de datos si no existe (idempotente).
- Deduplicación: saber si un post de Instagram ya fue procesado, para no
  avisar dos veces del mismo concurso.
- Guardar el historial de concursos detectados.
- Registrar el gasto diario por servicio (insumo del control de presupuesto).

Usa únicamente la librería estándar `sqlite3`, sin dependencias externas.
Todo el acceso a la base pasa por la clase BaseDatos, de modo que si algún
día cambiamos de motor de almacenamiento, solo se toca este archivo.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterator


class BaseDatos:
    """Encapsula todo el acceso a SQLite. Se instancia con la ruta al archivo .db."""

    def __init__(self, ruta_db: str | Path = "storage/monitor.db") -> None:
        self.ruta_db = Path(ruta_db)
        # Aseguramos que la carpeta contenedora exista (ej. "storage/").
        self.ruta_db.parent.mkdir(parents=True, exist_ok=True)
        # Creamos el esquema al instanciar; es seguro llamarlo siempre.
        self.inicializar()

    @contextmanager
    def _conexion(self) -> Iterator[sqlite3.Connection]:
        """
        Context manager que entrega una conexión y se encarga de cerrarla.
        Hace commit si todo sale bien y rollback si hay una excepción, de modo
        que nunca quede la base a medias ni conexiones abiertas colgando.
        """
        conexion = sqlite3.connect(self.ruta_db)
        conexion.row_factory = sqlite3.Row  # acceder a columnas por nombre
        try:
            yield conexion
            conexion.commit()
        except Exception:
            conexion.rollback()
            raise
        finally:
            conexion.close()

    def inicializar(self) -> None:
        """Crea las tablas si no existen. Seguro de llamar múltiples veces."""
        with self._conexion() as conexion:
            conexion.executescript(
                """
                -- Posts ya procesados: evita avisar dos veces del mismo post.
                CREATE TABLE IF NOT EXISTS posts_vistos (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    url         TEXT UNIQUE NOT NULL,
                    plataforma  TEXT,
                    fecha_vista DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                -- Concursos detectados: historial de lo que pasó el filtro.
                CREATE TABLE IF NOT EXISTS concursos (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    cuenta          TEXT,
                    caption         TEXT,
                    url             TEXT,
                    plataforma      TEXT,
                    fecha_post      TEXT,
                    fecha_deteccion DATETIME DEFAULT CURRENT_TIMESTAMP,
                    estado          TEXT DEFAULT 'nuevo'  -- nuevo / revisado / interesante / descartado
                );

                -- Gasto por día y servicio: insumo del control de presupuesto.
                CREATE TABLE IF NOT EXISTS gasto_diario (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    fecha     DATE NOT NULL,
                    servicio  TEXT NOT NULL,
                    costo_usd REAL DEFAULT 0,
                    llamadas  INTEGER DEFAULT 0
                );

                -- Estado del sistema: clave-valor para el filtro dinámico y futuros usos.
                CREATE TABLE IF NOT EXISTS estado (
                    clave TEXT PRIMARY KEY,
                    valor TEXT
                );

                -- Actividad por día: un renglón por fecha local. Alimenta dos cosas:
                --   * el resumen diario que se manda al final del día (posts/alertas);
                --   * el tope de corridas/día del candado anti-costo (campo `corridas`).
                CREATE TABLE IF NOT EXISTS actividad_diaria (
                    fecha    DATE PRIMARY KEY,
                    corridas INTEGER DEFAULT 0,
                    posts    INTEGER DEFAULT 0,
                    nuevos   INTEGER DEFAULT 0,
                    alertas  INTEGER DEFAULT 0
                );
                """
            )
            # Migración idempotente: columna de alertas de la fuente web en el ledger
            # diario. Las bases creadas antes de la fuente web no la tienen; el ALTER
            # falla con OperationalError si ya existe, y se ignora.
            try:
                conexion.execute(
                    "ALTER TABLE actividad_diaria ADD COLUMN alertas_web INTEGER DEFAULT 0"
                )
            except sqlite3.OperationalError:
                pass

    # ------------------------------------------------------------------ #
    # Deduplicación (tabla posts_vistos)
    # ------------------------------------------------------------------ #

    def ya_visto(self, url: str) -> bool:
        """Devuelve True si el post (identificado por su URL) ya fue procesado."""
        with self._conexion() as conexion:
            fila = conexion.execute(
                "SELECT 1 FROM posts_vistos WHERE url = ? LIMIT 1", (url,)
            ).fetchone()
            return fila is not None

    def marcar_visto(self, url: str, plataforma: str = "instagram") -> bool:
        """
        Registra un post como ya procesado.
        Devuelve True si se insertó (era nuevo), False si ya existía.
        Usa INSERT OR IGNORE para que sea seguro ante llamadas repetidas
        sin lanzar error por la restricción UNIQUE de la columna `url`.
        """
        with self._conexion() as conexion:
            cursor = conexion.execute(
                "INSERT OR IGNORE INTO posts_vistos (url, plataforma) VALUES (?, ?)",
                (url, plataforma),
            )
            return cursor.rowcount > 0

    # ------------------------------------------------------------------ #
    # Historial de concursos (tabla concursos)
    # ------------------------------------------------------------------ #

    def guardar_concurso(
        self,
        cuenta: str,
        caption: str,
        url: str,
        plataforma: str = "instagram",
        fecha_post: str | None = None,
    ) -> int:
        """Guarda un concurso detectado en el historial. Devuelve su id."""
        with self._conexion() as conexion:
            cursor = conexion.execute(
                """
                INSERT INTO concursos (cuenta, caption, url, plataforma, fecha_post)
                VALUES (?, ?, ?, ?, ?)
                """,
                (cuenta, caption, url, plataforma, fecha_post),
            )
            return int(cursor.lastrowid)

    # ------------------------------------------------------------------ #
    # Control de gasto (tabla gasto_diario)
    # ------------------------------------------------------------------ #

    def registrar_gasto(
        self,
        servicio: str,
        costo_usd: float,
        llamadas: int = 1,
        fecha: date | None = None,
    ) -> None:
        """
        Suma gasto al acumulado del día para un servicio (ej. "apify").
        Si ya existe un registro de ese día y servicio, lo actualiza sumando;
        si no existe, lo crea. Así llevamos un único renglón por día/servicio.
        """
        dia = (fecha or date.today()).isoformat()
        with self._conexion() as conexion:
            fila = conexion.execute(
                "SELECT id, costo_usd, llamadas FROM gasto_diario "
                "WHERE fecha = ? AND servicio = ?",
                (dia, servicio),
            ).fetchone()
            if fila is None:
                conexion.execute(
                    "INSERT INTO gasto_diario (fecha, servicio, costo_usd, llamadas) "
                    "VALUES (?, ?, ?, ?)",
                    (dia, servicio, costo_usd, llamadas),
                )
            else:
                conexion.execute(
                    "UPDATE gasto_diario SET costo_usd = ?, llamadas = ? WHERE id = ?",
                    (fila["costo_usd"] + costo_usd, fila["llamadas"] + llamadas, fila["id"]),
                )

    def gasto_del_dia(self, servicio: str | None = None, fecha: date | None = None) -> float:
        """
        Devuelve el gasto total (USD) de un día.
        Si se pasa `servicio`, lo limita a ese servicio; si no, suma todos.
        """
        dia = (fecha or date.today()).isoformat()
        with self._conexion() as conexion:
            if servicio is None:
                fila = conexion.execute(
                    "SELECT COALESCE(SUM(costo_usd), 0) AS total "
                    "FROM gasto_diario WHERE fecha = ?",
                    (dia,),
                ).fetchone()
            else:
                fila = conexion.execute(
                    "SELECT COALESCE(SUM(costo_usd), 0) AS total "
                    "FROM gasto_diario WHERE fecha = ? AND servicio = ?",
                    (dia, servicio),
                ).fetchone()
            return float(fila["total"])

    # ------------------------------------------------------------------ #
    # Actividad diaria (tabla actividad_diaria)
    # ------------------------------------------------------------------ #

    def registrar_corrida(
        self,
        posts: int,
        nuevos: int,
        alertas: int,
        fecha: date | None = None,
    ) -> None:
        """
        Suma una corrida al acumulado del día y le agrega sus conteos.
        Se llama una vez por ciclo EXITOSO (no por corrida fallida ni pausada),
        de modo que `corridas` cuenta solo las búsquedas que de verdad se hicieron.
        Usa la fecha local (date.today), igual que el gasto, para alinear con el
        día del cliente.
        """
        dia = (fecha or date.today()).isoformat()
        with self._conexion() as conexion:
            conexion.execute(
                """
                INSERT INTO actividad_diaria (fecha, corridas, posts, nuevos, alertas)
                VALUES (?, 1, ?, ?, ?)
                ON CONFLICT(fecha) DO UPDATE SET
                    corridas = corridas + 1,
                    posts    = posts + excluded.posts,
                    nuevos   = nuevos + excluded.nuevos,
                    alertas  = alertas + excluded.alertas
                """,
                (dia, posts, nuevos, alertas),
            )

    def registrar_alertas_web(self, alertas: int, fecha: date | None = None) -> None:
        """
        Suma alertas de la fuente WEB al ledger del día (clave fecha local, igual que
        `registrar_corrida`). Se llama una vez por ciclo web. Usa UPSERT para crear la
        fila del día si aún no existe.
        """
        dia = (fecha or date.today()).isoformat()
        with self._conexion() as conexion:
            conexion.execute(
                """
                INSERT INTO actividad_diaria (fecha, alertas_web)
                VALUES (?, ?)
                ON CONFLICT(fecha) DO UPDATE SET alertas_web = alertas_web + excluded.alertas_web
                """,
                (dia, alertas),
            )

    def contar_corridas_hoy(self, fecha: date | None = None) -> int:
        """Devuelve cuántas corridas exitosas se llevan en el día (0 si ninguna)."""
        dia = (fecha or date.today()).isoformat()
        with self._conexion() as conexion:
            fila = conexion.execute(
                "SELECT corridas FROM actividad_diaria WHERE fecha = ?", (dia,)
            ).fetchone()
            return int(fila["corridas"]) if fila else 0

    def resumen_dia(self, fecha: date | None = None) -> dict:
        """
        Devuelve el acumulado del día como dict
        {fecha, corridas, posts, nuevos, alertas}. Si no hubo actividad, todo en 0.
        Insumo del resumen diario por Telegram.
        """
        dia = (fecha or date.today()).isoformat()
        with self._conexion() as conexion:
            fila = conexion.execute(
                "SELECT corridas, posts, nuevos, alertas, COALESCE(alertas_web, 0) AS alertas_web "
                "FROM actividad_diaria WHERE fecha = ?",
                (dia,),
            ).fetchone()
        if fila is None:
            return {
                "fecha": dia, "corridas": 0, "posts": 0,
                "nuevos": 0, "alertas": 0, "alertas_web": 0,
            }
        return {
            "fecha": dia,
            "corridas": int(fila["corridas"]),
            "posts": int(fila["posts"]),
            "nuevos": int(fila["nuevos"]),
            "alertas": int(fila["alertas"]),
            "alertas_web": int(fila["alertas_web"]),
        }

    # ------------------------------------------------------------------ #
    # Estado del sistema (tabla estado)
    # ------------------------------------------------------------------ #

    def leer_estado(self, clave: str) -> str | None:
        """Devuelve el valor asociado a `clave`, o None si no existe."""
        with self._conexion() as conexion:
            fila = conexion.execute(
                "SELECT valor FROM estado WHERE clave = ?", (clave,)
            ).fetchone()
            return fila["valor"] if fila else None

    def guardar_estado(self, clave: str, valor: str) -> None:
        """Guarda o actualiza un valor en la tabla estado (UPSERT)."""
        with self._conexion() as conexion:
            conexion.execute(
                "INSERT INTO estado (clave, valor) VALUES (?, ?) "
                "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
                (clave, valor),
            )


if __name__ == "__main__":
    # Auto-prueba rápida: crea una base temporal, verifica la deduplicación,
    # el historial y el registro de gasto, imprime los resultados y la borra.
    # Sirve para confirmar que el módulo funciona sin tocar la base real.
    import os
    import tempfile

    ruta_temporal = os.path.join(tempfile.gettempdir(), "concurso_radar_prueba.db")
    if os.path.exists(ruta_temporal):
        os.remove(ruta_temporal)

    db = BaseDatos(ruta_temporal)
    print("Base de datos creada en:", ruta_temporal)

    url_ejemplo = "https://instagram.com/p/ABC123"

    print("¿Visto antes?           ->", db.ya_visto(url_ejemplo))            # False
    print("Marcar visto (nuevo)    ->", db.marcar_visto(url_ejemplo))        # True
    print("Marcar visto (repetido) ->", db.marcar_visto(url_ejemplo))        # False
    print("¿Visto ahora?           ->", db.ya_visto(url_ejemplo))            # True

    id_concurso = db.guardar_concurso(
        cuenta="falabella_co",
        caption="¡Participa y gana! Aplican T&C.",
        url=url_ejemplo,
    )
    print("Concurso guardado con id ->", id_concurso)

    db.registrar_gasto("apify", 0.012)
    db.registrar_gasto("apify", 0.008)
    print("Gasto de hoy (apify)     ->", round(db.gasto_del_dia("apify"), 4), "USD")

    db.guardar_estado("ultima_corrida_utc", "2026-06-11T12:00:00.000Z")
    print("Estado guardado          ->", db.leer_estado("ultima_corrida_utc"))
    db.guardar_estado("ultima_corrida_utc", "2026-06-11T13:00:00.000Z")  # UPSERT
    print("Estado actualizado       ->", db.leer_estado("ultima_corrida_utc"))
    print("Estado inexistente       ->", db.leer_estado("no_existe"))    # None

    print("Corridas hoy (inicio)    ->", db.contar_corridas_hoy())       # 0
    db.registrar_corrida(posts=44, nuevos=3, alertas=1)
    db.registrar_corrida(posts=40, nuevos=2, alertas=0)
    print("Corridas hoy (tras 2)    ->", db.contar_corridas_hoy())       # 2
    print("Resumen del día          ->", db.resumen_dia())  # posts 84, nuevos 5, alertas 1

    os.remove(ruta_temporal)
    print("Prueba completada. Base temporal eliminada.")
