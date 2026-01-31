import requests
import json
from datetime import datetime


VENTANA_SEGUNDOS = 60
SIZE_MINIMO = 1.0

ESTADO_FILLS = "fills_vistos.json"
ESTADO_ALERTAS = "alertas_emitidas.json"
ESTADO_POSICIONES = "posiciones_previas.json"

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
    # ID ÚNICO Y ESTABLE DEL FILL
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

    if pos_antes < 0:  # venía SHORT
        cierre_short = min(buy_qty, abs(pos_antes))
        if cierre_short > 0:
            eventos.append(("CIERRE SHORT", cierre_short))

        apertura_long = max(0, buy_qty - abs(pos_antes))
        if apertura_long > 0:
            eventos.append(("APERTURA LONG", apertura_long))

    elif pos_antes > 0:  # venía LONG
        cierre_long = min(sell_qty, pos_antes)
        if cierre_long > 0:
            eventos.append(("CIERRE LONG", cierre_long))

        apertura_short = max(0, sell_qty - pos_antes)
        if apertura_short > 0:
            eventos.append(("APERTURA SHORT", apertura_short))

    else:  # estaba plano
        if buy_qty > 0:
            eventos.append(("APERTURA LONG", buy_qty))
        if sell_qty > 0:
            eventos.append(("APERTURA SHORT", sell_qty))

    return eventos

# --------------------------------------------------

def main():
    print("🐋 Monitor MACRO de Ballena iniciado")

    fills_vistos = set(cargar_json(ESTADO_FILLS, []))
    alertas_emitidas = cargar_json(ESTADO_ALERTAS, {})
    posiciones_previas = cargar_json(ESTADO_POSICIONES, {})

    posiciones_actuales = obtener_posiciones()
    fills = obtener_recent_fills()

    nuevos_fills = []
    for f in fills:
        fid = fill_id(f)
        if fid not in fills_vistos:
            nuevos_fills.append(f)
            fills_vistos.add(fid)

    if nuevos_fills:
        grupos = agrupar_fills(nuevos_fills)

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

            # 🔥 ALERTA ID ESTABLE (CLAVE)
            alerta_id = "_".join(sorted(fill_id(f) for f in g["fills"]))

            if alerta_id in alertas_emitidas:
                continue

            precios = [float(f["px"]) for f in g["fills"]]

            print("🚨 CONFIRMACIÓN MACRO DETECTADA")
            print(f"🪙 Mercado: {coin}")
            print(f"📦 BUY: {round(buy_qty,4)} | SELL: {round(sell_qty,4)}")

            for tipo, qty in eventos:
                print(f"🧠 {tipo}: {round(qty,4)}")

            print(f"📦 Tamaño total fills: {round(size_total, 4)}")
            print(f"💰 Precio medio: {round(sum(precios)/len(precios), 2)}")
            print(
                f"🕒 Ventana: "
                f"{formatear_time(int(g['inicio_t']*1000))} → "
                f"{formatear_time(int(g['ultimo_t']*1000))}"
            )
            print("-" * 50)

            alertas_emitidas[alerta_id] = {
                "coin": coin,
                "eventos": eventos,
                "buy_qty": buy_qty,
                "sell_qty": sell_qty,
                "size": size_total,
                "time": g["inicio_t"]
            }

    guardar_json(ESTADO_FILLS, list(fills_vistos))
    guardar_json(ESTADO_ALERTAS, alertas_emitidas)
    guardar_json(ESTADO_POSICIONES, posiciones_actuales)

# --------------------------------------------------

if __name__ == "__main__":
    main()
