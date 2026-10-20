"""Lógica de datos de la trazabilidad de módulos retornables (SQLite).

Aquí viven las reglas: qué campos pide cada etapa, cómo cambia el estado del
módulo y qué advertencias se generan. La interfaz (app.py) solo dibuja esto.
"""
import datetime as dt
import json
import os
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

# Si existe la variable DATABASE_URL se usa esa base de datos (PostgreSQL, ej. Neon).
# Si no, se usa un archivo SQLite local (solo para pruebas: se pierde si el equipo se reinicia).
TZ = ZoneInfo("America/Bogota")

FASES = ["Iniciación", "Levante", "Engorde", "Postura"]
# Color de la tapa/etiqueta según el tipo de alimento (hex para la pantalla).
FASE_COLOR = {
    "Iniciación": "#F4C20D",
    "Levante": "#34A853",
    "Engorde": "#4285F4",
    "Postura": "#E8710A",
    None: "#9AA0A6",
}
FASE_EMOJI = {"Iniciación": "🟨", "Levante": "🟩", "Engorde": "🟦", "Postura": "🟧", None: "⬜"}
UBICACIONES = ["En planta", "En tránsito", "En granja", "En lavado"]

CHECKS_LAVADO = [
    ("retiro_seco", "Retiro en seco de residuos de alimento"),
    ("lavado_presion", "Lavado con agua a presión y detergente"),
    ("desinfeccion", "Desinfección con producto aprobado"),
    ("secado", "Secado completo antes de volver a llenar"),
    ("inspeccion", "Inspección visual (grietas, tapa, empaque, precinto)"),
]

# Campos de cada etapa. tipo: texto | area | select | planta | granja | bool
ETAPAS = {
    "llenado": {
        "titulo": "Llenado en planta",
        "emoji": "🏭",
        "descripcion": "Se registra cuando el módulo se llena con alimento en la planta.",
        "campos": [
            {"k": "planta", "label": "Planta de origen", "tipo": "planta", "req": True,
             "ayuda": "Planta donde se llenó el módulo."},
            {"k": "fase", "label": "Tipo de alimento", "tipo": "select", "opciones": FASES, "req": True,
             "ayuda": "Fase para la que sirve el alimento. Debe coincidir con el color de la tapa del módulo."},
            {"k": "lote", "label": "Lote de producción", "tipo": "texto", "req": True,
             "ayuda": "Código del lote que aparece en el reporte de producción.", "ej": "L-2026-0345"},
            {"k": "observaciones", "label": "Observaciones", "tipo": "area", "req": False,
             "ayuda": "Opcional. Cualquier detalle que convenga anotar."},
        ],
    },
    "despacho": {
        "titulo": "Despacho",
        "emoji": "🚚",
        "descripcion": "Se registra cuando el módulo sale de la planta hacia una granja.",
        "campos": [
            {"k": "granja", "label": "Granja de destino", "tipo": "granja", "req": True,
             "ayuda": "Granja a la que va el alimento."},
            {"k": "transportista", "label": "Placa del vehículo o transportista", "tipo": "texto", "req": True,
             "ayuda": "Sirve para saber quién transportó el módulo.", "ej": "SXY123"},
            {"k": "observaciones", "label": "Observaciones", "tipo": "area", "req": False,
             "ayuda": "Opcional."},
        ],
    },
    "recepcion": {
        "titulo": "Recepción en granja",
        "emoji": "🐔",
        "descripcion": "Se registra cuando el módulo llega a la granja.",
        "campos": [
            {"k": "granja", "label": "Granja", "tipo": "granja", "req": True,
             "ayuda": "Granja donde se recibe el módulo."},
            {"k": "galpon", "label": "Galpón", "tipo": "texto", "req": False,
             "ayuda": "Opcional. Galpón donde se usará el alimento.", "ej": "Galpón 3"},
            {"k": "precinto", "label": "Estado del precinto de seguridad", "tipo": "select",
             "opciones": ["Intacto", "Roto"], "req": True,
             "ayuda": "Si el precinto llegó roto, se genera una alerta."},
            {"k": "estado_modulo", "label": "Estado del módulo", "tipo": "select",
             "opciones": ["Bueno", "Golpeado", "Dañado"], "req": True,
             "ayuda": "Revise tapa, empaque y asas."},
            {"k": "observaciones", "label": "Observaciones", "tipo": "area", "req": False,
             "ayuda": "Opcional."},
        ],
    },
    "recoleccion": {
        "titulo": "Recolección",
        "emoji": "↩️",
        "descripcion": "Se registra cuando el módulo se recoge en la granja para volver a la planta.",
        "campos": [
            {"k": "granja", "label": "Granja donde se recoge", "tipo": "granja", "req": True,
             "ayuda": "Granja de la que sale el módulo."},
            {"k": "vacio", "label": "¿El módulo está vacío?", "tipo": "select",
             "opciones": ["Sí", "No"], "req": True,
             "ayuda": "Si no está vacío se genera una alerta."},
            {"k": "observaciones", "label": "Observaciones", "tipo": "area", "req": False,
             "ayuda": "Opcional."},
        ],
    },
    "lavado": {
        "titulo": "Lavado y desinfección",
        "emoji": "🧼",
        "descripcion": "Se registra en la planta cuando se lava el módulo. Si se marcan todos los pasos, "
                       "el módulo queda limpio y listo para llenarse.",
        "campos": [
            {"k": "planta", "label": "Planta o punto de lavado", "tipo": "planta", "req": True,
             "ayuda": "Lugar donde se hizo el lavado."},
        ]
        + [{"k": k, "label": lab, "tipo": "bool", "req": False,
            "ayuda": "Marque si el paso se hizo."} for k, lab in CHECKS_LAVADO]
        + [
            {"k": "producto", "label": "Desinfectante usado", "tipo": "texto", "req": False,
             "ayuda": "Opcional. Nombre del producto.", "ej": "Amonio cuaternario"},
            {"k": "observaciones", "label": "Observaciones", "tipo": "area", "req": False,
             "ayuda": "Opcional."},
        ],
    },
}


def ahora():
    return dt.datetime.now(TZ).replace(microsecond=0, tzinfo=None)


def fmt(fecha):
    return fecha.strftime("%Y-%m-%d %H:%M")


_engine = None


def get_engine():
    global _engine
    if _engine is None:
        url = os.environ.get("DATABASE_URL", "").strip()
        if url:
            for pref in ("postgres://", "postgresql://"):
                if url.startswith(pref):
                    url = "postgresql+psycopg2://" + url[len(pref):]
                    break
            _engine = create_engine(url, pool_pre_ping=True, pool_recycle=300)
        else:
            _engine = create_engine(f"sqlite:///{os.environ.get('DB_PATH', 'trazabilidad.db')}")
    return _engine


def es_postgres():
    return get_engine().dialect.name == "postgresql"


def modo_base():
    return "PostgreSQL (permanente)" if es_postgres() else "SQLite local (temporal)"


def q(sql, **p):
    """SELECT -> lista de diccionarios."""
    with get_engine().connect() as c:
        return [dict(r._mapping) for r in c.execute(text(sql), p)]


def ejecutar(sql, **p):
    with get_engine().begin() as c:
        c.execute(text(sql), p)


def init_db():
    pk = "SERIAL PRIMARY KEY" if es_postgres() else "INTEGER PRIMARY KEY AUTOINCREMENT"
    ddl = [
        f"""CREATE TABLE IF NOT EXISTS lugares(
            id {pk},
            nombre TEXT UNIQUE NOT NULL,
            tipo TEXT NOT NULL CHECK(tipo IN ('planta','granja')))""",
        """CREATE TABLE IF NOT EXISTS modulos(
            id TEXT PRIMARY KEY,
            capacidad_kg REAL NOT NULL DEFAULT 25,
            fase TEXT,
            ubicacion TEXT NOT NULL DEFAULT 'En planta',
            lugar TEXT,
            lote TEXT,
            fecha_llenado TEXT,
            granja_destino TEXT,
            ciclos INTEGER NOT NULL DEFAULT 0,
            limpio INTEGER NOT NULL DEFAULT 1,
            ultimo_lavado TEXT,
            ultimo_evento TEXT,
            creado TEXT)""",
        f"""CREATE TABLE IF NOT EXISTS eventos(
            id {pk},
            modulo_id TEXT NOT NULL,
            etapa TEXT NOT NULL,
            fecha TEXT NOT NULL,
            responsable TEXT NOT NULL,
            datos TEXT NOT NULL,
            advertencias TEXT NOT NULL DEFAULT '')""",
        "CREATE TABLE IF NOT EXISTS meta(clave TEXT PRIMARY KEY, valor TEXT)",
    ]
    with get_engine().begin() as c:
        for stmt in ddl:
            c.execute(text(stmt))
    # Los datos de ejemplo se cargan una sola vez en la vida de la base de datos.
    if not q("SELECT valor FROM meta WHERE clave='ejemplo'"):
        if not q("SELECT 1 AS x FROM modulos LIMIT 1"):
            cargar_ejemplo()
        marcar_ejemplo()


def marcar_ejemplo():
    ejecutar("INSERT INTO meta(clave, valor) VALUES('ejemplo','1') ON CONFLICT(clave) DO NOTHING")


# ---------- lugares ----------
def listar_lugares(tipo=None):
    if tipo:
        return [r["nombre"] for r in q("SELECT nombre FROM lugares WHERE tipo=:t ORDER BY nombre", t=tipo)]
    return q("SELECT nombre, tipo FROM lugares ORDER BY tipo, nombre")


def agregar_lugar(nombre, tipo):
    nombre = (nombre or "").strip()
    if not nombre:
        return False, "Escriba un nombre."
    try:
        ejecutar("INSERT INTO lugares(nombre,tipo) VALUES(:n,:t)", n=nombre, t=tipo)
    except IntegrityError:
        return False, "Ese nombre ya existe."
    return True, f"Se agregó «{nombre}»."


# ---------- módulos ----------
def siguiente_id():
    ids = [r["id"] for r in q("SELECT id FROM modulos")]
    nums = [int(i.split("-")[1]) for i in ids if i.startswith("MOD-") and i.split("-")[1].isdigit()]
    return max(nums, default=0) + 1


def crear_modulos(cantidad, capacidad_kg):
    inicio = siguiente_id()
    creados = []
    with get_engine().begin() as c:
        for i in range(cantidad):
            mid = f"MOD-{inicio + i:03d}"
            c.execute(
                text("INSERT INTO modulos(id,capacidad_kg,ubicacion,creado) VALUES(:i,:c,:u,:f)"),
                {"i": mid, "c": capacidad_kg, "u": "En planta", "f": fmt(ahora())},
            )
            creados.append(mid)
    return creados


def listar_modulos():
    return q("SELECT * FROM modulos ORDER BY id")


def obtener_modulo(mid):
    r = q("SELECT * FROM modulos WHERE id=:i", i=mid)
    return r[0] if r else None


def eventos_de(mid=None):
    if mid:
        rows = q("SELECT * FROM eventos WHERE modulo_id=:i ORDER BY fecha DESC, id DESC", i=mid)
    else:
        rows = q("SELECT * FROM eventos ORDER BY fecha DESC, id DESC")
    for d in rows:
        d["datos"] = json.loads(d["datos"])
    return rows


# ---------- registro de eventos ----------
def registrar_evento(modulo_id, etapa, datos, responsable, fecha=None):
    """Valida, guarda el evento y actualiza el estado del módulo.

    Devuelve (ok, errores, advertencias).
    """
    errores, avisos = [], []
    if etapa not in ETAPAS:
        return False, ["Etapa desconocida."], []
    m = obtener_modulo(modulo_id)
    if not m:
        return False, [f"El módulo {modulo_id} no existe."], []
    if not (responsable or "").strip():
        errores.append("Escriba el nombre del responsable.")
    for campo in ETAPAS[etapa]["campos"]:
        if campo["req"] and not str(datos.get(campo["k"], "") or "").strip():
            errores.append(f"Falta: {campo['label']}.")
    if errores:
        return False, errores, []

    fecha = fecha or ahora()
    f = fmt(fecha)
    cambios = {}

    if etapa == "llenado":
        if m["fase"]:
            avisos.append(f"El módulo figura con alimento de {m['fase']} (lote {m['lote']}). Verifique que esté vacío.")
        if not m["limpio"]:
            avisos.append("No hay un lavado completo registrado desde su último uso (riesgo de bioseguridad).")
        cambios = dict(ubicacion="En planta", lugar=datos["planta"], fase=datos["fase"], lote=datos["lote"].strip(),
                       fecha_llenado=f, granja_destino=None, limpio=0)
    elif etapa == "despacho":
        if not m["fase"]:
            errores.append("El módulo está vacío: primero hay que registrar su llenado.")
        elif m["ubicacion"] != "En planta":
            avisos.append(f"El módulo figura «{m['ubicacion']}», no en planta.")
        if not errores:
            cambios = dict(ubicacion="En tránsito", lugar=None, granja_destino=datos["granja"])
    elif etapa == "recepcion":
        if datos.get("precinto") == "Roto":
            avisos.append("El precinto llegó roto: revise el alimento antes de usarlo.")
        if datos.get("estado_modulo") != "Bueno":
            avisos.append(f"El módulo llegó {datos.get('estado_modulo', '').lower()}.")
        if m["granja_destino"] and m["granja_destino"] != datos["granja"]:
            avisos.append(f"El destino registrado era «{m['granja_destino']}», no «{datos['granja']}».")
        cambios = dict(ubicacion="En granja", lugar=datos["granja"])
    elif etapa == "recoleccion":
        cambios = dict(ubicacion="En tránsito", lugar=None, granja_destino=None)
        if datos.get("vacio") == "Sí":
            cambios.update(fase=None, lote=None, fecha_llenado=None)
        else:
            avisos.append("El módulo se recoge con alimento: revise por qué no se vació.")
    elif etapa == "lavado":
        if m["fase"]:
            avisos.append("El módulo todavía figura con alimento: debe estar vacío antes de lavarlo.")
        completo = all(datos.get(k) for k, _ in CHECKS_LAVADO)
        if completo:
            cambios = dict(ubicacion="En planta", lugar=datos["planta"], fase=None, lote=None, fecha_llenado=None,
                           granja_destino=None, limpio=1, ultimo_lavado=f, ciclos=m["ciclos"] + 1)
        else:
            faltan = [lab for k, lab in CHECKS_LAVADO if not datos.get(k)]
            avisos.append("Lavado incompleto, el módulo sigue «En lavado». Falta: " + "; ".join(faltan) + ".")
            cambios = dict(ubicacion="En lavado", lugar=datos["planta"], limpio=0)

    if errores:
        return False, errores, []

    cambios["ultimo_evento"] = f
    sets = ", ".join(f"{k}=:{k}" for k in cambios)
    with get_engine().begin() as c:
        c.execute(text(f"UPDATE modulos SET {sets} WHERE id=:mid_"), {**cambios, "mid_": modulo_id})
        c.execute(
            text("INSERT INTO eventos(modulo_id,etapa,fecha,responsable,datos,advertencias) "
                 "VALUES(:m,:e,:f,:r,:d,:a)"),
            {"m": modulo_id, "e": etapa, "f": f, "r": responsable.strip(),
             "d": json.dumps(datos, ensure_ascii=False), "a": " | ".join(avisos)},
        )
    return True, [], avisos


# ---------- datos de ejemplo ----------
def borrar_todo():
    with get_engine().begin() as c:
        for t in ("eventos", "modulos", "lugares"):
            c.execute(text(f"DELETE FROM {t}"))
    marcar_ejemplo()


def cargar_ejemplo():
    for n in ["Planta de concentrados (ejemplo)"]:
        agregar_lugar(n, "planta")
    for n in ["Granja El Mirador (ejemplo)", "Granja La Esperanza (ejemplo)"]:
        agregar_lugar(n, "granja")
    planta = "Planta de concentrados (ejemplo)"
    g1, g2 = "Granja El Mirador (ejemplo)", "Granja La Esperanza (ejemplo)"
    ids = crear_modulos(6, 25)
    base = ahora() - dt.timedelta(days=9)

    def ev(mid, etapa, datos, dias, horas=8, quien="Operario demo"):
        registrar_evento(mid, etapa, datos, quien, base + dt.timedelta(days=dias, hours=horas - 8))

    lav = {k: True for k, _ in CHECKS_LAVADO}
    # MOD-001: ciclo completo, ya lavado y listo en planta
    ev(ids[0], "llenado", {"planta": planta, "fase": "Iniciación", "lote": "L-0001"}, 0)
    ev(ids[0], "despacho", {"granja": g1, "transportista": "SXY123"}, 1)
    ev(ids[0], "recepcion", {"granja": g1, "precinto": "Intacto", "estado_modulo": "Bueno"}, 1, 14)
    ev(ids[0], "recoleccion", {"granja": g1, "vacio": "Sí"}, 5)
    ev(ids[0], "lavado", {"planta": planta, **lav, "producto": "Amonio cuaternario"}, 6)
    # MOD-002: en granja con engorde
    ev(ids[1], "llenado", {"planta": planta, "fase": "Engorde", "lote": "L-0002"}, 6)
    ev(ids[1], "despacho", {"granja": g2, "transportista": "TUV456"}, 7)
    ev(ids[1], "recepcion", {"granja": g2, "galpon": "Galpón 2", "precinto": "Intacto", "estado_modulo": "Bueno"}, 7, 15)
    # MOD-003: en tránsito con levante
    ev(ids[2], "llenado", {"planta": planta, "fase": "Levante", "lote": "L-0003"}, 8)
    ev(ids[2], "despacho", {"granja": g1, "transportista": "SXY123"}, 9)
    # MOD-004: en lavado (incompleto)
    ev(ids[3], "llenado", {"planta": planta, "fase": "Postura", "lote": "L-0004"}, 2)
    ev(ids[3], "despacho", {"granja": g2, "transportista": "TUV456"}, 3)
    ev(ids[3], "recepcion", {"granja": g2, "precinto": "Intacto", "estado_modulo": "Bueno"}, 3, 14)
    ev(ids[3], "recoleccion", {"granja": g2, "vacio": "Sí"}, 8)
    ev(ids[3], "lavado", {"planta": planta, "retiro_seco": True, "lavado_presion": True}, 9)
    # MOD-005: llenado en planta, engorde
    ev(ids[4], "llenado", {"planta": planta, "fase": "Engorde", "lote": "L-0005"}, 9)
    # MOD-006: nuevo, sin movimientos
