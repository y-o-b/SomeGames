#!/usr/bin/env python3
"""Find Klondike draw-one deals solvable by the rules in solitaire.html.

Successful deals are appended to solvable-deals.json. Card IDs are integers
0..51 (suit * 13 + rank), in the order used to deal the tableau and stock.
The script also writes solitaire-deals-with-solutions.json for consumers that
need both each deck order and its complete solution.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import heapq
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
from typing import Iterator


SUITS = ["♠", "♥", "♦", "♣"]
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
COLORS = (0, 1, 1, 0)  # black, red, red, black
RULES = "klondike-draw-1-unlimited-redeals-no-foundation-return"
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "solvable-deals.json"
DEFAULT_GAME_OUTPUT = Path(__file__).resolve().parent.parent / "solitaire-deals.json"
DEFAULT_SOLUTIONS_OUTPUT = Path(__file__).resolve().parent.parent / "solitaire-deals-with-solutions.json"

# State: (columns, stock, waste, foundations); a column is (cards, face_up_count).
State = tuple[tuple[tuple[int, ...], int], ...], tuple[int, ...], tuple[int, ...], tuple[int, ...]


def rank(card: int) -> int:
    return card % 13


def suit(card: int) -> int:
    return card // 13


def card_name(card: int) -> str:
    return f"{RANKS[rank(card)]}{SUITS[suit(card)]}"


def initial_state(deck: list[int]) -> State:
    columns = []
    offset = 0
    for size in range(1, 8):
        columns.append((tuple(deck[offset : offset + size]), 1))
        offset += size
    return tuple(columns), tuple(deck[offset:]), (), (0, 0, 0, 0)


def priority(state: State, depth: int) -> float:
    columns, stock, _, foundations = state
    completed = sum(foundations)
    hidden = sum(len(cards) - face_up for cards, face_up in columns)
    return depth + (52 - completed) * 2 + hidden * 8 + len(stock) * 0.08


def compatible_on_tableau(card: int, target: int | None) -> bool:
    if target is None:
        return rank(card) == 12
    return rank(target) == rank(card) + 1 and COLORS[suit(target)] != COLORS[suit(card)]


def moves_from(state: State) -> Iterator[tuple[State, str]]:
    columns, stock, waste, foundations = state

    # Tableau top card to foundation.
    for column_index, (cards, face_up) in enumerate(columns):
        if not face_up:
            continue
        card = cards[-1]
        card_suit = suit(card)
        if rank(card) == foundations[card_suit]:
            next_columns = list(columns)
            remaining = cards[:-1]
            next_up = face_up - 1
            if not next_up and remaining:
                next_up = 1  # Turn over the newly exposed card.
            next_columns[column_index] = (remaining, next_up)
            next_foundations = list(foundations)
            next_foundations[card_suit] += 1
            yield (
                (tuple(next_columns), stock, waste, tuple(next_foundations)),
                f"Spalte {column_index + 1} → Ablage {SUITS[card_suit]} ({card_name(card)})",
            )

    # Waste top card to foundation.
    if waste:
        card = waste[-1]
        card_suit = suit(card)
        if rank(card) == foundations[card_suit]:
            next_foundations = list(foundations)
            next_foundations[card_suit] += 1
            yield (
                (columns, stock, waste[:-1], tuple(next_foundations)),
                f"Ablage {card_name(card)} vom Abwurfstapel",
            )

    # Move any valid face-up tableau sequence to another column.
    for source_index, (source_cards, source_up) in enumerate(columns):
        first_up = len(source_cards) - source_up
        for start in range(first_up, len(source_cards)):
            moving = source_cards[start:]
            if any(
                rank(moving[index - 1]) != rank(moving[index]) + 1
                or COLORS[suit(moving[index - 1])] == COLORS[suit(moving[index])]
                for index in range(1, len(moving))
            ):
                continue
            card = moving[0]
            for target_index, (target_cards, target_up) in enumerate(columns):
                if target_index == source_index or not compatible_on_tableau(card, target_cards[-1] if target_cards else None):
                    continue
                next_columns = list(columns)
                remaining = source_cards[:start]
                next_up = source_up - len(moving)
                if not next_up and remaining:
                    next_up = 1
                next_columns[source_index] = (remaining, next_up)
                next_columns[target_index] = (target_cards + moving, target_up + len(moving))
                suffix = " und Folge" if len(moving) > 1 else ""
                yield (
                    (tuple(next_columns), stock, waste, foundations),
                    f"Spalte {source_index + 1} → Spalte {target_index + 1} ({card_name(card)}{suffix})",
                )

    # Waste top card to tableau.
    if waste:
        card = waste[-1]
        for target_index, (target_cards, target_up) in enumerate(columns):
            if not compatible_on_tableau(card, target_cards[-1] if target_cards else None):
                continue
            next_columns = list(columns)
            next_columns[target_index] = (target_cards + (card,), target_up + 1)
            yield (
                (tuple(next_columns), stock, waste[:-1], foundations),
                f"Abwurfstapel {card_name(card)} → Spalte {target_index + 1}",
            )

    # Draw one card, or recycle the waste pile when stock is empty.
    if stock:
        card = stock[-1]
        yield (columns, stock[:-1], waste + (card,), foundations), f"Ziehe {card_name(card)}"
    elif waste:
        yield (columns, tuple(reversed(waste)), (), foundations), "Abwurfstapel wieder als Talon verwenden"


def solve(deck: list[int], max_states: int) -> tuple[list[str] | None, int, bool]:
    start = initial_state(deck)
    queue: list[tuple[float, int, int, State]] = []
    sequence = 0
    heapq.heappush(queue, (priority(start, 0), sequence, 0, start))
    best_depth = {start: 0}
    parent: dict[State, tuple[State, str] | None] = {start: None}
    expanded = 0
    truncated = False

    while queue and expanded < max_states:
        _, _, depth, state = heapq.heappop(queue)
        if best_depth.get(state) != depth:
            continue
        if all(count == 13 for count in state[3]):
            solution = []
            current = state
            while parent[current] is not None:
                previous, move = parent[current]  # type: ignore[misc]
                solution.append(move)
                current = previous
            solution.reverse()
            return solution, expanded, False
        expanded += 1

        for next_state, move in moves_from(state):
            next_depth = depth + 1
            old_depth = best_depth.get(next_state)
            if old_depth is not None and old_depth <= next_depth:
                continue
            if old_depth is None and len(best_depth) >= max_states:
                truncated = True
                continue
            best_depth[next_state] = next_depth
            parent[next_state] = (state, move)
            sequence += 1
            heapq.heappush(queue, (priority(next_state, next_depth), sequence, next_depth, next_state))

    # True only if the entire reachable state space was exhausted. If the
    # state budget stopped the search, the deal is unknown, not proven lost.
    return None, expanded, not queue and not truncated


def read_collection(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "rules": RULES, "deals": [], "rejectedDeals": []}
    with path.open(encoding="utf-8") as file:
        data = json.load(file)
    if data.get("version") != 1 or data.get("rules") != RULES or not isinstance(data.get("deals"), list):
        raise ValueError(f"{path} hat ein unbekanntes JSON-Format oder eine andere Regelvariante.")
    data.setdefault("rejectedDeals", [])
    if not isinstance(data["rejectedDeals"], list):
        raise ValueError(f"{path}: 'rejectedDeals' muss eine Liste sein.")
    return data


def write_collection(path: Path, data: dict) -> None:
    write_json(path, data)


def write_game_deals(path: Path, data: dict) -> None:
    # The browser only needs the ordered card IDs for each playable deal.
    write_json(path, [deal["deckOrder"] for deal in data["deals"]], compact=True)


def write_solution_deals(path: Path, data: dict) -> None:
    # Keep this browser-friendly file focused on the deck and its full move list.
    write_json(path, [
        {"deckOrder": deal["deckOrder"], "solution": deal["solution"]}
        for deal in data["deals"]
    ], compact=True)


def write_json(path: Path, data: object, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temp_name = file.name
            if compact:
                json.dump(data, file, ensure_ascii=False, separators=(",", ":"))
            else:
                json.dump(data, file, ensure_ascii=False, indent=2)
                file.write("\n")
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1, help="Wie viele neue lösbare Decks gefunden werden sollen (Standard: 1).")
    parser.add_argument("--max-attempts", type=int, default=1000, help="Maximale Zahl zufälliger Decks pro Aufruf (Standard: 1000).")
    parser.add_argument("--max-states", type=int, default=100_000, help="Maximale Zahl geprüfter Zustände pro Deck (Standard: 100000).")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help=f"JSON-Zieldatei (Standard: {DEFAULT_OUTPUT}).")
    parser.add_argument("--game-output", type=Path, default=DEFAULT_GAME_OUTPUT, help=f"Kompakte JSON-Datei für solitaire.html (Standard: {DEFAULT_GAME_OUTPUT}).")
    parser.add_argument("--solutions-output", type=Path, default=DEFAULT_SOLUTIONS_OUTPUT, help=f"Decks samt Lösungswegen (Standard: {DEFAULT_SOLUTIONS_OUTPUT}).")
    args = parser.parse_args()
    if min(args.count, args.max_attempts, args.max_states) < 1:
        parser.error("count, max-attempts und max-states müssen mindestens 1 sein.")
    output_paths = [args.output.resolve(), args.game_output.resolve(), args.solutions_output.resolve()]
    if len(set(output_paths)) != len(output_paths):
        parser.error("--output, --game-output und --solutions-output müssen verschiedene Dateien sein.")

    data = read_collection(args.output)
    write_game_deals(args.game_output, data)
    write_solution_deals(args.solutions_output, data)
    existing = {tuple(deal.get("deckOrder", [])) for deal in data["deals"]}
    existing.update(tuple(deal.get("deckOrder", [])) for deal in data["rejectedDeals"])
    rng = secrets.SystemRandom()
    found = 0

    for attempt in range(1, args.max_attempts + 1):
        deck = list(range(52))
        rng.shuffle(deck)
        if tuple(deck) in existing:
            continue
        solution, expanded, exhausted = solve(deck, args.max_states)
        if solution is None:
            rejected = {
                "id": secrets.token_hex(6),
                "deckOrder": deck,
                "status": "exhausted" if exhausted else "search_limit",
                "statesExpanded": expanded,
            }
            data["rejectedDeals"].append(rejected)
            existing.add(tuple(deck))
            data["generatedAt"] = datetime.now(timezone.utc).isoformat()
            write_collection(args.output, data)
            write_solution_deals(args.solutions_output, data)
            print(
                f"Versuch {attempt}/{args.max_attempts}: Deck gespeichert ({rejected['status']}, {expanded} Zustände).",
                file=sys.stderr,
            )
            continue

        deal = {
            "id": secrets.token_hex(6),
            "deckOrder": deck,
            "solution": solution,
            "statesExpanded": expanded,
        }
        data["deals"].append(deal)
        existing.add(tuple(deck))
        found += 1
        data["generatedAt"] = datetime.now(timezone.utc).isoformat()
        write_collection(args.output, data)
        write_game_deals(args.game_output, data)
        write_solution_deals(args.solutions_output, data)
        print(f"Deck {found}/{args.count} gespeichert: {deal['id']} ({len(solution)} Züge, {expanded} Zustände).", file=sys.stderr)
        if found >= args.count:
            break

    if found < args.count:
        print(
            f"Nur {found} von {args.count} gewünschten Decks gefunden. JSON enthält {len(data['deals'])} Decks insgesamt.",
            file=sys.stderr,
        )
        return 1
    print(f"{args.count} neues lösbares Deck in {args.output} gespeichert; Sammlung enthält {len(data['deals'])} Deck(s).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Fehler: {error}", file=sys.stderr)
        raise SystemExit(2)
