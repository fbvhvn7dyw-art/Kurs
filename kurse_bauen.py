#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Holt Kurse bei Yahoo Finance und baut daraus die Seite docs/index.html.

Laeuft einmal taeglich bei GitHub Actions. Braucht nichts ausser Python
selbst - keine zusaetzlichen Pakete.
"""

import html
import http.cookiejar
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    BERLIN = ZoneInfo("Europe/Berlin")
except Exception:
    BERLIN = timezone(timedelta(hours=1))

ORDNER = Path(__file__).resolve().parent
DATEI_LISTE = ORDNER / "wertpapiere.txt"
DATEI_CACHE = ORDNER / "isin_kuerzel.json"
DATEI_ZIEL = ORDNER / "docs" / "index.html"

ANZAHL_TOP = 20      # Laenge der Listen nach Jahr und nach KGV
ANZAHL_KAUF = 40     # Laenge der Liste mit Kaufurteil
JAHRE_RISIKO = 3     # Zeitraum fuer Beta, Alpha und Sortino
ZINS = 0.02          # angenommener risikoloser Zins pro Jahr (2 %)

# Vergleichsindex fuer Beta und Alpha, nach Boersenkuerzel.
# Alles, was hier nicht steht, wird mit dem S&P 500 verglichen.
VERGLEICHSINDEX = {
    ".DE": "^GDAXI", ".F": "^GDAXI",
    ".PA": "^STOXX50E", ".AS": "^STOXX50E", ".MI": "^STOXX50E",
    ".MC": "^STOXX50E", ".ST": "^STOXX50E", ".CO": "^STOXX50E",
    ".OL": "^STOXX50E", ".HE": "^STOXX50E",
    ".SW": "^SSMI",
    ".L": "^FTSE",
    ".T": "^N225",
    ".TO": "^GSPTSE",
    ".AX": "^AXJO",
}
STANDARDINDEX = "^GSPC"
PAUSE = 1.0          # Sekunden zwischen zwei Abfragen - nicht kleiner machen,
                     # sonst bremst Yahoo bei so vielen Werten
ISIN_MUSTER = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")

BROWSERKOPF = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}


# ---------------------------------------------------------------- Abruf

# Alle Abfragen laufen ueber denselben Kanal, damit das Cookie erhalten
# bleibt, das Yahoo fuer die Kennzahlen verlangt.
OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def abrufen(url, versuche=4):
    """Holt eine JSON-Antwort. Bei Bremse durch Yahoo wird gewartet."""
    letzter = None
    for nummer in range(versuche):
        try:
            anfrage = urllib.request.Request(url, headers=BROWSERKOPF)
            with OPENER.open(anfrage, timeout=30) as antwort:
                return json.loads(antwort.read().decode("utf-8"))
        except urllib.error.HTTPError as fehler:
            letzter = fehler
            if fehler.code in (429, 500, 502, 503, 999) and nummer < versuche - 1:
                time.sleep(10 * (nummer + 1))
                continue
            break
        except Exception as fehler:
            letzter = fehler
            if nummer < versuche - 1:
                time.sleep(5)
                continue
            break
    raise letzter if letzter else RuntimeError("Abruf fehlgeschlagen")


def kuerzel_suchen(kennung):
    """Sucht zu einer ISIN das passende Yahoo-Kuerzel."""
    url = ("https://query1.finance.yahoo.com/v1/finance/search?q="
           + urllib.parse.quote(kennung) + "&quotesCount=8&newsCount=0")
    daten = abrufen(url)
    treffer = [q for q in daten.get("quotes", []) if q.get("symbol")]
    if not treffer:
        return None, None
    # Notierungen in Deutschland bevorzugen, sonst den ersten Treffer.
    bevorzugt = ("GER", "FRA", "STU", "MUN", "DUS", "HAM", "BER", "EBS")
    for q in treffer:
        if q.get("exchange") in bevorzugt:
            return q["symbol"], q.get("shortname") or q.get("longname")
    erster = treffer[0]
    return erster["symbol"], erster.get("shortname") or erster.get("longname")


def kurs_abrufen(kuerzel):
    """Holt zehn Jahre Tageskurse und die aktuellen Eckdaten."""
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           + urllib.parse.quote(kuerzel) + "?range=10y&interval=1d")
    daten = abrufen(url)
    ergebnis = (daten.get("chart") or {}).get("result") or []
    if not ergebnis:
        raise ValueError("keine Daten")
    treffer = ergebnis[0]
    meta = treffer.get("meta") or {}
    zeiten = treffer.get("timestamp") or []
    schluss = ((treffer.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []

    verlauf = []
    for i, zeitpunkt in enumerate(zeiten):
        wert = schluss[i] if i < len(schluss) else None
        if isinstance(wert, (int, float)):
            tag = datetime.fromtimestamp(zeitpunkt, tz=timezone.utc).date()
            verlauf.append((tag, float(wert)))
    if not verlauf:
        raise ValueError("keine Kurse")

    kurs = meta.get("regularMarketPrice")
    if not isinstance(kurs, (int, float)):
        kurs = verlauf[-1][1]

    # Tag, zu dem der aktuelle Kurs gehoert. Nur "previousClose" verwenden,
    # niemals "chartPreviousClose" - das ist der Kurs vom Anfang des ganzen
    # Zeitraums, also von vor zehn Jahren.
    zeitstempel = meta.get("regularMarketTime")
    if isinstance(zeitstempel, (int, float)):
        handelstag = datetime.fromtimestamp(zeitstempel, tz=timezone.utc).date()
    else:
        handelstag = verlauf[-1][0]

    return {
        "kuerzel": meta.get("symbol") or kuerzel,
        "name": meta.get("longName") or meta.get("shortName") or kuerzel,
        "kurs": float(kurs),
        "vortag": meta.get("previousClose"),
        "handelstag": handelstag,
        "waehrung": meta.get("currency") or "",
        "verlauf": verlauf,
    }


# ------------------------------------------------------------ Rechnung

def kurs_vor(verlauf, tage, stichtag):
    """Letzter Kurs, der mindestens so viele Tage zurueckliegt."""
    ziel = stichtag - timedelta(days=tage)
    gefunden = None
    for tag, wert in verlauf:
        if tag <= ziel:
            gefunden = wert
        else:
            break
    return gefunden


def schluss_davor(verlauf, handelstag):
    """Letzter Schlusskurs vor dem angegebenen Handelstag."""
    gefunden = None
    for tag, wert in verlauf:
        if tag < handelstag:
            gefunden = wert
        else:
            break
    return gefunden


def tagesrenditen(verlauf):
    """Taegliche Veraenderung, als Zuordnung Datum -> Rendite."""
    werte = {}
    for i in range(1, len(verlauf)):
        vorher, jetzt = verlauf[i - 1][1], verlauf[i][1]
        if vorher > 0:
            werte[verlauf[i][0]] = jetzt / vorher - 1
    return werte


def index_fuer(kuerzel, indizes):
    """Waehlt den passenden Vergleichsindex zur Boerse des Papiers."""
    gross = str(kuerzel).upper()
    for endung, name in VERGLEICHSINDEX.items():
        if gross.endswith(endung):
            return indizes.get(name) or indizes.get(STANDARDINDEX)
    return indizes.get(STANDARDINDEX)


def risiko_kennzahlen(verlauf, index_verlauf):
    """Beta, Alpha und Sortino-Verhaeltnis ueber die letzten Jahre.

    Beta: Wie stark schwankt das Papier im Vergleich zum Index.
    Alpha: Was blieb an Rendite uebrig, nachdem der Index erklaert ist.
    Sortino: Ueberrendite geteilt durch die Schwankung nach unten."""
    ergebnis = {"beta": None, "alpha": None, "sortino": None}
    if len(verlauf) < 2:
        return ergebnis

    grenze = verlauf[-1][0] - timedelta(days=365 * JAHRE_RISIKO)
    teil = [(tag, wert) for tag, wert in verlauf if tag >= grenze]
    rendite = tagesrenditen(teil)
    if len(rendite) < 400:            # weniger als rund anderthalb Jahre
        return ergebnis

    zins_tag = (1 + ZINS) ** (1 / 252) - 1
    ueberschuss = [wert - zins_tag for wert in rendite.values()]
    mittel = sum(ueberschuss) / len(ueberschuss)

    # Sortino: nur die Verlusttage gehen in die Schwankung ein.
    verluste = [wert for wert in ueberschuss if wert < 0]
    if verluste:
        abwaerts = (sum(wert * wert for wert in verluste) / len(ueberschuss)) ** 0.5
        abwaerts *= 252 ** 0.5
        if abwaerts > 0:
            ergebnis["sortino"] = mittel * 252 / abwaerts

    if index_verlauf:
        index_rendite = tagesrenditen(
            [(tag, wert) for tag, wert in index_verlauf if tag >= grenze])
        gemeinsam = sorted(set(rendite) & set(index_rendite))
        if len(gemeinsam) >= 400:
            x = [index_rendite[tag] for tag in gemeinsam]
            y = [rendite[tag] for tag in gemeinsam]
            mx, my = sum(x) / len(x), sum(y) / len(y)
            kovarianz = sum((a - mx) * (b - my) for a, b in zip(x, y)) / len(x)
            varianz = sum((a - mx) ** 2 for a in x) / len(x)
            if varianz > 0:
                beta = kovarianz / varianz
                ergebnis["beta"] = beta
                ergebnis["alpha"] = ((my - zins_tag)
                                     - beta * (mx - zins_tag)) * 252 * 100
    return ergebnis


def veraenderungen(satz):
    """Prozentuale Veraenderung ueber die fuenf Zeitraeume."""
    verlauf = satz["verlauf"]
    kurs = satz["kurs"]
    stichtag = verlauf[-1][0]
    werte = {}

    # Grundlage ist immer der letzte Schlusskurs VOR dem aktuellen Handelstag.
    # Yahoos Angabe "previousClose" wird nur genommen, wenn sie dazu passt -
    # so kann kein uralter Wert mehr hineinrutschen.
    vortag = schluss_davor(verlauf, satz.get("handelstag") or stichtag)
    gemeldet = satz.get("vortag")
    if isinstance(gemeldet, (int, float)) and gemeldet > 0:
        if vortag is None or abs(gemeldet - vortag) / vortag < 0.25:
            vortag = gemeldet
    werte["tag"] = (kurs - vortag) / vortag * 100 if vortag else None

    for name, tage in (("woche", 7), ("monat", 30), ("halbjahr", 182),
                       ("jahr", 365), ("fuenf", 1826)):
        basis = kurs_vor(verlauf, tage, stichtag)
        werte[name] = (kurs - basis) / basis * 100 if basis else None
    return werte


# ------------------------------------------------------------ Einlesen

def liste_einlesen():
    """Liest wertpapiere.txt und liefert zwei Listen von Eintraegen."""
    meine, vergleich = [], []
    ziel = meine
    for rohzeile in DATEI_LISTE.read_text(encoding="utf-8").splitlines():
        zeile = rohzeile.strip()
        if not zeile or zeile.startswith("#"):
            continue
        if zeile.startswith("["):
            ziel = vergleich if "VERGLEICH" in zeile.upper() else meine
            continue
        teile = [t.strip() for t in zeile.split(";")]
        kennung = teile[0]
        ziel.append({
            "kennung": kennung,
            "kuerzel": teile[1] if len(teile) > 1 and teile[1] and teile[1] != "-" else None,
            "name": teile[2] if len(teile) > 2 and teile[2] and teile[2] != "-" else None,
            "isin": kennung if ISIN_MUSTER.match(kennung) else None,
        })
    return meine, vergleich


def cache_lesen():
    if DATEI_CACHE.exists():
        try:
            return json.loads(DATEI_CACHE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


# ---------------------------------------------------------- Verarbeiten

def eintraege_holen(eintraege, cache, probleme, bekannte_kuerzel, indizes):
    """Loest ISINs auf, holt Kurse, rechnet die Veraenderungen aus."""
    zeilen = []
    for eintrag in eintraege:
        kuerzel = eintrag["kuerzel"]

        if not kuerzel and eintrag["isin"]:
            gemerkt = cache.get(eintrag["isin"])
            if gemerkt:
                kuerzel = gemerkt.get("kuerzel")
                eintrag["name"] = eintrag["name"] or gemerkt.get("name")
            else:
                try:
                    kuerzel, gefundener_name = kuerzel_suchen(eintrag["isin"])
                    time.sleep(PAUSE)
                    if kuerzel:
                        cache[eintrag["isin"]] = {"kuerzel": kuerzel, "name": gefundener_name}
                        eintrag["name"] = eintrag["name"] or gefundener_name
                except Exception as fehler:
                    probleme.append(f"{eintrag['kennung']}: Suche fehlgeschlagen ({fehler})")

        if not kuerzel:
            kuerzel = eintrag["kennung"] if not eintrag["isin"] else None

        if not kuerzel:
            probleme.append(f"{eintrag['kennung']}: kein Kürzel bei Yahoo gefunden")
            zeilen.append({"isin": eintrag["isin"] or "", "name": eintrag["name"] or eintrag["kennung"],
                           "kuerzel": "", "kurs": None, "waehrung": "", "werte": {},
                           "risiko": {}, "fehlt": True})
            continue

        if kuerzel.upper() in bekannte_kuerzel:
            continue

        try:
            satz = kurs_abrufen(kuerzel)
            time.sleep(PAUSE)
        except Exception as fehler:
            probleme.append(f"{eintrag['kennung']} ({kuerzel}): kein Kurs ({fehler})")
            zeilen.append({"isin": eintrag["isin"] or "", "name": eintrag["name"] or eintrag["kennung"],
                           "kuerzel": kuerzel, "kurs": None, "waehrung": "", "werte": {},
                           "risiko": {}, "fehlt": True})
            continue

        bekannte_kuerzel.add(kuerzel.upper())
        risiko = risiko_kennzahlen(satz["verlauf"], index_fuer(satz["kuerzel"], indizes))
        zeilen.append({
            "risiko": risiko,
            "isin": eintrag["isin"] or "",
            "name": eintrag["name"] or satz["name"],
            "kuerzel": satz["kuerzel"],
            "kurs": satz["kurs"],
            "waehrung": satz["waehrung"],
            "werte": veraenderungen(satz),
            "fehlt": False,
        })
    return zeilen


def kennung_holen():
    """Holt Cookie und Pruefzeichen, die Yahoo fuer Kennzahlen verlangt."""
    try:
        anfrage = urllib.request.Request("https://fc.yahoo.com/", headers=BROWSERKOPF)
        try:
            OPENER.open(anfrage, timeout=20).read()
        except urllib.error.HTTPError:
            pass          # Die Seite antwortet mit Fehler, setzt aber das Cookie.
        anfrage = urllib.request.Request(
            "https://query1.finance.yahoo.com/v1/test/getcrumb", headers=BROWSERKOPF)
        with OPENER.open(anfrage, timeout=20) as antwort:
            zeichen = antwort.read().decode("utf-8").strip()
        return zeichen or None
    except Exception as fehler:
        print("Kennung fuer KGV nicht erhalten:", fehler)
        return None


URTEILE = {
    "strong buy": ("Stark kaufen", "gut"),
    "buy": ("Kaufen", "gut"),
    "overweight": ("Kaufen", "gut"),
    "hold": ("Halten", "mittel"),
    "neutral": ("Halten", "mittel"),
    "underperform": ("Reduzieren", "schlecht"),
    "underweight": ("Reduzieren", "schlecht"),
    "reduce": ("Reduzieren", "schlecht"),
    "sell": ("Verkaufen", "schlecht"),
    "strong sell": ("Verkaufen", "schlecht"),
}


def urteil_uebersetzen(text):
    """Aus Yahoos '1.8 - Buy' wird ('Kaufen', 'gut', 1.8).

    Die Zahl ist Yahoos Notendurchschnitt: 1 ist das beste Urteil, 5 das
    schlechteste. Sie dient spaeter zum Sortieren der Kaufliste."""
    if not text:
        return None
    teile = str(text).split(" - ")
    wort = teile[-1].strip()
    if not wort:
        return None
    try:
        note = float(teile[0].strip().replace(",", "."))
    except (ValueError, IndexError):
        note = None
    gefunden = URTEILE.get(wort.lower(), (wort, "mittel"))
    return (gefunden[0], gefunden[1], note)


def kennzahlen_holen(kuerzel_liste, zeichen):
    """Holt KGV und Analystenurteil in Sammelabfragen zu je 50 Werten."""
    werte = {}
    if not zeichen:
        return werte
    for anfang in range(0, len(kuerzel_liste), 50):
        gruppe = kuerzel_liste[anfang:anfang + 50]
        url = ("https://query1.finance.yahoo.com/v7/finance/quote?symbols="
               + urllib.parse.quote(",".join(gruppe))
               + "&crumb=" + urllib.parse.quote(zeichen))
        try:
            daten = abrufen(url, versuche=2)
        except Exception as fehler:
            print("Kennzahlen-Abfrage fehlgeschlagen:", fehler)
            time.sleep(PAUSE)
            continue
        for eintrag in (daten.get("quoteResponse") or {}).get("result", []):
            name = str(eintrag.get("symbol", "")).upper()
            if not name:
                continue
            kgv = eintrag.get("trailingPE")
            kbv = eintrag.get("priceToBook")
            # Eigenkapitalrendite: Gewinn je Aktie geteilt durch Buchwert je Aktie.
            # Yahoo liefert beides mit, eine eigene Abfrage ist nicht noetig.
            gewinn = eintrag.get("epsTrailingTwelveMonths")
            buchwert = eintrag.get("bookValue")
            ekr = None
            if (isinstance(gewinn, (int, float)) and isinstance(buchwert, (int, float))
                    and buchwert > 0):
                ekr = gewinn / buchwert * 100
            elif (isinstance(kgv, (int, float)) and isinstance(kbv, (int, float))
                  and kgv > 0):
                ekr = kbv / kgv * 100          # rechnerisch dasselbe
            if ekr is not None and abs(ekr) > 500:
                ekr = None                     # unbrauchbar bei winzigem Eigenkapital
            werte[name] = {
                "ekr": ekr,
                "kgv": float(kgv) if isinstance(kgv, (int, float)) and 0 < kgv < 1000 else None,
                "kbv": float(kbv) if isinstance(kbv, (int, float)) and 0 < kbv < 200 else None,
                "urteil": urteil_uebersetzen(eintrag.get("averageAnalystRating")),
            }
        time.sleep(PAUSE)
    mit_kgv = sum(1 for w in werte.values() if w["kgv"])
    mit_urteil = sum(1 for w in werte.values() if w["urteil"])
    mit_ekr = sum(1 for w in werte.values() if w["ekr"])
    print(f"KGV fuer {mit_kgv}, Eigenkapitalrendite fuer {mit_ekr}, "
          f"Analystenurteil fuer {mit_urteil} von {len(kuerzel_liste)} Werten")
    return werte


# ------------------------------------------------------------- Ausgabe

def zahl(wert, stellen=2):
    if wert is None:
        return "–"
    text = f"{wert:,.{stellen}f}"
    return text.replace(",", "\u00a0").replace(".", ",").replace("\u00a0", ".")


def prozentzelle(wert):
    if wert is None:
        return '<td class="p">–</td>'
    klasse = "p minus" if wert < 0 else ("p plus" if wert > 0 else "p")
    zeichen = "+" if wert > 0 else ("−" if wert < 0 else "")
    return f'<td class="{klasse}">{zeichen}{zahl(abs(wert))}\u202f%</td>'


def zeile_bauen(z):
    if z["fehlt"]:
        return ("<tr class='leer'>"
                f"<td class='isin'>{html.escape(z['isin'] or z['kuerzel'])}</td>"
                f"<td class='bez'>{html.escape(z['name'])}</td>"
                "<td colspan='13' class='hinweiszelle'>kein Kurs gefunden</td></tr>")
    stellen = 4 if abs(z["kurs"]) < 5 else 2
    w = z["werte"]
    kgv = z.get("kgv")
    urteil = z.get("urteil")
    urteilszelle = (f"<td class='rat {urteil[1]}'>{html.escape(urteil[0])}</td>"
                    if urteil else "<td class='rat'>–</td>")

    risiko = z.get("risiko") or {}
    beta, alpha, sortino = risiko.get("beta"), risiko.get("alpha"), risiko.get("sortino")
    if beta is None and alpha is None:
        betazelle = "<td class='ba'>–</td>"
    else:
        if alpha is None:
            alphatext, alphaklasse = "–", ""
        else:
            alphatext = ("+" if alpha > 0 else "−" if alpha < 0 else "") \
                        + zahl(abs(alpha), 1) + "\u202f%"
            alphaklasse = "plus" if alpha > 0 else "minus" if alpha < 0 else ""
        betazelle = (f"<td class='ba'>{zahl(beta, 2) if beta is not None else '–'}"
                     f"<em class='{alphaklasse}'>{alphatext}</em></td>")
    ekr = z.get("ekr")
    if ekr is None:
        ekrzelle = "<td class='ekr'>–</td>"
    else:
        ekrzelle = (f"<td class='ekr {'minus' if ekr < 0 else ''}'>"
                    f"{zahl(ekr, 1)}\u202f%</td>")

    if sortino is None:
        sortinozelle = "<td class='sor'>–</td>"
    else:
        sortinozelle = (f"<td class='sor {'minus' if sortino < 0 else ''}'>"
                        f"{zahl(sortino, 2)}</td>")
    return ("<tr>"
            f"<td class='isin'>{html.escape(z['isin']) if z['isin'] else '–'}</td>"
            f"<td class='bez'><span>{html.escape(z['name'])}</span>"
            f"<em>{html.escape(z['kuerzel'])}</em></td>"
            f"<td class='kurs'>{zahl(z['kurs'], stellen)}<em>{html.escape(z['waehrung'])}</em></td>"
            + urteilszelle
            + f"<td class='kgv'>{zahl(kgv, 1) if kgv else '–'}</td>"
            + f"<td class='kgv'>{zahl(z.get('kbv'), 2) if z.get('kbv') else '–'}</td>"
            + ekrzelle + betazelle + sortinozelle
            + prozentzelle(w.get("tag")) + prozentzelle(w.get("woche"))
            + prozentzelle(w.get("monat")) + prozentzelle(w.get("halbjahr"))
            + prozentzelle(w.get("jahr"))
            + prozentzelle(w.get("fuenf")) + "</tr>")


VORLAGE = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Kursübersicht</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,300;6..72,400&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{
  --paper:#E7EAEF; --card:#F6F8FA; --ink:#16202B; --ink-soft:#5C6B7A;
  --rule:#CBD3DC; --rule-soft:#DDE3E9;
  --up:#1F6B57; --down:#C0392B; --marine:#2B3A55;
}
@media (prefers-color-scheme: dark){
  :root{
    --paper:#141A21; --card:#1B232C; --ink:#E6EBF0; --ink-soft:#93A2B1;
    --rule:#2C3844; --rule-soft:#232D37;
    --up:#5FBE9C; --down:#F0705A; --marine:#A9BEDC;
  }
}
*{box-sizing:border-box}
body{margin:0;padding:0 0 48px;background:var(--paper);color:var(--ink);
  font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
  -webkit-text-size-adjust:100%;}
header,section.fuss{padding:0 16px;max-width:1100px;margin:0 auto}
header{padding-top:26px}
h1{font-family:Newsreader,Georgia,serif;font-weight:300;font-size:2rem;margin:0;letter-spacing:-.01em}
.stand{color:var(--ink-soft);font-size:.85rem;margin:6px 0 0}
h2{font-family:Newsreader,Georgia,serif;font-weight:400;font-size:1.1rem;
   margin:26px 16px 8px;max-width:1100px}
@media(min-width:1132px){h2{margin-left:auto;margin-right:auto}}
.rolle{overflow-x:auto;-webkit-overflow-scrolling:touch;border-top:1px solid var(--rule);
  border-bottom:1px solid var(--rule);background:var(--card)}
/* Feste Spaltenbreiten, in allen drei Tabellen gleich.
   Die Einheit "ch" ist die Breite einer Ziffer - 15ch sind also 15 Stellen.
   Die Summe ergibt die Tabellenbreite: 15+35+11+13+7+7+8+11+8+6x8,8 = 167,8 */
table{table-layout:fixed;border-collapse:collapse;width:167.8ch;min-width:167.8ch;
  font-size:.84rem}
th:nth-child(1){width:15ch}
th:nth-child(2){width:35ch}
th:nth-child(3){width:11ch}
th:nth-child(4){width:13ch}
th:nth-child(5){width:7ch}
th:nth-child(6){width:7ch}
th:nth-child(7){width:8ch}
th:nth-child(8){width:11ch}
th:nth-child(9){width:8ch}
th:nth-child(n+10){width:8.8ch}
th,td{padding:9px 10px;text-align:right;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;border-bottom:1px solid var(--rule-soft)}
th{position:sticky;top:0;background:var(--card);font-weight:500;font-size:.74rem;
   color:var(--ink-soft);border-bottom:1px solid var(--rule);z-index:2}
th:first-child,td:first-child{text-align:left;position:sticky;left:0;background:var(--card);z-index:1}
th:first-child{z-index:3}
td.isin{font-size:.76rem;color:var(--ink-soft);letter-spacing:.01em}
td.bez{text-align:left;white-space:normal;overflow-wrap:anywhere;line-height:1.35}
td.bez span{font-weight:500}
td.bez em{display:block;font-style:normal;font-size:.72rem;color:var(--ink-soft)}
td.kurs{font-family:Newsreader,Georgia,serif;font-size:1.02rem;font-variant-numeric:tabular-nums}
td.kurs em{font-style:normal;font-size:.68rem;color:var(--ink-soft);margin-left:4px;
  font-family:Inter,sans-serif}
td.rat{font-size:.78rem;font-weight:500;color:var(--ink-soft)}
td.rat.gut{color:var(--up)}
td.rat.schlecht{color:var(--down)}
td.kgv{font-variant-numeric:tabular-nums;color:var(--ink-soft)}
td.ba{font-variant-numeric:tabular-nums;line-height:1.25}
td.ba em{display:block;font-style:normal;font-size:.72rem;color:var(--ink-soft)}
td.ba em.plus{color:var(--up)}
td.ba em.minus{color:var(--down)}
td.ekr{font-variant-numeric:tabular-nums}
td.ekr.minus{color:var(--down)}
td.sor{font-variant-numeric:tabular-nums}
td.sor.minus{color:var(--down)}
td.p{font-variant-numeric:tabular-nums;font-weight:500}
td.p.plus{color:var(--up)}
td.p.minus{color:var(--down)}
tr.leer td{color:var(--ink-soft)}
td.hinweiszelle{text-align:left;font-size:.78rem}
tbody tr:nth-child(even) td{background:var(--paper)}
tbody tr:nth-child(even) td:first-child{background:var(--paper)}
section.fuss{margin-top:30px;font-size:.78rem;color:var(--ink-soft);line-height:1.6}
section.fuss p{margin:0 0 8px}
details{margin-top:10px}
summary{cursor:pointer}
details ul{margin:8px 0 0;padding-left:18px}
</style>
</head>
<body>
<header>
  <h1>Kursübersicht</h1>
  <p class="stand">Stand __STAND__ Uhr · Kurse von Yahoo Finance, ohne Gewähr</p>
</header>

<div class="rolle"><table>
<thead><tr><th>ISIN</th><th>Bezeichnung</th><th>Kurs</th><th>Analysten</th><th>KGV</th><th>KBV</th><th>EKR</th><th>Beta / Alpha</th><th>Sortino</th><th>1 Tag</th><th>1 Woche</th>
<th>1 Monat</th><th>6 Monate</th><th>1 Jahr</th><th>5 Jahre</th></tr></thead>
<tbody>
__MEINE__
</tbody></table></div>

<h2>__T1__</h2>
<div class="rolle"><table>
<thead><tr><th>ISIN</th><th>Bezeichnung</th><th>Kurs</th><th>Analysten</th><th>KGV</th><th>KBV</th><th>EKR</th><th>Beta / Alpha</th><th>Sortino</th><th>1 Tag</th><th>1 Woche</th>
<th>1 Monat</th><th>6 Monate</th><th>1 Jahr</th><th>5 Jahre</th></tr></thead>
<tbody>
__TOP__
</tbody></table></div>

<h2>__T2__</h2>
<div class="rolle"><table>
<thead><tr><th>ISIN</th><th>Bezeichnung</th><th>Kurs</th><th>Analysten</th><th>KGV</th><th>KBV</th><th>EKR</th><th>Beta / Alpha</th><th>Sortino</th><th>1 Tag</th><th>1 Woche</th>
<th>1 Monat</th><th>6 Monate</th><th>1 Jahr</th><th>5 Jahre</th></tr></thead>
<tbody>
__GUENSTIG__
</tbody></table></div>

<h2>__T3__</h2>
<div class="rolle"><table>
<thead><tr><th>ISIN</th><th>Bezeichnung</th><th>Kurs</th><th>Analysten</th><th>KGV</th><th>KBV</th><th>EKR</th><th>Beta / Alpha</th><th>Sortino</th><th>1 Tag</th><th>1 Woche</th>
<th>1 Monat</th><th>6 Monate</th><th>1 Jahr</th><th>5 Jahre</th></tr></thead>
<tbody>
__KAUF__
</tbody></table></div>

<section class="fuss">
  <p>Die Seite wird jeden Werktagmorgen neu gebaut. Zum Blättern die Tabelle
     seitlich schieben.</p>
  <p>Die Spalte Analysten gibt das gemittelte Urteil der Banken wieder, die das Papier beobachten - so, wie Yahoo es ausweist. Das ist keine Empfehlung dieser Seite und ersetzt keine eigene Prüfung.</p>\n  <p>Beta, Alpha und das Sortino-Verhältnis sind über die letzten drei Jahre aus den
     Tageskursen gerechnet, mit 2 % als risikolosem Zins. Beta und Alpha jeweils gegen
     einen Index der Heimatbörse: DAX, Euro Stoxx 50, SMI, FTSE 100, Nikkei, TSX,
     ASX 200 oder S&amp;P 500. Alpha ist auf ein Jahr hochgerechnet.</p>
  <p>EKR ist die Eigenkapitalrendite: Gewinn der letzten zwölf Monate geteilt durch
     den Buchwert des Eigenkapitals, beides je Aktie. Eine Näherung – üblich wäre der
     Durchschnitt des Eigenkapitals über das Jahr.</p>
  <p>Das KGV bezieht sich auf den Gewinn der letzten zwölf Monate. Bei Fonds, ETFs, Indizes, Währungen und Rohstoffen gibt es keines.</p>
  <p>Bei Werten aus der Vergleichsliste steht keine ISIN, weil Yahoo dazu keine
     liefert. Trägst du sie in <code>wertpapiere.txt</code> als ISIN ein, erscheint sie.</p>
  __PROBLEME__
</section>
</body>
</html>
"""


def seite_bauen(meine_zeilen, top_zeilen, guenstig_zeilen, kauf_zeilen, probleme):
    stand = datetime.now(BERLIN).strftime("%d.%m.%Y, %H:%M")
    if probleme:
        punkte = "".join(f"<li>{html.escape(p)}</li>" for p in probleme)
        block = ("<details><summary>"
                 f"{len(probleme)} Wertpapier(e) ohne Kurs</summary><ul>{punkte}</ul></details>")
    else:
        block = "<p>Alle Wertpapiere konnten abgerufen werden.</p>"

    seite = (VORLAGE
             .replace("__STAND__", stand)
             .replace("__MEINE__", "\n".join(zeile_bauen(z) for z in meine_zeilen))
             .replace("__TOP__", "\n".join(zeile_bauen(z) for z in top_zeilen))
             .replace("__GUENSTIG__", "\n".join(zeile_bauen(z) for z in guenstig_zeilen))
             .replace("__KAUF__", "\n".join(zeile_bauen(z) for z in kauf_zeilen))
             .replace("__T1__", f"Top {len(top_zeilen)} nach Ein-Jahres-Entwicklung")
             .replace("__T2__", f"Top {len(guenstig_zeilen)} nach niedrigstem KGV")
             .replace("__T3__", f"Top {len(kauf_zeilen)} mit Kaufurteil der Analysten")
             .replace("__PROBLEME__", block))
    DATEI_ZIEL.parent.mkdir(parents=True, exist_ok=True)
    DATEI_ZIEL.write_text(seite, encoding="utf-8")


# ---------------------------------------------------------------- Start

def main():
    meine_eintraege, vergleich_eintraege = liste_einlesen()
    cache = cache_lesen()
    probleme = []
    bekannte = set()

    # Zuerst die Vergleichsindizes, sie werden fuer Beta und Alpha gebraucht.
    indizes = {}
    for name in sorted(set(list(VERGLEICHSINDEX.values()) + [STANDARDINDEX])):
        try:
            indizes[name] = kurs_abrufen(name)["verlauf"]
        except Exception as fehler:
            print("Vergleichsindex nicht verfuegbar:", name, fehler)
        time.sleep(PAUSE)
    print(f"Vergleichsindizes geladen: {len(indizes)}")

    print(f"Meine Wertpapiere: {len(meine_eintraege)}")
    meine_zeilen = eintraege_holen(meine_eintraege, cache, probleme, bekannte, indizes)

    print(f"Vergleichsliste: {len(vergleich_eintraege)}")
    vergleich_zeilen = eintraege_holen(vergleich_eintraege, cache, probleme, bekannte, indizes)

    # KGV fuer alle abgerufenen Werte in Sammelabfragen nachholen.
    alle_zeilen = meine_zeilen + vergleich_zeilen
    kuerzel = [z["kuerzel"] for z in alle_zeilen if z["kuerzel"] and not z["fehlt"]]
    kennzahlen = kennzahlen_holen(kuerzel, kennung_holen())
    for z in alle_zeilen:
        gefunden = kennzahlen.get(str(z["kuerzel"]).upper()) or {}
        z["kgv"] = gefunden.get("kgv")
        z["kbv"] = gefunden.get("kbv")
        z["ekr"] = gefunden.get("ekr")
        z["urteil"] = gefunden.get("urteil")

    mit_jahr = [z for z in vergleich_zeilen
                if not z["fehlt"] and z["werte"].get("jahr") is not None]
    mit_jahr.sort(key=lambda z: z["werte"]["jahr"], reverse=True)
    top_zeilen = mit_jahr[:ANZAHL_TOP]

    mit_kgv = [z for z in vergleich_zeilen if z.get("kgv")]
    mit_kgv.sort(key=lambda z: z["kgv"])
    guenstig_zeilen = mit_kgv[:ANZAHL_TOP]

    # Kaufurteile: bestes Urteil zuerst, bei gleicher Note die staerkere
    # Jahresentwicklung.
    mit_kauf = [z for z in vergleich_zeilen
                if z.get("urteil") and z["urteil"][1] == "gut"]
    mit_kauf.sort(key=lambda z: (z["urteil"][2] if z["urteil"][2] is not None else 2.5,
                                 -(z["werte"].get("jahr") or -999)))
    kauf_zeilen = mit_kauf[:ANZAHL_KAUF]

    seite_bauen(meine_zeilen, top_zeilen, guenstig_zeilen, kauf_zeilen, probleme)
    DATEI_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"Fertig. {len(top_zeilen)} nach Jahr, {len(guenstig_zeilen)} nach KGV, "
          f"{len(kauf_zeilen)} mit Kaufurteil, {len(probleme)} Probleme.")


if __name__ == "__main__":
    main()
