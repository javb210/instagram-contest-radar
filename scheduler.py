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
from classifier.ai_filter import ClasificadorIA
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
    clasificador: ClasificadorIA | None = None,
) -> dict:
    """
    Ejecuta un ciclo completo. Devuelve un resumen con conteos y estado.

    Flujo por cada post traído:
      - si ya fue visto -> se ignora (deduplicación)
      - si es candidato (keywords):
          * Fase 2 (clasificador presente): la IA decide si es relevante.
            Si NO lo es -> se marca visto y no se avisa. Si SÍ -> se avisa con el
            resumen estructurado. Si la IA falla -> se avisa igual con la alerta
            cruda (fail-open: nunca se pierde un concurso por un error de la IA).
          * Fase 1 (sin clasificador): se avisa con la alerta cruda directamente.
        Si el envío tuvo éxito, se guarda en el historial y se marca como visto.
      - si NO es candidato -> se marca como visto (no se reprocesa)
    Si un candidato no se pudo avisar (Telegram caído), NO se marca como visto,
    para reintentarlo en el próximo ciclo.
    """
    servicio = "apify"
    resumen = {"posts": 0, "nuevos": 0, "alertas": 0, "descartados_ia": 0, "estado": "ok"}

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
            # Fase 2: la IA confirma relevancia y produce el resumen. Si no hay
            # clasificador (sin api_key), se mantiene el comportamiento Fase 1.
            resumen_ia = None
            if clasificador is not None:
                try:
                    analisis = clasificador.analizar(post["caption"])
                    if not analisis["relevante"]:
                        db.marcar_visto(post["url"], "instagram")
                        resumen["descartados_ia"] += 1
                        log.info(
                            "IA descartó @%s %s (no relevante).", post["cuenta"], post["url"]
                        )
                        continue
                    resumen_ia = analisis
                except Exception as error:  # fail-open: avisar igual sin resumen
                    log.warning(
                        "La IA falló en %s; se envía la alerta cruda (fail-open). %s",
                        post["url"], error,
                    )

            if notificador.enviar_alerta(post, resumen_ia):
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
        "Ciclo terminado: %d posts, %d nuevos, %d alertas, %d descartados por IA. "
        "Gasto hoy: $%.4f USD.",
        resumen["posts"], resumen["nuevos"], resumen["alertas"],
        resumen["descartados_ia"], tracker.gasto_hoy(servicio),
    )

    # 4. Si este ciclo nos pasó del techo, avisar una vez.
    if tracker.supera_limite(servicio):
        notificador.enviar_heartbeat(
            "⚠️ Concurso Radar alcanzó el límite diario de gasto. "
            "Pauso las búsquedas hasta mañana."
        )
        log.warning("Límite diario alcanzado tras este ciclo.")

    # Persistir el timestamp de inicio de esta corrida para el próximo ciclo y
    # acumular la actividad del día (insumo del resumen diario y del tope de
    # corridas). Solo se llega aquí en una corrida con búsqueda exitosa.
    db.guardar_estado("ultima_corrida_utc", nueva_corrida_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z"))
    db.registrar_corrida(resumen["posts"], resumen["nuevos"], resumen["alertas"])
    return resumen


def heartbeat_diario(notificador: NotificadorTelegram, tracker: ControlPresupuesto) -> None:
    """Envía el mensaje diario de 'sigo activo', con el gasto del día."""
    gasto = tracker.gasto_hoy("apify")
    notificador.enviar_heartbeat(
        f"✅ Concurso Radar sigue activo. Gasto de hoy: ${gasto:.2f} USD."
    )
    log.info("Heartbeat diario enviado.")


def formatear_resumen(datos: dict, gasto_usd: float) -> str:
    """
    Arma el texto del resumen diario para Telegram (HTML). `datos` viene de
    `BaseDatos.resumen_dia`. Si el día no tuvo corridas (PC apagado/suspendido a
    las horas programadas), lo dice de forma explícita en vez de mostrar ceros secos.
    """
    fecha = datos.get("fecha", "")
    corridas = datos.get("corridas", 0)
    if corridas == 0:
        return (
            f"📊 <b>Resumen del día</b> — {fecha}\n\n"
            "No hubo corridas hoy (el PC estuvo apagado o suspendido a las horas "
            "programadas). No se revisaron posts."
        )
    return (
        f"📊 <b>Resumen del día</b> — {fecha}\n\n"
        f"🔁 Corridas: {corridas}\n"
        f"👀 Posts nuevos revisados: {datos.get('nuevos', 0)}\n"
        f"🏆 Alertas enviadas: {datos.get('alertas', 0)}\n"
        f"💰 Gasto Apify hoy: ${gasto_usd:.2f} USD"
    )


def _fecha_objetivo_resumen(config: dict, ahora: datetime | None = None) -> date:
    """
    Día que el resumen debe reportar.

    La tarea `ConcursoRadarResumen` está programada a `resumen.hora` (21:00). Si
    `StartWhenAvailable` la recupera pasada la medianoche (el PC estuvo apagado/
    suspendido a esa hora), `date.today()` apuntaría al día siguiente, todavía vacío,
    y el cliente recibiría un resumen en ceros del día equivocado. Por eso: si la hora
    actual es ANTERIOR a la hora programada, el resumen corresponde al día anterior
    (la tarde que acaba de terminar); de lo contrario, al día en curso.
    """
    ahora = ahora or datetime.now()
    hora_str = str(config.get("resumen", {}).get("hora", "21:00"))
    try:
        hora_corte = int(hora_str.split(":")[0])
    except (ValueError, IndexError):
        hora_corte = 21
    if ahora.hour < hora_corte:
        return ahora.date() - timedelta(days=1)
    return ahora.date()


def enviar_resumen_diario() -> dict:
    """
    Lee el registro de actividad del día y manda el resumen por Telegram.
    NO consulta Apify (costo cero): es el punto de entrada de la tarea programada
    de fin de día (`main.py --resumen`, registrada por install.py como
    `ConcursoRadarResumen`). Devuelve el dict del resumen para pruebas.

    Si `resumen.activo` está en false en la config, no manda nada (interruptor de
    apagado, igual que el heartbeat).
    """
    config = cargar_config()
    configurar_logging(config.get("logs", {}).get("ruta", "logs/system.log"))

    if not config.get("resumen", {}).get("activo", True):
        log.info("Resumen diario desactivado en config; no se envía.")
        return {}

    log.info("Concurso Radar: preparando el resumen diario.")
    db, _buscador, notificador, tracker = _construir_componentes(config)
    fecha = _fecha_objetivo_resumen(config)
    fecha_iso = fecha.isoformat()

    # Candado anti-duplicado: la tarea de resumen tiene un LogonTrigger de respaldo
    # (cubre el caso de PC apagado a la hora), así que puede dispararse varias veces.
    # Igual que el heartbeat, mandamos el resumen UNA sola vez por día reportado.
    if db.leer_estado("ultimo_resumen_fecha") == fecha_iso:
        log.info("Resumen del %s ya fue enviado; se omite el duplicado.", fecha_iso)
        return db.resumen_dia(fecha)

    datos = db.resumen_dia(fecha)
    gasto = tracker.gasto_hoy("apify", fecha)
    enviado = notificador.enviar_heartbeat(formatear_resumen(datos, gasto))
    if enviado:
        db.guardar_estado("ultimo_resumen_fecha", fecha_iso)
        log.info("Resumen diario enviado: %s, gasto $%.4f USD.", datos, gasto)
    else:
        log.warning("No se pudo enviar el resumen del %s; se reintentará.", fecha_iso)
    return datos


def _destinatarios_telegram(telegram_cfg: dict) -> list:
    """Reúne los chats destino desde la config.

    Acepta dos formas, combinables:
      - `chat_id`:  un único id (compatibilidad con la config anterior).
      - `chat_ids`: una lista de ids (varios destinatarios, ej. tú + el cliente).
    Devuelve la lista combinada sin duplicados, conservando el orden.
    """
    destinatarios: list[str] = []
    uno = telegram_cfg.get("chat_id")
    if uno not in (None, ""):
        destinatarios.append(str(uno).strip())
    for c in telegram_cfg.get("chat_ids") or []:
        if str(c).strip():
            destinatarios.append(str(c).strip())
    # quita duplicados conservando el orden
    return list(dict.fromkeys(destinatarios))


def _construir_componentes(
    config: dict,
) -> tuple[BaseDatos, BuscadorInstagram, NotificadorTelegram, ControlPresupuesto]:
    """Construye las cuatro piezas del sistema a partir de la configuración."""
    db = BaseDatos(config["base_datos"]["ruta"])
    buscador = BuscadorInstagram(config["apify"]["token"], config["apify"]["actor_id"])
    notificador = NotificadorTelegram(
        config["telegram"]["bot_token"], _destinatarios_telegram(config["telegram"])
    )
    tracker = ControlPresupuesto(
        db,
        config["presupuesto"]["limite_diario_usd"],
        config["presupuesto"]["costo_por_mil_resultados_usd"],
    )
    return db, buscador, notificador, tracker


def construir_clasificador(config: dict) -> ClasificadorIA | None:
    """
    Construye el clasificador de IA (Fase 2) SOLO si hay `anthropic.api_key` en la
    config. Sin key devuelve None y el sistema corre tal cual la Fase 1 (solo
    keywords). Así el cliente activa la IA con solo pegar su key, sin tocar código.
    """
    cfg = config.get("anthropic", {}) or {}
    api_key = cfg.get("api_key", "")
    if not api_key:
        return None
    return ClasificadorIA(
        api_key,
        modelo=cfg.get("modelo"),
        criterio_relevancia=cfg.get("criterio_relevancia"),
    )


def _motivo_para_omitir(config: dict, db: BaseDatos) -> str | None:
    """
    Decide si esta corrida debe omitirse y por qué. Devuelve el estado a reportar
    (`omitido_cupo_diario` u `omitido_reciente`) o None si la corrida debe correr.

    Son dos candados anti-costo que, juntos, garantizan ~2 corridas/día bien
    espaciadas pase lo que pase con el patrón de encendido del PC:

    - `max_corridas_por_dia` (tope DURO): nunca se pagan más de N búsquedas en el
      día. Cuenta solo las corridas EXITOSAS (tabla actividad_diaria), así que una
      corrida fallida o pausada por presupuesto no consume cupo.
    - `min_horas_entre_corridas` (SEPARACIÓN): evita dos corridas pegadas, p. ej. la
      del disparador por inicio de sesión seguida de un slot fijo. Si un slot cae
      dentro de esta ventana se omite; el slot de tarde extra (ver install.py:HORAS)
      lo repone una vez pasada la separación, de modo que no se pierde la 2.ª corrida
      del día (el problema que tenía el candado anterior, que solo descartaba).

    Se evalúa el tope ANTES que la separación: una vez completado el cupo del día,
    no importa cuánto haya pasado, no se corre más.
    """
    bq = config["busqueda"]

    max_dia = int(bq.get("max_corridas_por_dia", 0) or 0)
    if max_dia and db.contar_corridas_hoy() >= max_dia:
        return "omitido_cupo_diario"

    min_horas = float(bq.get("min_horas_entre_corridas", 0) or 0)
    if min_horas:
        ultima = db.leer_estado("ultima_corrida_utc")
        if ultima:
            transcurrido = datetime.now(timezone.utc) - datetime.fromisoformat(ultima)
            if transcurrido < timedelta(hours=min_horas):
                return "omitido_reciente"

    return None


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
        motivo = _motivo_para_omitir(config, db)
        if motivo == "omitido_cupo_diario":
            resumen = {"posts": 0, "nuevos": 0, "alertas": 0, "estado": motivo}
            log.info(
                "Se omite esta corrida: ya se completaron las %s corridas del día "
                "(tope anti-costo 'max_corridas_por_dia').",
                config["busqueda"].get("max_corridas_por_dia", 0),
            )
        elif motivo == "omitido_reciente":
            resumen = {"posts": 0, "nuevos": 0, "alertas": 0, "estado": motivo}
            log.info(
                "Se omite esta corrida: hubo una exitosa hace menos de %s h "
                "(separación mínima 'min_horas_entre_corridas'). Un slot posterior la repone.",
                config["busqueda"].get("min_horas_entre_corridas", 0),
            )
        else:
            clasificador = construir_clasificador(config)
            if clasificador is not None:
                log.info("Fase 2 activa: clasificación con IA habilitada (modelo %s).", clasificador.modelo)
            resumen = ejecutar_ciclo(config, db, buscador, notificador, tracker, clasificador)
            _heartbeat_si_toca(config, db, notificador, tracker)
    finally:
        liberar()

    log.info("Concurso Radar: corrida única terminada (estado: %s).", resumen["estado"])
    return resumen


if __name__ == "__main__":
    correr_una_vez()
