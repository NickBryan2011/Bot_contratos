import os, hmac, hashlib, json
import requests
from flask import Flask, request, abort

app = Flask(__name__)

VERIFY_TOKEN   = os.environ.get("VERIFY_TOKEN", "")
APP_SECRET     = os.environ.get("APP_SECRET", "")
ACCESS_TOKEN   = os.environ.get("ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "")
GRAPH = "https://graph.facebook.com/v21.0"

MENU = (
    "Hola 👋 ¿Qué tipo de venta vas a documentar?\n\n"
    "1️⃣ Contado\n"
    "2️⃣ Financiamiento\n"
    "3️⃣ A pedido\n"
    "4️⃣ Separación en piso\n\n"
    "Responde con el número."
)

TIPOS = {"1": "Contado", "2": "Financiamiento", "3": "A pedido", "4": "Separación en piso"}

PLANTILLA = (
    "Perfecto, venta: *{tipo}*.\n"
    "Copia, completa y envíame esto:\n\n"
    "Vendedor:\nNombre completo:\nDNI/RUC:\nEstado civil:\nCelular:\n"
    "Dirección:\nCorreo:\nMoto:\nColor:\nAño modelo:\nPrecio:\n"
    "Separó:\nResta:\nTrámite:\nChasis:\nMotor:\nRegalías:\nObservación:\nBono 500:"
)

# Estado simple en memoria (suficiente para empezar; se pierde si se reinicia)
estado = {}

def enviar(to, texto):
    r = requests.post(
        f"{GRAPH}/{PHONE_NUMBER_ID}/messages",
        headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
        json={"messaging_product": "whatsapp", "to": to,
              "type": "text", "text": {"body": texto}},
        timeout=15,
    )
    print("envio:", r.status_code, r.text[:200])

def firma_valida(req):
    if not APP_SECRET:
        return True
    recibida = req.headers.get("X-Hub-Signature-256", "")
    esperada = "sha256=" + hmac.new(APP_SECRET.encode(), req.get_data(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(recibida, esperada)

@app.get("/")
def home():
    return "Bot Leo Motos activo ✅"

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
                    if m.get("type") != "text":
                        continue
                    num = m["from"]
                    texto = m["text"]["body"].strip()
                    if texto in TIPOS and num not in estado:
                        estado[num] = TIPOS[texto]
                        enviar(num, PLANTILLA.format(tipo=TIPOS[texto]))
                    elif num in estado and ":" in texto:
                        tipo = estado.pop(num)
                        print("DATOS RECIBIDOS", tipo, texto)
                        enviar(num, f"✅ Datos recibidos para venta {tipo}. (Aquí se generarán los PDF en el siguiente paso.)")
                    else:
                        enviar(num, MENU)
    except Exception as e:
        print("error:", e)
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
