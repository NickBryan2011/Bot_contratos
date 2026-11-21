# -*- coding: utf-8 -*-
import os, re, hmac, hashlib
import requests
from flask import Flask, request, abort

import documentos as D
from documentos import sin_acentos, numero_a_letras

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
# MENÚ Y PLANTILLAS
# ----------------------------------------------------------------------------
MENU = (
    "Hola 👋 ¿Qué vas a documentar?\n\n"
    "1️⃣ Venta al contado (entrega de la moto)\n"
    "2️⃣ Separación (venta al contado, pago parcial)\n"
    "3️⃣ Financiamiento – inicial (separación)\n"
    "4️⃣ Financiamiento – entrega final (recoge la moto)\n\n"
    "Responde con el número."
)

_COMPRADOR = """COMPRADOR
NOMBRE COMPLETO:
TIPO DE DOCUMENTO (DNI / RUC / CE):
N° DE DOCUMENTO:
ESTADO CIVIL:
CELULAR:
CORREO:
{direccion}"""

_MOTO = """MOTO
MARCA:
MODELO:
AÑO:
COLOR:
CHASIS:
MOTOR:"""

_ENTREGA = """ENTREGA
RECOGE (COMPRADOR / TERCERO):
NOMBRE DEL TERCERO:
DNI DEL TERCERO:
FECHA DE ENTREGA:
LLAVES:
KILOMETRAJE:

EXTRAS
REGALÍAS (o ESTANDAR):
OBSERVACIONES:"""

PLANTILLA_CONTADO = (
    "TIPO: CONTADO\nVENDEDOR:\nRESPONSABLE DE ENTREGA:\n\n"
    + _COMPRADOR.format(direccion="").rstrip() + "\n\n" + _MOTO + "\n\n"
    "PRECIO\nPRECIO TOTAL:\n\n"
    "PAGOS (un pago por línea)\nPAGO 1: FECHA / MONTO / MEDIO / N° OP\nPAGO 2: FECHA / MONTO / MEDIO / N° OP\n"
    "PAGO 3: FECHA / MONTO / MEDIO / N° OP\n\n" + _ENTREGA
)

PLANTILLA_FIN_FINAL = (
    "TIPO: FINANCIAMIENTO FINAL\nVENDEDOR:\nRESPONSABLE DE ENTREGA:\n\n"
    + _COMPRADOR.format(direccion="DIRECCIÓN:") + "\n\n" + _MOTO + "\n\n"
    "PRECIO\nPRECIO TOTAL:\n\n"
    "PAGOS (incluye el DESEMBOLSO GLOBAL GO)\nPAGO 1: FECHA / MONTO / MEDIO / N° OP\n"
    "PAGO 2: FECHA / MONTO / MEDIO / N° OP\nPAGO 3: FECHA / MONTO / DESEMBOLSO GLOBAL GO / -\n\n" + _ENTREGA
)

_SEPARACION = """{tipo}
VENDEDOR:
FECHA (vacía = hoy):

COMPRADOR
NOMBRE COMPLETO:
TIPO DE DOCUMENTO (DNI / RUC / CE):
N° DE DOCUMENTO:

MOTO
MARCA:
MODELO:
AÑO:
COLOR:
PRECIO DEL VEHÍCULO:
MOTO EN PISO (SÍ / NO):
PLAZO ESTIMADO DE ENTREGA (solo si NO está en piso):

PAGOS (lo entregado como separación)
PAGO 1: FECHA / MONTO / MEDIO / N° OP
PAGO 2: FECHA / MONTO / MEDIO / N° OP"""
PLANTILLA_SEPARACION = _SEPARACION.format(tipo="TIPO: SEPARACIÓN")
PLANTILLA_FIN_INICIAL = _SEPARACION.format(tipo="TIPO: FINANCIAMIENTO INICIAL")

PLANTILLAS = {"1": PLANTILLA_CONTADO, "2": PLANTILLA_SEPARACION,
              "3": PLANTILLA_FIN_INICIAL, "4": PLANTILLA_FIN_FINAL}
NOMBRES_FLUJO = {"contado": "Venta al contado", "separacion": "Separación (contado)",
                 "fin_inicial": "Financiamiento – inicial", "fin_final": "Financiamiento – entrega final"}

# ----------------------------------------------------------------------------
# LECTURA DE LA PLANTILLA
# ----------------------------------------------------------------------------
def norm_label(s):
    s = sin_acentos(s.upper())
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r"[°º\.\*_]", "", s)
    return re.sub(r"\s+", " ", s).strip()

CAMPOS = {
    "TIPO": "tipo_venta",
    "VENDEDOR": "vendedor",
    "RESPONSABLE DE ENTREGA": "responsable", "RESPONSABLE": "responsable",
    "FECHA": "fecha",
    "NOMBRE COMPLETO": "nombre", "NOMBRE": "nombre",
    "TIPO DE DOCUMENTO": "tipo_doc", "TIPO DOCUMENTO": "tipo_doc",
    "N DE DOCUMENTO": "num_doc", "NRO DE DOCUMENTO": "num_doc",
    "NUMERO DE DOCUMENTO": "num_doc", "N DOCUMENTO": "num_doc",
    "ESTADO CIVIL": "estado_civil",
    "CELULAR": "celular", "CORREO": "correo", "DIRECCION": "direccion",
    "MARCA": "marca", "MODELO": "modelo", "ANO": "anio", "COLOR": "color",
    "CHASIS": "chasis", "MOTOR": "motor",
    "PRECIO TOTAL": "precio", "PRECIO": "precio", "PRECIO DEL VEHICULO": "precio",
    "MODALIDAD": "modalidad",
    "MOTO EN PISO": "en_piso",
    "PLAZO ESTIMADO DE ENTREGA": "plazo", "PLAZO DE ENTREGA": "plazo",
    "RECOGE": "recoge",
    "NOMBRE DEL TERCERO": "tercero_nombre", "DNI DEL TERCERO": "tercero_dni",
    "FECHA DE ENTREGA": "fecha_entrega",
    "LLAVES": "llaves", "KILOMETRAJE": "km",
    "TRAMITE": "tramite",
    "REGALIAS": "regalias",
    "BONO 500": "bono", "BONO": "bono",
    "OBSERVACIONES": "observaciones", "OBSERVACION": "observaciones",
}
ENCABEZADOS = {"COMPRADOR", "MOTO", "PRECIO", "PAGOS", "ENTREGA", "EXTRAS"}

def parsear(texto):
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
            if re.fullmatch(r"PAGO\s*\d+", et):
                if valor and valor != "-":
                    pagos.append(valor)
                ultimo = None
                continue
            if et in CAMPOS:
                datos[CAMPOS[et]] = valor
                ultimo = CAMPOS[et]
                continue
        n = norm_label(l)
        if n in ENCABEZADOS or n.startswith("PAGOS"):
            ultimo = None
            continue
        if ultimo:
            datos[ultimo] = (datos.get(ultimo, "") + "\n" + l).strip()
    return datos, pagos

def a_monto(s):
    s = s.upper().replace("S/", "").replace("$", "").replace(" ", "")
    if not re.search(r"\d", s):
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".") if len(s.split(",")[-1]) == 2 else s.replace(",", "")
    try:
        return round(float(s), 2)
    except ValueError:
        return None

def fmt(m):
    return f"S/ {m:,.2f}"

def parsear_pago(texto):
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
    op = partes[2] if len(partes) > 2 else ""
    return {"fecha": fecha, "monto": monto, "medio": partes[1].upper(),
            "op": "" if op in ("-", "N/A", "NA") else op}

MARCAS_SIN_GARANTIA_PROPIA = {"SUZUKI", "HAOJUE", "HAOUJUE", "CFMOTO"}

def lleva_garantia(marca):
    return re.sub(r"[^A-Z]", "", sin_acentos(marca.upper())) not in MARCAS_SIN_GARANTIA_PROPIA

# ----------------------------------------------------------------------------
# REVISIÓN POR TIPO DE VENTA
# ----------------------------------------------------------------------------
COMUNES = [("vendedor", "VENDEDOR"), ("nombre", "NOMBRE COMPLETO"), ("tipo_doc", "TIPO DE DOCUMENTO"),
           ("num_doc", "N° DE DOCUMENTO"), ("marca", "MARCA"), ("modelo", "MODELO"), ("color", "COLOR"),
           ("precio", "PRECIO")]
ENTREGA = [("responsable", "RESPONSABLE DE ENTREGA"), ("estado_civil", "ESTADO CIVIL"), ("celular", "CELULAR"),
           ("anio", "AÑO"), ("chasis", "CHASIS"), ("motor", "MOTOR"), ("recoge", "RECOGE"),
           ("llaves", "LLAVES"), ("km", "KILOMETRAJE")]
OBLIG = {
    "contado": COMUNES + ENTREGA,
    "fin_final": COMUNES + ENTREGA + [("direccion", "DIRECCIÓN")],
    "separacion": COMUNES,
    "fin_inicial": COMUNES,
}

def detectar_flujo(d):
    t = sin_acentos(d.get("tipo_venta", "").upper())
    if "INICIAL" in t: return "fin_inicial"
    if "FINAL" in t or "FINANCI" in t: return "fin_final"
    if "SEPARAC" in t: return "separacion"
    if "CONTADO" in t: return "contado"
    return "separacion" if "en_piso" in d else "contado"

def revisar(texto):
    d, lineas_pago = parsear(texto)
    flujo = detectar_flujo(d)
    faltan, avisos = [], []

    en_piso = None
    if flujo in ("separacion", "fin_inicial"):
        v = sin_acentos(d.get("en_piso", "").upper()).strip()
        if v in ("SI", "S"): en_piso = True
        elif v in ("NO", "N"): en_piso = False
        else: faltan.append("MOTO EN PISO (SÍ / NO)")
        if en_piso is True and not d.get("anio"): faltan.append("AÑO")
        if en_piso is False and not d.get("plazo"): faltan.append("PLAZO ESTIMADO DE ENTREGA")
        if d.get("fecha") and not D.parsear_fecha(d["fecha"]):
            avisos.append(f"FECHA '{d['fecha']}' no se entiende; usaré la de hoy. Formato: 19/11/2026")

    for clave, etiqueta in OBLIG[flujo]:
        if not d.get(clave):
            faltan.append(etiqueta)

    # documento
    tipo = sin_acentos(d.get("tipo_doc", "").upper())
    if tipo:
        if "RUC" in tipo: tipo = "RUC"
        elif tipo == "CE" or "EXTRANJ" in tipo or tipo.startswith("C.E"): tipo = "CE"
        elif "DNI" in tipo: tipo = "DNI"
        else: avisos.append(f"TIPO DE DOCUMENTO '{d['tipo_doc']}' no es DNI, RUC ni CE")
        num = re.sub(r"\D", "", d.get("num_doc", ""))
        if tipo == "DNI" and num and len(num) != 8: avisos.append(f"El DNI debería tener 8 dígitos (tiene {len(num)})")
        if tipo == "RUC" and num and len(num) != 11: avisos.append(f"El RUC debería tener 11 dígitos (tiene {len(num)})")
    cel = re.sub(r"\D", "", d.get("celular", ""))
    if cel and len(cel) not in (9, 11): avisos.append(f"El celular tiene {len(cel)} dígitos (se esperan 9)")
    ch = re.sub(r"\s", "", d.get("chasis", ""))
    if ch and len(ch) != 17: avisos.append(f"El chasis tiene {len(ch)} caracteres (normalmente 17)")
    if d.get("correo") and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", d["correo"]):
        avisos.append("El correo no parece válido")

    # modalidad / recoge
    modalidad = "GLOBAL GO" if flujo in ("fin_final", "fin_inicial") else "CONTADO"
    if flujo == "contado":
        mod = sin_acentos(d.get("modalidad", "CONTADO").upper()).replace(" ", "")
        modalidad = "GLOBAL GO" if "GLOBAL" in mod else "CONTADO"
    rec = sin_acentos(d.get("recoge", "").upper())
    if flujo in ("contado", "fin_final") and rec:
        if rec.startswith("TERCERO"):
            rec = "TERCERO"
            if not d.get("tercero_nombre"): faltan.append("NOMBRE DEL TERCERO")
            if not d.get("tercero_dni"): faltan.append("DNI DEL TERCERO")
        elif rec.startswith("COMPRADOR"):
            rec = "COMPRADOR"
        else:
            avisos.append(f"RECOGE '{d['recoge']}' no es COMPRADOR ni TERCERO")

    # precio y pagos
    precio = a_monto(d["precio"]) if d.get("precio") else None
    if d.get("precio") and precio is None:
        faltan.append(f"PRECIO ilegible: '{d['precio']}'")
    pagos = []
    if not lineas_pago:
        faltan.append("PAGO 1 (fecha / monto / medio / N° OP)")
    for i, lp in enumerate(lineas_pago, 1):
        p = parsear_pago(lp)
        if not p:
            faltan.append(f"PAGO {i} ilegible: '{lp}'. Formato: 19/11/2026 / 5300 / YAPE / 123456")
            continue
        if "EFECTIVO" not in p["medio"] and "DESEMBOLSO" not in p["medio"] and not p["op"]:
            faltan.append(f"N° DE OPERACIÓN del PAGO {i} ({p['medio']})")
        pagos.append(p)
    total = round(sum(p["monto"] for p in pagos), 2)

    # documentos que se enviarán
    marca = d.get("marca", "")
    docs = []
    if flujo == "contado":
        docs = ["contrato", "checklist", "acta"] + (["garantia"] if marca and lleva_garantia(marca) else [])
    elif flujo == "fin_final":
        docs = ["contrato", "contrato_gg", "acta", "checklist"] + (["garantia"] if marca and lleva_garantia(marca) else [])
    elif flujo == "separacion":
        docs = ["sep_piso"] if en_piso else ["sep_pedido"]
    elif flujo == "fin_inicial":
        docs = ["inicial_gg", "sep_piso" if en_piso else "sep_pedido"]

    # resumen
    nombres = {k: v[0] for k, v in DOCS.items()}
    out = [f"🧪 *PRUEBA 3 – {NOMBRES_FLUJO[flujo]}*", ""]
    out.append(f"*Comprador:* {d.get('nombre') or '—'} ({tipo or d.get('tipo_doc') or '—'} {d.get('num_doc') or ''})".replace(" )", ")"))
    moto = " ".join(x for x in [d.get("marca"), d.get("modelo"), d.get("anio")] if x)
    out.append(f"*Moto:* {moto or '—'} – {d.get('color') or '—'}")
    if precio is not None:
        out.append(f"*Precio:* {fmt(precio)} ({numero_a_letras(precio)})")
    if pagos:
        out.append(f"*Pagos:* {len(pagos)} = {fmt(total)}")
        if precio is not None and flujo in ("contado", "fin_final"):
            dif = round(precio - total, 2)
            if dif == 0: out.append("✅ Los pagos coinciden con el precio.")
            elif dif > 0: out.append(f"⚠️ Faltan {fmt(dif)} para completar el precio.")
            else: out.append(f"⚠️ Los pagos superan el precio por {fmt(-dif)}.")
        if flujo in ("separacion", "fin_inicial") and precio is not None and total > precio:
            avisos.append("Lo entregado como separación supera el precio del vehículo")
    if flujo in ("separacion", "fin_inicial") and en_piso is not None:
        out.append(f"*Moto en piso:* {'Sí' if en_piso else 'No (a pedido)'}")
    if docs:
        out.append("")
        out.append(f"*Documentos ({len(docs)}):* " + ", ".join(nombres[x] for x in docs))
    if "inicial_gg" in docs:
        out.append("⚠️ _“Inicial Global Go” aún no está configurado; se enviarán solo los demás._")
    if faltan:
        out += ["", "❌ *FALTA COMPLETAR:*"] + [f"• {x}" for x in faltan]
        out.append("\nNo genero los PDF hasta completar lo obligatorio. Corrige la plantilla y envíala de nuevo.")
    else:
        if avisos:
            out += ["", "⚠️ *REVISA:*"] + [f"• {x}" for x in avisos]
        out.append("\n✅ Datos completos. Generando los PDF…")
    ctx = {"d": d, "pagos": pagos, "precio": precio, "tipo": tipo, "modalidad": modalidad,
           "recoge": rec, "monto_sep": total, "en_piso": en_piso}
    return {"texto": "\n".join(out), "ctx": ctx, "faltan": faltan, "docs": docs}

DOCS = {
    "contrato":    ("Contrato", D.contrato_pdf),
    "checklist":   ("Checklist", D.checklist_pdf),
    "acta":        ("Acta de entrega", D.acta_pdf),
    "garantia":    ("Garantía", D.garantia_pdf),
    "contrato_gg": ("Contrato Global Go", D.contrato_globalgo_pdf),
    "sep_piso":    ("Separación en piso", D.separacion_piso_pdf),
    "sep_pedido":  ("Separación a pedido", D.separacion_pedido_pdf),
    "inicial_gg":  ("Inicial Global Go", None),
}

# ----------------------------------------------------------------------------
# WHATSAPP
# ----------------------------------------------------------------------------
def enviar(to, texto):
    for i in range(0, len(texto), 3800):
        r = requests.post(
            f"{GRAPH}/{PHONE_NUMBER_ID}/messages",
            headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
            json={"messaging_product": "whatsapp", "to": to, "type": "text",
                  "text": {"body": texto[i:i + 3800]}},
            timeout=15,
        )
        print("envio:", r.status_code, r.text[:120])

def enviar_pdf(to, pdf_bytes, nombre_archivo, caption=""):
    r = requests.post(
        f"{GRAPH}/{PHONE_NUMBER_ID}/media",
        headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
        data={"messaging_product": "whatsapp", "type": "application/pdf"},
        files={"file": (nombre_archivo, pdf_bytes, "application/pdf")},
        timeout=30,
    )
    print("media:", r.status_code, r.text[:120])
    media_id = r.json().get("id")
    if not media_id:
        raise RuntimeError("No se pudo subir el PDF: " + r.text[:200])
    r2 = requests.post(
        f"{GRAPH}/{PHONE_NUMBER_ID}/messages",
        headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
        json={"messaging_product": "whatsapp", "to": to, "type": "document",
              "document": {"id": media_id, "filename": nombre_archivo, "caption": caption}},
        timeout=15,
    )
    print("envio doc:", r2.status_code, r2.text[:120])

def firma_valida(req):
    if not APP_SECRET:
        return True
    recibida = req.headers.get("X-Hub-Signature-256", "")
    esperada = "sha256=" + hmac.new(APP_SECRET.encode(), req.get_data(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(recibida, esperada)

vistos = []

def parece_plantilla(texto):
    return len(re.findall(r"^\s*[^\n:]{2,45}:", texto, flags=re.M)) >= 5 and "NOMBRE" in sin_acentos(texto.upper())

def atender(num, texto):
    t = sin_acentos(texto.strip().upper())
    if parece_plantilla(texto):
        r = revisar(texto)
        enviar(num, r["texto"])
        if r["faltan"]:
            return
        nombre = re.sub(r"[^A-Za-z0-9]+", "_", sin_acentos(r["ctx"]["d"].get("nombre", "cliente"))).strip("_")[:35]
        enviados = 0
        for clave in r["docs"]:
            etiqueta, fn = DOCS[clave]
            if fn is None:
                continue
            try:
                pdf = fn(r["ctx"])
                enviar_pdf(num, pdf, f"{etiqueta.replace(' ', '_')}_{nombre}.pdf", etiqueta)
                enviados += 1
            except Exception as e:
                print("error pdf", clave, repr(e))
                enviar(num, f"⚠️ No pude generar *{etiqueta}* por un error interno. Avísale a Nick para revisar los logs.")
        if enviados:
            enviar(num, f"✅ Listo: {enviados} documento(s) enviados. Revísalos antes de usarlos (modo prueba).")
    elif t in PLANTILLAS or t in ("CONTADO", "SEPARACION"):
        clave = t if t in PLANTILLAS else {"CONTADO": "1", "SEPARACION": "2"}[t]
        enviar(num, "Perfecto. Copia el siguiente mensaje, complétalo y envíamelo 👇")
        enviar(num, PLANTILLAS[clave])
    else:
        enviar(num, MENU)

@app.get("/")
def home():
    return "Bot Leo Motos activo ✅ (Prueba 3)"

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
