# Concurso Radar

Sistema de monitoreo automatizado que detecta concursos y sorteos de marcas en
Instagram y envía alertas por Telegram. Uso personal, corre en el PC del cliente
(Windows 11).

## Estado

Fase 1 — primera entrega: estructura del proyecto + capa de base de datos.

## Requisitos

- Python 3.11 o superior
- Windows 11 (objetivo de producción; el desarrollo puede ser en cualquier SO,
  salvo el instalador/arranque automático que es específico de Windows)

## Puesta en marcha

```powershell
# 1. Crear y activar el entorno virtual
python -m venv venv
venv\Scripts\activate        # En Linux/macOS: source venv/bin/activate

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Crear el archivo de configuración a partir de la plantilla
Copy-Item config\settings.example.yaml config\settings.yaml
#   (Linux/macOS: cp config/settings.example.yaml config/settings.yaml)

# 4. Pegar los tokens reales (Apify, Telegram) dentro de config\settings.yaml
```

## Verificar la base de datos

La capa de almacenamiento no necesita credenciales ni dependencias externas.
Para comprobar que funciona, correr su auto-prueba:

```powershell
python storage\database.py
```

Debe crear una base temporal, probar deduplicación, historial y gasto, e
imprimir los resultados sin errores.

## Estructura

Cada archivo indica entre paréntesis la fase en la que se implementa.
✓ = ya implementado.

```
concurso-radar/
├── main.py                      # punto de entrada: corre UN ciclo y termina  ✓
├── scheduler.py                 # orquesta un ciclo (corrida única)  ✓
├── watchdog.py                  # vigila que main siga vivo (robustez)
├── install.py                   # instalador Windows + Task Scheduler (horas fijas)  ✓
├── config/
│   └── settings.example.yaml    # plantilla; copiar a settings.yaml (no versionado)
├── searchers/
│   ├── instagram_search.py      # Apify — núcleo (Fase 1)
│   └── web_search.py            # búsqueda web de concursos vía Anthropic (secundario, piloto)  ✓
├── filters/
│   └── keywords.py              # filtro por palabras clave (Fase 1)
├── classifier/
│   └── ai_filter.py             # Claude Haiku: relevancia + resumen (Fase 2)
├── notifier/
│   └── telegram.py              # alertas + heartbeat + comandos (Fase 1)
├── budget/
│   └── tracker.py               # control de gasto por servicio (Fase 1)
├── storage/
│   └── database.py              # capa de acceso a SQLite  ✓
├── logs/                        # logs rotativos
├── requirements.txt
└── .gitignore
```

Los archivos aún no implementados son **esqueletos**: tienen el docstring de su
rol y las firmas de sus funciones/clases, pero su cuerpo lanza
`NotImplementedError` indicando en qué fase se completan. Eso permite ver el
contrato de cada módulo y cómo encajan antes de escribir la lógica.

> **Importante:** `config/settings.yaml` contiene secretos y está excluido de Git.
> Nunca lo subas a un repositorio.
