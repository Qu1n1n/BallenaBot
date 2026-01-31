import requests
import json
import time
from datetime import datetime
#from IPython.display import clear_output

# ================== CONFIG ==================

WALLET = "0x5b5d51203a0f9079f8aeb098a6523a13f298c060"
URL = "https://api.hyperliquid.xyz/info"

VENTANA_SEGUNDOS = 60
SIZE_MINIMO = 1.0
INTERVALO = 60

TELEGRAM_TOKEN = "8490599588:AAE3es7AEYA9IU-hn30enntxHFDlzmQwk2Y"
TELEGRAM_CHAT_ID = "5612755129"

ESTADO_FILLS = "fills_vistos.json"
ESTADO_ALERTAS = "alertas_emitidas.json"
ESTADO_POSICIONES = "posiciones_previas.json"

# ==================================================

def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print("❌ Error enviando Telegram:", e)

# --------------------------------------------------

def obtener_recent_fills():
    payload = {"type": "userFills", "user": WALLET}
    r = requests.post(URL, json=payload, timeout=20)
    r.raise_for_status()
    return r.json()

def obtener_posiciones():
    payload = {"type": "clearinghouseState", "user": WALLET}
    r = requests.post(URL, json=payload, timeout=20)
    r.raise_for_status()
    data = r.json()

    posiciones = {}
    for p in data.get("assetPositions", []):
        pos = p.get("position", {})
        coin = pos.get("coin")
        size = float(pos.get("sz", 0))
        if coin:
            posiciones[coin] = size

    return posiciones

def cargar_json(path, default):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return default

def guardar_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def formatear_time(ms):
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S")

def fill_id(f):
    return f"{f['time']}_{f['coin']}_{f['side']}_{f['sz']}_{f['px']}"

# --------------------------------------------------

def agrupar_fills(fills):
    grupos = []

    for f in fills:
        agregado = False
        t = f["time"] / 1000

        for g in grupos:
            if g["coin"] == f["coin"] and abs(t - g["ultimo_t"]) <= VENTANA_SEGUNDOS:
                g["fills"].append(f)
                g["ultimo_t"] = t
                agregado = True
                break

        if not agregado:
            grupos.append({
                "coin": f["coin"],
                "fills": [f],
                "inicio_t": t,
                "ultimo_t": t
            })

    return grupos

# --------------------------------------------------

def interpretar_intencion(pos_antes, buy_qty, sell_qty):
    eventos = []

    if pos_antes < 0:
        cierre_short = min(buy_qty, abs(pos_antes))
        if cierre_short > 0:
            eventos.append(("CIERRE SHORT", cierre_short))
        apertura_long = max(0, buy_qty - abs(pos_antes))
        if apertura_long > 0:
            eventos.append(("APERTURA LONG", apertura_long))

    elif pos_antes > 0:
        cierre_long = min(sell_qty, pos_antes)
        if cierre_long > 0:
            eventos.append(("CIERRE LONG", cierre_long))
        apertura_short = max(0, sell_qty - pos_antes)
        if apertura_short > 0:
            eventos.append(("APERTURA SHORT", apertura_short))

    else:
        if buy_qty > 0:
            eventos.append(("APERTURA LONG", buy_qty))
        if sell_qty > 0:
            eventos.append(("APERTURA SHORT", sell_qty))

    return eventos

# --------------------------------------------------

def main():
    print("🐋 Monitor MACRO de Ballena iniciado...\n")

    mensaje_inicio = (
        "🟢 <b>Ballena operativa</b>\n\n"
        "🐋 Monitor MACRO iniciado correctamente\n"
        f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"⏱ Intervalo: {INTERVALO} segundos"
    )

    enviar_telegram(mensaje_inicio)
    
    fills_vistos = set(cargar_json(ESTADO_FILLS, []))
    alertas_emitidas = cargar_json(ESTADO_ALERTAS, {})
    posiciones_previas = cargar_json(ESTADO_POSICIONES, {})

    intentos = 0

    while True:
        try:
            posiciones_actuales = obtener_posiciones()
            fills = obtener_recent_fills()
            nuevos = []

            for f in fills:
                fid = fill_id(f)
                if fid not in fills_vistos:
                    nuevos.append(f)
                    fills_vistos.add(fid)

            if nuevos:
                grupos = agrupar_fills(nuevos)

                for g in grupos:
                    size_total = sum(float(f["sz"]) for f in g["fills"])
                    if size_total < SIZE_MINIMO:
                        continue

                    coin = g["coin"]
                    pos_antes = float(posiciones_previas.get(coin, 0))

                    buy_qty = sum(float(f["sz"]) for f in g["fills"] if f["side"] == "B")
                    sell_qty = sum(float(f["sz"]) for f in g["fills"] if f["side"] == "S")

                    eventos = interpretar_intencion(pos_antes, buy_qty, sell_qty)
                    if not eventos:
                        continue

                    alerta_id = f"{coin}_{int(g['inicio_t'])}_{'_'.join(e[0] for e in eventos)}"
                    if alerta_id in alertas_emitidas:
                        continue

                    precios = [float(f["px"]) for f in g["fills"]]

                    # ---------- TELEGRAM ----------
                    mensaje = (
                        f"🚨 <b>CONFIRMACIÓN MACRO</b>\n"
                        f"🪙 <b>{coin}</b>\n\n"
                        f"📦 BUY: {round(buy_qty,4)} | SELL: {round(sell_qty,4)}\n"
                    )
                    for tipo, qty in eventos:
                        mensaje += f"🧠 {tipo}: {round(qty,4)}\n"

                    mensaje += (
                        f"\n📦 Tamaño: {round(size_total,4)}"
                        f"\n💰 Precio medio: {round(sum(precios)/len(precios),2)}"
                        f"\n🕒 {formatear_time(int(g['inicio_t']*1000))}"
                    )

                    enviar_telegram(mensaje)

                    print("🚨 CONFIRMACIÓN MACRO DETECTADA")
                    print(mensaje.replace("<b>", "").replace("</b>", ""))
                    print("-" * 50)

                    alertas_emitidas[alerta_id] = {
                        "coin": coin,
                        "eventos": eventos,
                        "buy_qty": buy_qty,
                        "sell_qty": sell_qty,
                        "size": size_total,
                        "time": g["inicio_t"]
                    }

                guardar_json(ESTADO_ALERTAS, alertas_emitidas)

            guardar_json(ESTADO_FILLS, list(fills_vistos))
            guardar_json(ESTADO_POSICIONES, posiciones_actuales)

        except Exception as e:
            print("❌ Error:", e)

        intentos += 1
        if intentos % 10 == 0:
            #clear_output(wait=True)
            print("🧹 Salida limpiada automáticamente\n")

        print(f"⏳ Esperando {INTERVALO} segundos...\n")
        time.sleep(INTERVALO)

# --------------------------------------------------

if __name__ == "__main__":
    main()
