#!/usr/bin/env python3
"""Copia i post del canale pubblico https://t.me/starwarsita nella sezione
notizie/ del sito. Legge solo la pagina pubblica del canale (t.me/s/...):
non scrive nulla su Telegram e non usa alcun account.

Uscita:
  notizie/posts.json      i messaggi (piu' recenti per primi)
  notizie/img/*.jpg       le foto, ridotte a 1000 px di larghezza
Uso: python3 scripts/telegram_notizie.py
"""
import hashlib, io, json, os, re, sys, time, datetime, urllib.parse, urllib.request
from bs4 import BeautifulSoup
from PIL import Image

CANALE = "starwarsita"
MAX_MESSAGGI = 44           # ~20 notizie (foto e testo sono spesso due messaggi)
RICONTROLLO = 40            # ultimi messaggi riletti a ogni giro (modifiche e cancellazioni)
RADICE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "notizie")
CARTELLA_IMG = os.path.join(RADICE, "img")
FILE_JSON = os.path.join(RADICE, "posts.json")
UA = {"User-Agent": "Mozilla/5.0 (compatible; CambusaDelFalconBot/1.0; +https://cambusadelfalcon.it)"}
TAG_AMMESSI = {"a", "br", "b", "strong", "i", "em", "u", "s", "del", "code", "pre", "blockquote"}

def scarica(url, tentativi=3):
    for t in range(tentativi):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return r.read()
        except Exception as e:
            if t == tentativi - 1: raise
            time.sleep(2 + 3 * t)

def url_sfondo(el):
    m = re.search(r"background-image:url\('([^']+)'\)", el.get("style", "") if el else "")
    return m.group(1) if m else None

def id_youtube(url):
    u = urllib.parse.urlparse(url)
    if u.netloc.endswith("youtu.be"): return u.path.strip("/").split("/")[0] or None
    if "youtube.com" in u.netloc:
        if u.path == "/watch": return urllib.parse.parse_qs(u.query).get("v", [None])[0]
        m = re.match(r"/(?:shorts|embed|live)/([\w-]+)", u.path)
        if m: return m.group(1)
    return None

def pulisci_testo(div):
    """HTML del testo con soli tag semplici; emoji come caratteri; hashtag verso Telegram."""
    if div is None: return ""
    for e in div.select("i.emoji"):
        e.replace_with(e.get_text())
    for e in div.select("tg-emoji"):
        e.replace_with(e.get_text())
    for el in list(div.find_all(True)):
        if el.name not in TAG_AMMESSI:
            el.unwrap(); continue
        attrs = {}
        if el.name == "a":
            href = el.get("href", "")
            if href.startswith("?q="): href = f"https://t.me/s/{CANALE}{href}"
            if href.startswith(("http://", "https://")):
                attrs = {"href": href, "target": "_blank", "rel": "noopener"}
            else:
                el.unwrap(); continue
        el.attrs = attrs
    return div.decode_contents().strip()

def salva_foto(url, nome):
    # impronta dell'indirizzo nel nome: se una foto viene sostituita nel post, cambia file
    impronta = hashlib.sha1(re.sub(r"^https?://[^/]+", "", url).encode()).hexdigest()[:8]
    nome = nome.replace(".jpg", f"-{impronta}.jpg")
    percorso = os.path.join(CARTELLA_IMG, nome)
    if not os.path.exists(percorso):
        im = Image.open(io.BytesIO(scarica(url))).convert("RGB")
        if im.width > 1000:
            im = im.resize((1000, round(im.height * 1000 / im.width)), Image.LANCZOS)
        im.save(percorso, "JPEG", quality=82, optimize=True, progressive=True)
    with Image.open(percorso) as im:
        return {"src": "img/" + nome, "w": im.width, "h": im.height}

def leggi_pagina(prima_di=None):
    url = f"https://t.me/s/{CANALE}" + (f"?before={prima_di}" if prima_di else "")
    s = BeautifulSoup(scarica(url).decode("utf-8"), "html.parser")
    out = []
    for m in s.select(".tgme_widget_message[data-post]"):
        if "service_message" in m.get("class", []): continue
        mid = int(m["data-post"].split("/")[-1])
        t = m.select_one(".tgme_widget_message_date time")
        voce = {"id": mid, "data": t["datetime"] if t else None,
                "testo": pulisci_testo(m.select_one(".tgme_widget_message_text")),
                "foto": [], "link": None}
        for k, fw in enumerate(m.select(".tgme_widget_message_photo_wrap")):
            u = url_sfondo(fw)
            if u:
                try: voce["foto"].append(salva_foto(u, f"{mid}-{k}.jpg"))
                except Exception as e: print("foto non scaricata", mid, k, e, file=sys.stderr)
        lp = m.select_one("a.tgme_widget_message_link_preview")
        if lp is not None:
            g = lambda c: (lp.select_one(c).get_text(" ", strip=True) if lp.select_one(c) else "")
            link = {"url": lp.get("href", ""), "sito": g(".link_preview_site_name"),
                    "titolo": g(".link_preview_title"), "descrizione": g(".link_preview_description")[:300],
                    "youtube": id_youtube(lp.get("href", "")), "immagine": None}
            if link["youtube"]:
                link["immagine"] = f"https://i.ytimg.com/vi/{link['youtube']}/hqdefault.jpg"
            else:
                u = url_sfondo(lp.select_one(".link_preview_image, .link_preview_right_image"))
                if u:
                    try: link["immagine"] = salva_foto(u, f"{mid}-link.jpg")["src"]
                    except Exception as e: print("anteprima non scaricata", mid, e, file=sys.stderr)
            voce["link"] = link
        if voce["testo"] or voce["foto"] or voce["link"]:
            out.append(voce)
    return out

def main():
    os.makedirs(CARTELLA_IMG, exist_ok=True)
    vecchi = {}
    if os.path.exists(FILE_JSON):
        vecchi = {m["id"]: m for m in json.load(open(FILE_JSON, encoding="utf-8"))["messaggi"]}
    ultimo_noto = max(vecchi) if vecchi else 0
    letti, prima_di = {}, None
    # pagine dal piu' recente all'indietro: fino a coprire i nuovi + gli ultimi RICONTROLLO noti
    while True:
        pagina = leggi_pagina(prima_di)
        if not pagina: break
        for m in pagina: letti[m["id"]] = m
        minimo = min(m["id"] for m in pagina)
        if vecchi and minimo <= ultimo_noto - RICONTROLLO: break
        if len(letti) >= MAX_MESSAGGI: break
        prima_di = minimo
        time.sleep(1)
    if not letti:
        print("nessun messaggio letto: dati invariati"); return
    soglia = min(letti)
    uniti = {i: m for i, m in vecchi.items() if i < soglia}      # piu' vecchi: invariati
    uniti.update(letti)                                          # riletti e nuovi (cancellati spariscono)
    messaggi = sorted(uniti.values(), key=lambda m: -m["id"])[:MAX_MESSAGGI]
    dati = {"canale": CANALE, "messaggi": messaggi}
    nuovo = json.dumps(dati, ensure_ascii=False, separators=(",", ":"))
    vecchio = open(FILE_JSON, encoding="utf-8").read() if os.path.exists(FILE_JSON) else ""
    if nuovo != vecchio:
        open(FILE_JSON, "w", encoding="utf-8").write(nuovo)
    # foto non piu' usate
    usate = {f["src"] for m in messaggi for f in m["foto"]} | {m["link"]["immagine"] for m in messaggi if m["link"] and m["link"]["immagine"]}
    for f in os.listdir(CARTELLA_IMG):
        if "img/" + f not in usate: os.remove(os.path.join(CARTELLA_IMG, f))
    print(f"{len(messaggi)} messaggi, piu' recente {messaggi[0]['id']}, {len(usate)} immagini")

if __name__ == "__main__":
    main()
