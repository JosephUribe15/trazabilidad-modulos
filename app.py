"""Trazabilidad de módulos retornables de alimento avícola (prototipo).

Se ejecuta con:  streamlit run app.py
Cada módulo tiene un QR que abre su ficha:  <URL pública>/?modulo=MOD-001
"""
import datetime as dt
import io
import os

import pandas as pd
import qrcode
import streamlit as st
from PIL import Image, ImageDraw, ImageFont

import db

st.set_page_config(page_title="Trazabilidad de módulos", page_icon="📦", layout="centered")
# En la nube (Streamlit Cloud) los "secrets" se pasan a variables de entorno.
for _k in ("DATABASE_URL", "PUBLIC_URL"):
    try:
        if _k in st.secrets:
            os.environ[_k] = str(st.secrets[_k])
    except Exception:
        pass


@st.cache_resource
def _iniciar_base():
    db.init_db()
    return True


_iniciar_base()

PAGINAS = ["📋 Tablero", "📦 Ficha del módulo", "✍️ Registrar evento", "⚙️ Administración"]


# ---------------------------------------------------------------- utilidades
def badge(texto, color):
    return (f"<span style='background:{color};color:white;padding:3px 12px;border-radius:12px;"
            f"font-weight:600;font-size:0.9rem'>{texto}</span>")


def fase_badge(fase):
    return badge(fase or "Vacío", db.FASE_COLOR.get(fase, db.FASE_COLOR[None]))


def url_publica():
    if st.session_state.get("url_publica"):
        return st.session_state["url_publica"].rstrip("/")
    if os.environ.get("PUBLIC_URL"):
        return os.environ["PUBLIC_URL"].strip().rstrip("/")
    if os.path.exists("url_publica.txt"):
        with open("url_publica.txt") as f:
            u = f.read().strip()
            if u:
                return u.rstrip("/")
    return "http://localhost:8501"


def url_modulo(mid):
    return f"{url_publica()}/?modulo={mid}"


def imagen_qr(texto, tam=320):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(texto)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB").resize((tam, tam))


def fuente(tam):
    for ruta in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "DejaVuSans-Bold.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(ruta, tam)
        except OSError:
            continue
    return ImageFont.load_default(size=tam)


def etiqueta(mid):
    """Etiqueta imprimible: QR con el ID debajo."""
    ancho, alto = 360, 440
    img = Image.new("RGB", (ancho, alto), "white")
    img.paste(imagen_qr(url_modulo(mid), 320), (20, 10))
    d = ImageDraw.Draw(img)
    d.text((ancho // 2, 370), mid, fill="black", font=fuente(44), anchor="mm")
    d.text((ancho // 2, 415), "Escanee para ver o registrar", fill="#555555", font=fuente(18), anchor="mm")
    d.rectangle([0, 0, ancho - 1, alto - 1], outline="#bbbbbb", width=2)
    return img


def hoja_etiquetas(ids, columnas=3):
    imgs = [etiqueta(i) for i in ids]
    filas = -(-len(imgs) // columnas)
    w, h = imgs[0].size
    hoja = Image.new("RGB", (columnas * w, filas * h), "white")
    for n, im in enumerate(imgs):
        hoja.paste(im, ((n % columnas) * w, (n // columnas) * h))
    return hoja


def png_bytes(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def abrir_ficha(mid):
    st.session_state["modulo_sel"] = mid
    st.session_state["pagina"] = PAGINAS[1]


def fecha_hora_inputs(clave):
    ahora = db.ahora()
    c1, c2 = st.columns(2)
    f = c1.date_input("Fecha", value=ahora.date(), key=f"fecha_{clave}")
    h = c2.time_input("Hora", value=ahora.time().replace(second=0), key=f"hora_{clave}")
    st.caption("Se llenan solas con la fecha y hora actuales. Cámbielas solo si el evento ocurrió antes.")
    return dt.datetime.combine(f, h)


# ---------------------------------------------------------- formulario guiado
def formulario_evento(mid, etapa):
    cfg = db.ETAPAS[etapa]
    st.subheader(f"{cfg['emoji']} {cfg['titulo']} — {mid}")
    st.info(cfg["descripcion"])
    plantas, granjas = db.listar_lugares("planta"), db.listar_lugares("granja")
    if (any(c["tipo"] == "planta" for c in cfg["campos"]) and not plantas) or \
       (any(c["tipo"] == "granja" for c in cfg["campos"]) and not granjas):
        st.warning("Primero agregue las plantas y granjas en ⚙️ Administración.")
        return

    with st.form(f"form_{etapa}_{mid}", clear_on_submit=False):
        datos = {}
        for c in cfg["campos"]:
            k, req = c["k"], c["req"]
            etiqueta_campo = c["label"] + (" *" if req else "")
            clave = f"{etapa}_{mid}_{k}"
            if c["tipo"] == "texto":
                datos[k] = st.text_input(etiqueta_campo, key=clave, placeholder=c.get("ej", ""))
            elif c["tipo"] == "area":
                datos[k] = st.text_area(etiqueta_campo, key=clave, height=70)
            elif c["tipo"] == "select":
                datos[k] = st.selectbox(etiqueta_campo, ["— Elija una opción —"] + c["opciones"], key=clave)
                if datos[k].startswith("—"):
                    datos[k] = ""
            elif c["tipo"] in ("planta", "granja"):
                opciones = plantas if c["tipo"] == "planta" else granjas
                datos[k] = st.selectbox(etiqueta_campo, ["— Elija una opción —"] + opciones, key=clave)
                if datos[k].startswith("—"):
                    datos[k] = ""
            elif c["tipo"] == "bool":
                datos[k] = st.checkbox(c["label"], key=clave)
            if c["tipo"] != "bool":
                st.caption(c["ayuda"])
        st.divider()
        responsable = st.text_input("Su nombre (responsable) *", key=f"resp_{mid}_{etapa}",
                                    value=st.session_state.get("responsable", ""),
                                    placeholder="Nombre y apellido")
        st.caption("Queda guardado en el historial para saber quién hizo el registro.")
        fecha = fecha_hora_inputs(f"{etapa}_{mid}")
        enviar = st.form_submit_button("Guardar registro", type="primary", width="stretch")

    if enviar:
        st.session_state["responsable"] = responsable
        ok, errores, avisos = db.registrar_evento(mid, etapa, datos, responsable, fecha)
        if not ok:
            for e in errores:
                st.error(e)
            return
        st.session_state["flash"] = {"msg": f"✅ Registro guardado: {cfg['titulo']} de {mid}.", "avisos": avisos}
        st.session_state["etapa_sel"] = None
        st.rerun()


# ------------------------------------------------------------------ páginas
def pagina_tablero():
    st.title("📋 Tablero de módulos")
    st.caption("¿Dónde está cada módulo plástico y qué alimento lleva?")
    mods = db.listar_modulos()
    if not mods:
        st.info("Todavía no hay módulos. Créelos en ⚙️ Administración.")
        return
    cols = st.columns(4)
    for col, u in zip(cols, db.UBICACIONES):
        col.metric(u, sum(1 for m in mods if m["ubicacion"] == u))

    f1, f2 = st.columns(2)
    fil_u = f1.multiselect("Ubicación", db.UBICACIONES)
    fil_f = f2.multiselect("Tipo de alimento", db.FASES + ["Vacío"])
    filas = []
    for m in mods:
        if fil_u and m["ubicacion"] not in fil_u:
            continue
        if fil_f and (m["fase"] or "Vacío") not in fil_f:
            continue
        filas.append({
            "Módulo": m["id"],
            "Alimento": f"{db.FASE_EMOJI[m['fase']]} {m['fase'] or 'Vacío'}",
            "Ubicación": m["ubicacion"],
            "Lugar": m["lugar"] or m["granja_destino"] or "—",
            "Lote": m["lote"] or "—",
            "Ciclos": m["ciclos"],
            "Limpio": "Sí" if m["limpio"] else "No",
        })
    st.dataframe(pd.DataFrame(filas), hide_index=True, width="stretch")
    st.caption("🟨 Iniciación · 🟩 Levante · 🟦 Engorde · 🟧 Postura · ⬜ Vacío (el color coincide con la tapa del módulo)")

    st.subheader("Abrir la ficha de un módulo")
    c1, c2 = st.columns([3, 1])
    elegido = c1.selectbox("Módulo", [m["id"] for m in mods], label_visibility="collapsed", key="tablero_sel")
    c2.button("Abrir", on_click=abrir_ficha, args=(elegido,), width="stretch")


def pagina_ficha():
    mods = db.listar_modulos()
    if not mods:
        st.info("Todavía no hay módulos. Créelos en ⚙️ Administración.")
        return
    ids = [m["id"] for m in mods]
    actual = st.session_state.get("modulo_sel", ids[0])
    if actual not in ids:
        st.error(f"El módulo «{actual}» no existe.")
        actual = ids[0]
    mid = st.selectbox("Módulo", ids, index=ids.index(actual), key="ficha_select")
    st.session_state["modulo_sel"] = mid
    m = db.obtener_modulo(mid)

    st.title(f"📦 {mid}")
    st.markdown(fase_badge(m["fase"]), unsafe_allow_html=True)
    a, b = st.columns(2)
    a.metric("Ubicación", m["ubicacion"])
    b.metric("Lugar", m["lugar"] or "—")
    a.metric("Lote", m["lote"] or "—")
    b.metric("Destino", m["granja_destino"] or "—")
    a.metric("Último lavado", m["ultimo_lavado"] or "Nunca")
    b.metric("Ciclos completados", m["ciclos"])
    st.caption(f"Capacidad: {m['capacidad_kg']:g} kg · Llenado: {m['fecha_llenado'] or '—'}")
    if not m["limpio"] and not m["fase"]:
        st.warning("🧼 Este módulo no tiene un lavado completo registrado: no debería llenarse todavía.")

    st.subheader("¿Qué vas a registrar?")
    ucols = st.columns(len(db.ETAPAS))
    for col, (clave, cfg) in zip(ucols, db.ETAPAS.items()):
        if col.button(f"{cfg['emoji']}\n{cfg['titulo']}", key=f"btn_{clave}", width="stretch"):
            st.session_state["etapa_sel"] = clave
    etapa = st.session_state.get("etapa_sel")
    if etapa:
        st.divider()
        formulario_evento(mid, etapa)

    st.subheader("Historial del módulo")
    evs = db.eventos_de(mid)
    if not evs:
        st.caption("Aún no tiene eventos registrados.")
    for e in evs:
        cfg = db.ETAPAS[e["etapa"]]
        with st.expander(f"{cfg['emoji']} {e['fecha']} · {cfg['titulo']} · {e['responsable']}"):
            for c in cfg["campos"]:
                v = e["datos"].get(c["k"])
                if v in (None, "", False) and c["tipo"] != "bool":
                    continue
                if c["tipo"] == "bool":
                    st.write(f"{'✅' if v else '⬜'} {c['label']}")
                else:
                    st.write(f"**{c['label']}:** {v}")
            if e["advertencias"]:
                st.warning(e["advertencias"])


def pagina_registrar():
    st.title("✍️ Registrar evento")
    st.caption("Elija el módulo y la etapa. Lo más fácil es escanear el QR del módulo.")
    mods = db.listar_modulos()
    if not mods:
        st.info("Todavía no hay módulos. Créelos en ⚙️ Administración.")
        return
    ids = [m["id"] for m in mods]
    mid = st.selectbox("Módulo", ids, index=ids.index(st.session_state.get("modulo_sel", ids[0]))
                       if st.session_state.get("modulo_sel") in ids else 0, key="reg_modulo")
    etapa = st.radio("Etapa", list(db.ETAPAS), format_func=lambda k: f"{db.ETAPAS[k]['emoji']} {db.ETAPAS[k]['titulo']}",
                     horizontal=False, key="reg_etapa")
    st.divider()
    formulario_evento(mid, etapa)


def pagina_admin():
    st.title("⚙️ Administración")
    if db.es_postgres():
        st.success("Base de datos permanente conectada: los datos no se pierden si la app se reinicia.")
    else:
        st.warning("Base de datos temporal (archivo local): los datos se pierden si la app se reinicia. "
                   "Para guardarlos de forma permanente conecte una base PostgreSQL (ver LEEME.md).")
    t1, t2, t3, t4 = st.tabs(["Códigos QR", "Módulos", "Plantas y granjas", "Datos"])

    with t1:
        st.markdown("**Dirección pública de la app.** Los QR abren esta dirección. "
                    "Si es `localhost`, solo funcionarán en este mismo equipo.")
        u = st.text_input("URL pública", value=url_publica(), key="url_input")
        st.session_state["url_publica"] = u
        if "localhost" in u or "127.0.0.1" in u:
            st.warning("Esta dirección no es pública: los QR no abrirán desde otros celulares.")
        mods = [m["id"] for m in db.listar_modulos()]
        if mods:
            sel = st.multiselect("Módulos para imprimir", mods, default=mods)
            if sel:
                c1, c2 = st.columns([1, 2])
                c1.image(png_bytes(etiqueta(sel[0])), caption=f"Ejemplo: {sel[0]}")
                c2.write(f"Cada QR apunta a, por ejemplo: `{url_modulo(sel[0])}`")
                c2.download_button("⬇️ Descargar hoja de etiquetas (PNG)", png_bytes(hoja_etiquetas(sel)),
                                   file_name="etiquetas_qr.png", mime="image/png", width="stretch")
                c2.download_button(f"⬇️ Descargar solo {sel[0]}", png_bytes(etiqueta(sel[0])),
                                   file_name=f"{sel[0]}.png", mime="image/png", width="stretch")
        else:
            st.info("Primero cree módulos.")

    with t2:
        c1, c2 = st.columns(2)
        n = c1.number_input("Cantidad de módulos nuevos", 1, 200, 1)
        cap = c2.number_input("Capacidad por módulo (kg)", 1.0, 100.0, 25.0, step=1.0)
        if cap > 23:
            st.caption("Nota: el límite de levantamiento manual NIOSH citado en el proyecto es de 23 kg.")
        if st.button("Crear módulos", type="primary"):
            creados = db.crear_modulos(int(n), float(cap))
            st.success("Se crearon: " + ", ".join(creados))

    with t3:
        c1, c2, c3 = st.columns([2, 1, 1])
        nombre = c1.text_input("Nombre", key="lugar_nombre")
        tipo = c2.selectbox("Tipo", ["planta", "granja"])
        c3.write("")
        c3.write("")
        if c3.button("Agregar"):
            ok, msg = db.agregar_lugar(nombre, tipo)
            (st.success if ok else st.error)(msg)
        st.dataframe(pd.DataFrame(db.listar_lugares()), hide_index=True, width="stretch")

    with t4:
        evs = db.eventos_de()
        if evs:
            df = pd.DataFrame([{"fecha": e["fecha"], "modulo": e["modulo_id"], "etapa": e["etapa"],
                                "responsable": e["responsable"], "datos": str(e["datos"]),
                                "advertencias": e["advertencias"]} for e in evs])
            st.download_button("⬇️ Descargar historial completo (CSV)", df.to_csv(index=False).encode("utf-8-sig"),
                               file_name="trazabilidad_eventos.csv", mime="text/csv")
        st.divider()
        st.markdown("**Reiniciar con datos de ejemplo** (borra todo lo que hay ahora).")
        if st.checkbox("Entiendo que se borrarán todos los datos"):
            if st.button("Borrar y cargar ejemplo"):
                db.borrar_todo()
                db.cargar_ejemplo()
                st.success("Listo: datos de ejemplo cargados.")


# ------------------------------------------------------------------ arranque
if "pagina" not in st.session_state:
    st.session_state["pagina"] = PAGINAS[0]
    mod_qr = st.query_params.get("modulo")
    if mod_qr:  # llegó escaneando un QR
        st.session_state["modulo_sel"] = mod_qr
        st.session_state["pagina"] = PAGINAS[1]

st.sidebar.title("📦 Módulos retornables")
st.sidebar.radio("Ir a", PAGINAS, key="pagina")
st.sidebar.caption("Trazabilidad del alimento avícola: planta → granja → lavado.")

flash = st.session_state.pop("flash", None)
if flash:
    st.success(flash["msg"])
    for a in flash["avisos"]:
        st.warning("⚠️ " + a)

pag = st.session_state["pagina"]
if pag == PAGINAS[0]:
    pagina_tablero()
elif pag == PAGINAS[1]:
    pagina_ficha()
elif pag == PAGINAS[2]:
    pagina_registrar()
else:
    pagina_admin()
