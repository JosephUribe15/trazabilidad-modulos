# Trazabilidad de módulos retornables de alimento avícola

Prototipo en Python (Streamlit). Cada módulo plástico tiene un código QR que abre su ficha: allí se ve qué
alimento lleva, dónde está y todo su historial, y se pueden registrar las etapas del ciclo.

## Archivos
- `app.py`: la interfaz.
- `db.py`: las reglas (campos de cada etapa, cambios de estado, advertencias) y el acceso a la base de datos.
- `requirements.txt`: librerías necesarias.

## Qué hace
- **Tablero:** módulos en planta, en tránsito, en granja y en lavado, con filtros por alimento y ubicación.
- **Ficha del módulo (lo que abre el QR):** alimento con su color, lote, ubicación, destino, último lavado,
  ciclos e historial completo.
- **Registro guiado por etapa:** llenado, despacho, recepción, recolección y lavado. Cada campo explica qué
  escribir; los obligatorios llevan asterisco; fecha y hora se llenan solas.
- **Alertas automáticas:** precinto roto, módulo dañado, destino distinto, llenar sin lavado completo, etc.
- **Administración:** crear módulos, plantas y granjas; generar e imprimir etiquetas QR; descargar el historial (CSV).

## Ciclo de cada módulo
Llenado (planta) → Despacho (en tránsito) → Recepción (en granja) → Recolección (en tránsito) → Lavado (planta, limpio)

## Dos formas de usarlo

### A) Prueba rápida en Google Colab (temporal)
Abra `lanzar_en_colab.ipynb` en Colab y ejecute las celdas. La dirección cambia cada vez y los datos se pierden
si la sesión se reinicia. Sirve para probar, no para QR definitivos.

### B) Versión permanente: dirección fija y datos que no se pierden
Se necesitan tres cuentas gratuitas (sin tarjeta): Neon (base de datos), GitHub (guarda el código) y
Streamlit Community Cloud (publica la app). Tarda unos 15 minutos.

1. **Base de datos (Neon).** En neon.com cree una cuenta y un proyecto nuevo (nombre: trazabilidad). En el panel
   pulse **Connect** y copie la "connection string" (empieza por `postgresql://`). Es como una contraseña: no la
   comparta ni la suba a GitHub.
2. **Código (GitHub).** En github.com cree una cuenta y un repositorio nuevo (por ejemplo `trazabilidad-modulos`).
   Pulse "uploading an existing file" y arrastre `app.py`, `db.py`, `requirements.txt` y `LEEME.md`
   (los archivos sueltos, no el .zip). Pulse **Commit changes**.
3. **Publicar (Streamlit Cloud).** En share.streamlit.io entre con su cuenta de GitHub, pulse **Create app**,
   elija el repositorio, la rama `main` y el archivo `app.py`. En **App URL** escriba un nombre propio
   (por ejemplo `trazabilidad-modulos`): la dirección quedará `https://trazabilidad-modulos.streamlit.app`.
4. **Secretos.** En **Advanced settings → Secrets** pegue (con sus datos):
   ```
   DATABASE_URL = "postgresql://...(la que copió de Neon)..."
   PUBLIC_URL = "https://trazabilidad-modulos.streamlit.app"
   ```
   y pulse **Deploy**. Si el nombre de la dirección ya existe y debe cambiarlo, actualice `PUBLIC_URL` en
   Settings → Secrets de la app.
5. **Comprobar.** Abra la app → Administración. Debe decir en verde "Base de datos permanente conectada" y la URL
   pública debe ser la suya. Si no quiere los datos de ejemplo: Administración → Datos → borrar. Cree sus módulos
   y descargue la hoja de etiquetas QR.

La dirección no cambia aunque se reinicie la app, así que los QR impresos siguen sirviendo.

## Cosas a tener en cuenta
- Streamlit Community Cloud pone a dormir las apps tras un tiempo sin visitas (la comunidad reporta unas 12 horas;
  puede cambiar). Quien escanee entonces verá un botón "Yes, get this app back up!" y la app tarda un momento en
  despertar. La dirección y los datos siguen igual. Antes de una presentación, abra la app unas horas antes.
- Si la conexión con la base falla y el mensaje menciona `channel_binding`, borre `&channel_binding=require` del
  final de la dirección copiada de Neon.
- Es un prototipo: no tiene inicio de sesión, cualquiera con el enlace puede ver y registrar.
- Los datos de ejemplo (granjas, lotes, módulos) son inventados.
