"""
install.py
Instalador para el PC del cliente (Windows 11).

FASE FINAL (entrega).

Registra Concurso Radar en el Programador de Tareas de Windows para que corra solo
a **horas fijas** (ver HORAS), sin ventana de consola visible (pythonw.exe) y con
recuperación si el PC estaba apagado a esa hora. El cliente lo ejecuta una sola vez.

Uso (desde la raíz del proyecto, con el venv activado):

    python install.py              # registra la tarea con sus horarios
    python install.py --desinstalar  # elimina la tarea
    python install.py --verificar    # solo revisa requisitos, no instala nada

Implementado solo con librería estándar (subprocess, pathlib, sys, textwrap,
datetime). No requiere dependencias externas.

Por qué horas fijas (y no ONLOGON): el horario lo manda el Programador de Tareas
del SISTEMA OPERATIVO, no el proceso de Python. Así el costo es determinista (2
corridas/día pase lo que pase con reinicios) y, gracias a `StartWhenAvailable`, si
el PC estaba apagado a la hora, la corrida se recupera apenas el PC vuelve. Cada
disparo lanza `main.py`, que corre UN ciclo y termina.

Detalles técnicos: la tarea ejecuta `pythonw.exe main.py` directamente (sin .bat,
que parpadearía una consola) y fija el directorio de trabajo en el XML
(<WorkingDirectory>) para que las rutas relativas del proyecto resuelvan. Se genera
además `start_radar.bat` como atajo para arranque manual y pruebas.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from datetime import date
from pathlib import Path

# --- Constantes del proyecto -----------------------------------------------
NOMBRE_TAREA = "ConcursoRadar"
# Horas (24h, hora local del PC) que DISPARAN una búsqueda. Las 11:00, 15:00 y 18:00
# son las 3 corridas normales del día (tope 'max_corridas_por_dia'=3 en settings.yaml);
# las 20:00 son un SLOT DE TARDE EXTRA que repone la 3.ª corrida cuando el PC arrancó en
# la tarde y algún slot anterior cayó dentro de la separación mínima
# (min_horas_entre_corridas). En un día normal (PC prendido), las 20:00 se omiten por
# cupo lleno. Ver el candado _motivo_para_omitir en scheduler.py.
HORAS = ["11:00", "15:00", "18:00", "20:00"]

# Tarea aparte que manda el resumen del día (main.py --resumen). Sin costo Apify.
NOMBRE_TAREA_RESUMEN = "ConcursoRadarResumen"
HORA_RESUMEN = "21:00"

RAIZ = Path(__file__).resolve().parent
MAIN_PY = RAIZ / "main.py"
START_BAT = RAIZ / "start_radar.bat"
XML_TEMP = RAIZ / "_tarea_concurso_radar.xml"
RUTA_CONFIG = RAIZ / "config" / "settings.yaml"


def pythonw_exe() -> Path:
    """Devuelve la ruta a pythonw.exe del mismo entorno virtual que ejecuta esto."""
    return Path(sys.executable).parent / "pythonw.exe"


def usuario_actual() -> str:
    """
    Devuelve el usuario actual en formato DOMINIO\\USUARIO, como lo espera el
    XML del Programador de Tareas. Se obtiene con `whoami` para no depender de
    variables de entorno que pueden venir vacías.
    """
    resultado = subprocess.run(
        ["whoami"], capture_output=True, text=True, check=False
    )
    return resultado.stdout.strip()


def _escapar_xml(texto: str) -> str:
    """Escapa los caracteres que el XML reserva (las rutas rara vez los traen)."""
    return (
        texto.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def verificar_requisitos() -> bool:
    """
    Revisa que el entorno esté listo para instalar. No bloquea por settings.yaml
    (solo advierte), porque la tarea puede registrarse antes de pegar las
    credenciales. Devuelve True si se puede continuar con la instalación.
    """
    ok = True

    if sys.platform != "win32":
        print("[X] Este instalador solo funciona en Windows.")
        return False

    if sys.version_info < (3, 11):
        version = f"{sys.version_info.major}.{sys.version_info.minor}"
        print(f"[X] Se requiere Python 3.11 o superior (instalado: {version}).")
        ok = False
    else:
        print(f"[OK] Python {sys.version_info.major}.{sys.version_info.minor} detectado.")

    if not pythonw_exe().exists():
        print(f"[X] No se encontró pythonw.exe en {pythonw_exe()}.")
        print("  Revisa que el venv esté creado y que estés corriendo esto desde él.")
        ok = False
    else:
        print(f"[OK] pythonw.exe encontrado: {pythonw_exe()}")

    if not MAIN_PY.exists():
        print(f"[X] No se encontró main.py en {MAIN_PY}.")
        ok = False
    else:
        print(f"[OK] main.py encontrado: {MAIN_PY}")

    if not RUTA_CONFIG.exists():
        print(
            "[!] Falta config/settings.yaml. La tarea se puede registrar igual, pero "
            "el sistema NO correrá hasta que copies settings.example.yaml a "
            "settings.yaml y pegues las credenciales."
        )
    else:
        print("[OK] config/settings.yaml encontrado.")

    return ok


def crear_bat() -> None:
    """
    Crea start_radar.bat en la raíz: atajo para arrancar el sistema a mano
    (para pruebas o para correrlo sin reiniciar). Hace `cd` a la raíz y lanza
    pythonw para que no quede una consola abierta.
    """
    contenido = textwrap.dedent(
        f"""\
        @echo off
        rem Arranque manual de Concurso Radar (generado por install.py).
        cd /d "{RAIZ}"
        start "" "{pythonw_exe()}" "{MAIN_PY}"
        """
    )
    START_BAT.write_text(contenido, encoding="utf-8")
    print(f"[OK] Generado {START_BAT.name} (atajo de arranque manual).")


# GUID de "Permitir temporizadores de reactivación" (subgrupo Suspender de powercfg).
_GUID_WAKE_TIMERS = "BD3B718A-0680-4D9D-8AB2-E1D2B4AC806D"


def habilitar_wake_timers() -> None:
    """
    Permite los temporizadores de reactivación en el plan de energía activo (en
    corriente alterna y en batería). Sin esto, `WakeToRun` no puede despertar el
    PC para correr la tarea a la hora. Best-effort: si powercfg falla, solo avisa.
    """
    ok = True
    for verbo in ("/setacvalueindex", "/setdcvalueindex"):
        r = subprocess.run(
            ["powercfg", verbo, "SCHEME_CURRENT", "SUB_SLEEP", _GUID_WAKE_TIMERS, "1"],
            capture_output=True, text=True, check=False,
        )
        ok = ok and r.returncode == 0
    r = subprocess.run(
        ["powercfg", "/setactive", "SCHEME_CURRENT"],
        capture_output=True, text=True, check=False,
    )
    ok = ok and r.returncode == 0
    if ok:
        print("[OK] Temporizadores de reactivación habilitados (CA y batería).")
    else:
        print(
            "[!] No se pudieron habilitar los temporizadores de reactivación. "
            "WakeToRun podría no despertar el PC. Revisa la configuración de energía."
        )


def _triggers_xml(horas: list[str]) -> str:
    """
    Construye los disparadores por hora (un `CalendarTrigger` diario por cada hora
    de `horas`). El StartBoundary usa la fecha de hoy + la hora; la repetición
    diaria (DaysInterval=1) hace que dispare todos los días a esa hora.
    """
    hoy = date.today().isoformat()
    bloques = []
    for hora in horas:
        partes = (hora.split(":") + ["0"])[:2]
        hh, mm = int(partes[0]), int(partes[1])
        bloques.append(
            "    <CalendarTrigger>\n"
            f"      <StartBoundary>{hoy}T{hh:02d}:{mm:02d}:00</StartBoundary>\n"
            "      <Enabled>true</Enabled>\n"
            "      <ScheduleByDay>\n"
            "        <DaysInterval>1</DaysInterval>\n"
            "      </ScheduleByDay>\n"
            "    </CalendarTrigger>"
        )
    return "\n".join(bloques)


def _construir_xml(
    nombre: str,
    descripcion: str,
    triggers: str,
    argumentos: str,
    wake_to_run: bool,
) -> str:
    """
    Construye el XML de una tarea del Programador. Parametrizado para servir a las
    dos tareas del sistema (búsqueda y resumen), que comparten casi todo:
      - `triggers`: bloque XML de disparadores ya armado (ver `_triggers_xml` y abajo).
      - `argumentos`: argumentos del Exec ya escapados (ej. `"...main.py"` o con --resumen).
      - `wake_to_run`: despierta el PC suspendido para correr a la hora. La búsqueda
        sí (true, requiere wake timers, los habilita `habilitar_wake_timers`); el
        resumen no (false): si el PC está dormido a esa hora no vale despertarlo solo
        para mandar un mensaje, se enviará al volver gracias a StartWhenAvailable.

    El resto es común: StartWhenAvailable (recupera si el PC estaba no disponible),
    RunLevel HighestAvailable, WorkingDirectory en la raíz (rutas relativas), reintentos
    y ExecutionTimeLimit PT1H (corta una corrida colgada; cada corrida dura segundos).
    """
    usuario = _escapar_xml(usuario_actual())
    comando = _escapar_xml(str(pythonw_exe()))
    directorio = _escapar_xml(str(RAIZ))
    wake = "true" if wake_to_run else "false"

    plantilla = textwrap.dedent(
        """\
        <?xml version="1.0" encoding="UTF-16"?>
        <Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
          <RegistrationInfo>
            <Description>{descripcion}</Description>
            <URI>\\{nombre}</URI>
          </RegistrationInfo>
          <Triggers>
        {triggers}
          </Triggers>
          <Principals>
            <Principal id="Author">
              <UserId>{usuario}</UserId>
              <LogonType>InteractiveToken</LogonType>
              <RunLevel>HighestAvailable</RunLevel>
            </Principal>
          </Principals>
          <Settings>
            <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
            <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
            <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
            <AllowHardTerminate>true</AllowHardTerminate>
            <StartWhenAvailable>true</StartWhenAvailable>
            <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
            <IdleSettings>
              <StopOnIdleEnd>false</StopOnIdleEnd>
              <RestartOnIdle>false</RestartOnIdle>
            </IdleSettings>
            <AllowStartOnDemand>true</AllowStartOnDemand>
            <Enabled>true</Enabled>
            <Hidden>false</Hidden>
            <RunOnlyIfIdle>false</RunOnlyIfIdle>
            <WakeToRun>{wake}</WakeToRun>
            <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
            <Priority>7</Priority>
            <RestartOnFailure>
              <Interval>PT1M</Interval>
              <Count>2</Count>
            </RestartOnFailure>
          </Settings>
          <Actions Context="Author">
            <Exec>
              <Command>{comando}</Command>
              <Arguments>{argumentos}</Arguments>
              <WorkingDirectory>{directorio}</WorkingDirectory>
            </Exec>
          </Actions>
        </Task>
        """
    )
    return plantilla.format(
        nombre=nombre,
        descripcion=descripcion,
        triggers=triggers,
        usuario=usuario,
        comando=comando,
        argumentos=argumentos,
        directorio=directorio,
        wake=wake,
    )


def construir_xml_busqueda() -> str:
    """
    XML de la tarea de BÚSQUEDA (`ConcursoRadar`): corridas a horas fijas (HORAS) +
    un LogonTrigger de respaldo (cubre PC apagado a la hora). El gasto extra de tener
    varios disparos lo acotan el tope `max_corridas_por_dia` y la separación
    `min_horas_entre_corridas` (scheduler.py). WakeToRun para despertar a la hora.
    """
    usuario = _escapar_xml(usuario_actual())
    triggers = _triggers_xml(HORAS) + "\n" + (
        "    <LogonTrigger>\n"
        "      <Enabled>true</Enabled>\n"
        f"      <UserId>{usuario}</UserId>\n"
        "    </LogonTrigger>"
    )
    return _construir_xml(
        nombre=NOMBRE_TAREA,
        descripcion="Concurso Radar: monitorea Instagram y avisa por Telegram.",
        triggers=triggers,
        argumentos=_escapar_xml(f'"{MAIN_PY}"'),
        wake_to_run=True,
    )


def construir_xml_resumen() -> str:
    """
    XML de la tarea de RESUMEN (`ConcursoRadarResumen`): corre `main.py --resumen`
    (sin Apify, costo cero) a HORA_RESUMEN + un LogonTrigger de respaldo.

    `WakeToRun=true` despierta el PC suspendido (S3) a las 21:00 para mandar el
    resumen: es gratis (no llama a Apify), así que sí vale despertarlo. El
    LogonTrigger cubre el caso de PC apagado a esa hora (se manda al siguiente
    inicio de sesión). Ambos disparos no duplican el mensaje: `enviar_resumen_diario`
    lleva un candado por día en la tabla `estado` (`ultimo_resumen_fecha`) y, si la
    recuperación cae pasada la medianoche, reporta el día correcto (el que terminó),
    no el día en curso vacío.
    """
    usuario = _escapar_xml(usuario_actual())
    triggers = _triggers_xml([HORA_RESUMEN]) + "\n" + (
        "    <LogonTrigger>\n"
        "      <Enabled>true</Enabled>\n"
        f"      <UserId>{usuario}</UserId>\n"
        "    </LogonTrigger>"
    )
    return _construir_xml(
        nombre=NOMBRE_TAREA_RESUMEN,
        descripcion="Concurso Radar: resumen diario por Telegram (sin costo Apify).",
        triggers=triggers,
        argumentos=_escapar_xml(f'"{MAIN_PY}" --resumen'),
        wake_to_run=True,
    )


def _registrar_tarea(nombre: str, xml: str) -> bool:
    """
    Registra (o sobreescribe) una tarea en el Programador a partir de su XML.
    Escribe el XML en UTF-16 (lo que espera schtasks), corre `schtasks /Create /F`
    y limpia el temporal. Devuelve True si se registró bien.
    """
    # El Programador de Tareas espera el XML en UTF-16; write_text con 'utf-16'
    # añade el BOM correcto.
    XML_TEMP.write_text(xml, encoding="utf-16")
    comando = [
        "schtasks", "/Create", "/TN", nombre, "/XML", str(XML_TEMP),
        "/F",  # sobrescribe si ya existe -> idempotente
    ]
    resultado = subprocess.run(comando, capture_output=True, text=True, check=False)
    XML_TEMP.unlink(missing_ok=True)  # limpiar pase lo que pase

    if resultado.returncode != 0:
        print(f"[X] No se pudo registrar la tarea '{nombre}'.")
        if resultado.stdout.strip():
            print(resultado.stdout.strip())
        if resultado.stderr.strip():
            print(resultado.stderr.strip())
        return False
    print(f"[OK] Tarea '{nombre}' registrada correctamente.")
    return True


def instalar() -> None:
    """Verifica requisitos, genera el .bat y registra las dos tareas programadas."""
    print("== Instalando Concurso Radar ==\n")
    if not verificar_requisitos():
        print("\n[X] Faltan requisitos. Corrige lo anterior y vuelve a intentar.")
        sys.exit(1)

    crear_bat()
    habilitar_wake_timers()

    ok_busqueda = _registrar_tarea(NOMBRE_TAREA, construir_xml_busqueda())
    ok_resumen = _registrar_tarea(NOMBRE_TAREA_RESUMEN, construir_xml_resumen())

    if not (ok_busqueda and ok_resumen):
        print(
            "\n[X] No se pudieron registrar todas las tareas."
            "\nCausa más común: faltan permisos. Abre PowerShell o CMD como "
            "Administrador (clic derecho → 'Ejecutar como administrador') y vuelve "
            "a correr: python install.py"
        )
        sys.exit(1)

    horas_txt = ", ".join(HORAS)
    print(
        textwrap.dedent(
            f"""\

            Qué pasa ahora:
              - El sistema BUSCA a las {horas_txt} (hora local), todos los días. En un
                día normal corre 3 veces (11:00, 15:00 y 18:00): un tope de 3 búsquedas/día
                y una separación mínima de 2h dejan 3 corridas bien espaciadas.
                Las 20:00 son un slot de respaldo: reponen la 3.ª corrida los días en
                que el PC arrancó en la tarde y algún slot anterior quedó muy pegado.
              - Si el PC está suspendido a esa hora, se DESPIERTA solo para buscar
                (WakeToRun) y vuelve a dormir. Funciona enchufado o en batería.
              - Si el PC estaba APAGADO a la hora, la corrida se ejecuta apenas lo
                prendas e inicies sesión (disparador de respaldo por inicio de sesión).
              - Al final del día (≈{HORA_RESUMEN}) manda por Telegram un RESUMEN del día
                (posts revisados y alertas enviadas). Esa tarea NO consulta Apify (gratis)
                y NO despierta el PC: si está dormido, el resumen llega al volver a usarlo.
              - Cada corrida revisa las cuentas y termina; corre sin ventana (pythonw.exe).
              - Si una corrida falla, Windows la reintenta hasta 2 veces (1 min entre cada una).

            Para verificar:
              1. Abre el 'Programador de tareas' de Windows y busca '{NOMBRE_TAREA}' y
                 '{NOMBRE_TAREA_RESUMEN}'.
              2. Selecciónalas y pulsa 'Ejecutar' para probarlas sin esperar la hora;
                 luego revisa logs/system.log y espera el mensaje en Telegram.

            Para quitarlas:
              python install.py --desinstalar
            """
        )
    )


def desinstalar() -> None:
    """Elimina ambas tareas del Programador de Tareas y borra el .bat generado."""
    print("== Desinstalando Concurso Radar ==\n")
    hubo_error = False
    for nombre in (NOMBRE_TAREA, NOMBRE_TAREA_RESUMEN):
        comando = ["schtasks", "/Delete", "/TN", nombre, "/F"]
        resultado = subprocess.run(comando, capture_output=True, text=True, check=False)
        if resultado.returncode == 0:
            print(f"[OK] Tarea '{nombre}' eliminada.")
        else:
            # No es fatal: la tarea pudo no existir (ej. instalación previa sin resumen).
            print(f"[!] No se pudo eliminar '{nombre}' (quizás no estaba registrada).")
            if resultado.stderr.strip():
                print("    " + resultado.stderr.strip())
            hubo_error = True

    START_BAT.unlink(missing_ok=True)
    print("  Nota: el proceso ya en ejecución sigue vivo hasta el próximo reinicio.")
    if hubo_error:
        # Salida 0 igual: que falte una tarea por borrar no debe verse como falla dura.
        print("  (Alguna tarea no estaba registrada; nada más que hacer.)")


def main() -> None:
    """Procesa los argumentos de línea de comandos."""
    argumentos = sys.argv[1:]

    if not argumentos:
        instalar()
    elif "--desinstalar" in argumentos:
        desinstalar()
    elif "--verificar" in argumentos:
        print("== Verificando requisitos ==\n")
        ok = verificar_requisitos()
        sys.exit(0 if ok else 1)
    else:
        print("Uso: python install.py [--desinstalar | --verificar]")
        sys.exit(2)


if __name__ == "__main__":
    main()
