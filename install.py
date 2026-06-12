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
# Horas (24h, hora local del PC) en que corre el sistema. 2 corridas/día = palanca
# de costo. Elegidas dentro de la ventana en que el PC del cliente suele estar prendido.
HORAS = ["11:00", "18:00"]
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


def construir_xml() -> str:
    """
    Construye el XML de la tarea. Incluye:
      - CalendarTrigger por cada hora de HORAS: dispara a horas fijas, todos los días.
      - StartWhenAvailable: si el PC estaba apagado a la hora, recupera la corrida.
      - RunLevel HighestAvailable: privilegios altos disponibles.
      - WorkingDirectory: la raíz del proyecto (rutas relativas funcionan).
      - RestartOnFailure: hasta 2 reintentos, uno por minuto, si main.py falla.
      - ExecutionTimeLimit PT1H: corta una corrida colgada tras 1 hora (ya no es
        un proceso de larga vida; cada corrida dura segundos).
    """
    usuario = _escapar_xml(usuario_actual())
    comando = _escapar_xml(str(pythonw_exe()))
    argumentos = _escapar_xml(f'"{MAIN_PY}"')
    directorio = _escapar_xml(str(RAIZ))

    plantilla = textwrap.dedent(
        """\
        <?xml version="1.0" encoding="UTF-16"?>
        <Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
          <RegistrationInfo>
            <Description>Concurso Radar: monitorea Instagram y avisa por Telegram.</Description>
            <URI>\\{NOMBRE_TAREA}</URI>
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
            <WakeToRun>false</WakeToRun>
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
        NOMBRE_TAREA=NOMBRE_TAREA,
        triggers=_triggers_xml(HORAS),
        usuario=usuario,
        comando=comando,
        argumentos=argumentos,
        directorio=directorio,
    )


def instalar() -> None:
    """Verifica requisitos, genera el .bat y registra la tarea de arranque automático."""
    print("== Instalando Concurso Radar ==\n")
    if not verificar_requisitos():
        print("\n[X] Faltan requisitos. Corrige lo anterior y vuelve a intentar.")
        sys.exit(1)

    crear_bat()

    # El Programador de Tareas espera el XML en UTF-16; lo escribimos con esa
    # codificación (write_text con 'utf-16' añade el BOM correcto).
    XML_TEMP.write_text(construir_xml(), encoding="utf-16")

    comando = [
        "schtasks",
        "/Create",
        "/TN",
        NOMBRE_TAREA,
        "/XML",
        str(XML_TEMP),
        "/F",  # sobrescribe si ya existe -> idempotente
    ]
    resultado = subprocess.run(comando, capture_output=True, text=True, check=False)

    # Limpiamos el XML temporal pase lo que pase.
    XML_TEMP.unlink(missing_ok=True)

    if resultado.returncode != 0:
        print("\n[X] No se pudo registrar la tarea.")
        if resultado.stdout.strip():
            print(resultado.stdout.strip())
        if resultado.stderr.strip():
            print(resultado.stderr.strip())
        print(
            "\nCausa más común: faltan permisos. Abre PowerShell o CMD como "
            "Administrador (clic derecho → 'Ejecutar como administrador') y vuelve "
            "a correr: python install.py"
        )
        sys.exit(1)

    horas_txt = " y ".join(HORAS)
    print(f"\n[OK] Tarea '{NOMBRE_TAREA}' registrada correctamente.")
    print(
        textwrap.dedent(
            f"""\

            Qué pasa ahora:
              - El sistema corre solo a las {horas_txt} (hora local), todos los días.
              - Cada corrida revisa las cuentas y termina; no queda nada abierto.
              - Corre en segundo plano, sin ventana (proceso pythonw.exe).
              - Si el PC estaba apagado a esa hora, la corrida se ejecuta apenas lo
                prendas e inicies sesión (recuperación automática).
              - Si una corrida falla, Windows la reintenta hasta 2 veces (1 min entre cada una).

            Para verificar:
              1. Abre el 'Programador de tareas' de Windows y busca '{NOMBRE_TAREA}'.
              2. Selecciónala y pulsa 'Ejecutar' para probarla sin esperar la hora;
                 luego revisa logs/system.log y espera el mensaje en Telegram.

            Para quitarla:
              python install.py --desinstalar
            """
        )
    )


def desinstalar() -> None:
    """Elimina la tarea del Programador de Tareas y borra el .bat generado."""
    print(f"== Desinstalando '{NOMBRE_TAREA}' ==\n")
    comando = ["schtasks", "/Delete", "/TN", NOMBRE_TAREA, "/F"]
    resultado = subprocess.run(comando, capture_output=True, text=True, check=False)

    if resultado.returncode != 0:
        print("[X] No se pudo eliminar la tarea (quizás no estaba registrada).")
        if resultado.stderr.strip():
            print(resultado.stderr.strip())
        sys.exit(1)

    START_BAT.unlink(missing_ok=True)
    print(f"[OK] Tarea '{NOMBRE_TAREA}' eliminada.")
    print("  Nota: el proceso ya en ejecución sigue vivo hasta el próximo reinicio.")


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
