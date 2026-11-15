# Solitär: Karten auswählen und verschieben

Dieses Dokument beschreibt den Karten-Eingabeweg in `solitaire.html`.

## Bezeichnungen der Stapel

- **Ziehstapel** (`stock`): verdeckter Kartenstapel oben links. Ein Tap zieht die oberste Karte auf die Ablage. Ist er leer, wird die Ablage zurückgedreht.
- **Ablagestapel** (`waste`): Stapel neben dem Ziehstapel mit der zuletzt gezogenen, offenen Karte.
- **Zielstapel** (`foundations`): die vier Stapel oben rechts. Auf ihnen werden die Karten nach Farbe vom Ass aufwärts abgelegt.
- **Spielspalten** bzw. **Tableau** (`tableau`): die sieben Spalten im Hauptspielfeld. Hier werden Kartenfolgen absteigend mit wechselnden Farben gebaut.

## Kartengröße und Proportionen

Alle Maße der Karten leiten sich aus der Kartenbreite `--card-width` ab, damit Werte, Symbole und Linien auf jedem Gerät und in jedem Browser dieselben Proportionen haben:

- `--card-width` ist auf dem Desktop 68 px und auf dem Handy (bis 600 px Breite) `(100vw − 22px) / 7`.
- `--card-height` ist immer das 1,4-Fache, `--card-overlap` das 1,05-Fache der Breite.
- `--u` ist die Kartenbreite geteilt durch 53. Die Referenz sind die Werte auf dem iPhone-Simulator (393 px breit, Karte 53 px). Schrift, Abstände, Rundungen, Schatten und Rahmen der Karten stehen als `calc(n * var(--u))`, nicht mehr in `rem` oder `px`. Damit ändern sie sich weder mit der Schrifteinstellung des Browsers noch weichen sie zwischen Desktop und Handy ab.
- Die Karten-Symbole werden mit dem Textvariantenselektor U+FE0E gezeichnet (`face()`), damit ♥ und ♦ nirgends als farbiges Emoji erscheinen. `font-variant-emoji: text` ergänzt das, und `text-size-adjust: 100%` verhindert die automatische Textvergrößerung mobiler Browser.
- Rahmenlinien rundet der Browser auf ganze Gerätepixel. Dort kann die Linienstärke daher um bis zu einen Pixel vom Sollwert abweichen.

## Datenmodell der Auswahl

Eine Auswahl wird in `selected` als `{ source, index, cardIndex }` gespeichert:

- `source`: `tableau`, `waste` oder `foundation`
- `index`: Spalten- bzw. Stapelindex
- `cardIndex`: Position der Karte innerhalb einer Tableau-Spalte

`picked()` löst daraus die tatsächlich bewegte Karte oder Kartenfolge auf. Im Tableau umfasst die Auswahl die angeklickte offene Karte und alle offenen Karten darunter. Ablage und Zielstapel liefern jeweils nur ihre oberste Karte.

## Klick und Touch-Tap

Alle sichtbaren Karten werden von `cardButton()` erzeugt. Maus (Klick) und Touch (`pointerup`) laufen über dieselbe Funktion `tapCard()`, ohne verzögerten Einzelklick:

1. Ein einzelner Tap wählt nichts aus: Markieren per Einzelklick ist abgeschaltet, `tapCard()` merkt sich nur Karte und Zeit (`lastCardTap`).
2. Ein weiterer Tap auf dieselbe Karten-ID innerhalb von 500 ms ruft `autoMove()` auf. Die Karte wird auf einen erlaubten Zielstapel bewegt; falls keiner passt, wird sie auf einen passenden Tableau-Stapel gesetzt.
3. Ist „💡 Tipp“ an, führt ein Tap auf das gestrichelt markierte Ziel oder ein Doppeltap auf die markierte Karte genau den Zug des Tipps aus (`playHint()`), nicht den erstbesten Automatikzug.
4. Ein Tap auf einen Grundstapel verwendet dessen Capture-Phase-Handler. So wird auch ein belegter Grundstapel als Ziel erkannt, obwohl darin selbst ein Karten-Button liegt.

Ein Touch-Tap ruft `tapCard()` direkt im `pointerup` auf und setzt `suppressClick`; der danach vom Browser erzeugte Click wird so nicht doppelt verarbeitet. Dasselbe gilt nach einem Touch-Drag.

Die Buttons (Ziehstapel, Rückgängig, Gleiches Deck, Neues Spiel, Fertigspielen) verwenden `onTap()`: Touch löst direkt im `pointerup` aus (der Finger muss noch auf dem Button sein). Grund: Safari verschluckt sonst den ersten Click nach einem Touch-Drag. Nach jedem verarbeiteten Touch-Tap (Karte oder Button) verwirft `noteTouchTap()` Clicks 800 ms lang global. Das verhindert, dass der von Safari nachgeschobene Click ein anderes Element trifft, wenn sich das Layout inzwischen verschoben hat (z. B. „Fertigspielen" verschwindet und „Neues Spiel" liegt unter dem Finger).

Tastatur und Hilfstechnik: Ein Click ohne Zeiger (`event.detail === 0`) läuft über `keyCard()` statt über `tapCard()`. Die erste Betätigung wählt die Karte bzw. Folge aus (`selected`, rot markiert), eine zweite auf derselben Karte macht den Automatikzug, eine auf der obersten Karte einer anderen Spalte oder auf einem Zielstapel legt die Auswahl dorthin. Leere Spalten und leere Zielstapel sind per Tab erreichbar und nehmen die Auswahl mit Enter oder Leertaste an. `render()` stellt den Fokus nach dem Neuzeichnen auf derselben Karte bzw. demselben Stapel wieder her.

## Ziehstapel

Ein Tap auf den Ziehstapel ruft `drawStock()` sofort auf. `lastStockTapAt` fasst einen zweiten Tap innerhalb von 250 ms zusammen, sodass eine versehentlich doppelt ausgelöste Eingabe nicht zwei Karten zieht; zügiges Weiterblättern bleibt möglich. Ist der Vorrat leer, wird die Ablage zurück in den Vorrat gedreht.

## Regeln und Zielprüfung

`moveToTableau()` prüft vor einer Änderung:

- Die ausgewählte Folge ist absteigend und wechselt zwischen Rot und Schwarz (`validSequence()`).
- Auf eine leere Spalte darf nur ein König.
- Auf eine belegte Spalte darf eine Karte, wenn sie eine Rangstufe niedriger und von der Gegenfarbe ist.

`moveToFoundation()` akzeptiert nur eine einzelne Karte. Ein leerer Grundstapel nimmt ein Ass auf; andernfalls müssen Farbe und Folge stimmen. Dieselbe Regel wird für die automatische Ablage durch `canPlaceOnFoundation()` verwendet.

Ungültige Züge ändern den Spielstand nicht. Gültige Züge sichern vorher den Zustand für „Rückgängig“, aktualisieren die Zähler und zeichnen das Spielfeld neu.

## Drag & Drop (Maus, Touch, Stift)

Es gibt kein natives HTML5-Drag&Drop mehr (`draggable`, `dragstart`, `drop`). Maus, Touch und Stift verwenden dieselbe Pointer-Logik direkt an der Originalkarte, damit das Ziehen auf allen Geräten gleich aussieht:

1. `pointerdown` (bei der Maus nur die linke Taste) merkt Ausgangspunkt und bewegte offene Folge.
2. Nach mindestens 8 px Bewegung werden alle Karten der Folge gemeinsam mit dem Zeiger verschoben (Klasse `dragging`, leicht transparent, über allen anderen Karten). Bei der Maus zeigt der Cursor dabei die greifende Hand (`body.dragging-cards`), und die Textauswahl ist auf dem Spielfeld abgeschaltet.
3. `pointerup` ermittelt das Ziel unter dem Zeiger, übergibt die Ausgangspositionen für die Animation und führt den passenden Zug aus. Ohne gültiges Ziel fliegt die Karte zurück.
4. `pointercancel` setzt temporäre Styles zurück.

Ein Klick ohne Bewegung läuft bei der Maus weiter über `click` (auswählen, Doppelklick = Automatikzug). Nach einem Maus-Drag werden Clicks 250 ms lang verworfen, nach einem Touch-Drag länger (600 bis 1200 ms), weil Safari den Click verzögert nachschiebt.

## Verschiebe- und Umdreh-Animation

`animateCardMoves()` verwendet die gespeicherten Ausgangsrechtecke und die neuen Kartenpositionen (FLIP). Die Web-Animations-API bewegt die Karten 600 ms lang; währenddessen erhalten sie einen hohen `z-index`. Bei Kartenfolgen wird jede Karte einzeln animiert.

Wird durch einen Tableau-Zug eine verdeckte Karte frei, bleibt sie während der Verschiebung verdeckt. Erst nach Ende der Verschiebe-Animation setzt `revealAfterMove()` `faceUp` und startet die Umdreh-Animation.

### Karte unter der obersten Karte

Ablage und Zielstapel zeichnen nicht nur die oberste Karte, sondern mit `underCard()` auch die darunterliegende (Klasse `under-card`) bzw. den leeren Platz (`under-card slot`, bei nur einer Karte). Beim Ziehen oder Wegfliegen der obersten Karte ist so schon die nächste sichtbar. Der Platzhalter unter der untersten Karte eines Zielstapels (`foundation-base`) hat keinen eigenen Schatten und sieht wie ein leerer Stapel aus.

Karten, die gerade zum Ziel fliegen, stehen in `flyingIds`. `cardButton()` zeichnet sie bei jedem `render()` ausgeblendet, bis die Flug-Animation endet. So taucht die Zielkarte auch bei zwei schnell aufeinanderfolgenden Zügen nicht zu früh auf, und die bisherige oberste Karte des Ziels bleibt bis zur Landung sichtbar. Ein neues Spiel leert `flyingIds`.

## Neues Spiel und Austeilen

- Es gibt keinen eingebauten Ersatz für die Deck-Sammlung. Die Spiele kommen ausschließlich aus `solitaire-decks/index.json` und den einzelnen Deckdateien `solitaire-decks/deck-*.json`. Der Index wird beim ersten neuen Spiel geladen; `solvableDeck()` versucht dann höchstens zwei Deckdateien über das Netz und greift danach direkt auf Decks zurück, die der Service Worker schon gespeichert hat (`cachedDeckNames()`). So bleibt „Neues Spiel“ auch bei hängendem Netz kurz, und offline kommen die bereits gespielten Decks wieder. Während des Ladens startet kein zweiter Ladevorgang (`loadingDeck`); dauert es länger als 400 ms, steht „Deck wird geladen …“ unter dem Spielfeld. Lässt sich kein Deck laden, zeigt `start()` eine Meldung und ändert nichts; der nächste Versuch lädt den Index erneut. „Gleiches Deck“ ohne geladenes Deck verhält sich wie „Neues Spiel“.
- Deckdateien werden über einen Inhalts-Hash benannt (`deck-<hash>.json`). Dasselbe Deck kann dadurch nicht doppelt abgelegt werden; das Skript dedupliziert zusätzlich beim Einlesen und Schreiben.
- „Neues Spiel" und „Gleiches Deck" (`startNewGame()`) lassen alle 52 Karten von ihrer aktuellen Position (auch aus dem Haufen oder den Zielstapeln) an ihren Platz im neuen Spiel fliegen. Die Reihenfolge entspricht dem Austeilen: Spalte für Spalte reihum, zuletzt der Ziehstapel. Karten, die ihre Seite wechseln, drehen sich unterwegs (Breite skaliert auf nahe 0 und wieder zurück). Während des Austeilens ist das Spielfeld gesperrt. Bei „Bewegung reduzieren" entfällt die Animation.

## Lösungstipp

- Der Button „💡 Tipp“ (`solutionMode`) schaltet die Tipps ein oder aus. `currentDeckSolutions` kommt aus der geladenen Deckdatei (ein Lösungsweg je Deck, ohne Ziehzüge) und wird im Spielstand mitgespeichert.
- `hintMap()` baut je Deck einmal eine Karte „Spielstand → nächster Zug“ aus dem gespeicherten Weg. Der Talon zählt darin nur als Kartenfolge; wo er gerade aufgeschlagen ist, ist egal. Liegt die benötigte Karte nicht oben, lautet der Tipp „ziehen“ bzw. „neu auslegen“ und der Ziehstapel wird markiert.
- Abseits des gespeicherten Wegs rechnet `hintSearch()` selbst weiter: Bestensuche vom aktuellen Stand bis zum Sieg oder zurück auf einen bekannten Stand, mit derselben Bewertung wie `scripts/find-solvable-solitaire.py` und höchstens `HINT_SEARCH_LIMIT` Zuständen. Sie läuft in Scheiben von `HINT_SEARCH_SLICE` ms; solange steht „Ich suche einen Lösungsweg …“ da, der Tipp wird nachgereicht. Gefundene Wege kommen in die Karte, Stände ohne Fund werden gemerkt.
- `updateHint()` übersetzt den Zug in die Anzeige, `markHint()` zeichnet sie: Quelle durchgezogen rot (über `cardButton()`), Ziel gestrichelt (`.solution-target`), dazu der Zug als Text. Ohne Fund wird „Rückgängig“ bzw. „Gleiches Deck“ markiert. Die Meldung unterscheidet zwei Fälle (`hintCache.failed`): `limit` – das Budget ist ausgeschöpft, der Stand kann trotzdem lösbar sein („Von hier finde ich keinen Lösungsweg“); `dead` – alles Erreichbare ist durchsucht („nicht mehr lösbar, außer mit Karten vom Grundstapel zurück“, denn solche Züge nutzt die Suche nicht).
- Der Tipp wird bei jedem `render()` neu bestimmt. Bei Sieg, Haufenansicht oder laufender Austeil-/Fertigspiel-Animation bleibt er aus; `start()` bricht eine laufende Suche ab.

## Fertigspielen und Spielende

- „Fertigspielen" erscheint, sobald keine verdeckte Karte mehr liegt. `autoFinishGame()` sperrt das Spielfeld bis auf „Neues Spiel" (`lockBoard()`, `inert`); „Neues Spiel" bricht den Ablauf ab. Die Flugkarten verwenden Seitenkoordinaten und bleiben beim Scrollen auf Kurs. Bei „Bewegung reduzieren" (`prefers-reduced-motion`) entfällt die Animation. Die übrigen Karten fliegen einzeln auf ihren Zielstapel: aufsteigend nach Rang, reihum über die vier Stapel (110 ms Takt, 450 ms Flug). Jede Farbe landet auf dem Stapel, der mit ihrem Ass begonnen wurde.
- Nach jedem Sieg, auch durch den letzten regulären Zug, fliegen alle Karten von den Zielstapeln auf einen wilden Haufen (`startHeap()`, Overlay `#heap`). Danach ist nur noch „Neues Spiel" aktiv: Rückgängig und Gleiches Deck sind gesperrt, das Spielfeld zeigt leere Stapel (`renderHeapView()`).
- Wird ein gewonnenes Spiel aus dem Speicher geladen, erscheint der Haufen sofort ohne Animation. „Neues Spiel" räumt den Haufen weg (`clearHeap()`).
- Die Zielpositionen des Haufens werden als Verhältniswerte gespeichert. Bei einer Größenänderung (z. B. Drehen) berechnet `layoutHeap()` Overlay und Karten neu.

## Speichern

- Die Zeit startet bei der ersten Bedienung des Spielfelds oder einer Spielaktion, nicht beim Austeilen. Auch ein geladener Spielstand wartet auf die erste Interaktion; seine gespeicherte Zeit bleibt erhalten. „Neues Spiel“ und „Gleiches Deck“ setzen die Zeit zurück und starten sie nicht selbst.
- Der Spielstand liegt im `localStorage` (`STORAGE_KEY`). Geschrieben wird bei jeder Zustandsänderung (`updateStatus()`) sowie beim Verbergen oder Verlassen der Seite (`visibilitychange`, `pagehide`), nicht mehr jede Sekunde und nicht bei jedem Neuzeichnen.
- Der Rückgängig-Verlauf ist auf `HISTORY_LIMIT` (200) Einträge begrenzt, damit der gespeicherte Stand nicht unbegrenzt wächst.
- Beim Laden prüft `validState()`, dass der Stand (und jeder Verlaufseintrag) genau die 52 Karten enthält und jede Karte zu ihrer ID passt. Ein beschädigter oder manipulierter Stand wird verworfen und ein neues Spiel gestartet. Karten werden ohne `innerHTML` gezeichnet (`face()` nutzt `textContent`).
- Ein gespeicherter Stand wird sofort angezeigt, ohne auf den Deck-Index zu warten. Nur ein neues Spiel braucht den Index und eine Deckdatei.

## Relevante Funktionen

| Funktion | Aufgabe |
| --- | --- |
| `cardButton()` | Karten-UI, native Drag- und Touch-Pointer-Events |
| `tapCard()` | Tap-Logik für Maus und Touch: Doppeltap = Automatikzug, Tap auf das Tipp-Ziel = Tipp ausführen |
| `keyCard()` | Bedienung ohne Zeiger: auswählen, dann Ziel wählen oder Automatikzug |
| `onTap()` | Button-Aktion direkt im Touch-`pointerup`, der folgende Click wird ignoriert |
| `picked()` | Ermittelt die bewegte Karte bzw. Folge |
| `autoMove()` | Findet für Doppeltap ein erlaubtes Ziel |
| `canPlaceOnFoundation()` | Prüft die Grundstapel-Regel |
| `moveToTableau()` | Validiert und führt Tableau-Züge aus |
| `moveToFoundation()` | Validiert und führt Grundstapel-Züge aus |
| `animateCardMoves()` | Animiert Karten vom Ursprung zum Ziel |
| `revealAfterMove()` | Deckt nach der Bewegung eine freigelegte Karte auf |
| `autoFinishGame()` | Fertigspielen: Karten fliegen nacheinander auf die Zielstapel |
| `startHeap()` | Lässt nach dem Sieg alle Karten auf einen wilden Haufen fliegen |
