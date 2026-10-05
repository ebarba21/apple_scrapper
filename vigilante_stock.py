#!/usr/bin/env python3
"""
Vigilante de stock de recogida en Apple Store (Barcelona).
Consulta el mismo endpoint que usa apple.com/es y avisa por Telegram cuando
un producto pasa de "sin stock" a "con stock". Sin dependencias (solo Python 3.8+).

Funciona en dos sitios con el mismo codigo:
  - En tu PC:         python vigilante_stock.py            (bucle infinito)
  - En GitHub Actions: python vigilante_stock.py --loop 33  (bucle de 33 min; lo relanza el cron)

Secretos (NUNCA en config.json, que se sube a GitHub):
  variables de entorno TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID  (Actions: Settings > Secrets)
  o, en tu PC, el archivo secretos.json (esta en .gitignore).

Otros comandos:
  --once [--notify]   una comprobacion (con --notify avisa y guarda estado; sirve de diagnostico)
  --test-telegram     manda un mensaje de prueba
  --chat-id           muestra tu chat_id (escribe antes al bot)
"""
import argparse
import csv
import html
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9
    ZoneInfo = None

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "config.json")
SECRETS_PATH = os.path.join(BASE, "secretos.json")
STATE_PATH = os.path.join(BASE, "state.json")
HISTORY_PATH = os.path.join(BASE, "history.csv")
LOG_PATH = os.path.join(BASE, "vigilante.log")
IN_ACTIONS = os.environ.get("GITHUB_ACTIONS") == "true"
MIN_INTERVAL = 30  # segundos; nunca consultar mas rapido (Apple limita)

ENDPOINT = "https://www.apple.com/es/shop/retail/pickup-message"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-ES,es;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.apple.com/es/shop/buy-iphone",
}


def now_local(cfg=None):
    tz = (cfg or {}).get("zona_horaria", "Europe/Madrid")
    if ZoneInfo:
        try:
            return datetime.now(ZoneInfo(tz))
        except Exception:  # noqa: BLE001  (Windows sin tzdata)
            pass
    return datetime.now()


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    if not IN_ACTIONS:
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


# ---------------------------------------------------------------- config / estado
def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    token, chat = "", ""
    try:
        with open(SECRETS_PATH, encoding="utf-8") as f:
            sec = json.load(f)
        token, chat = sec.get("telegram_bot_token", ""), str(sec.get("telegram_chat_id", ""))
    except (OSError, ValueError):
        pass
    cfg["_token"] = os.environ.get("TELEGRAM_BOT_TOKEN") or token
    cfg["_chat"] = os.environ.get("TELEGRAM_CHAT_ID") or chat
    return cfg


def load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    st.setdefault("stock", {})
    st.setdefault("heartbeat", "")
    st.setdefault("blocked", False)
    return st


def save_state(state):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, STATE_PATH)


def record_history(product, store, available):
    """Solo se anota cuando CAMBIA el estado: sirve para ver patrones de reposicion."""
    new = not os.path.exists(HISTORY_PATH)
    with open(HISTORY_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["fecha_utc", "producto", "tienda", "estado"])
        w.writerow([datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    product, store, "disponible" if available else "agotado"])


# ---------------------------------------------------------------- Apple
class AppleBlocked(Exception):
    """Apple ha bloqueado/limitado la consulta o respondio algo inesperado."""


def fetch_pickup(part, location, timeout=20):
    qs = urllib.parse.urlencode({"pl": "true", "mts.0": "regular", "parts.0": part, "location": location})
    req = urllib.request.Request(f"{ENDPOINT}?{qs}", headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise AppleBlocked(f"HTTP {e.code} (posible limite o bloqueo de IP)") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise AppleBlocked(f"error de red: {e}") from e
    try:
        return json.loads(raw)
    except ValueError as e:
        raise AppleBlocked("respuesta no es JSON (bloqueo o cambio de Apple)") from e


def parse_stores(data, part, wanted_store_numbers):
    """{storeNumber: {"name","available","quote"}}. Lanza AppleBlocked si la estructura
    no es la esperada o no hay ninguna tienda: asi nunca se confunde un fallo con 'sin stock'."""
    try:
        stores = data["body"]["stores"]
    except (KeyError, TypeError) as e:
        raise AppleBlocked("estructura JSON inesperada") from e
    out = {}
    for s in stores:
        num = s.get("storeNumber")
        if num not in wanted_store_numbers:
            continue
        pa = (s.get("partsAvailability") or {}).get(part)
        if pa is None:
            continue
        quote = ((pa.get("messageTypes") or {}).get("regular") or {}).get("storePickupQuote", "")
        out[num] = {"name": s.get("storeName", num),
                    "available": pa.get("pickupDisplay") == "available", "quote": quote}
    if not out:
        raise AppleBlocked("Apple no devolvio ninguna de las tiendas vigiladas")
    return out


# ---------------------------------------------------------------- Telegram
def telegram_send(cfg, text):
    token, chat = cfg.get("_token"), cfg.get("_chat")
    if not token or not chat:
        log("Telegram sin configurar (token/chat_id): solo aviso por consola.")
        return False
    body = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "HTML"}).encode()
    try:
        with urllib.request.urlopen(
                urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body),
                timeout=20) as r:
            return json.loads(r.read().decode()).get("ok", False)
    except Exception as e:  # noqa: BLE001
        log(f"Fallo al enviar a Telegram: {type(e).__name__}")  # sin detalles: la URL lleva el token
        return False


def alert_text(product, store_name):
    return (f"📲 <b>{html.escape(product['name'])}</b> disponible\n"
            f"en <b>Apple {html.escape(store_name)}</b>\n\n"
            f"🛒 <a href=\"{html.escape(product['buy_url'])}\">Comprar / reservar recogida</a>")


# ---------------------------------------------------------------- logica
def check_once(cfg, state, notify=True):
    wanted = {s["store_number"] for s in cfg["stores"]}
    results = {}
    for product in cfg["products"]:
        part = product["part_number"]
        found = parse_stores(fetch_pickup(part, cfg.get("location", "Barcelona")), part, wanted)
        for num, info in found.items():
            key = f"{part}|{num}"
            was, now = state["stock"].get(key, False), info["available"]
            results[key] = (product["name"], info["name"], now, info["quote"])
            if now != was:
                record_history(product["name"], info["name"], now)
            if now and not was:
                log(f"STOCK: {product['name']} en {info['name']}")
                if notify:
                    telegram_send(cfg, alert_text(product, info["name"]))
            elif was and not now:
                log(f"Se ha agotado: {product['name']} en {info['name']}")
                if notify and cfg.get("avisar_si_se_agota", False):
                    telegram_send(cfg, f"❌ {html.escape(product['name'])} ya no esta en Apple {html.escape(info['name'])}")
            state["stock"][key] = now
        missing = wanted - set(found)
        if missing:
            log(f"Aviso: Apple no devolvio datos de {sorted(missing)} para {part}")
    return results


def maybe_heartbeat(cfg, state, results):
    """Un mensaje al dia ('sigo vivo'): en Actions un fallo silencioso es lo peor que puede pasar."""
    hb = cfg.get("latido_diario_hora")
    if hb is None:
        return
    t = now_local(cfg)
    today = t.strftime("%Y-%m-%d")
    if t.hour >= int(hb) and state.get("heartbeat") != today:
        lines = [f"{'🟢' if ok else '⚪'} {html.escape(s)}: {'DISPONIBLE' if ok else 'sin stock'}"
                 for (_, s, ok, _) in results.values()]
        if telegram_send(cfg, "✅ <b>Vigilante activo</b> (" + t.strftime("%H:%M") + ")\n" + "\n".join(lines)):
            state["heartbeat"] = today


def run_loop(cfg, minutes=None):
    state = load_state()
    interval = max(MIN_INTERVAL, int(cfg.get("intervalo_segundos", 60)))
    deadline = time.time() + minutes * 60 if minutes else None
    errors = 0
    log(f"Vigilando {len(cfg['products'])} producto(s) en {len(cfg['stores'])} tienda(s) cada ~{interval}s"
        + (f" durante {minutes} min." if minutes else ". Ctrl+C para parar."))
    while True:
        try:
            res = check_once(cfg, state)
            if errors or state["blocked"]:
                log("Conexion con Apple recuperada.")
                if state["blocked"]:
                    telegram_send(cfg, "✅ El vigilante vuelve a poder consultar a Apple.")
            errors, state["blocked"] = 0, False
            maybe_heartbeat(cfg, state, res)
            save_state(state)
            log("OK -> " + " | ".join(f"{s}: {'SI' if ok else 'no'}" for (_, s, ok, _) in res.values()))
            wait = interval + random.uniform(-0.15, 0.15) * interval
        except AppleBlocked as e:
            errors += 1
            wait = min(600, 60 * 2 ** errors) if deadline else min(1800, 300 * 2 ** (errors - 1))
            log(f"No se pudo consultar ({e}). Reintento en {wait / 60:.0f} min. NO cuenta como 'sin stock'.")
            if errors >= 3 and not state["blocked"]:
                state["blocked"] = True
                telegram_send(cfg, f"⚠️ El vigilante no puede consultar a Apple ({html.escape(str(e))}). Sigo reintentando.")
                save_state(state)
        except KeyboardInterrupt:
            log("Parado por el usuario.")
            return
        if deadline and time.time() + wait >= deadline:
            log("Fin del turno de vigilancia; el cron lanzara el siguiente.")
            return
        try:
            time.sleep(wait)
        except KeyboardInterrupt:
            log("Parado por el usuario.")
            return


def cmd_once(cfg, notify):
    state = load_state()
    try:
        res = check_once(cfg, state, notify=notify)
    except AppleBlocked as e:
        print(f"ERROR consultando a Apple: {e}")
        if notify:
            telegram_send(cfg, f"⚠️ Diagnostico: este entorno no puede consultar a Apple ({html.escape(str(e))}).")
        return 1
    for (prod, store, ok, quote) in res.values():
        print(f"{prod} @ {store}: {'DISPONIBLE' if ok else 'no disponible'}  ({quote})")
    if notify:
        save_state(state)
        telegram_send(cfg, "🧪 Diagnostico OK: este entorno consulta a Apple bien.\n" + "\n".join(
            f"{'🟢' if ok else '⚪'} {html.escape(s)}: {'DISPONIBLE' if ok else 'sin stock'}" for (_, s, ok, _) in res.values()))
    return 0


def cmd_chat_id(cfg):
    token = cfg.get("_token")
    if not token:
        print("Falta el token (secretos.json o variable TELEGRAM_BOT_TOKEN).")
        return
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20) as r:
        data = json.loads(r.read().decode())
    chats = {m["message"]["chat"]["id"]: m["message"]["chat"].get("first_name", "")
             for m in data.get("result", []) if "message" in m}
    if not chats:
        print("No hay mensajes. Abre tu bot, pulsa Start, escribe 'hola' y repite.")
    for cid, name in chats.items():
        print(f"chat_id: {cid}  ({name})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--notify", action="store_true")
    ap.add_argument("--loop", type=float, metavar="MINUTOS")
    ap.add_argument("--test-telegram", action="store_true")
    ap.add_argument("--chat-id", action="store_true")
    args = ap.parse_args()
    cfg = load_config()
    if args.chat_id:
        return cmd_chat_id(cfg)
    if args.test_telegram:
        ok = telegram_send(cfg, "✅ Prueba del vigilante de stock: Telegram funciona.")
        print("Enviado" if ok else "No se pudo enviar (revisa token y chat_id)")
        return 0 if ok else 1
    if args.once:
        return cmd_once(cfg, args.notify)
    if IN_ACTIONS and not (cfg.get("_token") and cfg.get("_chat")):
        print("ERROR: faltan los secretos TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID en GitHub (Settings > Secrets and variables > Actions).")
        return 2
    run_loop(cfg, args.loop)
    return 0


if __name__ == "__main__":
    sys.exit(main())
