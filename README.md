# LittleGames

Kleine Spiele für zwischendurch, als statische Website (GitHub Pages, <https://www.y-o-b.de>) und als Inhalt der iOS-App „Little Games“: Tic Tac Toe, Memory, Solitär, Detektor und Blackjack.

## Aufbau

- `index.html` – Startseite; je Spiel eine eigenständige HTML-Datei ohne Build-Schritt und ohne Abhängigkeiten.
- `sw.js`, `manifest.webmanifest` – Offline-Betrieb und Installation als Web-App. Neue Dateien in `PRECACHE` eintragen und `CACHE` erhöhen.
- `solitaire-decks/` – ein lösbares Solitär-Deck je Datei mit einem geprüften Lösungsweg, dazu `index.json`.
- `scripts/find-solvable-solitaire.py` – erzeugt und prüft die Decks. `--verify` spielt alle Lösungswege gegen die vollen Regeln nach, `--count 0` bringt nur die Ablage in die aktuelle Form, `--backfill-limit N` durchsucht Decks aus `deals-without-solutions.json` erneut.
- `SOLITAIR-KARTENBEDIENUNG.md` – wie Karten in Solitär ausgewählt, bewegt und als Tipp markiert werden.
- `_config.yml` – hält Entwicklerdateien (Skript, ungelöste Decks, Doku) aus der veröffentlichten Website heraus.

## Lokal ansehen

```bash
python3 -m http.server 8000
```

Danach <http://localhost:8000> öffnen. Über `file://` funktionieren Solitär und der Offline-Betrieb nicht.

## Veröffentlichen

Siehe `AGENTS.md`: Bei jeder Code-Änderung `VERSION`, alle sichtbaren Versionsangaben und `version` im Manifest auf denselben Wert setzen, committen, pushen und den Pages-Lauf abwarten.
