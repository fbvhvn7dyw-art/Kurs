# Kursübersicht bei GitHub einrichten

Das Ganze besteht aus vier Dateien. GitHub holt damit jeden Werktagmorgen
die Kurse und legt eine fertige Seite ab. Die Seite öffnet sich später
sofort, weil beim Aufrufen nichts mehr abgerufen werden muss.

## Was wohin gehört

```
wertpapiere.txt                  deine Liste - die einzige Datei, die du je anfasst
kurse_bauen.py                   das Programm, das die Kurse holt
.github/workflows/kurse.yml      der Zeitplan
LIESMICH.md                      diese Anleitung
```

Die Ordnernamen mit dem Punkt am Anfang sind wichtig, genau so schreiben.

## Einrichten, Schritt für Schritt

**1. Projekt anlegen.** Bei github.com anmelden, oben rechts auf das Plus,
dann *New repository*. Namen vergeben, zum Beispiel `kursuebersicht`.
*Public* auswählen (bei *Private* kostet der Zeitplan Geld). Anlegen.

**2. Dateien hochladen.** Im leeren Projekt auf *uploading an existing file*.
Alle vier Dateien hineinziehen. Wichtig: `kurse.yml` muss im Ordner
`.github/workflows/` landen. Beim Hochladen im Feld über der Dateiliste
kannst du den Pfad eintippen — schreibe dort `.github/workflows/` vor den
Dateinamen. Unten auf *Commit changes*.

**3. Dem Roboter das Schreiben erlauben.** Reiter *Settings* →
links *Actions* → *General* → ganz unten bei *Workflow permissions*
auf **Read and write permissions** stellen und speichern.
Ohne das kann er die Seite nicht ablegen.

**4. Erster Lauf.** Reiter *Actions* → links *Kurse aktualisieren* →
rechts *Run workflow*. Das dauert etwa drei bis fünf Minuten. Danach gibt
es einen neuen Ordner `docs` mit der Datei `index.html`.

**5. Seite veröffentlichen.** *Settings* → links *Pages* →
bei *Source* auf *Deploy from a branch*, dann Zweig `main` und Ordner
`/docs` wählen, speichern. Nach ein paar Minuten steht dort die Adresse,
etwa `https://deinname.github.io/kursuebersicht/`.

Diese Adresse auf dem Handy als Lesezeichen speichern oder auf den
Startbildschirm legen. Fertig.

## Wenn ein Wertpapier fehlt

Ganz unten auf der Seite steht eine aufklappbare Zeile mit allem, was
nicht abgerufen werden konnte. Zwei häufige Gründe:

*Yahoo kennt die ISIN nicht.* Dann suchst du das Papier einmal von Hand
auf finance.yahoo.com und schreibst das dortige Kürzel in die Zeile,
getrennt durch Strichpunkte:

```
LU0203975197 ; 0P00009MAA.F ; Mein Mischfonds
```

Der mittlere Teil ist das Kürzel, der hintere ein Name deiner Wahl.
Beides darf auch leer bleiben (dann einen Bindestrich setzen).

*Yahoo hat kurz gebremst.* Kommt vor. Beim nächsten Lauf ist es meist
wieder da. Von Hand neu starten geht über *Actions* → *Run workflow*.

## Liste ändern

Nur `wertpapiere.txt` bearbeiten — auf GitHub die Datei anklicken, dann
auf den Stift, ändern, unten auf *Commit changes*. Der nächste Lauf
übernimmt es. Oben stehen deine eigenen Werte, unten die Vergleichsliste,
aus der die Top 20 nach Ein-Jahres-Entwicklung gewählt werden. Je mehr du
dort hineinschreibst, desto aussagekräftiger die Top 20 — aber auch desto
länger der Lauf.

## Uhrzeit ändern

In `kurse.yml` steht `cron: "15 5 * * 1-5"`. Die erste Zahl ist die
Minute, die zweite die Stunde in Weltzeit — also im Sommer zwei Stunden
vor unserer Uhr, im Winter eine. `1-5` heißt Montag bis Freitag.
Für zweimal täglich schreibst du eine zweite Zeile darunter.
