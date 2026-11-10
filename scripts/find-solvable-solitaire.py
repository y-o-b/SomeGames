#!/usr/bin/env python3
"""Find Klondike draw-one deals solvable by the rules in solitaire.html.

Successful deals are stored as one JSON file per deck in solitaire-decks/ plus an
index.json, so the game can load a single deck on demand. Card IDs are integers
0..51 (suit * 13 + rank), in the order used to deal the tableau and stock.
Solutions use compact integer action arrays (column/card indices are zero-based):
`[0, fromColumn, cardId]` tableau→foundation; `[1, cardId]` waste→foundation;
`[2, fromColumn, toColumn, startIndex, count, cardId]` tableau→tableau;
`[3, toColumn, cardId]` waste→tableau; `[4, cardId]` draw stock; `[5]` recycle waste.
Deals without a solution are kept in deals-without-solutions.json.
solitaire-deals.json remains a deck-only fallback list.
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
DEFAULT_GAME_OUTPUT = Path(__file__).resolve().parent.parent / "solitaire-deals.json"
DEFAULT_UNSOLVED_OUTPUT = Path(__file__).resolve().parent.parent / "deals-without-solutions.json"

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


def valid_deck(deck: object) -> bool:
    return isinstance(deck, list) and len(deck) == 52 and len(set(deck)) == 52 and all(type(card) is int and 0 <= card < 52 for card in deck)


def deck_file_name(deck: list[int]) -> str:
    digest = hashlib.sha1(json.dumps(deck, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"deck-{digest[:12]}.json"


def read_solved_decks(directory: Path) -> dict:
    index_path = directory / "index.json"
    deals = []
    if index_path.exists():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            names = index.get("decks", []) if isinstance(index, dict) else index
        except (OSError, json.JSONDecodeError):
            names = []
        for name in names if isinstance(names, list) else []:
            if not isinstance(name, str) or "/" in name or "\\" in name:
                continue
            path = directory / name
            if not path.exists():
                continue
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(item, dict) or not valid_deck(item.get("deckOrder")):
                continue
            solutions = structured_solutions(item)
            if solutions:
                deals.append({"deckOrder": item["deckOrder"], "solutions": solutions})
    return {"deals": deals}


def write_solved_decks(directory: Path, data: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    names = []
    for deal in data["deals"]:
        solutions = structured_solutions(deal)
        if not solutions:
            continue
        name = deck_file_name(deal["deckOrder"])
        names.append(name)
        write_json(directory / name, {"deckOrder": deal["deckOrder"], "solutions": solutions}, compact=True)
    write_json(directory / "index.json", {"version": 1, "rules": RULES, "decks": names}, compact=True)
    keep = set(names) | {"index.json"}
    for path in directory.glob("deck-*.json"):
        if path.name not in keep:
            path.unlink()


def read_unsolved_collection(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "rules": RULES, "deals": [], "solutionSearchCursor": 0}
    with path.open(encoding="utf-8") as file:
        data = json.load(file)
    if isinstance(data, list):
        data = {"version": 1, "rules": RULES, "deals": data, "solutionSearchCursor": 0}
    if not isinstance(data, dict) or data.get("version") != 1 or data.get("rules") != RULES or not isinstance(data.get("deals"), list):
        raise ValueError(f"{path} hat ein unbekanntes JSON-Format oder eine andere Regelvariante.")
    cursor = data.get("solutionSearchCursor", 0)
    return {
        "version": 1,
        "rules": RULES,
        "solutionSearchCursor": cursor if isinstance(cursor, int) and not isinstance(cursor, bool) else 0,
        "deals": [deal for deal in data["deals"] if isinstance(deal, dict) and valid_deck(deal.get("deckOrder"))],
    }


def write_unsolved_collection(path: Path, data: dict) -> None:
    deals = []
    for deal in data["deals"]:
        item = {"deckOrder": deal["deckOrder"]}
        search = deal.get("solutionSearch")
        if isinstance(search, dict) and search.get("status") in {"search_limit", "exhausted"}:
            item["solutionSearch"] = search
        deals.append(item)
    write_json(path, {
        "version": 1,
        "rules": RULES,
        "solutionSearchCursor": data.get("solutionSearchCursor", 0),
        "deals": deals,
    }, compact=True)


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
    parser.add_argument("--backfill-limit", type=int, default=None, help="Backfills aktivieren und bis zu N bestehende Decks ohne Lösung pro Lauf prüfen (nur bei Angabe).")
    parser.add_argument("--deck-dir", type=Path, default=DEFAULT_DECK_DIR, help=f"Verzeichnis mit einem JSON je lösbarem Deck (Standard: {DEFAULT_DECK_DIR}).")
    parser.add_argument("--unsolved-output", type=Path, default=DEFAULT_UNSOLVED_OUTPUT, help=f"Decks ohne Lösungsweg (Standard: {DEFAULT_UNSOLVED_OUTPUT}).")
    parser.add_argument("--game-output", type=Path, default=DEFAULT_GAME_OUTPUT, help=f"Deckliste als Ausfallsicherung für solitaire.html (Standard: {DEFAULT_GAME_OUTPUT}).")
    args = parser.parse_args()
    if min(args.count, args.max_attempts, args.max_states, args.solutions_per_deal) < 1 or (args.backfill_limit is not None and args.backfill_limit < 1):
        parser.error("count, max-attempts, max-states, solutions-per-deal und ein angegebenes backfill-limit müssen mindestens 1 sein.")
    output_paths = [args.unsolved_output.resolve(), args.game_output.resolve()]
    if len(set(output_paths)) != len(output_paths):
        parser.error("--unsolved-output und --game-output müssen verschiedene Dateien sein.")

    data = read_solved_decks(args.deck_dir)
    unsolved_data = read_unsolved_collection(args.unsolved_output)
    remove_legacy_text_solutions(data)
    remove_legacy_text_solutions(unsolved_data)

    # Solved decks take precedence; any solutionless duplicate stays only in
    # the backlog file.
    solved_by_deck = {tuple(deal["deckOrder"]): deal for deal in data["deals"]}
    unsolved_by_deck = {}
    for deal in unsolved_data["deals"]:
        key = tuple(deal["deckOrder"])
        if key not in solved_by_deck:
            unsolved_by_deck[key] = deal
    unsolved_data["deals"] = list(unsolved_by_deck.values())

    def save_outputs() -> None:
        data["deals"] = list(solved_by_deck.values())
        write_solved_decks(args.deck_dir, data)
        write_unsolved_collection(args.unsolved_output, unsolved_data)
        write_game_deals(args.game_output, data)

    save_outputs()

    # Existing solutionless decks are searched only when explicitly requested.
    if args.backfill_limit is not None:
        pending = deals_needing_solutions(unsolved_data)
    else:
        pending = []
    if pending:
        deal_count = len(unsolved_data["deals"])
        cursor = unsolved_data.get("solutionSearchCursor", 0)
        if not isinstance(cursor, int) or isinstance(cursor, bool):
            cursor = 0
        cursor %= deal_count
        pending.sort(key=lambda index: (index - cursor) % deal_count)
        pending_decks = [tuple(unsolved_data["deals"][index]["deckOrder"]) for index in pending[:args.backfill_limit]]
        found_existing = 0
        tried = 0
        for deck_key in pending_decks:
            index = next(i for i, item in enumerate(unsolved_data["deals"]) if tuple(item["deckOrder"]) == deck_key)
            deal = unsolved_data["deals"][index]
            solutions, expanded, exhausted = solve(deal["deckOrder"], args.max_states, args.solutions_per_deal)
            tried += 1
            if solutions:
                solved_by_deck[tuple(deal["deckOrder"])] = {"deckOrder": deal["deckOrder"], "solutions": solutions}
                unsolved_data["deals"].pop(index)
                cursor = index % max(1, len(unsolved_data["deals"]))
                found_existing += 1
                status = f"{len(solutions)} Lösungen gefunden"
            else:
                deal["solutionSearch"] = {
                    "status": "exhausted" if exhausted else "search_limit",
                    "statesExpanded": expanded,
                }
                cursor = (index + 1) % max(1, len(unsolved_data["deals"]))
                status = f"keine Lösung ({deal['solutionSearch']['status']})"
            unsolved_data["solutionSearchCursor"] = cursor
            data["deals"] = list(solved_by_deck.values())
            save_outputs()
            print(f"Bestandsdeck: {status}, {expanded} Zustände.", file=sys.stderr)
            if found_existing >= args.count:
                break

        remaining = deals_needing_solutions(unsolved_data)
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

    existing = set(solved_by_deck)
    existing.update(tuple(deal.get("deckOrder", [])) for deal in unsolved_data["deals"])
    rng = secrets.SystemRandom()
    found = 0

    for attempt in range(1, args.max_attempts + 1):
        deck = list(range(52))
        rng.shuffle(deck)
        if tuple(deck) in existing:
            continue
        solutions, expanded, exhausted = solve(deck, args.max_states, args.solutions_per_deal)
        if not solutions:
            unsolved_data["deals"].append({
                "deckOrder": deck,
                "solutionSearch": {"status": "exhausted" if exhausted else "search_limit", "statesExpanded": expanded},
            })
            existing.add(tuple(deck))
            save_outputs()
            print(f"Versuch {attempt}/{args.max_attempts}: Deck ohne Lösung gespeichert ({expanded} Zustände).", file=sys.stderr)
            continue

        deal = {
            "deckOrder": deck,
            "solutions": solutions,
        }
        solved_by_deck[tuple(deck)] = deal
        existing.add(tuple(deck))
        found += 1
        save_outputs()
        print(f"Deck {found}/{args.count} gespeichert ({len(solutions)} Lösungen, {expanded} Zustände).", file=sys.stderr)
        if found >= args.count:
            break

    if found < args.count:
        print(
            f"Nur {found} von {args.count} gewünschten Decks gefunden. Sammlung enthält {len(solved_by_deck)} Decks insgesamt.",
            file=sys.stderr,
        )
        return 1
    print(f"{args.count} neues lösbares Deck in {args.deck_dir} gespeichert; Sammlung enthält {len(solved_by_deck)} Deck(s).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Fehler: {error}", file=sys.stderr)
        raise SystemExit(2)
