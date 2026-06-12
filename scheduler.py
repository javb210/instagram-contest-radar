"""
scheduler.py
Orquestador de un ciclo de búsqueda.

FASE 1 — corazón del sistema. Conecta las cuatro piezas en el flujo real:

    buscar (Apify) -> descartar vistos (SQLite) -> filtrar (keywords)
        -> avisar (Telegram) -> marcar vistos -> contabilizar gasto

Modelo de ejecución: **corrida única** (`correr_una_vez`). Quien manda el horario
es el Programador de Tareas de Windows (ver `install.py`), que lanza el proceso a
horas fijas; este módulo corre UN ciclo y termina. Antes el horario vivía aquí con
APScheduler, pero eso ataba el costo y la cobertura al patrón de encendido del PC;
moverlo al SO hace el gasto determinista (2 corridas/día) y resiliente a apagados.

`ejecutar_ciclo` recibe sus dependencias ya construidas (inyección de dependencias)
para poder probarlo de forma aislada.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

from budget.tracker import ControlPresupuesto
from filters.keywords import es_candidato
from notifier.telegram import NotificadorTelegram
from power import liberar, mantener_despierto
from searchers.instagram_search import BuscadorInstagram
from storage.database import BaseDatos

RAIZ = Path(__file__).resolve().parent
RUTA_CONFIG = RAIZ / "config" / "settings.yaml"

log = logging.getLogger("concurso_radar")


def cargar_config(ruta: Path = RUTA_CONFIG) -> dict:
    """Carga config/settings.yaml. Lanza error claro si no existe."""
    ruta = Path(ruta)
    if not ruta.exists():
        raise FileNotFoundError(
            f"No se encontró {ruta}. Copia config/settings.example.yaml a "
            "config/settings.yaml y pega tus credenciales."
        )
    return yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}


def configurar_logging(ruta_log: str) -> None:
    """Configura el log a consola y a archivo (logs/system.log)."""
    Path(ruta_log).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(ruta_log, encoding="utf-8"),
        ],
    )


def ejecutar_ciclo(
    config: dict,
    db: BaseDatos,
    buscador: BuscadorInstagram,
    notificador: NotificadorTelegram,
    tracker: ControlPresupuesto,
) -> dict:
    """
    Ejecuta un ciclo completo. Devuelve un resumen con conteos y estado.

    Flujo por cada post traído:
      - si ya fue visto -> se ignora (deduplicación)
      - si es candidato (keywords) -> se envía alerta; si el envío tuvo éxito,
        se guarda en el historial y se marca como visto
      - si NO es candidato -> se marca como visto (no se reprocesa)
    Si un candidato no se pudo avisar (Telegram caído), NO se marca como visto,
    para reintentarlo en el próximo ciclo.
    """
    servicio = "apify"
    resumen = {"posts": 0, "nuevos": 0, "alertas": 0, "estado": "ok"}

    # Si ya se alcanzó el techo de gasto del día, no gastar más.
    if tracker.supera_limite(servicio):
        log.warning("Límite diario de gasto alcanzado; se omite el ciclo.")
        resumen["estado"] = "pausado_presupuesto"
        return resumen

    cuentas = config["cuentas"]
    posts_por_cuenta = config["busqueda"]["posts_por_cuenta"]
    saltar_fijados = config["busqueda"].get("saltar_posts_fijados", True)
    incluir = config["keywords"]["incluir"]
    excluir = config["keywords"]["excluir"]

    # Filtro de fecha dinámico: calcula newer_than desde la última corrida exitosa.
    # En la primera corrida (sin historial) usa el fallback de config.
    nueva_corrida_utc = datetime.now(timezone.utc)
    ultima_corrida_str = db.leer_estado("ultima_corrida_utc")
    if ultima_corrida_str:
        ultima_corrida = datetime.fromisoformat(ultima_corrida_str)
        newer_than_dt = ultima_corrida - timedelta(minutes=5)
        tope = nueva_corrida_utc - timedelta(hours=26)
        if newer_than_dt < tope:
            newer_than_dt = tope
            log.warning("Lookback limitado a 26 horas; el PC estuvo apagado más de un día.")
        newer_than = newer_than_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    else:
        newer_than = config["busqueda"].get("solo_posts_mas_nuevos_que") or None

    log.info(
        "Buscando: %d cuentas, %d posts/cuenta, filtro de fecha: %s, saltar fijados: %s",
        len(cuentas), posts_por_cuenta, newer_than or "NINGUNO (sin filtro)", saltar_fijados,
    )

    # 1. Buscar en Instagram. Si falla, avisar y salir sin tumbar el sistema.
    try:
        posts = buscador.buscar(
            cuentas, posts_por_cuenta, newer_than=newer_than, saltar_fijados=saltar_fijados
        )
    except RuntimeError as error:
        log.error("Falló la búsqueda en Instagram: %s", error)
        notificador.enviar_heartbeat(
            f"⚠️ Concurso Radar: error al buscar en Instagram.\n{error}"
        )
        resumen["estado"] = "error_busqueda"
        return resumen

    resumen["posts"] = len(posts)

    # 2. Contabilizar el gasto (Apify cobra por resultado devuelto).
    tracker.registrar(servicio, len(posts))

    # 3. Procesar cada post: dedup -> filtro -> alerta.
    for post in posts:
        if db.ya_visto(post["url"]):
            continue
        resumen["nuevos"] += 1

        if es_candidato(post["caption"], incluir, excluir):
            if notificador.enviar_alerta(post):
                db.guardar_concurso(
                    post["cuenta"], post["caption"], post["url"],
                    plataforma="instagram", fecha_post=post["fecha"],
                )
                db.marcar_visto(post["url"], "instagram")
                resumen["alertas"] += 1
                log.info("Alerta enviada: @%s %s", post["cuenta"], post["url"])
            else:
                log.error(
                    "No se pudo enviar la alerta de %s; se reintentará el próximo ciclo.",
                    post["url"],
                )
        else:
            db.marcar_visto(post["url"], "instagram")

    log.info(
        "Ciclo terminado: %d posts, %d nuevos, %d alertas. Gasto hoy: $%.4f USD.",
        resumen["posts"], resumen["nuevos"], resumen["alertas"], tracker.gasto_hoy(servicio),
    )

    # 4. Si este ciclo nos pasó del techo, avisar una vez.
    if tracker.supera_limite(servicio):
        notificador.enviar_heartbeat(
            "⚠️ Concurso Radar alcanzó el límite diario de gasto. "
            "Pauso las búsquedas hasta mañana."
        )
        log.warning("Límite diario alcanzado tras este ciclo.")

    # Persistir el timestamp de inicio de esta corrida para el próximo ciclo.
    db.guardar_estado("ultima_corrida_utc", nueva_corrida_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z"))
    return resumen


def heartbeat_diario(notificador: NotificadorTelegram, tracker: ControlPresupuesto) -> None:
    """Envía el mensaje diario de 'sigo activo', con el gasto del día."""
    gasto = tracker.gasto_hoy("apify")
    notificador.enviar_heartbeat(
        f"✅ Concurso Radar sigue activo. Gasto de hoy: ${gasto:.2f} USD."
    )
    log.info("Heartbeat diario enviado.")


def _construir_componentes(
    config: dict,
) -> tuple[BaseDatos, BuscadorInstagram, NotificadorTelegram, ControlPresupuesto]:
    """Construye las cuatro piezas del sistema a partir de la configuración."""
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
    return db, buscador, notificador, tracker


def _heartbeat_si_toca(
    config: dict,
    db: BaseDatos,
    notificador: NotificadorTelegram,
    tracker: ControlPresupuesto,
) -> None:
    """
    Envía el heartbeat diario (mensaje de 'sigo activo') a lo sumo una vez por día.
    En el modelo de corrida única no hay un proceso vivo a las 20:00, así que el
    aviso se manda en la PRIMERA corrida de cada día. Se usa la tabla `estado`
    para recordar la fecha del último heartbeat enviado.
    """
    if not config.get("heartbeat", {}).get("activo", False):
        return
    hoy = date.today().isoformat()
    if db.leer_estado("ultimo_heartbeat_fecha") == hoy:
        return  # ya se avisó hoy
    heartbeat_diario(notificador, tracker)
    db.guardar_estado("ultimo_heartbeat_fecha", hoy)


def correr_una_vez() -> dict:
    """
    Ejecuta UN ciclo completo y termina. Es el punto de entrada de producción:
    el Programador de Tareas de Windows lo invoca a horas fijas (ver `install.py`).

    Devuelve el resumen del ciclo. Si ocurre un error inesperado, lo propaga para
    que el proceso termine con código distinto de cero y el Programador de Tareas
    pueda reintentar.
    """
    config = cargar_config()
    configurar_logging(config.get("logs", {}).get("ruta", "logs/system.log"))
    log.info("Concurso Radar: corrida única iniciada.")

    # Evitar suspensión por inactividad durante la corrida (puede tardar si Apify
    # se demora). Se libera siempre al terminar, salga bien o mal.
    mantener_despierto()
    try:
        db, buscador, notificador, tracker = _construir_componentes(config)
        resumen = ejecutar_ciclo(config, db, buscador, notificador, tracker)
        _heartbeat_si_toca(config, db, notificador, tracker)
    finally:
        liberar()

    log.info("Concurso Radar: corrida única terminada (estado: %s).", resumen["estado"])
    return resumen


if __name__ == "__main__":
    correr_una_vez()
