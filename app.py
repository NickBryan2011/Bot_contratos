# -*- coding: utf-8 -*-
import os, re, hmac, hashlib
import requests
from flask import Flask, request, abort

import time
import documentos as D
import cotizacion as COT
import simulador as SIM
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
    "4️⃣ Financiamiento – entrega final (recoge la moto)\n"
    "5️⃣ Cotización (moto, moto + accesorios o accesorios)\n"
    "6️⃣ Simular cuotas (Global Go)\n\n"
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


_COT_CABECERA = """FECHA (vacía = hoy):
CLIENTE:
DNI / RUC (opcional):
VENDEDOR (vacío = Nick Sánchez):
TELÉFONO DEL VENDEDOR (vacío = 925 912 101):
"""

_COT_MOTO = """
MOTO
MARCA:
MODELO:
COLOR:
ETIQUETA (ej. PRE-VENTA, opcional):
TEXTO DEL PRECIO (opcional, ej. PRECIO DE PREVENTA):
PRECIO:
"""

_COT_ACC = """
ACCESORIOS (CANT / DESCRIPCIÓN / PRECIO UNITARIO)
ACC 1: CANT / DESCRIPCIÓN / PRECIO UNIT.
ACC 2: CANT / DESCRIPCIÓN / PRECIO UNIT.
ACC 3: CANT / DESCRIPCIÓN / PRECIO UNIT.
DESCUENTO ACCESORIOS (% , opcional):
INSTALACIÓN 1 (DESCRIPCIÓN / MONTO, opcional): 
"""

PLANTILLA_COT_MOTO = ("TIPO: COTIZACIÓN MOTO\n" + _COT_CABECERA + _COT_MOTO + """
REGALOS Y BENEFICIOS
REGALOS (uno por línea, opcional):
BONO (monto en soles, opcional):
INCLUYE (uno por línea, o ESTANDAR):
TEXTO PRECIO FINAL (opcional):""")
PLANTILLA_COT_MOTO_ACC = "TIPO: COTIZACIÓN MOTO Y ACCESORIOS\n" + _COT_CABECERA + _COT_MOTO + _COT_ACC
PLANTILLA_COT_ACC = "TIPO: COTIZACIÓN ACCESORIOS\n" + _COT_CABECERA + _COT_ACC

MENU_COT = ("¿Qué vas a cotizar?\n\n1️⃣ Moto (con regalos y beneficios)\n2️⃣ Moto + accesorios\n"
            "3️⃣ Solo accesorios\n\nResponde con el número.")
PLANTILLAS_COT = {"1": PLANTILLA_COT_MOTO, "2": PLANTILLA_COT_MOTO_ACC, "3": PLANTILLA_COT_ACC}

PLANTILLA_SIMULACION = """TIPO: SIMULACIÓN DE CUOTAS
FECHA (vacía = hoy):
CLIENTE (opcional):
MARCA (opcional):
MODELO (opcional):
COLOR (opcional):
PRECIO DE LA MOTO:

INICIALES (monto en soles o porcentaje, ej. 2000 o 25%)
INICIAL 1:
INICIAL 2 (opcional):
INICIAL 3 (opcional):"""

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
    "CLIENTE": "cliente", "DNI / RUC": "doc_cliente", "DNI/RUC": "doc_cliente", "RUC / DNI": "doc_cliente",
    "TELEFONO DEL VENDEDOR": "tel_vendedor", "TELEFONO VENDEDOR": "tel_vendedor",
    "ETIQUETA": "etiqueta", "TEXTO DEL PRECIO": "texto_precio",
    "REGALOS": "regalos", "INCLUYE": "incluye", "TEXTO PRECIO FINAL": "texto_final",
    "DESCUENTO ACCESORIOS": "descuento", "DESCUENTO": "descuento",
    "PRECIO DE LA MOTO": "precio",
}
ENCABEZADOS = {"COMPRADOR", "MOTO", "PRECIO", "PAGOS", "ENTREGA", "EXTRAS", "ACCESORIOS", "REGALOS Y BENEFICIOS", "INICIALES"}

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
            if re.fullmatch(r"INICIAL\s*\d+", et):
                if valor and not valor.upper().startswith("MONTO"):
                    datos.setdefault("_ini", []).append(valor)
                ultimo = None
                continue
            if re.fullmatch(r"(ACC|ACCESORIO)\s*\d+", et):
                if valor and not valor.upper().startswith("CANT"):
                    datos.setdefault("_acc", []).append(valor)
                ultimo = None
                continue
            if re.fullmatch(r"(INSTALACION|INST)\s*\d*", et):
                if valor and not valor.upper().startswith("DESCRIP"):
                    datos.setdefault("_inst", []).append(valor)
                ultimo = None
                continue
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
    t = sin_acentos(texto.upper())
    return len(re.findall(r"^\s*[^\n:]{2,60}:", texto, flags=re.M)) >= 4 and ("NOMBRE" in t or "CLIENTE" in t)

# ----------------------------------------------------------------------------
# COTIZACIONES
# ----------------------------------------------------------------------------
estado = {}   # num -> {"menu": "cot"}
espera = {}   # num -> {"fotos": [bytes], "ctx": dict|None, "t": epoch}
MAX_FOTOS = 4
VIGENCIA = 30 * 60  # segundos que se recuerdan fotos/cotización pendientes

def _espera(num):
    e = espera.get(num)
    if e and time.time() - e["t"] > VIGENCIA:
        e = None
    if not e:
        e = espera[num] = {"fotos": [], "ctx": None, "t": time.time()}
    e["t"] = time.time()
    return e

def _linea_item(v):
    """'2 / Llanta Pirelli 90/90-17 / S/ 185' -> (2, 'Llanta Pirelli 90/90-17', 185)."""
    m = re.match(r"^\s*([\dxX.,]+)\s*/\s*(.+?)\s*/\s*(?:S/\.?\s*)?([\d.,]+)\s*$", v, re.S)
    if not m:
        return None
    cant, desc, pu = a_monto(m.group(1).lower().replace("x", "")), m.group(2).strip(), a_monto(m.group(3))
    if not cant or cant <= 0 or pu is None or not desc:
        return None
    return (cant, desc[0].upper() + desc[1:], pu)

def _linea_inst(v):
    m = re.match(r"^\s*(.+?)\s*/\s*(?:S/\.?\s*)?([\d.,]+)\s*$", v, re.S)
    if not m:
        return None
    desc, monto = m.group(1).strip(), a_monto(m.group(2))
    if monto is None or not desc:
        return None
    return (desc[0].upper() + desc[1:], monto)

def revisar_cotizacion(texto):
    d, _ = parsear(texto)
    t = sin_acentos(d.get("tipo_venta", "").upper())
    modo = "moto_acc" if ("MOTO" in t and "ACCESORIOS" in t) else ("acc" if "ACCESORIOS" in t else "moto")
    faltan, avisos = [], []
    if not d.get("cliente"):
        faltan.append("CLIENTE")
    doc = re.sub(r"\D", "", d.get("doc_cliente", ""))
    if d.get("doc_cliente") and len(doc) not in (8, 9, 11):
        avisos.append(f"DNI / RUC '{d['doc_cliente']}' no parece válido (8 dígitos DNI, 11 RUC)")
    precio = None
    if modo in ("moto", "moto_acc"):
        for k, et in (("marca", "MARCA"), ("modelo", "MODELO")):
            if not d.get(k):
                faltan.append(et)
        precio = a_monto(d["precio"]) if d.get("precio") else None
        if precio is None:
            faltan.append("PRECIO" + (f" ilegible: '{d['precio']}'" if d.get("precio") else ""))
    items, insts = [], []
    if modo in ("moto_acc", "acc"):
        if not d.get("_acc"):
            faltan.append("ACC 1 (cantidad / descripción / precio unitario)")
        for i, v in enumerate(d.get("_acc", []), 1):
            it = _linea_item(v)
            if it: items.append(it)
            else: faltan.append(f"ACC {i} ilegible: '{v}'. Formato: 2 / Exploradoras / 160")
        for i, v in enumerate(d.get("_inst", []), 1):
            it = _linea_inst(v)
            if it: insts.append(it)
            else: faltan.append(f"INSTALACIÓN {i} ilegible: '{v}'. Formato: Instalación de exploradoras / 120")
    pct = 0.0
    if d.get("descuento"):
        pct = a_monto(d["descuento"].replace("%", "")) or 0.0
        if not 0 <= pct <= 100:
            avisos.append("El descuento debe estar entre 0 y 100"); pct = 0.0
    if d.get("fecha") and not D.parsear_fecha(d["fecha"]):
        avisos.append(f"FECHA '{d['fecha']}' no se entiende; usaré la de hoy. Formato: 19/11/2026")
    if d.get("bono") and a_monto(d["bono"]) is None and len(d["bono"]) > 30:
        avisos.append("El BONO es muy largo; escribe solo el monto, por ejemplo 500")

    ctx = {"modo": modo, "d": d, "precio": precio, "items": items, "instalaciones": insts, "pct": pct, "fotos": []}
    nombres = {"moto": "Cotización de moto", "moto_acc": "Cotización de moto + accesorios", "acc": "Cotización de accesorios"}
    out = [f"🧾 *{nombres[modo]}*", ""]
    out.append(f"*Cliente:* {d.get('cliente') or '—'}" + (f" ({d['doc_cliente']})" if d.get("doc_cliente") else ""))
    if modo != "acc":
        out.append(f"*Moto:* {' '.join(x for x in [d.get('marca'), d.get('modelo'), d.get('color')] if x) or '—'}")
        if precio is not None:
            out.append(f"*Precio de la moto:* {COT.money(precio)}")
    if items:
        sub, desc, neto, inst, total = COT.totales(ctx)
        out.append(f"*Accesorios:* {len(items)} ítem(s) = {COT.money(sub)}")
        if pct:
            out.append(f"*Descuento {pct:g}%:* − {COT.money(desc)}  → {COT.money(neto)}")
        if inst:
            out.append(f"*Instalación:* {COT.money(inst)}")
        out.append(f"*TOTAL:* {COT.money(total)}")
    if faltan:
        out += ["", "❌ *FALTA COMPLETAR:*"] + [f"• {x}" for x in faltan]
        out.append("\nCorrige la plantilla y envíala de nuevo.")
    elif avisos:
        out += ["", "⚠️ *REVISA:*"] + [f"• {x}" for x in avisos]
    return {"texto": "\n".join(out), "ctx": ctx, "faltan": faltan}


def revisar_simulacion(texto):
    d, _ = parsear(texto)
    faltan, avisos = [], []
    precio = a_monto(d["precio"]) if d.get("precio") else None
    if precio is None or precio <= 0:
        faltan.append("PRECIO DE LA MOTO" + (f" ilegible: '{d['precio']}'" if d.get("precio") else ""))
    if not d.get("_ini"):
        faltan.append("INICIAL 1 (monto o porcentaje)")
    sims = []
    for i, v in enumerate(d.get("_ini", []), 1):
        if "%" in v:
            p = a_monto(v.replace("%", ""))
            monto = round(precio * p / 100.0, 2) if (p is not None and precio) else None
        else:
            monto = a_monto(v)
        if monto is None or monto < 0:
            faltan.append(f"INICIAL {i} ilegible: '{v}'. Escribe un monto (2000) o un porcentaje (25%)")
            continue
        if precio and monto >= precio:
            faltan.append(f"INICIAL {i} no puede ser igual o mayor al precio")
            continue
        if precio:
            r = SIM.simular(precio, monto)
            if r["aviso"]:
                avisos.append(f"INICIAL {i}: {r['aviso']}")
            sims.append((monto, r))
    if d.get("fecha") and not D.parsear_fecha(d["fecha"]):
        avisos.append(f"FECHA '{d['fecha']}' no se entiende; usaré la de hoy. Formato: 19/11/2026")
    out = ["🧮 *Simulación de cuotas (Global Go)*", ""]
    moto = " ".join(x for x in [d.get("marca"), d.get("modelo"), d.get("color")] if x)
    if d.get("cliente"): out.append(f"*Cliente:* {d['cliente']}")
    if moto: out.append(f"*Moto:* {moto}")
    if precio: out.append(f"*Precio:* {COT.money(precio)}")
    for monto, r in sims:
        out.append("")
        out.append(f"*Inicial {COT.money(monto)} ({r['inicial_pct']:.0f}%) · financia {COT.money(r['financiado'])}*")
        for m, v in r["plazos"].items():
            out.append(f"• {m} meses: S/ {v['sin_soat']:,.2f} sin SOAT | S/ {v['con_soat']:,.2f} con SOAT (semanal)")
    if faltan:
        out += ["", "❌ *FALTA COMPLETAR:*"] + [f"• {x}" for x in faltan]
        out.append("\nCorrige la plantilla y envíala de nuevo.")
    else:
        if avisos:
            out += ["", "⚠️ *REVISA:*"] + [f"• {x}" for x in avisos]
        out += ["", "_Cuotas semanales referenciales; el valor final depende de la evaluación crediticia de Global Go._"]
    return {"texto": "\n".join(out), "faltan": faltan, "d": d, "precio": precio, "sims": sims}

def descargar_media(media_id):
    h = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    r = requests.get(f"{GRAPH}/{media_id}", headers=h, timeout=15)
    url = r.json().get("url")
    if not url:
        raise RuntimeError("Meta no devolvió la URL de la imagen: " + r.text[:150])
    r2 = requests.get(url, headers=h, timeout=30)
    r2.raise_for_status()
    return r2.content

def generar_cotizacion(num):
    e = espera.get(num)
    if not e or not e.get("ctx"):
        enviar(num, "No tengo ninguna cotización pendiente. Escribe *5* para empezar una.")
        return
    ctx = e["ctx"]
    ctx["fotos"] = e["fotos"][:MAX_FOTOS]
    try:
        pdf = COT.cotizacion_pdf(ctx)
        d = ctx["d"]
        base = d.get("cliente", "cliente") + "_" + (d.get("modelo") or "accesorios")
        nombre = re.sub(r"[^A-Za-z0-9]+", "_", sin_acentos(base)).strip("_")[:50]
        enviar_pdf(num, pdf, f"Cotizacion_{nombre}.pdf", "Cotización")
        enviar(num, "✅ Cotización lista. Revísala antes de enviarla al cliente.")
    except Exception as ex:
        print("error cotizacion:", repr(ex))
        enviar(num, "⚠️ No pude generar la cotización por un error interno. Avísale a Nick para revisar los logs.")
    espera.pop(num, None)

def atender_imagen(num, m):
    try:
        datos = COT.preparar_foto(descargar_media(m["image"]["id"]))
    except Exception as ex:
        print("error imagen:", repr(ex))
        enviar(num, "⚠️ No pude leer esa foto. Intenta enviarla de nuevo (como foto, no como documento).")
        return
    e = _espera(num)
    if len(e["fotos"]) < MAX_FOTOS:
        e["fotos"].append(datos)
    n = len(e["fotos"])
    if e["ctx"]:
        if e["ctx"]["modo"] == "moto" or n >= MAX_FOTOS:   # la cotización de moto usa una sola foto principal
            generar_cotizacion(num)
        else:
            enviar(num, f"📷 Foto {n} recibida. Envía otra (máx. {MAX_FOTOS}) o escribe *LISTO* para generar la cotización.")
    else:
        enviar(num, f"📷 Foto {n} guardada. Ahora escribe *5*, elige el tipo de cotización y envía los datos; la pondré en el PDF.")

def atender(num, texto):
    t = sin_acentos(texto.strip().upper())
    if parece_plantilla(texto):
        d0, _ = parsear(texto)
        if "SIMULAC" in sin_acentos(d0.get("tipo_venta", "").upper()):
            r = revisar_simulacion(texto)
            enviar(num, r["texto"])
            if not r["faltan"]:
                try:
                    pdf = COT.simulacion_pdf({"d": r["d"], "precio": r["precio"], "simulaciones": r["sims"]})
                    base = r["d"].get("cliente") or r["d"].get("modelo") or "cliente"
                    nombre = re.sub(r"[^A-Za-z0-9]+", "_", sin_acentos(base)).strip("_")[:40]
                    enviar_pdf(num, pdf, f"Simulacion_cuotas_{nombre}.pdf", "Simulación de cuotas")
                except Exception as ex:
                    print("error simulacion:", repr(ex))
                    enviar(num, "⚠️ No pude generar el PDF de la simulación. Avísale a Nick para revisar los logs.")
            return
        if "COTIZ" in sin_acentos(d0.get("tipo_venta", "").upper()):
            r = revisar_cotizacion(texto)
            enviar(num, r["texto"])
            if r["faltan"]:
                return
            e = _espera(num)
            e["ctx"] = r["ctx"]
            if e["fotos"]:
                generar_cotizacion(num)
            else:
                enviar(num, "📷 ¿Quieres agregar foto? Envíala ahora (la moto o los accesorios). "
                            "Si no, escribe *LISTO* y la genero sin foto.")
            return
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
    elif t in ("LISTO", "SIN FOTO", "NO", "GENERAR") and espera.get(num, {}).get("ctx"):
        generar_cotizacion(num)
    elif estado.get(num, {}).get("menu") == "cot" and t in PLANTILLAS_COT:
        estado.pop(num, None)
        enviar(num, "Perfecto. Copia el siguiente mensaje, complétalo y envíamelo 👇\n"
                    "(Los campos opcionales puedes borrarlos o dejarlos vacíos.)")
        enviar(num, PLANTILLAS_COT[t])
    elif t in ("6", "SIMULAR", "SIMULACION", "CUOTAS"):
        enviar(num, "Perfecto. Copia el siguiente mensaje, complétalo y envíamelo 👇")
        enviar(num, PLANTILLA_SIMULACION)
    elif t in ("5", "COTIZACION", "COTIZAR"):
        estado[num] = {"menu": "cot"}
        enviar(num, MENU_COT)
    elif t in PLANTILLAS or t in ("CONTADO", "SEPARACION"):
        clave = t if t in PLANTILLAS else {"CONTADO": "1", "SEPARACION": "2"}[t]
        enviar(num, "Perfecto. Copia el siguiente mensaje, complétalo y envíamelo 👇")
        enviar(num, PLANTILLAS[clave])
    else:
        enviar(num, MENU)

@app.get("/")
def home():
    ok = COT.FUENTES_OK and D.FUENTES_OK
    return "Bot Leo Motos activo ✅ (Prueba 5) – Fuentes: " + ("OK ✅" if ok else "FALTAN ⚠️ (sube la carpeta fonts completa)")

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
                    if m.get("type") == "image":
                        atender_imagen(num, m)
                        continue
                    if m.get("type") != "text":
                        enviar(num, "Por ahora solo leo texto y fotos 🙂")
                        continue
                    atender(num, m["text"]["body"])
    except Exception as e:
        print("error:", repr(e))
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
