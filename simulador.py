# -*- coding: utf-8 -*-
"""Simulador referencial de cuotas semanales (modelo deducido de las simulaciones del portal de Global Go).

Modelo:  cuota semanal = (F + g + S) * a(i, m) / 4
  F = precio - inicial          (monto financiado)
  g = gasto fijo que se financia (según plazo)
  S = SOAT financiado (solo en la opción "SOAT incluido")
  a(i, m) = i / (1 - (1+i)^-m)  (cuota mensual de un crédito de m meses con tasa mensual i)
  la cuota semanal es la cuota mensual / 4
Los parámetros están en tarifas_globalgo.json (se pueden editar sin tocar el código).
"""
import json
import os

_RUTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tarifas_globalgo.json")

TARIFAS_DEFECTO = {
    "plazos": {"12": {"tem": 0.0581, "gasto": 181.50},
               "18": {"tem": 0.057882, "gasto": 189.94},
               "24": {"tem": 0.057796, "gasto": 194.48}},
    "soat": 832.0,                 # SOAT financiado cuando la inicial es mayor al mínimo
    "soat_inicial_minima": 665.6,  # SOAT financiado cuando la inicial es exactamente el mínimo (20%)
    "inicial_minima_pct": 20.0,
}


def cargar():
    try:
        with open(_RUTA, encoding="utf-8") as f:
            t = json.load(f)
        for k, v in TARIFAS_DEFECTO.items():
            t.setdefault(k, v)
        return t
    except Exception:
        return TARIFAS_DEFECTO


def _ann(i, n):
    return i / (1 - (1 + i) ** -n)


def cuota_semanal(financiado, meses, tem, gasto, extra=0.0):
    return (financiado + gasto + extra) * _ann(tem, meses) / 4.0


def simular(precio, inicial, tarifas=None):
    """Devuelve {'financiado', 'inicial_pct', 'aviso', 'plazos': {meses: {'sin_soat', 'con_soat'}}}"""
    t = tarifas or cargar()
    precio, inicial = float(precio), float(inicial)
    F = precio - inicial
    pct = inicial / precio * 100.0 if precio else 0.0
    minimo = float(t["inicial_minima_pct"])
    en_minimo = pct <= minimo + 0.05
    soat = float(t["soat_inicial_minima"] if en_minimo else t["soat"])
    aviso = ""
    if pct < minimo - 0.05:
        aviso = f"La inicial es menor al {minimo:g}% (las pruebas de Global Go fueron desde {minimo:g}%): el resultado puede variar."
    out = {}
    for m, p in sorted(t["plazos"].items(), key=lambda kv: int(kv[0])):
        m = int(m)
        sin = cuota_semanal(F, m, p["tem"], p["gasto"])
        con = cuota_semanal(F, m, p["tem"], p["gasto"], soat)
        out[m] = {"sin_soat": round(sin, 2), "con_soat": round(con, 2)}
    return {"financiado": F, "inicial_pct": pct, "aviso": aviso, "plazos": out}
