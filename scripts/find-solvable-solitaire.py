#!/usr/bin/env python3
"""Find Klondike draw-one deals solvable by the rules in solitaire.html.

Each solvable deck is one JSON file in solitaire-decks/ plus an index.json, so the
game can load a single deck on demand. Card IDs are integers 0..51 (suit * 13 +
rank), in the order used to deal the tableau and stock. A deck file holds one
solution path as compact integer action arrays (indices zero-based):
`[0, fromColumn, cardId]` tableau→foundation; `[1, cardId]` talon→foundation;
`[2, fromColumn, toColumn, startIndex, count, cardId]` tableau→tableau;
`[3, toColumn, cardId]` talon→tableau.

Drawing and recycling are not stored: with draw-one and unlimited redeals every
talon card can be brought to the top, so the solver treats the talon as a plain
sequence and the game derives the draws itself. Before a path is stored it is
expanded with the necessary draws and replayed against the full rules. Older files
with several paths and draw actions (`[4, cardId]`, `[5]`) are reduced to their
shortest path when read. Deals without a solution are kept in
deals-without-solutions.json. Deck files are named by a content hash, so the same
deck can never be stored twice; this script never deletes a deck file.
"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
from typing import Iterator


COLORS = (0, 1, 1, 0)  # black, red, red, black
RULES = "klondike-draw-1-unlimited-redeals-no-foundation-return"
DEFAULT_DECK_DIR = Path(__file__).resolve().parent.parent / "solitaire-decks"
DEFAULT_UNSOLVED_OUTPUT = Path(__file__).resolve().parent.parent / "deals-without-solutions.json"
ACTION_LENGTHS = {0: 3, 1: 2, 2: 6, 3: 3}

Action = list[int]
Columns = tuple[tuple[tuple[int, ...], int], ...]  # a column is (cards, face_up_count)
# Solver state: the talon is one sequence in draw order, wherever it is currently open.
State = tuple[Columns, tuple[int, ...], tuple[int, ...]]  # (columns, talon, foundations)
# Game state with the stock/waste split, used only to check a path against the full rules.
FullState = tuple[Columns, tuple[int, ...], tuple[int, ...], tuple[int, ...]]  # (columns, stock, waste, foundations)


def rank(card: int) -> int:
    return card % 13


def suit(card: int) -> int:
    return card // 13


def compatible_on_tableau(card: int, target: int | None) -> bool:
    if target is None:
        return rank(card) == 12
    return rank(target) == rank(card) + 1 and COLORS[suit(target)] != COLORS[suit(card)]


def deal_columns(deck: list[int]) -> Columns:
    columns = []
    offset = 0
    for size in range(1, 8):
        columns.append((tuple(deck[offset : offset + size]), 1))
        offset += size
    return tuple(columns)


def without_top(cards: tuple[int, ...], face_up: int, count: int) -> tuple[tuple[int, ...], int]:
    """Remove the top `count` cards of a column and turn over a newly exposed card."""
    remaining = cards[:-count]
    next_up = face_up - count
    return remaining, (1 if not next_up and remaining else next_up)


# --- Solver (talon as a sequence) -------------------------------------------------


def initial_state(deck: list[int]) -> State:
    # The stock is drawn from its end, so the draw order is the reversed remainder.
    return deal_columns(deck), tuple(reversed(deck[28:])), (0, 0, 0, 0)


def priority(state: State, depth: int) -> int:
    columns, _, foundations = state
    hidden = sum(len(cards) - face_up for cards, face_up in columns)
    return depth + (52 - sum(foundations)) * 2 + hidden * 8


def moves_from(state: State) -> Iterator[tuple[State, Action]]:
    columns, talon, foundations = state
    tops = [cards[-1] if cards else None for cards, _ in columns]

    def to_foundation(card: int) -> tuple[int, ...]:
        return tuple(count + (index == suit(card)) for index, count in enumerate(foundations))

    def replaced(*changes: tuple[int, tuple[tuple[int, ...], int]]) -> Columns:
        next_columns = list(columns)
        for index, column in changes:
            next_columns[index] = column
        return tuple(next_columns)

    for source, (cards, face_up) in enumerate(columns):
        if not cards:
            continue
        card = cards[-1]
        if rank(card) == foundations[suit(card)]:
            yield (replaced((source, without_top(cards, face_up, 1))), talon, to_foundation(card)), [0, source, card]
        # Face-up cards of a column always form a valid sequence, so any tail may move.
        for start in range(len(cards) - face_up, len(cards)):
            card = cards[start]
            count = len(cards) - start
            for target, (target_cards, target_up) in enumerate(columns):
                if target == source or not compatible_on_tableau(card, tops[target]):
                    continue
                if start == 0 and not target_cards:
                    continue  # A whole column onto an empty one changes nothing.
                yield (
                    replaced((source, without_top(cards, face_up, count)), (target, (target_cards + cards[start:], target_up + count))),
                    talon,
                    foundations,
                ), [2, source, target, start, count, card]

    for index, card in enumerate(talon):
        rest = talon[:index] + talon[index + 1 :]
        if rank(card) == foundations[suit(card)]:
            yield (columns, rest, to_foundation(card)), [1, card]
        for target, (target_cards, target_up) in enumerate(columns):
            if compatible_on_tableau(card, tops[target]):
                yield (replaced((target, (target_cards + (card,), target_up + 1))), rest, foundations), [3, target, card]


def solve(deck: list[int], max_states: int) -> tuple[list[Action] | None, int, bool]:
    """Best-first search. Returns (path or None, states expanded, search space exhausted)."""
    start = initial_state(deck)
    parents: dict[State, tuple[State, Action] | None] = {start: None}
    queue: list[tuple[int, int, int, State]] = [(priority(start, 0), 0, 0, start)]
    sequence = 0
    expanded = 0
    while queue and expanded < max_states:
        _, _, depth, state = heapq.heappop(queue)
        if sum(state[2]) == 52:
            path: list[Action] = []
            step = parents[state]
            while step is not None:
                path.append(step[1])
                step = parents[step[0]]
            path.reverse()
            return path, expanded, False
        expanded += 1
        for next_state, action in moves_from(state):
            if next_state in parents:
                continue
            parents[next_state] = (state, action)
            sequence += 1
            heapq.heappush(queue, (priority(next_state, depth + 1), sequence, depth + 1, next_state))
    # Exhausted only if nothing is left to expand; a spent budget means "unknown".
    return None, expanded, not queue


# --- Check against the full rules (stock and waste) ------------------------------


def apply_full(state: FullState, action: Action) -> FullState | None:
    """Apply one action (including 4 draw, 5 recycle) under the game's rules, or return None if illegal."""
    columns, stock, waste, foundations = state
    kind = action[0]
    if kind == 4:
        return (columns, stock[:-1], waste + (stock[-1],), foundations) if stock and stock[-1] == action[1] else None
    if kind == 5:
        return (columns, tuple(reversed(waste)), (), foundations) if waste and not stock else None
    card = action[-1]
    next_columns = list(columns)
    if kind in (1, 3):
        if not waste or waste[-1] != card:
            return None
        waste = waste[:-1]
    if kind in (0, 2):
        cards, face_up = columns[action[1]]
        start = len(cards) - 1 if kind == 0 else action[3]
        if not cards or not len(cards) - face_up <= start < len(cards) or cards[start] != card:
            return None
        moving = cards[start:]
        if kind == 2 and (action[4] != len(moving) or action[2] == action[1]):
            return None
        next_columns[action[1]] = without_top(cards, face_up, len(moving))
    else:
        moving = (card,)
    if kind in (0, 1):
        if rank(card) != foundations[suit(card)]:
            return None
        foundations = tuple(count + (index == suit(card)) for index, count in enumerate(foundations))
    else:
        target = action[2] if kind == 2 else action[1]
        target_cards, target_up = columns[target]
        if not compatible_on_tableau(card, target_cards[-1] if target_cards else None):
            return None
        next_columns[target] = (target_cards + moving, target_up + len(moving))
    return tuple(next_columns), stock, waste, foundations


def path_wins(deck: list[int], path: list[Action]) -> bool:
    """Replay a stored path with the draws the game would need; True only if it wins."""
    state: FullState | None = (deal_columns(deck), tuple(deck[28:]), (), (0, 0, 0, 0))
    for action in path:
        if action[0] in (1, 3):
            card = action[-1]
            if card not in state[1] and card not in state[2]:
                return False
            while not state[2] or state[2][-1] != card:
                state = apply_full(state, [4, state[1][-1]] if state[1] else [5])
        state = apply_full(state, action)
        if state is None:
            return False
    return sum(state[3]) == 52


# --- Storage -----------------------------------------------------------------------


def valid_deck(deck: object) -> bool:
    return isinstance(deck, list) and len(deck) == 52 and len(set(deck)) == 52 and all(type(card) is int and 0 <= card < 52 for card in deck)


def deck_file_name(deck: list[int]) -> str:
    digest = hashlib.sha1(json.dumps(deck, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"deck-{digest[:12]}.json"


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temp_name = file.name
            json.dump(data, file, ensure_ascii=False, separators=(",", ":"))
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def stored_path(deck: list[int], item: dict) -> list[Action] | None:
    """The shortest stored path that wins under the full rules, without draw actions."""
    candidates = []
    solutions = item.get("solutions")
    for solution in solutions if isinstance(solutions, list) else []:
        if not isinstance(solution, list):
            continue
        path = [action for action in solution if not (isinstance(action, list) and action and action[0] in (4, 5))]
        if path and all(
            isinstance(action, list) and action and all(type(value) is int for value in action) and ACTION_LENGTHS.get(action[0]) == len(action)
            for action in path
        ):
            candidates.append(path)
    for path in sorted(candidates, key=len):
        if path_wins(deck, path):
            return path
    return None


def deck_document(deck: list[int], path: list[Action]) -> dict:
    return {"deckOrder": deck, "solutions": [path]}


def read_index(directory: Path) -> list[str]:
    try:
        index = json.loads((directory / "index.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    names = index.get("decks") if isinstance(index, dict) else None
    if not isinstance(names, list):
        raise ValueError(f"{directory / 'index.json'} hat ein unbekanntes Format.")
    return [name for name in names if isinstance(name, str) and name and "/" not in name and "\\" not in name]


def write_index(directory: Path, names: list[str]) -> None:
    write_json(directory / "index.json", {"version": 1, "rules": RULES, "decks": names})


def load_decks(directory: Path, rewrite: bool) -> tuple[list[str], set[tuple[int, ...]], list[str]]:
    """Read every indexed deck. Returns (usable names, their decks, names without a winning path).

    With `rewrite`, files that are not yet in the one-path form are rewritten in place.
    """
    names, decks, broken = [], set(), []
    for name in read_index(directory):
        try:
            item = json.loads((directory / name).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            item = None
        deck = item.get("deckOrder") if isinstance(item, dict) else None
        path = stored_path(deck, item) if valid_deck(deck) else None
        if path is None:
            broken.append(name)
            continue
        if tuple(deck) in decks:
            continue
        names.append(name)
        decks.add(tuple(deck))
        document = deck_document(deck, path)
        if rewrite and item != document:
            write_json(directory / name, document)
    return names, decks, broken


def read_unsolved(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "rules": RULES, "solutionSearchCursor": 0, "deals": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1 or data.get("rules") != RULES or not isinstance(data.get("deals"), list):
        raise ValueError(f"{path} hat ein unbekanntes JSON-Format oder eine andere Regelvariante.")
    cursor = data.get("solutionSearchCursor", 0)
    data["solutionSearchCursor"] = cursor if type(cursor) is int else 0
    data["deals"] = [deal for deal in data["deals"] if isinstance(deal, dict) and valid_deck(deal.get("deckOrder"))]
    return data


# --- Command line ------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=1, help="Wie viele neue lösbare Decks gefunden werden sollen (Standard: 1); 0 bringt nur die Ablage in die aktuelle Form.")
    parser.add_argument("--max-attempts", type=int, default=1000, help="Maximale Zahl zufälliger Decks pro Aufruf (Standard: 1000).")
    parser.add_argument("--max-states", type=int, default=100_000, help="Maximale Zahl geprüfter Zustände pro Deck (Standard: 100000).")
    parser.add_argument("--backfill-limit", type=int, default=None, help="Statt neuer Decks bis zu N bestehende Decks ohne Lösung erneut prüfen.")
    parser.add_argument("--verify", action="store_true", help="Nur prüfen: alle gespeicherten Wege gegen die vollen Regeln nachspielen, nichts schreiben.")
    parser.add_argument("--deck-dir", type=Path, default=DEFAULT_DECK_DIR, help=f"Verzeichnis mit einem JSON je lösbarem Deck (Standard: {DEFAULT_DECK_DIR}).")
    parser.add_argument("--unsolved-output", type=Path, default=DEFAULT_UNSOLVED_OUTPUT, help=f"Decks ohne Lösungsweg (Standard: {DEFAULT_UNSOLVED_OUTPUT}).")
    args = parser.parse_args()
    if args.count < 0 or min(args.max_attempts, args.max_states) < 1 or (args.backfill_limit is not None and args.backfill_limit < 1):
        parser.error("count darf nicht negativ sein; max-attempts, max-states und ein angegebenes backfill-limit müssen mindestens 1 sein.")
    if args.deck_dir.resolve() == args.unsolved_output.resolve():
        parser.error("--deck-dir und --unsolved-output müssen verschiedene Pfade sein.")

    names, solved, broken = load_decks(args.deck_dir, rewrite=not args.verify)
    for name in broken:
        print(f"Warnung: {name} hat keinen gültigen Lösungsweg und fehlt im Index, die Datei bleibt liegen.", file=sys.stderr)
    if args.verify:
        print(f"{len(names)} Decks geprüft, {len(broken)} ohne gültigen Lösungsweg.", file=sys.stderr)
        return 1 if broken else 0

    unsolved = read_unsolved(args.unsolved_output)
    unsolved["deals"] = [deal for deal in unsolved["deals"] if tuple(deal["deckOrder"]) not in solved]

    def save() -> None:
        write_index(args.deck_dir, names)
        write_json(args.unsolved_output, unsolved)

    save()
    if args.count == 0:
        print(f"{len(names)} Decks mit je einem Lösungsweg gespeichert.", file=sys.stderr)
        return 0

    def search(deck: list[int]) -> tuple[bool, dict]:
        """Solve one deck; store it if a path is found. Returns (solved, search record)."""
        path, expanded, exhausted = solve(deck, args.max_states)
        if path is not None and not path_wins(deck, path):
            raise ValueError(f"Gefundener Weg besteht die Regelprüfung nicht: {deck}")
        if path is None:
            return False, {"status": "exhausted" if exhausted else "search_limit", "statesExpanded": expanded}
        name = deck_file_name(deck)
        write_json(args.deck_dir / name, deck_document(deck, path))
        names.append(name)
        solved.add(tuple(deck))
        return True, {"statesExpanded": expanded, "moves": len(path)}

    found = 0
    if args.backfill_limit is not None:
        # Decks ohne Lösung reihum ab dem gespeicherten Zeiger erneut prüfen; erschöpfend widerlegte bleiben außen vor.
        deals = unsolved["deals"]
        cursor = unsolved["solutionSearchCursor"] % max(1, len(deals))
        pending = [deal for deal in deals[cursor:] + deals[:cursor] if (deal.get("solutionSearch") or {}).get("status") != "exhausted"]
        for deal in pending[: args.backfill_limit]:
            index = deals.index(deal)
            is_solved, record = search(deal["deckOrder"])
            if is_solved:
                deals.pop(index)
                found += 1
            else:
                deal["solutionSearch"] = record
                index += 1
            unsolved["solutionSearchCursor"] = index % max(1, len(deals))
            save()
            print(f"Bestandsdeck: {'gelöst' if is_solved else 'keine Lösung'} ({record}).", file=sys.stderr)
            if found >= args.count:
                break
        print(f"{found} bestehende Decks gelöst, {len(deals)} ohne Lösung verbleiben.", file=sys.stderr)
        return 0 if found >= args.count else 1

    known = solved | {tuple(deal["deckOrder"]) for deal in unsolved["deals"]}
    rng = secrets.SystemRandom()
    for attempt in range(1, args.max_attempts + 1):
        deck = list(range(52))
        rng.shuffle(deck)
        if tuple(deck) in known:
            continue
        known.add(tuple(deck))
        is_solved, record = search(deck)
        if is_solved:
            found += 1
        else:
            unsolved["deals"].append({"deckOrder": deck, "solutionSearch": record})
        save()
        print(f"Versuch {attempt}/{args.max_attempts}: {'gelöst' if is_solved else 'keine Lösung'} ({record}).", file=sys.stderr)
        if found >= args.count:
            break

    print(f"{found} von {args.count} gewünschten Decks gefunden; Sammlung enthält {len(names)} Decks.", file=sys.stderr)
    return 0 if found >= args.count else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Fehler: {error}", file=sys.stderr)
        raise SystemExit(2)
