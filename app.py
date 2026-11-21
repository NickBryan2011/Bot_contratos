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
            datos[ultimo] = (datos.get(ultimo, "") + "\n" + l).strip()
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
            faltan.append(f"PAGO {i} ilegible: '{lp}'. Formato: 19/11/2026 / 5300 / YAPE / 123456")
            continue
        if p["medio"] != "EFECTIVO" and "EFECTIVO" not in p["medio"] and not p["op"]:
            faltan.append(f"N° DE OPERACIÓN del PAGO {i} ({p['medio']})")
        pagos.append(p)
    total_pagado = round(sum(p["monto"] for p in pagos), 2)

    # --- armar respuesta ---
    out = ["🧪 *PRUEBA 2 – Contado*", "_Reviso tus datos y, si está todo completo, te envío el contrato en PDF._", ""]
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
    if faltan:
        out.append("No genero el PDF hasta completar lo obligatorio. Corrige la plantilla y envíala de nuevo.")
    elif avisos:
        out.append("Genero el PDF igual; revisa los avisos antes de usarlo.")
    else:
        out.append("✅ Todo lo obligatorio está completo. Te envío el contrato en PDF 👇")
    return {"texto": "\n".join(out), "datos": d, "pagos": pagos, "precio": precio, "tipo": tipo,
            "modalidad": mod, "recoge": rec, "faltan": faltan}

# ----------------------------------------------------------------------------
# PDF DEL CONTRATO (réplica del formato Word 002 - CONTRATO COMPRAVENTA)
# ----------------------------------------------------------------------------
from io import BytesIO
from xml.sax.saxutils import escape as _esc
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib import colors
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph,
                                Spacer, Table, TableStyle, KeepTogether)
from reportlab.pdfgen import canvas as _canvas

AZUL = colors.HexColor("#4F81BD")
FUENTE, FUENTE_B, FUENTE_I = "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"
FUENTE_BI = "Helvetica-BoldOblique"
from reportlab.platypus.flowables import Flowable

class _Casilla(Flowable):
    def __init__(self, marcada=False, lado=9):
        super().__init__()
        self.marcada, self.lado = marcada, lado
        self.width, self.height = lado + 3, lado + 2
    def draw(self):
        c, l = self.canv, self.lado
        c.setLineWidth(0.8)
        c.rect(0, 1.5, l, l)
        if self.marcada:
            c.setLineWidth(1.4)
            c.line(1.8, 3.3, l - 1.8, l - 0.3)
            c.line(1.8, l - 0.3, l - 1.8, 3.3)

def _fila_casilla(marcada, texto, estilo):
    t = Table([[_Casilla(marcada), Paragraph(texto, estilo)]], colWidths=[16, 416])
    t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                           ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t

def _estilos():
    base = dict(fontName=FUENTE, fontSize=10, leading=13, spaceAfter=7, alignment=TA_LEFT)
    return {
        "marca": ParagraphStyle("marca", parent=None, fontName=FUENTE_B, fontSize=12.5, leading=15,
                                textColor=AZUL, alignment=TA_CENTER, spaceAfter=2),
        "titulo": ParagraphStyle("titulo", fontName=FUENTE_B, fontSize=11, leading=14,
                                 alignment=TA_CENTER, spaceAfter=6),
        "h": ParagraphStyle("h", fontName=FUENTE_B, fontSize=11.5, leading=14, textColor=AZUL,
                            spaceBefore=9, spaceAfter=3, keepWithNext=1),
        "p": ParagraphStyle("p", **base),
        "campo": ParagraphStyle("campo", **{**base, "spaceAfter": 4, "leading": 12.5}),
        "j": ParagraphStyle("j", **{**base, "alignment": TA_JUSTIFY}),
        "b": ParagraphStyle("b", **{**base, "fontName": FUENTE_B, "alignment": TA_JUSTIFY}),
        "ib": ParagraphStyle("ib", **{**base, "fontName": FUENTE_BI, "alignment": TA_JUSTIFY}),
        "bullet": ParagraphStyle("bullet", **{**base, "fontName": FUENTE_B, "spaceAfter": 1,
                                              "leftIndent": 36, "bulletIndent": 18}),
        "obs": ParagraphStyle("obs", fontName=FUENTE_B, fontSize=10, leading=13, textColor=AZUL,
                              spaceBefore=8, spaceAfter=2),
        "celda": ParagraphStyle("celda", fontName=FUENTE, fontSize=9.5, leading=12),
        "celda_b": ParagraphStyle("celda_b", fontName=FUENTE_B, fontSize=9.5, leading=12),
    }

def _x(s):
    return _esc(str(s or ""))

def _campo(et, val=""):
    val = _x(val)
    return f"<b>{_x(et)}</b> {val}".rstrip()

class _NumCanvas(_canvas.Canvas):
    """Pie de página: 'Leo Motos Perú | RUC ... | Av. ...' y 'N de M'."""
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._paginas = []
    def showPage(self):
        self._paginas.append(dict(self.__dict__))
        self._startPage()
    def save(self):
        total = len(self._paginas)
        for est in self._paginas:
            self.__dict__.update(est)
            self.setFont(FUENTE, 9)
            self.drawString(90, 38, "Leo Motos Perú | RUC 20606384212 | Av. Tomás Valle 1641 – SMP")
            self.drawRightString(612 - 90, 38, f"{self._pageNumber} de {total}")
            super().showPage()
        super().save()

REGALIAS_ESTANDAR = ["Llaves", "Tarjeta de propiedad virtual", "Trámite de placa",
                     "Casco de regalo", "Descuento por 3 meses en accesorios"]

def _lista_regalias(txt):
    if not txt:
        return []
    if sin_acentos(txt.strip().upper()) in ("ESTANDAR", "STANDARD"):
        return list(REGALIAS_ESTANDAR)
    items = [i.strip() for i in re.split(r"[,;\n]+", txt) if i.strip()]
    out = []
    for i in items:
        out.append(i[0].upper() + i[1:].lower() if i.isupper() else i[0].upper() + i[1:])
    return out

def generar_contrato_pdf(d, pagos, precio, tipo, modalidad, recoge):
    S = _estilos()
    buf = BytesIO()
    doc = BaseDocTemplate(buf, pagesize=letter, leftMargin=90, rightMargin=90,
                          topMargin=50, bottomMargin=64,
                          title="Contrato de compraventa", author="Leo Motos Perú")
    doc.addPageTemplates([PageTemplate(id="p", frames=[Frame(90, 64, 432, 792 - 50 - 64, id="f",
                                       leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)])])
    el = []
    P = lambda t, s="p": el.append(Paragraph(t, S[s]))
    H = lambda t: el.append(Paragraph(_x(t), S["h"]))

    P("LEO MOTOS PERÚ", "marca")
    P("CONTRATO DE COMPRAVENTA DE MOTOCICLETA NUEVA (0 KM)", "titulo")

    H("1. DATOS DEL VENDEDOR")
    P(_campo("Razón social:", "Leo Motos Perú Motorcycle Shop E.I.R.L."), "campo")
    P(_campo("RUC:", "20606384212"), "campo")
    P(_campo("Domicilio:", "Tomás Valle 1641, San Martín de Porres, Lima."), "campo")

    tipo_txt = {"DNI": "DNI", "RUC": "RUC", "CE": "Carnet de Extranjería"}.get(tipo, d.get("tipo_doc", ""))
    H("2. DATOS DEL COMPRADOR")
    P(_campo("Nombre / Razón social:", d.get("nombre")), "campo")
    P(_campo("Tipo de documento:", tipo_txt), "campo")
    P(_campo("N.° de documento:", d.get("num_doc")), "campo")
    P(_campo("Celular:", d.get("celular")), "campo")
    P(_campo("Correo electrónico:", d.get("correo")), "campo")
    P(_campo("Estado civil:", d.get("estado_civil")), "campo")

    H("3. DATOS DE LA MOTOCICLETA")
    P(_campo("Marca:", d.get("marca")), "campo")
    P(_campo("Modelo:", d.get("modelo")), "campo")
    P(_campo("Año:", d.get("anio")), "campo")
    P(_campo("Color:", d.get("color")), "campo")
    P(_campo("N.° de chasis:", d.get("chasis")), "campo")
    P(_campo("N.° de motor:", d.get("motor")), "campo")

    H("4. PRECIO DE VENTA")
    P(f"<b>Precio total:</b> S/{precio:,.2f} ({_x(numero_a_letras(precio))}).", "campo")

    H("5. FORMA DE PAGO")
    mod_txt = "Financiado por Global Go" if modalidad == "GLOBAL GO" else "Contado"
    P(_campo("Modalidad de venta:", mod_txt + "."), "campo")
    P("Detalle de los pagos realizados:", "campo")
    filas = [[Paragraph("Fecha", S["celda"]), Paragraph("Monto", S["celda"]),
              Paragraph("Medio de pago", S["celda"])]]
    for p in pagos:
        medio = p["medio"] + (f" OP {p['op']}" if p["op"] else "")
        filas.append([Paragraph(_x(p["fecha"]), S["celda"]),
                      Paragraph(f"S/{p['monto']:,.2f}", S["celda"]),
                      Paragraph(_x(medio), S["celda_b"])])
    t = Table(filas, colWidths=[144, 144, 144], repeatRows=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.6, colors.black),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    el.append(Spacer(1, 4)); el.append(t); el.append(Spacer(1, 6))

    s6 = [Paragraph("6. RECEPCIÓN DE LA MOTOCICLETA", S["h"]),
          Paragraph("<b>Modalidad de recepción:</b>", S["campo"]),
          _fila_casilla(recoge == "COMPRADOR", "El comprador recogerá personalmente la motocicleta.", S["campo"]),
          _fila_casilla(recoge == "TERCERO", "El comprador autoriza que la motocicleta sea entregada a un tercero.", S["campo"]),
          Paragraph(_campo("Nombre del tercero autorizado (si corresponde):",
                           d.get("tercero_nombre") if recoge == "TERCERO" else ""), S["campo"]),
          Paragraph(_campo("DNI:", d.get("tercero_dni") if recoge == "TERCERO" else ""), S["campo"]),
          Paragraph("La persona autorizada podrá recibir la unidad y firmar el Acta de Entrega y el Checklist de "
                    "Revisión y Entrega del Vehículo.", S["j"]),
          Paragraph(_campo("Fecha pactada de entrega:", d.get("fecha_entrega")), S["campo"])]
    el.append(KeepTogether(s6))

    H("7. GARANTÍA")
    P("La motocicleta cuenta con garantía del fabricante, conforme a las condiciones establecidas en el "
      "manual de garantía o certificado de garantía. Para conservar su vigencia, el comprador deberá "
      "cumplir con los mantenimientos y servicios establecidos en la cartilla de mantenimiento, "
      "respetando los plazos y condiciones indicados por el fabricante.", "j")

    H("8. REGALÍAS OFRECIDAS")
    regalias = _lista_regalias(d.get("regalias", ""))
    if regalias:
        for r in regalias:
            el.append(Paragraph(_x(r), S["bullet"], bulletText="•"))
    else:
        P("Sin regalías.", "p")
    if d.get("observaciones"):
        P("Observaciones y condiciones de las regalías:", "obs")
        P(_x(d["observaciones"]).replace("\n", "<br/>"), "p")

    H("9. CONDICIONES ADICIONALES PARA VENTAS FINANCIADAS POR GLOBAL GO")
    P("Esta cláusula aplica únicamente cuando la adquisición de la motocicleta se realiza mediante "
      "financiamiento otorgado por Global Go.", "ib")
    P("El comprador declara conocer que el financiamiento de la motocicleta ha sido otorgado por Global Go, "
      "siendo dicha entidad la responsable de establecer las condiciones del crédito, incluyendo el monto "
      "financiado, cuotas, intereses, cronograma de pagos y demás obligaciones derivadas del "
      "financiamiento.", "j")
    P("En consecuencia, el comprador reconoce que las obligaciones de pago correspondientes al "
      "financiamiento deberán ser atendidas directamente ante Global Go, conforme al contrato y las "
      "condiciones aceptadas con dicha entidad.", "j")
    P("Asimismo, cualquier incumplimiento de pago, penalidad, cobranza, retención o recuperación de la "
      "motocicleta, cuando corresponda, será gestionado por Global Go de acuerdo con las condiciones de su "
      "contrato de financiamiento y la normativa aplicable.", "j")
    P("Leo Motos Perú Motorcycle Shop E.I.R.L. interviene en esta operación exclusivamente como vendedor "
      "de la motocicleta y no como entidad financiadora ni acreedora del préstamo.", "b")
    P("Por tanto, las condiciones financieras y la administración del crédito corresponden a Global Go.", "j")
    P("La responsabilidad de Leo Motos Perú respecto de la motocicleta se limita a las obligaciones que le "
      "correspondan como vendedor, incluyendo la atención de la garantía del fabricante conforme a sus "
      "condiciones, sin perjuicio de las responsabilidades legales que resulten aplicables.", "j")

    firmas = [
        Paragraph("10. ACEPTACIÓN Y FIRMAS", S["h"]),
        Paragraph("El comprador declara haber revisado la información consignada en el presente contrato y "
                  "manifiesta su conformidad con las condiciones de compraventa aquí establecidas.", S["j"]),
        Spacer(1, 40),
    ]
    tf = Table([[Paragraph("<b>FIRMA DEL COMPRADOR</b>", S["p"]), Paragraph("<b>FIRMA DEL CONCESIONARIO</b>", S["p"])],
                [Spacer(1, 26), Spacer(1, 26)],
                [Paragraph("<b>" + "-" * 36 + "</b>", S["p"]), Paragraph("<b>" + "-" * 36 + "</b>", S["p"])]],
               colWidths=[216, 216])
    tf.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    firmas += [tf, Paragraph("<b>Nombre:</b>", S["campo"]), Paragraph("<b>DNI / RUC:</b>", S["campo"]),
               Paragraph("<b>Fecha:</b>", S["campo"])]
    el.append(KeepTogether(firmas))

    doc.build(el, canvasmaker=_NumCanvas)
    return buf.getvalue()

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

def enviar_pdf(to, pdf_bytes, nombre_archivo, caption=""):
    r = requests.post(
        f"{GRAPH}/{PHONE_NUMBER_ID}/media",
        headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
        data={"messaging_product": "whatsapp", "type": "application/pdf"},
        files={"file": (nombre_archivo, pdf_bytes, "application/pdf")},
        timeout=30,
    )
    print("media:", r.status_code, r.text[:150])
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
    print("envio doc:", r2.status_code, r2.text[:150])

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
        r = revisar_contado(texto)
        enviar(num, r["texto"])
        if not r["faltan"]:
            try:
                pdf = generar_contrato_pdf(r["datos"], r["pagos"], r["precio"], r["tipo"],
                                           r["modalidad"], r["recoge"])
                nombre = re.sub(r"[^A-Za-z0-9]+", "_", sin_acentos(r["datos"].get("nombre", "cliente"))).strip("_")[:40]
                enviar_pdf(num, pdf, f"Contrato_{nombre}.pdf", "Contrato de compraventa – PRUEBA 2")
            except Exception as e:
                print("error pdf:", repr(e))
                enviar(num, "⚠️ No pude generar el PDF por un error interno. Avísale a Nick para revisar los logs.")
    elif t in ("1", "CONTADO"):
        enviar(num, "Perfecto: venta al *contado*. Copia el siguiente mensaje, complétalo y envíamelo 👇")
        enviar(num, PLANTILLA_CONTADO)
    elif t in ("2", "3", "4"):
        enviar(num, "Ese tipo de venta aún no está activo en las pruebas. Por ahora prueba con *1* (Contado).")
    else:
        enviar(num, MENU)

@app.get("/")
def home():
    return "Bot Leo Motos activo ✅ (Prueba 2)"

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
