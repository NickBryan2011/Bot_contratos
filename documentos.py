# -*- coding: utf-8 -*-
"""Generadores de PDF de Leo Motos Perú (réplica de los formatos Word)."""
import re
import unicodedata
from io import BytesIO
from datetime import datetime, timezone, timedelta
from xml.sax.saxutils import escape as _esc

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib import colors
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph,
                                Spacer, Table, TableStyle, KeepTogether)
from reportlab.platypus.flowables import Flowable
from reportlab.pdfgen import canvas as _canvas

# ----------------------------------------------------------------------------
# UTILIDADES
# ----------------------------------------------------------------------------
def sin_acentos(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")

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

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]

def hoy_lima():
    return datetime.now(timezone(timedelta(hours=-5)))

def parsear_fecha(s):
    """'19/11/2026' -> datetime o None"""
    m = re.fullmatch(r"\s*(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\s*", s or "")
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y += 2000
    try:
        return datetime(y, mo, d)
    except ValueError:
        return None

def _x(s):
    return _esc(str(s if s is not None else ""))

def _campo(et, val=""):
    return f"<b>{_x(et)}</b> {_x(val)}".rstrip()

def _s(m):      # S/5,460.00
    return f"S/{m:,.2f}"

def _sp(m):     # S/.5,460.00
    return f"S/.{m:,.2f}"

AZUL = colors.HexColor("#4F81BD")
AZUL_OSC = colors.HexColor("#366091")
GRIS = colors.HexColor("#7F8FA6")
VERDE = colors.HexColor("#3B9B50")
F, FB, FI, FBI = "Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique"

def _estilos(cuerpo=10):
    base = dict(fontName=F, fontSize=cuerpo, leading=cuerpo * 1.3, spaceAfter=7, alignment=TA_LEFT)
    S = {
        "marca": ParagraphStyle("marca", fontName=FB, fontSize=12.5, leading=15, textColor=AZUL,
                                alignment=TA_CENTER, spaceAfter=2),
        "titulo": ParagraphStyle("titulo", fontName=FB, fontSize=11, leading=14,
                                 alignment=TA_CENTER, spaceAfter=6),
        "tituloazul": ParagraphStyle("tituloazul", fontName=FB, fontSize=11, leading=14, textColor=AZUL,
                                     alignment=TA_CENTER, spaceAfter=3),
        "titulo_sep": ParagraphStyle("titulo_sep", fontName=F, fontSize=10.5, leading=14,
                                     alignment=TA_CENTER, spaceAfter=14),
        "h": ParagraphStyle("h", fontName=FB, fontSize=11.5, leading=14, textColor=AZUL,
                            spaceBefore=9, spaceAfter=3, keepWithNext=1),
        "hs": ParagraphStyle("hs", fontName=F, fontSize=cuerpo, leading=cuerpo * 1.3,
                             spaceBefore=8, spaceAfter=3, keepWithNext=1),
        "p": ParagraphStyle("p", **base),
        "pc": ParagraphStyle("pc", **{**base, "spaceAfter": 0}),
        "campo": ParagraphStyle("campo", **{**base, "spaceAfter": 4, "leading": cuerpo * 1.25}),
        "j": ParagraphStyle("j", **{**base, "alignment": TA_JUSTIFY}),
        "b": ParagraphStyle("b", **{**base, "fontName": FB, "alignment": TA_JUSTIFY}),
        "ib": ParagraphStyle("ib", **{**base, "fontName": FBI, "alignment": TA_JUSTIFY}),
        "bullet": ParagraphStyle("bullet", **{**base, "fontName": FB, "spaceAfter": 1,
                                              "leftIndent": 36, "bulletIndent": 18}),
        "bulletn": ParagraphStyle("bulletn", **{**base, "spaceAfter": 2, "leftIndent": 36, "bulletIndent": 18}),
        "obs": ParagraphStyle("obs", fontName=FB, fontSize=10, leading=13, textColor=AZUL,
                              spaceBefore=8, spaceAfter=2),
        "celda": ParagraphStyle("celda", fontName=F, fontSize=9.5, leading=12),
        "celda_b": ParagraphStyle("celda_b", fontName=FB, fontSize=9.5, leading=12),
        "linea": ParagraphStyle("linea", **{**base, "spaceAfter": 2, "leading": cuerpo * 1.2}),
    }
    return S

# ----------------------------------------------------------------------------
# PIE DE PÁGINA
# ----------------------------------------------------------------------------
class _NumCanvas(_canvas.Canvas):
    pie = "leo"
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
            n = self._pageNumber
            if self.pie == "leo":
                self.setFont(F, 9)
                self.drawString(90, 38, "Leo Motos Perú | RUC 20606384212 | Av. Tomás Valle 1641 – SMP")
                self.drawRightString(522, 38, f"{n} de {total}")
            elif self.pie == "num":
                self.setFont(F, 9)
                self.drawRightString(522, 38, f"{n} de {total}")
            elif self.pie == "sep":
                self.setFont(F, 9)
                self.setFillColor(GRIS)
                self.drawRightString(612 - 85, 38, f"Condiciones de separación de vehículo  Página {n} | {total}")
            super().showPage()
        super().save()

def _canvas_con_pie(pie):
    class C(_NumCanvas):
        pass
    C.pie = pie
    return C

def _construir(el, pie="leo", margenes=(90, 90, 50, 64), titulo=""):
    izq, der, sup, inf = margenes
    buf = BytesIO()
    doc = BaseDocTemplate(buf, pagesize=letter, leftMargin=izq, rightMargin=der, topMargin=sup,
                          bottomMargin=inf, title=titulo, author="Leo Motos Perú")
    ancho = 612 - izq - der
    doc.addPageTemplates([PageTemplate(id="p", frames=[Frame(izq, inf, ancho, 792 - sup - inf, id="f",
                                       leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)])])
    doc.build(el, canvasmaker=_canvas_con_pie(pie))
    return buf.getvalue()

# ----------------------------------------------------------------------------
# ELEMENTOS COMUNES
# ----------------------------------------------------------------------------
class _Casilla(Flowable):
    def __init__(self, marcada=False, lado=9, verde=False):
        super().__init__()
        self.marcada, self.lado, self.verde = marcada, lado, verde
        self.width, self.height = lado + 3, lado + 2
    def draw(self):
        c, l = self.canv, self.lado
        if self.verde:
            c.setFillColor(VERDE); c.setStrokeColor(VERDE)
            c.roundRect(0, 1.5, l, l, 1.5, stroke=1, fill=1)
            c.setStrokeColor(colors.white); c.setLineWidth(1.6)
            c.line(1.8, l / 2 + 1, l / 2 - 0.5, 3.2); c.line(l / 2 - 0.5, 3.2, l - 1.5, l - 0.2)
            return
        c.setLineWidth(0.8); c.rect(0, 1.5, l, l)
        if self.marcada:
            c.setLineWidth(1.4)
            c.line(1.8, 3.3, l - 1.8, l - 0.3); c.line(1.8, l - 0.3, l - 1.8, 3.3)

def _fila_casilla(marcada, texto, estilo, ancho=432, verde=False):
    t = Table([[_Casilla(marcada, verde=verde), Paragraph(texto, estilo)]], colWidths=[16, ancho - 16])
    t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                           ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t

TIPO_DOC_TXT = {"DNI": "DNI", "RUC": "RUC", "CE": "Carnet de Extranjería"}

def _bloque_partes(S, c, extra_comprador=True):
    d = c["d"]
    tipo_txt = TIPO_DOC_TXT.get(c.get("tipo"), d.get("tipo_doc", ""))
    el = [Paragraph("1. DATOS DEL VENDEDOR", S["h"]),
          Paragraph(_campo("Razón social:", "Leo Motos Perú Motorcycle Shop E.I.R.L."), S["campo"]),
          Paragraph(_campo("RUC:", "20606384212"), S["campo"]),
          Paragraph(_campo("Domicilio:", "Tomás Valle 1641, San Martín de Porres, Lima."), S["campo"]),
          Paragraph("2. DATOS DEL COMPRADOR", S["h"]),
          Paragraph(_campo("Nombre / Razón social:", d.get("nombre")), S["campo"]),
          Paragraph(_campo("Tipo de documento:", tipo_txt), S["campo"]),
          Paragraph(_campo("N.° de documento:", d.get("num_doc")), S["campo"]),
          Paragraph(_campo("Celular:", d.get("celular")), S["campo"]),
          Paragraph(_campo("Correo electrónico:", d.get("correo")), S["campo"]),
          Paragraph(_campo("Estado civil:", d.get("estado_civil")), S["campo"]),
          Paragraph("3. DATOS DE LA MOTOCICLETA", S["h"]),
          Paragraph(_campo("Marca:", d.get("marca")), S["campo"]),
          Paragraph(_campo("Modelo:", d.get("modelo")), S["campo"]),
          Paragraph(_campo("Año:", d.get("anio")), S["campo"]),
          Paragraph(_campo("Color:", d.get("color")), S["campo"]),
          Paragraph(_campo("N.° de chasis:", d.get("chasis")), S["campo"]),
          Paragraph(_campo("N.° de motor:", d.get("motor")), S["campo"])]
    return el

def _tabla_pagos(S, pagos, ancho=432):
    filas = [[Paragraph("Fecha", S["celda"]), Paragraph("Monto", S["celda"]),
              Paragraph("Medio de pago", S["celda"])]]
    for p in pagos:
        medio = p["medio"] + (f" OP {p['op']}" if p["op"] else "")
        filas.append([Paragraph(_x(p["fecha"]), S["celda"]), Paragraph(_s(p["monto"]), S["celda"]),
                      Paragraph(_x(medio), S["celda_b"])])
    t = Table(filas, colWidths=[ancho / 3] * 3, repeatRows=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.6, colors.black),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    return t

def _firmas_dobles(S, izq, der, lineas=("Nombre:", "DNI / RUC:", "Fecha:"), espacio=40):
    raya = "<b>" + "-" * 36 + "</b>"
    tf = Table([[Paragraph(f"<b>{izq}</b>", S["p"]), Paragraph(f"<b>{der}</b>", S["p"])],
                [Spacer(1, 26), Spacer(1, 26)],
                [Paragraph(raya, S["p"]), Paragraph(raya, S["p"])]], colWidths=[216, 216])
    tf.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    return [Spacer(1, espacio), tf] + [Paragraph(f"<b>{l}</b>", S["campo"]) for l in lineas]

REGALIAS_ESTANDAR = ["Trámite de tarjeta de propiedad", "Trámite de placa", "Casco certificado de regalo",
                     "10% de descuento por 3 meses"]
REGALIAS_ESTANDAR_GG = REGALIAS_ESTANDAR

def lista_regalias(txt, estandar):
    """Acepta ESTANDAR solo o combinado con otras (ej. 'ESTANDAR, BONO 500')."""
    if not txt:
        return []
    out = []
    for i in [x.strip() for x in re.split(r"[,;\n]+", txt) if x.strip()]:
        if sin_acentos(i.upper()) in ("ESTANDAR", "STANDARD"):
            out += list(estandar)
        else:
            out.append(i[0].upper() + i[1:].lower() if i.isupper() else i[0].upper() + i[1:])
    return out

# ----------------------------------------------------------------------------
# 1) CONTRATO DE COMPRAVENTA (002)
# ----------------------------------------------------------------------------
def contrato_pdf(c):
    S = _estilos()
    d, pagos, precio, recoge = c["d"], c["pagos"], c["precio"], c.get("recoge")
    el = [Paragraph("LEO MOTOS PERÚ", S["marca"]),
          Paragraph("CONTRATO DE COMPRAVENTA DE MOTOCICLETA NUEVA (0 KM)", S["titulo"])]
    el += _bloque_partes(S, c)
    el.append(Paragraph("4. PRECIO DE VENTA", S["h"]))
    el.append(Paragraph(f"<b>Precio total:</b> {_s(precio)} ({_x(numero_a_letras(precio))}).", S["campo"]))
    el.append(Paragraph("5. FORMA DE PAGO", S["h"]))
    mod = "Financiado por Global Go" if c.get("modalidad") == "GLOBAL GO" else "Contado"
    el.append(Paragraph(_campo("Modalidad de venta:", mod + "."), S["campo"]))
    el.append(Paragraph("Detalle de los pagos realizados:", S["campo"]))
    el += [Spacer(1, 4), _tabla_pagos(S, pagos), Spacer(1, 6)]
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
    el += [Paragraph("7. GARANTÍA", S["h"]),
           Paragraph("La motocicleta cuenta con garantía del fabricante, conforme a las condiciones establecidas en el "
                     "manual de garantía o certificado de garantía. Para conservar su vigencia, el comprador deberá "
                     "cumplir con los mantenimientos y servicios establecidos en la cartilla de mantenimiento, "
                     "respetando los plazos y condiciones indicados por el fabricante.", S["j"]),
           Paragraph("8. REGALÍAS OFRECIDAS", S["h"])]
    regalias = lista_regalias(d.get("regalias", ""), REGALIAS_ESTANDAR)
    if regalias:
        for r in regalias:
            el.append(Paragraph(_x(r), S["bullet"], bulletText="•"))
    else:
        el.append(Paragraph("Sin regalías.", S["p"]))
    if d.get("observaciones"):
        el.append(Paragraph("Observaciones y condiciones de las regalías:", S["obs"]))
        el.append(Paragraph(_x(d["observaciones"]).replace("\n", "<br/>"), S["p"]))
    el += [Paragraph("9. CONDICIONES ADICIONALES PARA VENTAS FINANCIADAS POR GLOBAL GO", S["h"]),
           Paragraph("Esta cláusula aplica únicamente cuando la adquisición de la motocicleta se realiza mediante "
                     "financiamiento otorgado por Global Go.", S["ib"]),
           Paragraph("El comprador declara conocer que el financiamiento de la motocicleta ha sido otorgado por Global Go, "
                     "siendo dicha entidad la responsable de establecer las condiciones del crédito, incluyendo el monto "
                     "financiado, cuotas, intereses, cronograma de pagos y demás obligaciones derivadas del "
                     "financiamiento.", S["j"]),
           Paragraph("En consecuencia, el comprador reconoce que las obligaciones de pago correspondientes al "
                     "financiamiento deberán ser atendidas directamente ante Global Go, conforme al contrato y las "
                     "condiciones aceptadas con dicha entidad.", S["j"]),
           Paragraph("Asimismo, cualquier incumplimiento de pago, penalidad, cobranza, retención o recuperación de la "
                     "motocicleta, cuando corresponda, será gestionado por Global Go de acuerdo con las condiciones de su "
                     "contrato de financiamiento y la normativa aplicable.", S["j"]),
           Paragraph("Leo Motos Perú Motorcycle Shop E.I.R.L. interviene en esta operación exclusivamente como vendedor "
                     "de la motocicleta y no como entidad financiadora ni acreedora del préstamo.", S["b"]),
           Paragraph("Por tanto, las condiciones financieras y la administración del crédito corresponden a Global Go.", S["j"]),
           Paragraph("La responsabilidad de Leo Motos Perú respecto de la motocicleta se limita a las obligaciones que le "
                     "correspondan como vendedor, incluyendo la atención de la garantía del fabricante conforme a sus "
                     "condiciones, sin perjuicio de las responsabilidades legales que resulten aplicables.", S["j"])]
    firmas = [Paragraph("10. ACEPTACIÓN Y FIRMAS", S["h"]),
              Paragraph("El comprador declara haber revisado la información consignada en el presente contrato y "
                        "manifiesta su conformidad con las condiciones de compraventa aquí establecidas.", S["j"])]
    firmas += _firmas_dobles(S, "FIRMA DEL COMPRADOR", "FIRMA DEL CONCESIONARIO")
    el.append(KeepTogether(firmas))
    return _construir(el, "leo", titulo="Contrato de compraventa")

# ----------------------------------------------------------------------------
# 2) GARANTÍA (003)
# ----------------------------------------------------------------------------
def garantia_pdf(c):
    S = _estilos()
    el = [Paragraph("LEO MOTOS PERÚ", S["marca"]),
          Paragraph("CERTIFICADO DE GARANTIA", S["titulo"])]
    el += _bloque_partes(S, c)
    el.append(Paragraph("4. ALCANCE DE LA GARANTÍA", S["h"]))
    el.append(Paragraph("La garantía comercial es otorgada exclusivamente por el fabricante o la marca de la "
                        "motocicleta, no por Leo Motos Perú Motorcycle Shop E.I.R.L. Tiene una vigencia de un (1) año "
                        "o 10000 km, lo que ocurra primero. Está orientada principalmente a defectos de fabricación "
                        "relacionados con el motor. Cualquier otra cobertura dependerá exclusivamente de la evaluación "
                        "técnica y de las políticas vigentes del fabricante.", S["j"]))
    el.append(Paragraph("5. REQUISITOS PARA CONSERVAR LA GARANTÍA", S["h"]))
    for t in ["Realizar los mantenimientos dentro del tiempo o kilometraje establecido.",
              "Presentar la cartilla de mantenimientos.", "Seguir las recomendaciones de uso.",
              "Utilizar lubricantes y repuestos recomendados.", "No modificar el motor ni componentes originales."]:
        el.append(_fila_casilla(True, t, S["campo"], verde=True))
    el.append(Paragraph("6. EXCLUSIONES DE GARANTÍA", S["h"]))
    for t in ["Desgaste normal y piezas de desgaste o consumibles.",
              "Mantenimientos fuera del plazo o realizados por talleres no autorizados.",
              "Accidentes, golpes, caídas, inundaciones o incendios.",
              "Uso indebido, sobrecarga, modificaciones o reparaciones no autorizadas.",
              "Cualquier situación que la marca no considere defecto de fabricación."]:
        el.append(Paragraph(t, S["bulletn"], bulletText="•"))
    el.append(Paragraph("7. PROCEDIMIENTO", S["h"]))
    el.append(Paragraph("Las solicitudes de garantía serán recibidas por Leo Motos y evaluadas conforme a las políticas "
                        "del fabricante. El ingreso de la motocicleta no implica la aprobación automática de la garantía. "
                        "El plazo referencial de atención es de hasta 15 días calendario, pudiendo ampliarse cuando la "
                        "marca requiere evaluación adicional o repuestos.", S["j"]))
    firmas = [Paragraph("8. ACEPTACIÓN Y FIRMAS", S["h"]),
              Paragraph("El comprador declara haber revisado la información consignada en el presente contrato y "
                        "manifiesta su conformidad con las condiciones aquí establecidas.", S["j"])]
    firmas += _firmas_dobles(S, "FIRMA DEL COMPRADOR", "FIRMA DEL CONCESIONARIO")
    el.append(KeepTogether(firmas))
    return _construir(el, "num", titulo="Certificado de garantía")

# ----------------------------------------------------------------------------
# 3) CHECKLIST DE REVISIÓN (004)
# ----------------------------------------------------------------------------
def checklist_pdf(c):
    S = _estilos(9.5)
    d = c["d"]
    fecha = d.get("fecha_entrega") or hoy_lima().strftime("%d/%m/%Y")
    el = [Spacer(1, 18), Paragraph("CHECKLIST DE REVISIÓN DEL VEHÍCULO",
          ParagraphStyle("t", fontName=FB, fontSize=11, textColor=AZUL_OSC, alignment=TA_CENTER, spaceAfter=24))]
    P = lambda t: Paragraph(t, S["celda"])
    datos = Table([[P(f"Cliente: {_x(d.get('nombre'))}"), P(f"DNI: {_x(d.get('num_doc'))}")],
                   [P(f"Marca: {_x(d.get('marca'))}"), P(f"Color: {_x(d.get('color'))}")],
                   [P(f"Modelo : {_x(d.get('modelo'))}"), P(f"Fecha: {_x(fecha)}")],
                   [P(f"VIN / Chasis: {_x(d.get('chasis'))}"), P(f"Responsable: {_x(d.get('responsable'))}")],
                   [P(f"Kilometraje: {_x(d.get('km'))}"), P(f"Llaves: {_x(d.get('llaves'))}")]],
                  colWidths=[290, 142])
    datos.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.6, colors.black),
                               ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    el += [datos, Spacer(1, 12), Paragraph("Revisión realizada junto al cliente al momento de la entrega.", S["p"])]
    izq = ["Faro", "Luz de freno", "Direccionales", "Claxon", "Tablero"]
    der = ["Motor", "Embrague", "Frenos", "Dirección", "Velocímetro", "Sonido del motor", "Nivel de aceite"]
    filas = [[P("1. SISTEMA ELÉCTRICO"), P("2. PRUEBA DE FUNCIONAMIENTO")]]
    for i in range(7):
        a = _fila_casilla(False, izq[i], S["celda"], ancho=205) if i < len(izq) else ""
        b = _fila_casilla(False, der[i], S["celda"], ancho=205)
        filas.append([a, b])
    t = Table(filas, colWidths=[216, 216])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.6, colors.black), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                           ("LEFTPADDING", (0, 0), (-1, -1), 5)]))
    el += [t, Paragraph("Observaciones", S["obs"])]
    for _ in range(3):
        el.append(Paragraph("_" * 76, S["linea"]))
    el += [Paragraph("Conformidad", S["obs"]),
           Paragraph("El cliente recibe la motocicleta conforme y en buen estado.", S["p"]),
           Spacer(1, 34)]
    raya = "-" * 34
    f = Table([[Paragraph(raya, S["p"]), Paragraph("_" * 26, S["p"])],
               [Paragraph("El CLIENTE", S["p"]), Paragraph("EL RESPONSABLE", S["p"])]], colWidths=[216, 216])
    f.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    el.append(KeepTogether([f]))
    return _construir(el, "none", margenes=(90, 90, 72, 72), titulo="Checklist de revisión")

# ----------------------------------------------------------------------------
# 4) ACTA DE ENTREGA (005)
# ----------------------------------------------------------------------------
def acta_pdf(c):
    S = _estilos()
    d = c["d"]
    el = [Paragraph("LEO MOTOS PERU", S["tituloazul"]),
          Paragraph("ACTA DE ENTREGA DE MOTOCICLETA",
                    ParagraphStyle("t2", fontName=FB, fontSize=11, textColor=AZUL, alignment=TA_CENTER, spaceAfter=8))]
    el += _bloque_partes(S, c)
    el.append(Paragraph("4. ACCESORIOS Y DOCUMENTOS ENTREGADOS", S["h"]))
    llaves = (d.get("llaves") or "").strip()
    juegos = f"{llaves} juegos de llaves." if llaves and llaves != "1" else "1 juego de llaves."
    for t in ["Manual del usuario (físico / digital).", "Manual o certificado de garantía (físico / digital).",
              "Cartilla de mantenimiento (física / digital).", "Recomendaciones de uso de la motocicleta.",
              juegos, "Casco certificado.", "Otros: __________"]:
        el.append(Paragraph(_x(t), S["linea"]))
    fecha = d.get("fecha_entrega") or "____ / ____ / ______"
    km = d.get("km") or "__________"
    s5 = [Paragraph("5. ACEPTACIÓN Y FIRMAS", S["h"]),
          Paragraph("Declaro haber revisado la información consignada en la presente acta y manifiesto mi conformidad "
                    "con la entrega de la motocicleta, sus accesorios y documentos detallados en ella.", S["b"]),
          Paragraph("En la fecha indicada, Leo Motos Perú Motorcycle Shop E.I.R.L. hace entrega de la motocicleta "
                    "descrita en la presente acta, dejando constancia de lo siguiente:", S["b"])]
    for t in ["Participé en la revisión física de la motocicleta junto con el mecánico o asesor comercial, mediante el "
              "Checklist de Revisión y Entrega del Vehículo.",
              "Recibí la motocicleta, así como los accesorios y documentos detallados en el punto 4 de la presente acta.",
              "Recibí las indicaciones sobre los mantenimientos que debo realizar conforme a la cartilla de mantenimiento.",
              "Recibí el documento de recomendaciones para el uso y cuidado de la motocicleta."]:
        s5.append(_fila_casilla(False, f"<b>{_x(t)}</b>", S["campo"]))
    s5.append(Paragraph(f"<b>Lugar de entrega: Leo Motos Perú – SMP.<br/>Fecha: {_x(fecha)}<br/>Hora: __________<br/>"
                        f"Kilometraje de entrega: {_x(km)} km.</b>", S["p"]))
    el.append(KeepTogether(s5))
    firmas = _firmas_dobles(S, "FIRMA DEL COMPRADOR o Autorizado", "FIRMA DEL CONCESIONARIO", espacio=24)
    el.append(KeepTogether(firmas))
    return _construir(el, "leo", titulo="Acta de entrega")

# ----------------------------------------------------------------------------
# 5) SEPARACIÓN EN PISO (007) y 6) VEHÍCULO A PEDIDO (008)
# ----------------------------------------------------------------------------
def _fecha_larga(c):
    f = parsear_fecha(c["d"].get("fecha", "")) or hoy_lima()
    return f.day, MESES[f.month - 1], f.year

def _firma_vendedor_comprador(S):
    t = Table([[Paragraph("EL VENDEDOR", S["pc"]), Paragraph("EL COMPRADOR", S["pc"])]], colWidths=[216, 216])
    t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    return [Spacer(1, 60), t]

def separacion_piso_pdf(c):
    S = _estilos(10.5)
    d = c["d"]
    monto = c["monto_sep"]
    dia, mes, anio = _fecha_larga(c)
    tipo_txt = TIPO_DOC_TXT.get(c.get("tipo"), "DNI/CE")
    ret = round(monto * 0.20, 2)
    nombre = _x(d.get("nombre"))
    el = [Paragraph("CONDICIONES DE SEPARACIÓN DE VEHÍCULO (MOTOCICLETA)", S["titulo_sep"]),
          Paragraph(f"En la ciudad de Lima, a los {dia} días del mes de {mes} de {anio}, el presente documento se celebra "
                    f"entre LEO MOTOS PERU MOTORCYCLE SHOP EIRL con RUC N.º 20606384212, en adelante EL VENDEDOR, y "
                    f"{nombre}, identificado(a) con {tipo_txt} N.º {_x(d.get('num_doc'))} en adelante EL CLIENTE, bajo las "
                    f"siguientes condiciones:", S["j"]),
          Spacer(1, 8),
          Paragraph("1. OBJETO", S["hs"]),
          Paragraph(f"El CLIENTE entrega a EL VENDEDOR la suma de {_sp(monto)} ({_x(numero_a_letras(monto))}) por concepto "
                    f"de separación del vehículo, con la finalidad de preservar la motocicleta y asegurar su "
                    f"disponibilidad exclusiva hasta la fecha estimada para concretar la compra.", S["j"]),
          Paragraph("Datos del vehículo:", S["p"])]
    modelo = " ".join(x for x in [d.get("modelo"), d.get("color")] if x)
    for t in [f"Marca: {d.get('marca', '')}", f"Modelo: {modelo}", f"Año: {d.get('anio', '')}",
              f"Precio de venta del vehículo: {_sp(c['precio'])}"]:
        el.append(Paragraph(_x(t), S["bulletn"], bulletText="•"))
    el += [Spacer(1, 4),
           Paragraph("EL CLIENTE declara haber efectuado el pago indicado, el cual corresponde a la cancelación parcial del "
                     "precio de la motocicleta descrita, quedando reservada a su nombre.", S["j"]),
           Paragraph("2. NATURALEZA DEL DOCUMENTO", S["hs"]),
           Paragraph("Las partes acuerdan que la presente constancia no constituye contrato de compraventa ni implica "
                     "entrega del vehículo, la cual se realizará en fecha posterior, oportunidad en el cual se suscribió el "
                     "Contrato de Compraventa y Entrega de Motocicleta correspondiente.", S["j"]),
           Paragraph("3. PLAZO DE SEPARACIÓN", S["hs"]),
           Paragraph("La separación del vehículo tendrá una vigencia de 7 días calendario, contados desde la fecha de firma "
                     "del presente documento. Dentro de dicho plazo, el CLIENTE deberá concretar la compra del vehículo "
                     "mediante el pago del saldo correspondiente. Durante el periodo de separación, el vehículo no será "
                     "ofrecido ni vendido a terceros.", S["j"]),
           Paragraph("4. DESISTIMIENTO DEL CLIENTE Y RETENCIÓN PARCIAL", S["hs"]),
           Paragraph("El CLIENTE es informado de manera clara y expresa que, si decide no continuar con la compra del "
                     "vehículo por decisión propia, o si no concreta la compra dentro del plazo de separación establecido, "
                     "por causa imputable a su decisión, EL VENDEDOR retendrá el equivalente al veinte por ciento (20%) del "
                     f"monto entregado por separación, hasta un monto máximo de S/ {ret:,.2f}, como compensación razonable "
                     "por los gastos administrativos, comerciales y por la inmovilización del vehículo.", S["j"]),
           Paragraph("El saldo restante del monto entregado será devuelto al CLIENTE dentro de un plazo de 3 días hábiles, "
                     "contados desde la comunicación del desistimiento o desde el vencimiento del plazo de separación.", S["j"]),
           Paragraph("5. IMPUTABILIDAD", S["hs"]),
           Paragraph("La retención parcial establecida en la cláusula anterior sólo será aplicable cuando el desistimiento "
                     "o la no concreción de la compra sea imputable al CLIENTE.", S["j"]),
           Paragraph("No será aplicable dicha retención en caso de imposibilidad de entrega del vehículo atribuible a EL "
                     "VENDEDOR.", S["j"])]
    cierre = [Paragraph("6. INFORMACIÓN Y ACEPTACIÓN", S["hs"]),
              Paragraph("El CLIENTE declara haber recibido información clara, suficiente y oportuna sobre las condiciones "
                        "de la separación, el plazo establecido y la retención parcial aplicable en caso de desistimiento.",
                        S["j"]),
              Paragraph(f"Yo, {nombre}, identificado(a) con {tipo_txt} N.º {_x(d.get('num_doc'))}, declaro que he leído, "
                        "entendido y aceptado todas las condiciones del presente documento, especialmente aquellas referidas "
                        "a la retención del veinte por ciento (20%) del monto entregado por separación, hasta el monto "
                        "máximo indicado, en caso de desistimiento o de no concretar la compra dentro del plazo establecido, "
                        "firmando de manera libre y voluntaria.", S["j"])]
    cierre += _firma_vendedor_comprador(S)
    el.append(KeepTogether(cierre))
    return _construir(el, "sep", margenes=(85, 85, 70, 70), titulo="Separación de vehículo en piso")

def separacion_pedido_pdf(c):
    S = _estilos(10.5)
    d = c["d"]
    monto = c["monto_sep"]
    dia, mes, anio = _fecha_larga(c)
    tipo_txt = TIPO_DOC_TXT.get(c.get("tipo"), "DNI/CE")
    nombre = _x(d.get("nombre"))
    plazo = _x(d.get("plazo") or "")
    el = [Paragraph("CONDICIONES DE SEPARACIÓN DE VEHÍCULO (MOTOCICLETA) – VEHÍCULO POR PEDIDO", S["titulo_sep"]),
          Paragraph(f"En la ciudad de Lima, a los {dia} días del mes de {mes} del {anio}, el presente documento se celebra "
                    f"entre LEO MOTOS PERU MOTORCYCLE SHOP E.I.R.L., con RUC N.º 20606384212, en adelante EL VENDEDOR, "
                    f"{nombre}, identificado(a) con {tipo_txt} N.º {_x(d.get('num_doc'))}, en adelante EL CLIENTE, bajo las "
                    f"siguientes condiciones:", S["j"]),
          Spacer(1, 6),
          Paragraph("1. OBJETO", S["hs"]),
          Paragraph(f"El CLIENTE entrega a EL VENDEDOR la suma de {_sp(monto)} ({_x(numero_a_letras(monto))}) por concepto "
                    "de separación y adelanto de pago, con la finalidad de reservar y adquirir una motocicleta solicitada "
                    "expresamente a pedido del CLIENTE, la cual no se encuentra en stock y ha sido o será comprada "
                    "exclusivamente para atender dicho pedido, asumiendo EL VENDEDOR costos administrativos, comerciales, "
                    "logísticos, de importación y la inmovilización del bien.", S["j"]),
          Paragraph("Datos del vehículo:", S["linea"]),
          Paragraph(f"Marca: {_x(d.get('marca'))}", S["linea"]),
          Paragraph(f"Modelo: {_x(d.get('modelo'))}", S["linea"]),
          Paragraph(f"Color: {_x(d.get('color'))}", S["linea"]),
          Paragraph(f"Precio: {_sp(c['precio'])}", S["p"]),
          Paragraph("2. DESISTIMIENTO DEL CLIENTE", S["hs"]),
          Paragraph("En caso de desistimiento voluntario de la compra por causa imputable al CLIENTE, el monto entregado "
                    "por separación no será devuelto, hasta el límite del tope máximo aplicable según el valor total del "
                    "vehículo, por tratarse de un bien adquirido a pedido expreso del CLIENTE.", S["j"]),
          Paragraph("La retención aplicable será la menor entre el monto efectivamente entregado y el tope máximo "
                    "establecido, conforme al siguiente cuadro:", S["j"])]
    for t in ["Vehículos hasta S/ 7,000.00 → Tope máximo de retención: S/ 500.00",
              "Vehículos desde S/ 7,001.00 hasta S/ 15,000.00 → Tope máximo de retención: S/ 1000.00",
              "Vehículos mayores a S/ 15,000.00 → Tope máximo de retención: S/ 1500.00"]:
        el.append(Paragraph(_x(t).replace("→", "-&gt;"), S["bulletn"], bulletText="•"))
    el += [Spacer(1, 4),
           Paragraph("Dicho monto será retenido como compensación razonable por los gastos administrativos, comerciales, "
                     "de adquisición, importación, logística e inmovilización del vehículo, conforme a la normativa vigente "
                     "de protección al consumidor.", S["j"]),
           Paragraph("3. IMPOSIBILIDAD NO IMPUTABLE AL CLIENTE", S["hs"]),
           Paragraph("En caso de que la operación no pueda concretarse por causas no imputables al CLIENTE, EL VENDEDOR "
                     "procederá a la devolución del monto entregado, descontando únicamente los gastos efectivamente "
                     "asumidos y debidamente sustentados, de ser el caso, dentro de un plazo máximo de 3 días hábiles.", S["j"]),
           Paragraph("4. PLAZO DE ENTREGA DEL VEHÍCULO A PEDIDO", S["hs"]),
           Paragraph("El CLIENTE declara conocer y aceptar que, al tratarse de un vehículo solicitado a pedido y no "
                     "disponible en stock, el plazo de entrega no es inmediato y será variable, dependiendo de factores "
                     "logísticos, comerciales, de importación, disponibilidad del proveedor, transporte, trámites "
                     "administrativos y/o aduaneros.", S["j"]),
           Paragraph(f"EL VENDEDOR informará al CLIENTE el plazo estimado de entrega, {plazo} o el tiempo que "
                     "razonablemente sea necesario, sin que dicho plazo constituya una fecha fija o improrrogable.", S["j"]),
           Paragraph("Cualquier retraso razonable derivado de causas ajenas a EL VENDEDOR no será considerado "
                     "incumplimiento, siempre que se mantenga comunicación con el CLIENTE sobre el estado del pedido.", S["j"]),
           Paragraph("5. PAGO DEL SALDO E INCUMPLIMIENTO", S["hs"]),
           Paragraph("El CLIENTE declara conocer que caso exista un saldo pendiente, éste deberá ser cancelado íntegramente "
                     "cuando el vehículo se encuentre disponible en piso, antes de su entrega física y de la suscripción "
                     "del contrato de compraventa correspondiente.", S["j"]),
           Paragraph("Una vez que EL VENDEDOR comunique al CLIENTE que el vehículo se encuentra disponible en piso, el "
                     "CLIENTE contará con un plazo máximo de 7 días calendario para cancelar el saldo pendiente.", S["j"]),
           Paragraph("Vencido dicho plazo sin que el CLIENTE cumpla con el pago total por causa imputable a su decisión, se "
                     "considerará que el CLIENTE desiste de la compra, siendo aplicable lo establecido en la cláusula de "
                     "desistimiento y retención, quedando EL VENDEDOR facultado para resolver la reserva y disponer "
                     "libremente del vehículo.", S["j"])]
    cierre = [Paragraph("DECLARACIÓN DEL CLIENTE", S["hs"]),
              Paragraph(f"Yo, {nombre}, identificado(a) con {tipo_txt} N.º {_x(d.get('num_doc'))}, declaro que he leído, "
                        "entendido y aceptado las condiciones del presente documento, especialmente aquellas referidas a la "
                        "retención del monto entregado en caso de desistimiento voluntario, reconociendo que la motocicleta "
                        "ha sido adquirida a pedido y exclusivamente para mi compra, firmando en señal de conformidad.", S["j"])]
    cierre += _firma_vendedor_comprador(S)
    el.append(KeepTogether(cierre))
    return _construir(el, "sep", margenes=(85, 70, 62, 70), titulo="Separación de vehículo a pedido")

# ----------------------------------------------------------------------------
# 7) CONTRATO PARA VENTAS CON GLOBAL GO (2_2)
# ----------------------------------------------------------------------------
def contrato_globalgo_pdf(c):
    S = _estilos()
    d, pagos, precio = c["d"], c["pagos"], c["precio"]
    tipo_txt = {"DNI": "DNI", "RUC": "RUC", "CE": "CE"}.get(c.get("tipo"), d.get("tipo_doc", ""))
    contacto = " / ".join(x for x in [d.get("celular"), d.get("direccion"), d.get("correo")] if x)

    def tabla(filas):
        t = Table([[Paragraph(_x(a), S["celda"]), Paragraph(_x(b), S["celda"])] for a, b in filas],
                  colWidths=[165, 267])
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.6, colors.black),
                               ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
        return t

    el = [Paragraph("CONTRATO DE COMPRAVENTA DE MOTOCICLETA NUEVA (0 KM)", S["tituloazul"]),
          Paragraph("LEO MOTOS PERU - VENTA FINANCIADA POR GLOBAL GO",
                    ParagraphStyle("t3", fontName=F, fontSize=9.5, alignment=TA_CENTER, spaceAfter=10)),
          Paragraph("DATOS DE LAS PARTES", S["h"]),
          tabla([("Vendedor", "Leo Motos Perú Motorcycle Shop E.I.R.L."), ("RUC", "20606384212"),
                 ("Domicilio", "TOMAS VALLE 1641- SAN MARTIN DE PORRES"), ("Comprador", d.get("nombre", "")),
                 (f"{tipo_txt} " if False else "DNI / CE", d.get("num_doc", "")),
                 ("Estado civil", d.get("estado_civil", "")), ("Celular / Correo / Domicilio", contacto)]),
          Paragraph("DATOS DE LA MOTOCICLETA", S["h"]),
          tabla([("Marca", d.get("marca", "")), ("Modelo", d.get("modelo", "")), ("Año", d.get("anio", "")),
                 ("Color", d.get("color", "")), ("N.° de Chasis", d.get("chasis", "")),
                 ("N.° de Motor", d.get("motor", ""))]),
          Paragraph("PRECIO DE VENTA", S["h"]),
          Paragraph(f"Precio total: {_s(precio)} ({_x(numero_a_letras(precio))}).", S["campo"]),
          Paragraph("FORMA DE PAGO", S["h"]), _tabla_pagos(S, pagos), Spacer(1, 8),
          Paragraph("El COMPRADOR declara conocer que el financiamiento de la motocicleta ha sido gestionado mediante "
                    "GlobalGo. Las obligaciones derivadas del contrato de financiamiento, incluyendo el cronograma de pagos, "
                    "garantías, intereses, garantía mobiliaria y demás condiciones financieras, se regirán exclusivamente "
                    "por los documentos suscritos entre el COMPRADOR y GlobalGo, no formando parte del presente contrato de "
                    "compraventa celebrado con Leo Motos Perú Motorcycle Shop E.I.R.L..", S["j"]),
          Paragraph("GARANTÍA", S["h"]),
          Paragraph("La motocicleta cuenta con garantía del fabricante conforme a la cartilla de garantía. Para conservarla "
                    "vigente, el cliente deberá cumplir los mantenimientos establecidos.", S["j"]),
          Paragraph("REGALIAS OFRECIDAS", S["h"])]
    regalias = lista_regalias(d.get("regalias", ""), REGALIAS_ESTANDAR_GG)
    if regalias:
        for r in regalias:
            el.append(Paragraph(_x(r), S["bulletn"], bulletText="•"))
    else:
        el.append(Paragraph("Sin regalías.", S["p"]))
    if d.get("observaciones"):
        el.append(Paragraph("OBSERVACIONES DE REGALÍAS", S["h"]))
        el.append(Paragraph(_x(d["observaciones"]).replace("\n", "<br/>"), S["p"]))
    firmas = [Paragraph("FIRMAS", S["h"]), Spacer(1, 10),
              Paragraph("Firma del cliente ____________________", S["p"]),
              Paragraph("Nombre: ____________________", S["linea"]),
              Paragraph("DNI: ____________________", S["linea"]),
              Paragraph("Fecha: ____/____/______", S["linea"])]
    el.append(KeepTogether(firmas))
    return _construir(el, "leo", titulo="Contrato de compraventa - Global Go")
