import os, re, hmac, hashlib, unicodedata
from datetime import datetime
import requests
from flask import Flask, request, abort

app = Flask(__name__)

VERIFY_TOKEN    = os.environ.get("VERIFY_TOKEN", "")
APP_SECRET      = os.environ.get("APP_SECRET", "")
ACCESS_TOKEN    = os.environ.get("ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "")
# Números autorizados durante las pruebas, separados por coma (ej. 51925912101,51999999999).
# Si está vacío, responde a todos.
ALLOWED = {n.strip() for n in os.environ.get("ALLOWED_NUMBERS", "").split(",") if n.strip()}
GRAPH = "https://graph.facebook.com/v21.0"

# ----------------------------------------------------------------------------
# TEXTOS
# ----------------------------------------------------------------------------
MENU = (
    "Hola 👋 ¿Qué tipo de venta vas a documentar?\n\n"
    "1️⃣ Contado\n"
    "2️⃣ Financiamiento (próximamente)\n"
    "3️⃣ A pedido (próximamente)\n"
    "4️⃣ Separación en piso (próximamente)\n\n"
    "Responde con el número."
)

PLANTILLA_CONTADO = """VENDEDOR:
RESPONSABLE DE ENTREGA:

COMPRADOR
NOMBRE COMPLETO:
TIPO DE DOCUMENTO (DNI / RUC / CE):
N° DE DOCUMENTO:
ESTADO CIVIL:
CELULAR:
CORREO:

MOTO
MARCA:
MODELO:
AÑO:
COLOR:
CHASIS:
MOTOR:

PRECIO
PRECIO TOTAL:
MODALIDAD (CONTADO / GLOBAL GO):

PAGOS (un pago por línea)
PAGO 1: FECHA / MONTO / MEDIO / N° OP
PAGO 2: FECHA / MONTO / MEDIO / N° OP
PAGO 3: FECHA / MONTO / MEDIO / N° OP

ENTREGA
RECOGE (COMPRADOR / TERCERO):
NOMBRE DEL TERCERO:
DNI DEL TERCERO:
FECHA DE ENTREGA:
LLAVES:
KILOMETRAJE:

EXTRAS
TRÁMITE (LIMA / PROVINCIA):
REGALÍAS:
BONO 500 (SÍ / NO):
OBSERVACIONES:"""

# ----------------------------------------------------------------------------
# UTILIDADES
# ----------------------------------------------------------------------------
def sin_acentos(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")

def norm_label(s):
    s = sin_acentos(s.upper())
    s = re.sub(r"\(.*?\)", "", s)          # quita lo que está entre paréntesis
    s = re.sub(r"[°º\.\*_]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

CAMPOS = {
    "VENDEDOR": "vendedor",
    "RESPONSABLE DE ENTREGA": "responsable", "RESPONSABLE": "responsable",
    "NOMBRE COMPLETO": "nombre", "NOMBRE": "nombre",
    "TIPO DE DOCUMENTO": "tipo_doc", "TIPO DOCUMENTO": "tipo_doc",
    "N DE DOCUMENTO": "num_doc", "NRO DE DOCUMENTO": "num_doc",
    "NUMERO DE DOCUMENTO": "num_doc", "N DOCUMENTO": "num_doc",
    "ESTADO CIVIL": "estado_civil",
    "CELULAR": "celular", "CORREO": "correo",
    "MARCA": "marca", "MODELO": "modelo", "ANO": "anio", "COLOR": "color",
    "CHASIS": "chasis", "MOTOR": "motor",
    "PRECIO TOTAL": "precio", "PRECIO": "precio",
    "MODALIDAD": "modalidad",
    "RECOGE": "recoge",
    "NOMBRE DEL TERCERO": "tercero_nombre",
    "DNI DEL TERCERO": "tercero_dni",
    "FECHA DE ENTREGA": "fecha_entrega",
    "LLAVES": "llaves", "KILOMETRAJE": "km",
    "TRAMITE": "tramite",
    "REGALIAS": "regalias",
    "BONO 500": "bono", "BONO": "bono",
    "OBSERVACIONES": "observaciones", "OBSERVACION": "observaciones",
}
ENCABEZADOS = {"COMPRADOR", "MOTO", "PRECIO", "PAGOS", "ENTREGA", "EXTRAS", "PAGOS UN PAGO POR LINEA"}

def parsear(texto):
    """Devuelve (datos: dict, pagos: list[str])"""
    datos, pagos = {}, []
    ultimo = None
    for linea in texto.replace("\r", "").split("\n"):
        l = linea.strip()
        if not l:
            ultimo = None
            continue
        if ":" in l:
            etiqueta, valor = l.split(":", 1)
            et = norm_label(etiqueta)
            valor = valor.strip()
            m = re.fullmatch(r"PAGO\s*(\d+)", et)
            if m:
                if valor and valor != "-":
                    pagos.append(valor)
                ultimo = None
                continue
            if et in CAMPOS:
                clave = CAMPOS[et]
                datos[clave] = valor
                ultimo = clave
                continue
        if norm_label(l) in ENCABEZADOS:
            ultimo = None
            continue
        if ultimo:  # continuación de un campo en varias líneas (regalías, observaciones)
            datos[ultimo] = (datos.get(ultimo, "") + " " + l).strip()
    return datos, pagos

def a_monto(s):
    s = s.upper().replace("S/", "").replace("$", "").replace(" ", "")
    if not re.search(r"\d", s):
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        partes = s.split(",")
        s = s.replace(",", ".") if len(partes[-1]) == 2 else s.replace(",", "")
    try:
        return round(float(s), 2)
    except ValueError:
        return None

def fmt(m):
    return f"S/ {m:,.2f}"

def parsear_pago(texto):
    """'19/11/2026 / 5300 / TARJETA BCP / 000008' -> dict o None"""
    m = re.match(r"\s*(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})\s*[/|;,\-]?\s*(.*)$", texto)
    if not m:
        return None
    fecha, resto = m.group(1).replace("-", "/").replace(".", "/"), m.group(2)
    partes = [p.strip() for p in re.split(r"\s*[/|;]\s*", resto) if p.strip()]
    if len(partes) < 2:
        return None
    monto = a_monto(partes[0])
    if monto is None:
        return None
    medio = partes[1].upper()
    op = partes[2] if len(partes) > 2 else ""
    if op in ("-", "N/A", "NA"):
        op = ""
    return {"fecha": fecha, "monto": monto, "medio": medio, "op": op}

# --- número a letras (soles) ---------------------------------------------------
_U = ["", "UNO", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO", "NUEVE",
      "DIEZ", "ONCE", "DOCE", "TRECE", "CATORCE", "QUINCE", "DIECISEIS", "DIECISIETE",
      "DIECIOCHO", "DIECINUEVE", "VEINTE", "VEINTIUNO", "VEINTIDOS", "VEINTITRES",
      "VEINTICUATRO", "VEINTICINCO", "VEINTISEIS", "VEINTISIETE", "VEINTIOCHO", "VEINTINUEVE"]
_D = ["", "", "", "TREINTA", "CUARENTA", "CINCUENTA", "SESENTA", "SETENTA", "OCHENTA", "NOVENTA"]
_C = ["", "CIENTO", "DOSCIENTOS", "TRESCIENTOS", "CUATROCIENTOS", "QUINIENTOS",
      "SEISCIENTOS", "SETECIENTOS", "OCHOCIENTOS", "NOVECIENTOS"]

def _menos_mil(n):
    if n == 0:
        return ""
    if n == 100:
        return "CIEN"
    c, r = divmod(n, 100)
    out = _C[c]
    if r:
        if r < 30:
            out += (" " if out else "") + _U[r]
        else:
            d, u = divmod(r, 10)
            out += (" " if out else "") + _D[d] + (" Y " + _U[u] if u else "")
    return out

def numero_a_letras(valor):
    entero = int(valor)
    cent = int(round((valor - entero) * 100))
    if entero == 0:
        txt = "CERO"
    else:
        miles, resto = divmod(entero, 1000)
        txt = ""
        if miles:
            if miles == 1:
                txt = "MIL"
            else:
                m = _menos_mil(miles)
                m = re.sub(r"\bUNO$", "UN", m)
                m = re.sub(r"\bVEINTIUNO$", "VEINTIUN", m)
                txt = m + " MIL"
        if resto:
            txt += (" " if txt else "") + _menos_mil(resto)
    if entero == 1:
        txt = "UN"
    moneda = "SOL" if entero == 1 and cent == 0 else "SOLES"
    return f"{txt} CON {cent:02d}/100 {moneda}" if cent else f"{txt} {moneda}"

# --- marcas -------------------------------------------------------------------
MARCAS_SIN_GARANTIA_PROPIA = {"SUZUKI", "HAOJUE", "HAOUJUE", "CFMOTO"}

def marca_clave(m):
    return re.sub(r"[^A-Z]", "", sin_acentos(m.upper()))

# ----------------------------------------------------------------------------
# REVISIÓN DE LA PLANTILLA (PRUEBA 1: solo lectura, sin PDF)
# ----------------------------------------------------------------------------
OBLIGATORIOS = [
    ("vendedor", "VENDEDOR"), ("responsable", "RESPONSABLE DE ENTREGA"),
    ("nombre", "NOMBRE COMPLETO"), ("tipo_doc", "TIPO DE DOCUMENTO"),
    ("num_doc", "N° DE DOCUMENTO"), ("estado_civil", "ESTADO CIVIL"),
    ("celular", "CELULAR"), ("marca", "MARCA"), ("modelo", "MODELO"),
    ("anio", "AÑO"), ("color", "COLOR"), ("chasis", "CHASIS"), ("motor", "MOTOR"),
    ("precio", "PRECIO TOTAL"), ("modalidad", "MODALIDAD"), ("recoge", "RECOGE"),
    ("llaves", "LLAVES"), ("km", "KILOMETRAJE"), ("tramite", "TRÁMITE"),
]

def revisar_contado(texto):
    d, lineas_pago = parsear(texto)
    faltan, avisos = [], []

    for clave, etiqueta in OBLIGATORIOS:
        if not d.get(clave):
            faltan.append(etiqueta)

    # tipo de documento
    tipo = sin_acentos(d.get("tipo_doc", "").upper())
    if tipo:
        if "RUC" in tipo: tipo = "RUC"
        elif "CE" == tipo or "EXTRANJ" in tipo or tipo.startswith("C.E"): tipo = "CE"
        elif "DNI" in tipo: tipo = "DNI"
        else:
            avisos.append(f"TIPO DE DOCUMENTO '{d['tipo_doc']}' no es DNI, RUC ni CE")
        num = re.sub(r"\D", "", d.get("num_doc", ""))
        if tipo == "DNI" and num and len(num) != 8:
            avisos.append(f"El DNI debería tener 8 dígitos (tiene {len(num)})")
        if tipo == "RUC" and num and len(num) != 11:
            avisos.append(f"El RUC debería tener 11 dígitos (tiene {len(num)})")
    cel = re.sub(r"\D", "", d.get("celular", ""))
    if cel and len(cel) not in (9, 11):
        avisos.append(f"El celular tiene {len(cel)} dígitos (se esperan 9)")
    ch = re.sub(r"\s", "", d.get("chasis", ""))
    if ch and len(ch) != 17:
        avisos.append(f"El chasis tiene {len(ch)} caracteres (normalmente 17)")
    if d.get("correo") and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", d["correo"]):
        avisos.append("El correo no parece válido")

    # modalidad / recoge
    mod = sin_acentos(d.get("modalidad", "").upper()).replace(" ", "")
    if mod:
        if mod.startswith("CONTADO"): mod = "CONTADO"
        elif "GLOBAL" in mod: mod = "GLOBAL GO"
        else:
            avisos.append(f"MODALIDAD '{d['modalidad']}' no es CONTADO ni GLOBAL GO")
    rec = sin_acentos(d.get("recoge", "").upper())
    if rec:
        if rec.startswith("TERCERO"):
            rec = "TERCERO"
            if not d.get("tercero_nombre"): faltan.append("NOMBRE DEL TERCERO")
            if not d.get("tercero_dni"): faltan.append("DNI DEL TERCERO")
        elif rec.startswith("COMPRADOR"):
            rec = "COMPRADOR"
        else:
            avisos.append(f"RECOGE '{d['recoge']}' no es COMPRADOR ni TERCERO")

    # precio y pagos
    precio = a_monto(d.get("precio", "")) if d.get("precio") else None
    if d.get("precio") and precio is None:
        avisos.append(f"No pude leer el PRECIO TOTAL '{d['precio']}'")
    pagos = []
    if not lineas_pago:
        faltan.append("PAGO 1 (fecha / monto / medio / N° OP)")
    for i, lp in enumerate(lineas_pago, 1):
        p = parsear_pago(lp)
        if not p:
            avisos.append(f"No pude leer PAGO {i}: '{lp}'. Formato: 19/11/2026 / 5300 / YAPE / 123456")
            continue
        if p["medio"] != "EFECTIVO" and "EFECTIVO" not in p["medio"] and not p["op"]:
            faltan.append(f"N° DE OPERACIÓN del PAGO {i} ({p['medio']})")
        pagos.append(p)
    total_pagado = round(sum(p["monto"] for p in pagos), 2)

    # --- armar respuesta ---
    out = ["🧪 *PRUEBA 1 – Lectura de datos (Contado)*", "_No se generó ningún PDF; solo reviso lo que entendí._", ""]
    out.append("*VENTA*")
    out.append(f"Vendedor: {d.get('vendedor') or '—'}")
    out.append(f"Responsable de entrega: {d.get('responsable') or '—'}")
    out.append("")
    out.append("*COMPRADOR*")
    out.append(f"Nombre: {d.get('nombre') or '—'}")
    out.append(f"Documento: {tipo or d.get('tipo_doc') or '—'} {d.get('num_doc') or ''}".strip())
    out.append(f"Estado civil: {d.get('estado_civil') or '—'}")
    out.append(f"Celular: {d.get('celular') or '—'}")
    out.append(f"Correo: {d.get('correo') or '(no indicado)'}")
    out.append("")
    out.append("*MOTO*")
    out.append(f"{d.get('marca') or '—'} {d.get('modelo') or ''} {d.get('anio') or ''} – {d.get('color') or '—'}".strip())
    out.append(f"Chasis: {d.get('chasis') or '—'}")
    out.append(f"Motor: {d.get('motor') or '—'}")
    out.append("")
    out.append("*PRECIO Y PAGOS*")
    if precio is not None:
        out.append(f"Precio total: {fmt(precio)}")
        out.append(f"En letras: {numero_a_letras(precio)}")
    out.append(f"Modalidad: {mod or d.get('modalidad') or '—'}")
    for i, p in enumerate(pagos, 1):
        op = f" – OP {p['op']}" if p["op"] else ""
        out.append(f"{i}) {p['fecha']} – {fmt(p['monto'])} – {p['medio']}{op}")
    if pagos:
        out.append(f"Total pagado: {fmt(total_pagado)}")
        if precio is not None:
            dif = round(precio - total_pagado, 2)
            if dif == 0:
                out.append("✅ Los pagos coinciden con el precio.")
            elif dif > 0:
                out.append(f"⚠️ Faltan {fmt(dif)} para completar el precio.")
            else:
                out.append(f"⚠️ Los pagos superan el precio por {fmt(-dif)}.")
    out.append("")
    out.append("*ENTREGA*")
    out.append(f"Recoge: {rec or d.get('recoge') or '—'}")
    if rec == "TERCERO":
        out.append(f"Tercero: {d.get('tercero_nombre') or '—'} (DNI {d.get('tercero_dni') or '—'})")
    out.append(f"Fecha de entrega: {d.get('fecha_entrega') or '(no indicada)'}")
    out.append(f"Llaves: {d.get('llaves') or '—'}   Kilometraje: {d.get('km') or '—'}")
    out.append("")
    out.append("*EXTRAS*")
    out.append(f"Trámite: {d.get('tramite') or '—'}")
    out.append(f"Regalías: {d.get('regalias') or '(ninguna)'}")
    out.append(f"Bono 500: {d.get('bono') or '(no indicado)'}")
    out.append(f"Observaciones: {d.get('observaciones') or '(ninguna)'}")
    out.append("")
    if d.get("marca"):
        if marca_clave(d["marca"]) in MARCAS_SIN_GARANTIA_PROPIA:
            out.append("*Documentos que se generarían (3):* Contrato, Checklist de revisión, Acta de entrega")
        else:
            out.append("*Documentos que se generarían (4):* Contrato, Garantía, Checklist de revisión, Acta de entrega")
        out.append("")
    if faltan:
        out.append("❌ *FALTA COMPLETAR:*")
        out += [f"• {x}" for x in faltan]
        out.append("")
    if avisos:
        out.append("⚠️ *REVISA:*")
        out += [f"• {x}" for x in avisos]
        out.append("")
    if not faltan and not avisos:
        out.append("✅ Todo lo obligatorio está completo.")
    out.append("Si algo está mal, corrige la plantilla y envíala de nuevo.")
    return "\n".join(out)

# ----------------------------------------------------------------------------
# WHATSAPP
# ----------------------------------------------------------------------------
def enviar(to, texto):
    # WhatsApp admite hasta 4096 caracteres por mensaje
    for i in range(0, len(texto), 3800):
        r = requests.post(
            f"{GRAPH}/{PHONE_NUMBER_ID}/messages",
            headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
            json={"messaging_product": "whatsapp", "to": to, "type": "text",
                  "text": {"body": texto[i:i + 3800]}},
            timeout=15,
        )
        print("envio:", r.status_code, r.text[:150])

def firma_valida(req):
    if not APP_SECRET:
        return True
    recibida = req.headers.get("X-Hub-Signature-256", "")
    esperada = "sha256=" + hmac.new(APP_SECRET.encode(), req.get_data(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(recibida, esperada)

vistos = []  # ids de mensajes ya procesados (evita duplicados por reintentos de Meta)

def parece_plantilla(texto):
    return len(re.findall(r"^\s*[^\n:]{2,45}:", texto, flags=re.M)) >= 5 and "NOMBRE" in sin_acentos(texto.upper())

def atender(num, texto):
    t = sin_acentos(texto.strip().upper())
    if parece_plantilla(texto):
        enviar(num, revisar_contado(texto))
    elif t in ("1", "CONTADO"):
        enviar(num, "Perfecto: venta al *contado*. Copia el siguiente mensaje, complétalo y envíamelo 👇")
        enviar(num, PLANTILLA_CONTADO)
    elif t in ("2", "3", "4"):
        enviar(num, "Ese tipo de venta aún no está activo en las pruebas. Por ahora prueba con *1* (Contado).")
    else:
        enviar(num, MENU)

@app.get("/")
def home():
    return "Bot Leo Motos activo ✅ (Prueba 1)"

@app.get("/webhook")
def verificar():
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge", ""), 200
    abort(403)

@app.post("/webhook")
def recibir():
    if not firma_valida(request):
        abort(403)
    data = request.get_json(silent=True) or {}
    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                for m in change.get("value", {}).get("messages", []):
                    if m.get("id") in vistos:
                        continue
                    vistos.append(m.get("id"))
                    del vistos[:-200]
                    num = m.get("from", "")
                    if ALLOWED and num not in ALLOWED:
                        print("ignorado (no autorizado):", num)
                        continue
                    if m.get("type") != "text":
                        enviar(num, "Por ahora solo leo mensajes de texto 🙂")
                        continue
                    atender(num, m["text"]["body"])
    except Exception as e:
        print("error:", repr(e))
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
