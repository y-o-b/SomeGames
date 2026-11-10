#!/usr/bin/env python3
"""Find Klondike draw-one deals solvable by the rules in solitaire.html.

Successful deals are appended to solvable-deals.json. Card IDs are integers
0..51 (suit * 13 + rank), in the order used to deal the tableau and stock.
Solutions use compact integer action arrays (column/card indices are zero-based):
`[0, fromColumn, cardId]` tableau→foundation; `[1, cardId]` waste→foundation;
`[2, fromColumn, toColumn, startIndex, count, cardId]` tableau→tableau;
`[3, toColumn, cardId]` waste→tableau; `[4, cardId]` draw stock; `[5]` recycle waste.
The script also writes solitaire-deals-with-solutions.json for consumers that
need each deck order and several distinct complete solutions.
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


def moves_from(state: State) -> Iterator[tuple[State, list[int]]]:
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
                [0, column_index, card],
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
                [1, card],
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
                yield (
                    (tuple(next_columns), stock, waste, foundations),
                    [2, source_index, target_index, start, len(moving), card],
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
                [3, target_index, card],
            )

    # Draw one card, or recycle the waste pile when stock is empty.
    if stock:
        card = stock[-1]
        yield (columns, stock[:-1], waste + (card,), foundations), [4, card]
    elif waste:
        yield (columns, tuple(reversed(waste)), (), foundations), [5]


def solve(deck: list[int], max_states: int, solution_limit: int = 3) -> tuple[list[list[list[int]]], int, bool]:
    start = initial_state(deck)
    # Nodes retain their own parent path so several routes to the same state
    # can be explored without overwriting each other.
    nodes: list[tuple[State, int | None, list[int] | None, int, int]] = [(start, None, None, 0, hash(()))]
    queue: list[tuple[float, int, int, int]] = []
    sequence = 0
    heapq.heappush(queue, (priority(start, 0), sequence, 0, 0))
    paths_by_state: dict[State, set[int]] = {start: {hash(())}}
    solutions: list[list[list[int]]] = []
    unique_solutions: set[tuple[tuple[int, ...], ...]] = set()
    expanded = 0
    truncated = False

    while queue and expanded < max_states:
        _, _, depth, node_index = heapq.heappop(queue)
        state, _, _, _, path_hash = nodes[node_index]
        if all(count == 13 for count in state[3]):
            reversed_solution: list[list[int]] = []
            current_index: int | None = node_index
            while current_index is not None:
                _, parent_index, move, _, _ = nodes[current_index]
                if move is not None:
                    reversed_solution.append(move)
                current_index = parent_index
            solution = tuple(tuple(move) for move in reversed(reversed_solution))
            if solution not in unique_solutions:
                unique_solutions.add(solution)
                solutions.append(list(reversed(reversed_solution)))
                if len(solutions) >= solution_limit:
                    return solutions, expanded, False
            continue
        expanded += 1

        for next_state, move in moves_from(state):
            next_depth = depth + 1
            # Exclude loops within a path; they cannot help solve the game and
            # would otherwise consume the per-state allowance for alternatives.
            ancestor_index: int | None = node_index
            is_ancestor = False
            while ancestor_index is not None:
                if nodes[ancestor_index][0] == next_state:
                    is_ancestor = True
                    break
                ancestor_index = nodes[ancestor_index][1]
            if is_ancestor:
                continue

            next_path_hash = hash((path_hash, tuple(move)))
            state_paths = paths_by_state.setdefault(next_state, set())
            if next_path_hash in state_paths or len(state_paths) >= solution_limit:
                continue
            if len(nodes) >= max_states:
                truncated = True
                continue
            state_paths.add(next_path_hash)
            nodes.append((next_state, node_index, move, next_depth, next_path_hash))
            next_node_index = len(nodes) - 1
            sequence += 1
            heapq.heappush(queue, (priority(next_state, next_depth), sequence, next_depth, next_node_index))

    # True only if the entire reachable state space was exhausted. If the
    # state budget stopped the search, the deal is unknown, not proven lost.
    return solutions, expanded, not queue and not truncated


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


ACTION_LENGTHS = {0: 3, 1: 2, 2: 6, 3: 3, 4: 2, 5: 1}


def compact_action(action: object) -> list[int] | None:
    if isinstance(action, list):
        if action and type(action[0]) is int and ACTION_LENGTHS.get(action[0]) == len(action) and all(type(value) is int for value in action):
            return action
        return None
    if not isinstance(action, dict):
        return None
    fields = {
        "tableau-to-foundation": (0, "fromColumn", "cardId"),
        "waste-to-foundation": (1, "cardId"),
        "tableau-to-tableau": (2, "fromColumn", "toColumn", "startIndex", "count", "cardId"),
        "waste-to-tableau": (3, "toColumn", "cardId"),
        "draw-stock": (4, "cardId"),
        "recycle-waste": (5,),
    }
    spec = fields.get(action.get("type"))
    if spec is None:
        return None
    try:
        compact = [spec[0], *(action[field] for field in spec[1:])]
    except KeyError:
        return None
    return compact if all(type(value) is int for value in compact) else None


def structured_solutions(deal: dict) -> list[list[list[int]]]:
    candidates = deal.get("solutions")
    if not isinstance(candidates, list):
        candidates = [deal["solution"]] if isinstance(deal.get("solution"), list) else []
    compact_solutions = []
    for solution in candidates:
        if not isinstance(solution, list) or not solution:
            continue
        actions = [compact_action(action) for action in solution]
        if all(action is not None for action in actions):
            compact_solutions.append(actions)
    return compact_solutions


def remove_legacy_text_solutions(data: dict) -> None:
    """Migrate older prose paths away and retain only machine-readable actions."""
    for deal in data["deals"]:
        deal["solutions"] = structured_solutions(deal)
        deal.pop("solution", None)


def deals_needing_solutions(data: dict) -> list[int]:
    pending = []
    for index, deal in enumerate(data["deals"]):
        search = deal.get("solutionSearch")
        if not structured_solutions(deal) and (not isinstance(search, dict) or search.get("status") != "exhausted"):
            pending.append(index)
    return pending


def write_solution_deals(path: Path, data: dict) -> None:
    # Keep this browser-friendly file focused on each deck and its action paths.
    write_json(path, [
        {"deckOrder": deal["deckOrder"], "solutions": structured_solutions(deal)}
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
    parser.add_argument("--solutions-per-deal", type=int, default=3, help="Wie viele unterschiedliche Lösungswege pro Deck gesucht werden (Standard: 3).")
    parser.add_argument("--backfill-limit", type=int, default=10, help="Maximale Zahl bestehender Decks ohne Lösung, die pro Lauf zuerst geprüft werden (Standard: 10).")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help=f"JSON-Zieldatei (Standard: {DEFAULT_OUTPUT}).")
    parser.add_argument("--game-output", type=Path, default=DEFAULT_GAME_OUTPUT, help=f"Kompakte JSON-Datei für solitaire.html (Standard: {DEFAULT_GAME_OUTPUT}).")
    parser.add_argument("--solutions-output", type=Path, default=DEFAULT_SOLUTIONS_OUTPUT, help=f"Decks samt Lösungswegen (Standard: {DEFAULT_SOLUTIONS_OUTPUT}).")
    args = parser.parse_args()
    if min(args.count, args.max_attempts, args.max_states, args.solutions_per_deal, args.backfill_limit) < 1:
        parser.error("count, max-attempts, max-states, solutions-per-deal und backfill-limit müssen mindestens 1 sein.")
    output_paths = [args.output.resolve(), args.game_output.resolve(), args.solutions_output.resolve()]
    if len(set(output_paths)) != len(output_paths):
        parser.error("--output, --game-output und --solutions-output müssen verschiedene Dateien sein.")

    data = read_collection(args.output)
    remove_legacy_text_solutions(data)
    write_collection(args.output, data)
    write_game_deals(args.game_output, data)
    write_solution_deals(args.solutions_output, data)

    def save_outputs() -> None:
        data["generatedAt"] = datetime.now(timezone.utc).isoformat()
        write_collection(args.output, data)
        write_game_deals(args.game_output, data)
        write_solution_deals(args.solutions_output, data)

    # Backfill old known deals before spending time searching for new ones.
    pending = deals_needing_solutions(data)
    if pending:
        deal_count = len(data["deals"])
        cursor = data.get("solutionSearchCursor", 0)
        if not isinstance(cursor, int) or isinstance(cursor, bool):
            cursor = 0
        cursor %= deal_count
        pending.sort(key=lambda index: (index - cursor) % deal_count)
        found_existing = 0
        tried = 0
        for index in pending[:args.backfill_limit]:
            deal = data["deals"][index]
            solutions, expanded, exhausted = solve(deal["deckOrder"], args.max_states, args.solutions_per_deal)
            tried += 1
            cursor = (index + 1) % deal_count
            if solutions:
                deal["solutions"] = solutions
                deal.pop("solution", None)
                deal.pop("solutionSearch", None)
                deal["statesExpanded"] = expanded
                found_existing += 1
                status = f"{len(solutions)} Lösungen gefunden"
            else:
                deal["solutionSearch"] = {
                    "status": "exhausted" if exhausted else "search_limit",
                    "statesExpanded": expanded,
                }
                status = f"keine Lösung ({deal['solutionSearch']['status']})"
            data["solutionSearchCursor"] = cursor
            save_outputs()
            print(f"Bestandsdeck {index + 1}/{deal_count}: {status}, {expanded} Zustände.", file=sys.stderr)
            if found_existing >= args.count:
                break

        remaining = deals_needing_solutions(data)
        if found_existing >= args.count:
            print(f"{found_existing} bestehendes Deck mit Lösungswegen ergänzt.", file=sys.stderr)
            return 0
        if remaining:
            print(
                f"Bestandsdecks werden priorisiert: {tried} Deck(s) geprüft, {len(remaining)} ohne Lösung verbleiben. "
                "Erneut ausführen, um fortzufahren.",
                file=sys.stderr,
            )
            return 1

    existing = {tuple(deal.get("deckOrder", [])) for deal in data["deals"]}
    existing.update(tuple(deal.get("deckOrder", [])) for deal in data["rejectedDeals"])
    rng = secrets.SystemRandom()
    found = 0

    for attempt in range(1, args.max_attempts + 1):
        deck = list(range(52))
        rng.shuffle(deck)
        if tuple(deck) in existing:
            continue
        solutions, expanded, exhausted = solve(deck, args.max_states, args.solutions_per_deal)
        if not solutions:
            rejected = {
                "id": secrets.token_hex(6),
                "deckOrder": deck,
                "status": "exhausted" if exhausted else "search_limit",
                "statesExpanded": expanded,
            }
            data["rejectedDeals"].append(rejected)
            existing.add(tuple(deck))
            save_outputs()
            print(
                f"Versuch {attempt}/{args.max_attempts}: Deck gespeichert ({rejected['status']}, {expanded} Zustände).",
                file=sys.stderr,
            )
            continue

        deal = {
            "id": secrets.token_hex(6),
            "deckOrder": deck,
            "solutions": solutions,
            "statesExpanded": expanded,
        }
        data["deals"].append(deal)
        existing.add(tuple(deck))
        found += 1
        save_outputs()
        print(f"Deck {found}/{args.count} gespeichert: {deal['id']} ({len(solutions)} Lösungen, {expanded} Zustände).", file=sys.stderr)
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
