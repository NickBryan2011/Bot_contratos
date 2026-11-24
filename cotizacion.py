# -*- coding: utf-8 -*-
"""Cotizaciones de Leo Motos Perú (diseño beige / negro / amarillo)."""
import os
from io import BytesIO
from datetime import datetime, timezone, timedelta

from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Paragraph
from PIL import Image, ImageOps

W, H = 595.28, 841.89
MX = 40.6
CW = W - 2 * MX
C_BG = colors.HexColor("#F5F4EF")
C_DARK = colors.HexColor("#11141B")
C_YEL = colors.HexColor("#F4C400")
C_WHITE = colors.white
C_BORDER = colors.HexColor("#E3E2DA")
C_GRAY = colors.HexColor("#4A4F57")
C_LINE = colors.HexColor("#E3E3DB")

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]

# ---------------------------------------------------------------------------
# FUENTES (Inter = texto, Barlow Condensed = títulos); si faltan usa Helvetica
# ---------------------------------------------------------------------------
_FDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

def _reg(nombre, archivo, fallback):
    try:
        pdfmetrics.registerFont(TTFont(nombre, os.path.join(_FDIR, archivo)))
        return nombre
    except Exception as e:
        print("Fuente no disponible:", archivo, repr(e))
        return fallback

F_REG = _reg("Inter", "Inter-Regular.ttf", "Helvetica")
F_MED = _reg("Inter-Medium", "Inter-Medium.ttf", "Helvetica")
F_SEMI = _reg("Inter-SemiBold", "Inter-SemiBold.ttf", "Helvetica-Bold")
F_BOLD = _reg("Inter-Bold", "Inter-Bold.ttf", "Helvetica-Bold")
F_TIT = _reg("BarlowCondensed-Bold", "BarlowCondensed-Bold.ttf", "Helvetica-Bold")
try:
    pdfmetrics.registerFontFamily("Inter", normal=F_REG, bold=F_BOLD, italic=F_REG, boldItalic=F_BOLD)
except Exception:
    pass


def fecha_larga(dt=None):
    dt = dt or datetime.now(timezone(timedelta(hours=-5)))
    return f"Lima, {dt.day} de {MESES[dt.month - 1]} de {dt.year}"


def money(v):
    """17000 -> 'S/ 17,000'  |  1359.5 -> 'S/ 1,359.50'"""
    if abs(v - round(v)) < 0.005:
        return f"S/ {int(round(v)):,}"
    return f"S/ {v:,.2f}"


def preparar_foto(datos):
    """Bytes de una foto -> JPEG RGB (máx. 1400 px), respetando la orientación."""
    im = Image.open(BytesIO(datos))
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        fondo = Image.new("RGB", im.size, (255, 255, 255))
        fondo.paste(im, mask=im.split()[-1])
        im = fondo
    else:
        im = im.convert("RGB")
    im.thumbnail((1400, 1400))
    out = BytesIO()
    im.save(out, "JPEG", quality=86)
    return out.getvalue()


class Hoja:
    def __init__(self):
        self.buf = BytesIO()
        self.c = canvas.Canvas(self.buf, pagesize=(W, H))
        self.c.setTitle("Cotización - Leo Motos Perú")
        self.y = 0
        self.primera = True
        self._fondo()

    # --- primitivas -------------------------------------------------------
    def _fondo(self):
        self.c.setFillColor(C_BG)
        self.c.rect(0, 0, W, H, stroke=0, fill=1)

    def nueva_pagina(self):
        self.c.showPage()
        self._fondo()
        self.y = 40
        self.primera = False

    def necesita(self, alto):
        if self.y + alto > H - 42:
            self.nueva_pagina()

    def Y(self, y):
        return H - y

    def caja(self, x, y, w, h, fill=C_WHITE, borde=C_BORDER, grosor=0.7):
        c = self.c
        c.setFillColor(fill)
        if borde is None:
            c.rect(x, self.Y(y + h), w, h, stroke=0, fill=1)
        else:
            c.setStrokeColor(borde); c.setLineWidth(grosor)
            c.rect(x, self.Y(y + h), w, h, stroke=1, fill=1)

    def linea(self, x1, x2, y, color=C_LINE, grosor=0.7):
        self.c.setStrokeColor(color); self.c.setLineWidth(grosor)
        self.c.line(x1, self.Y(y), x2, self.Y(y))

    def texto(self, x, y, s, fuente, tam, color=C_DARK, tr=0.0, alinear="l"):
        s = str(s)
        ancho = stringWidth(s, fuente, tam) + tr * len(s)
        if alinear == "r":
            x = x - ancho
        elif alinear == "c":
            x = x - ancho / 2
        t = self.c.beginText()
        t.setTextOrigin(x, self.Y(y))
        t.setFont(fuente, tam)
        t.setFillColor(color)
        t.setCharSpace(tr)
        t.textOut(s)
        self.c.drawText(t)
        return ancho

    def ajustar(self, s, fuente, tam_max, ancho_max, tam_min=12):
        tam = tam_max
        while tam > tam_min and stringWidth(s, fuente, tam) > ancho_max:
            tam -= 1
        return tam

    def parrafo(self, html, x, y, ancho, fuente=None, tam=10.5, leading=13.5, color=C_DARK, dibujar=True):
        st = ParagraphStyle("p", fontName=fuente or F_REG, fontSize=tam, leading=leading, textColor=color)
        p = Paragraph(html, st)
        _, h = p.wrap(ancho, 1000)
        if dibujar:
            p.drawOn(self.c, x, self.Y(y + h))
        return h

    def dividir(self, s, fuente, tam, ancho):
        palabras, lineas, act = s.split(), [], ""
        for p in palabras:
            prueba = (act + " " + p).strip()
            if stringWidth(prueba, fuente, tam) <= ancho:
                act = prueba
            else:
                if act: lineas.append(act)
                act = p
        if act: lineas.append(act)
        return lineas or [""]

    def foto(self, datos, x, y, w, h, pad=10):
        try:
            img = ImageReader(BytesIO(datos))
            iw, ih = img.getSize()
            esc = min((w - 2 * pad) / iw, (h - 2 * pad) / ih)
            dw, dh = iw * esc, ih * esc
            self.c.drawImage(img, x + (w - dw) / 2, self.Y(y + (h + dh) / 2), dw, dh, mask=None)
        except Exception as e:
            print("foto no válida:", repr(e))

    # --- bloques ----------------------------------------------------------
    def encabezado(self, fecha_txt):
        self.texto(MX, 58, "LEO MOTOS PERÚ", F_TIT, 31)
        self.texto(MX, 72, "MOTORCYCLE SHOP E.I.R.L. · RUC 20606384212", F_MED, 7.6, C_GRAY, tr=1.7)
        self.texto(W - MX, 57, "COTIZACIÓN", F_TIT, 26, alinear="r")
        self.texto(W - MX, 71, fecha_txt, F_REG, 8.6, C_GRAY, alinear="r")
        self.linea(MX, W - MX, 86, C_DARK, 1.8)
        self.y = 107

    def tarjetas_cliente(self, cliente, doc, vend):
        ancho = (CW - 12.3) / 2
        xs = [MX, MX + ancho + 12.3]
        contenidos = []
        sub_c = ""
        if doc:
            d = "".join(ch for ch in doc if ch.isdigit())
            sub_c = f"{'DNI' if len(d) == 8 else 'RUC' if len(d) == 11 else 'DOC.'}: {doc}"
        contenidos.append(("CLIENTE", cliente.upper(), sub_c))
        if doc:  # trato formal: vende la empresa
            contenidos.append(("VENDEDOR", "LEO MOTOS PERÚ MOTORCYCLE SHOP E.I.R.L.", "RUC: 20606384212"))
        else:
            nombre = vend["nombre"].upper() + (f" · {vend['cargo'].upper()}" if vend.get("cargo") else "")
            contenidos.append(("VENDEDOR", nombre, f"Leo Motos Perú · {vend['tel']}"))
        # alturas
        lineas_n = [self.dividir(n, F_TIT, 18, ancho - 28) for _, n, _ in contenidos]
        alto = max(68, max(14 + 11 + 23 * len(l) + (14 if s else 0) + 8 for l, (_, _, s) in zip(lineas_n, contenidos)))
        for x, (et, nom, sub), lns in zip(xs, contenidos, lineas_n):
            self.caja(x, self.y, ancho, alto)
            self.texto(x + 14, self.y + 21, et, F_SEMI, 7, C_GRAY, tr=1.6)
            yy = self.y + 42
            for ln in lns:
                self.texto(x + 14, yy, ln, F_TIT, 18)
                yy += 19
            if sub:
                self.texto(x + 14, yy + 1, sub, F_REG, 8.6, C_GRAY)
        self.y += alto + 14

    # moto (diseño A): marca/modelo a la izquierda, precio a la derecha
    def moto_A(self, marca, color, modelo, etiqueta, texto_precio, precio):
        h = 82
        self.caja(MX, self.y, CW, h)
        sub = " · ".join(x for x in [marca.upper(), f"COLOR {color.upper()}" if color else ""] if x)
        self.texto(MX + 16, self.y + 24, sub, F_SEMI, 7, C_GRAY, tr=1.6)
        t = self.ajustar(modelo, F_TIT, 36, CW * 0.55 - 20)
        self.texto(MX + 16, self.y + 62, modelo, F_TIT, t)
        self.texto(W - MX - 16, self.y + 27, (texto_precio or "PRECIO").upper(), F_SEMI, 7, C_GRAY, tr=1.6, alinear="r")
        self.texto(W - MX - 16, self.y + 62, money(precio), F_TIT, 36, alinear="r")
        if etiqueta:
            self._etiqueta(MX + 16 + stringWidth(modelo, F_TIT, t) + 10, self.y + 38, etiqueta)
        self.y += h + 12

    def _etiqueta(self, x, y, txt, alinear="l"):
        txt = txt.upper()
        w = stringWidth(txt, F_BOLD, 7.4) + 1.8 * len(txt) + 18
        if alinear == "r":
            x = x - w
        self.c.setFillColor(C_YEL)
        self.c.rect(x, self.Y(y + 19), w, 19, stroke=0, fill=1)
        self.texto(x + 9, y + 13, txt, F_BOLD, 7.4, C_DARK, tr=1.8)
        return w

    def foto_card(self, fotos, alto):
        if not fotos:
            return
        self.caja(MX, self.y, CW, alto)
        n = len(fotos)
        ancho = CW / n
        for i, f in enumerate(fotos):
            self.foto(f, MX + i * ancho, self.y, ancho, alto, pad=12)
        self.y += alto + 12

    # moto (diseño B): foto dentro de la tarjeta, precio abajo
    def moto_B(self, marca, color, modelo, etiqueta, texto_precio, precio, foto):
        alto_foto = 170 if foto else 0
        h = 72 + ((alto_foto + 10) if foto else 0) + 46
        self.necesita(h + 20)
        self.caja(MX, self.y, CW, h)
        sub = " · ".join(x for x in [marca.upper(), f"COLOR {color.upper()}" if color else ""] if x)
        self.texto(MX + 16, self.y + 26, sub, F_SEMI, 7, C_GRAY, tr=1.6)
        t = self.ajustar(modelo, F_TIT, 40, CW - 190)
        self.texto(MX + 16, self.y + 62, modelo, F_TIT, t)
        if etiqueta:
            self._etiqueta(W - MX - 16, self.y + 32, etiqueta, alinear="r")
        yy = self.y + 72
        if foto:
            self.foto(foto, MX, yy, CW, alto_foto, pad=6)
            yy += alto_foto + 10
        self.linea(MX + 16, W - MX - 16, yy, C_LINE, 0.8)
        self.texto(MX + 16, yy + 29, (texto_precio or "PRECIO").upper(), F_SEMI, 7, C_GRAY, tr=1.6)
        self.texto(W - MX - 16, yy + 34, money(precio), F_TIT, 34, alinear="r")
        self.y += h + 16

    def _items(self, textos, ancho):
        """Altura de cada fila de lista (con paréntesis en gris y más pequeño)."""
        out = []
        for t in textos:
            html = t.replace("&", "&amp;").replace("<", "&lt;")
            if "(" in html:
                a, b = html.split("(", 1)
                html = f'{a}<font size="8.6" color="#4A4F57">({b}</font>'
            h = self.parrafo(html, 0, 0, ancho - 20, F_REG, 10.4, 13, dibujar=False)
            out.append((html, h + 13))
        return out

    def listas_A(self, regalos, bono, incluye):
        colw = (CW - 24) / 2
        izq = self._items(regalos, colw)
        der = self._items(incluye, colw)
        alto = 58 + max(sum(h for _, h in izq), sum(h for _, h in der))
        self.necesita(alto + 10)
        for x, titulo, items, con_bono in [(MX, "ACCESORIOS DE REGALO", izq, True),
                                          (MX + colw + 24, "INCLUYE", der, False)]:
            if not items:
                continue
            self.texto(x, self.y + 19, titulo, F_TIT, 19)
            if con_bono and bono:
                self._etiqueta(x, self.y + 27, bono)
            self.linea(x, x + colw, self.y + 54, C_DARK, 1.3)
            yy = self.y + 54
            for html, h in items:
                self.texto(x + 2, yy + 17, "+", F_BOLD, 10.5)
                self.parrafo(html, x + 20, yy + 5, colw - 20, F_REG, 10.4, 13)
                yy += h
                self.linea(x, x + colw, yy, C_LINE, 0.7)
        self.y += alto + 4

    def barra_final(self, lineas, monto):
        self.necesita(76)
        self.caja(MX, self.y, CW, 62, fill=C_DARK, borde=None)
        yy = self.y + 28 if len(lineas) > 1 else self.y + 35
        for ln in lineas:
            self.texto(MX + 28, yy, ln.upper(), F_BOLD, 7.8, C_YEL, tr=1.8)
            yy += 11
        self.texto(W - MX - 28, self.y + 44, money(monto), F_TIT, 40, C_WHITE, alinear="r")
        self.y += 62 + 12

    def contacto_banda(self, vend):
        self.necesita(50)
        self.caja(MX, self.y, CW, 46, fill=C_YEL, borde=None)
        self.texto(MX + 16, self.y + 17, "CONTACTO COMERCIAL", F_BOLD, 7, C_DARK, tr=1.8)
        nom = vend["nombre"] + (f" · {vend['cargo']}" if vend.get("cargo") else "") + " · Leo Motos Perú"
        self.texto(MX + 16, self.y + 33, nom, F_SEMI, 10, C_DARK)
        self.texto(W - MX - 16, self.y + 35, vend["tel"], F_TIT, 30, C_DARK, alinear="r")
        self.y += 46 + 12

    def pie(self):
        y = H - 30
        if self.y > y - 6:
            self.nueva_pagina()
        self.linea(MX, W - MX, H - 38, C_DARK, 0.6)
        self.texto(MX, H - 26, "RUC 20606384212 · Leo Motos Perú Motorcycle Shop E.I.R.L.", F_REG, 8, C_GRAY)
        self.texto(W - MX, H - 26, "Documento sin valor tributario", F_REG, 8, C_GRAY, alinear="r")

    # --- accesorios -------------------------------------------------------
    def accesorios(self, items, pct, instalaciones):
        """items: [(cant, desc, pu)], instalaciones: [(desc, monto)] -> (subtotal, desc, neto, inst)"""
        sub = round(sum(c * p for c, _, p in items), 2)
        desc = round(sub * pct / 100.0, 2) if pct else 0.0
        neto = round(sub - desc, 2)
        inst = round(sum(m for _, m in instalaciones), 2)
        self.necesita(150)
        self.texto(MX, self.y + 20, "ACCESORIOS", F_TIT, 24)
        if pct:
            txt = f"{pct:g}% DE DESCUENTO EN ACCESORIOS"
            w = stringWidth(txt, F_BOLD, 7.4) + 1.8 * len(txt) + 30
            self.caja(W - MX - w, self.y + 3, w, 22, fill=C_DARK, borde=None)
            self.texto(W - MX - w + 15, self.y + 18, txt, F_BOLD, 7.4, C_YEL, tr=1.8)
        self.y += 40

        def cabecera():
            self.texto(MX, self.y + 8, "DESCRIPCIÓN", F_SEMI, 6.8, C_GRAY, tr=1.7)
            self.texto(398, self.y + 8, "CANT.", F_SEMI, 6.8, C_GRAY, tr=1.7, alinear="c")
            self.texto(482, self.y + 8, "P. UNIT.", F_SEMI, 6.8, C_GRAY, tr=1.7, alinear="r")
            self.texto(W - MX, self.y + 8, "IMPORTE", F_SEMI, 6.8, C_GRAY, tr=1.7, alinear="r")
            self.linea(MX, W - MX, self.y + 16, C_DARK, 1.4)
            self.y += 16
        cabecera()
        for cant, d, pu in items:
            if self.y + 30 > H - 60:
                self.nueva_pagina(); cabecera()
            self.texto(MX, self.y + 19, d, F_REG, 10.5)
            self.texto(398, self.y + 19, f"{cant:g}", F_REG, 10.5, alinear="c")
            self.texto(482, self.y + 19, money(pu), F_REG, 10.5, alinear="r")
            self.texto(W - MX, self.y + 19, money(cant * pu), F_REG, 10.5, alinear="r")
            self.y += 29
            self.linea(MX, W - MX, self.y, C_LINE, 0.7)
        # subtotales
        self.necesita(100)
        if pct or instalaciones:
            self.y += 6
            self.texto(MX, self.y + 14, "Subtotal accesorios", F_REG, 10.5, C_GRAY)
            self.texto(W - MX, self.y + 14, money(sub), F_REG, 10.5, C_GRAY, alinear="r")
            self.y += 21
        if pct:
            self.texto(MX, self.y + 14, f"Descuento {pct:g}% (solo accesorios)", F_BOLD, 10.5)
            self.texto(W - MX, self.y + 14, "− " + money(desc), F_BOLD, 10.5, alinear="r")
            self.y += 21
            self.texto(MX, self.y + 14, "Accesorios con descuento", F_BOLD, 10.5)
            self.texto(W - MX, self.y + 14, money(neto), F_BOLD, 10.5, alinear="r")
            self.y += 21
        if instalaciones:
            self.linea(MX, W - MX, self.y + 4, C_LINE, 0.7)
            self.y += 6
            for d, m in instalaciones:
                self.necesita(30)
                self.texto(MX, self.y + 17, d, F_REG, 10.5)
                w = stringWidth(d, F_REG, 10.5)
                self.texto(MX + w + 5, self.y + 17, "· sin descuento", F_REG, 8.2, C_GRAY)
                self.texto(W - MX, self.y + 17, money(m), F_REG, 10.5, alinear="r")
                self.y += 22
        self.linea(MX, W - MX, self.y + 4, C_DARK, 1.6)
        self.y += 20
        return sub, desc, neto, inst

    def total_con_contacto(self, partes, total, vend):
        self.necesita(90)
        wl = 306
        self.caja(MX, self.y, wl, 72, fill=C_DARK, borde=None)
        self.texto(MX + 22, self.y + 25, "TOTAL", F_BOLD, 7.8, C_YEL, tr=1.8)
        sub = "(" + " + ".join(partes) + ")" if len(partes) > 1 else ""
        yy = self.y + 37
        if sub:
            for ln in self.dividir(sub, F_BOLD, 7.8, 125):
                self.texto(MX + 22, yy, ln, F_BOLD, 7.4, C_YEL, tr=1.5)
                yy += 10
        txt = money(total)
        t = self.ajustar(txt, F_TIT, 38, wl - 170)
        self.texto(MX + wl - 22, self.y + 47, txt, F_TIT, t, C_WHITE, alinear="r")
        x2 = MX + wl + 12
        w2 = W - MX - x2
        self.caja(x2, self.y, w2, 72, fill=C_YEL, borde=None)
        self.texto(x2 + 16, self.y + 20, "CONTACTO COMERCIAL", F_BOLD, 6.8, C_DARK, tr=1.7)
        self.texto(x2 + 16, self.y + 44, vend["tel"], F_TIT, 25, C_DARK)
        self.texto(x2 + 16, self.y + 57, vend["nombre"], F_BOLD, 8.6, C_DARK)
        if vend.get("cargo"):
            self.texto(x2 + 16, self.y + 67, f"{vend['cargo']} · Leo Motos Perú", F_REG, 7.8, C_DARK)
        self.y += 72 + 14

    def galeria(self, fotos):
        if not fotos:
            return
        self.necesita(150)
        n = len(fotos)
        ancho = (CW - 10 * (n - 1)) / n
        for i, f in enumerate(fotos):
            x = MX + i * (ancho + 10)
            self.caja(x, self.y, ancho, 130)
            self.foto(f, x, self.y, ancho, 130, pad=8)
        self.y += 130 + 16

    def cerrar(self):
        self.pie()
        self.c.save()
        return self.buf.getvalue()


# ---------------------------------------------------------------------------
# CONSTRUCTORES POR TIPO
# ---------------------------------------------------------------------------
VEND_DEFECTO = {"nombre": "Nick Sánchez", "cargo": "Jefe Comercial", "tel": "925 912 101"}


def _vend(d):
    v = dict(VEND_DEFECTO)
    if d.get("vendedor"):
        v = {"nombre": d["vendedor"].strip(), "cargo": "", "tel": d.get("tel_vendedor") or VEND_DEFECTO["tel"]}
        if d["vendedor"].strip().lower().startswith("nick"):
            v["cargo"] = "Jefe Comercial"
    elif d.get("tel_vendedor"):
        v["tel"] = d["tel_vendedor"]
    return v


INCLUYE_ESTANDAR = ["Trámite de tarjeta de propiedad", "Trámite de placa",
                    "Casco certificado (o S/ 100 de descuento en otro modelo)",
                    "1 año de garantía o 10,000 km", "Kit de herramientas"]


def lista_lineas(txt, estandar=None):
    if not txt:
        return []
    out = []
    for ln in [x.strip() for x in txt.replace("\r", "").split("\n") if x.strip()]:
        ln = ln.lstrip("+-•· ").strip()
        if not ln:
            continue
        if estandar is not None and ln.upper().replace("Á", "A") in ("ESTANDAR", "STANDARD"):
            out += list(estandar)
        else:
            out.append(ln[0].upper() + ln[1:])
    return out


def cotizacion_pdf(c):
    """c: dict con modo ('moto'|'moto_acc'|'acc'), d (datos), precio, items, instalaciones, pct, fotos"""
    d, modo, fotos = c["d"], c["modo"], c.get("fotos", [])
    vend = _vend(d)
    dt = None
    try:
        from documentos import parsear_fecha
        dt = parsear_fecha(d.get("fecha", ""))
    except Exception:
        pass
    h = Hoja()
    h.encabezado(fecha_larga(dt))
    h.tarjetas_cliente(d.get("cliente", ""), d.get("doc_cliente", ""), vend)
    modelo = d.get("modelo", "")

    if modo == "moto":
        h.moto_A(d.get("marca", ""), d.get("color", ""), modelo, d.get("etiqueta", ""), d.get("texto_precio", ""), c["precio"])
        regalos = lista_lineas(d.get("regalos", ""))
        incluye = lista_lineas(d.get("incluye", ""), INCLUYE_ESTANDAR)
        bono = ""
        if d.get("bono"):
            b = d["bono"].strip()
            bono = f"BONO DE S/ {b}" if b.replace(",", "").replace(".", "").isdigit() else b
        # alto disponible para la foto
        colw = (CW - 24) / 2
        alto_l = 58 + max(sum(hh for _, hh in h._items(regalos, colw)) if regalos else 0,
                          sum(hh for _, hh in h._items(incluye, colw)) if incluye else 0)
        resto = (alto_l + 4 if (regalos or incluye) else 0) + 74 + 58
        alto_foto = max(120, min(230, H - 44 - h.y - resto - 12))
        if fotos:
            h.foto_card(fotos[:1] if len(fotos) == 1 else fotos[:2], alto_foto)
        if regalos or incluye:
            h.listas_A(regalos, bono, incluye)
        lineas = (d.get("texto_final") or "PRECIO FINAL|CON ACCESORIOS Y TRÁMITES INCLUIDOS").replace("\n", "|").split("|")
        h.barra_final([x.strip() for x in lineas if x.strip()], c["precio"])
        h.contacto_banda(vend)
        return h.cerrar()

    if modo == "moto_acc":
        h.moto_B(d.get("marca", ""), d.get("color", ""), modelo, d.get("etiqueta", ""), d.get("texto_precio", ""),
                 c["precio"], fotos[0] if fotos else None)
        extra = fotos[1:5]
    else:
        extra = fotos[:4]
    h.galeria(extra)
    sub, desc, neto, inst = h.accesorios(c["items"], c.get("pct") or 0, c.get("instalaciones", []))
    partes, total = [], 0.0
    if modo == "moto_acc":
        partes.append("MOTO"); total += c["precio"]
    partes.append("ACCESORIOS"); total += neto
    if inst:
        partes.append("INSTALACIÓN"); total += inst
    h.total_con_contacto(partes, round(total, 2), vend)
    return h.cerrar()


def totales(c):
    """Para el resumen del bot: (subtotal, descuento, neto, instalación, total)"""
    items = c.get("items", [])
    sub = round(sum(a * b for a, _, b in items), 2)
    desc = round(sub * (c.get("pct") or 0) / 100.0, 2)
    neto = round(sub - desc, 2)
    inst = round(sum(m for _, m in c.get("instalaciones", [])), 2)
    total = round((c["precio"] if c["modo"] in ("moto_acc", "moto") and c.get("precio") else 0) + (neto if c["modo"] != "moto" else 0) + inst, 2)
    return sub, desc, neto, inst, total
