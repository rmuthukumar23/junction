"""Checkers (English draughts) tournament, run locally and fanned out on Modal.

Throwaway load test for Modal; independent of envkit. Agents are scripted
stand-ins (random, greedy, minimax) because no model credentials are configured.
Games are deterministic for a fixed seed, so local and Modal results must match.

    python -m modal run test/checkers_sim.py --games 6 --depth 4
"""

import random
import time

import modal

app = modal.App("junction-checkers-sim")
image = modal.Image.debian_slim(python_version="3.12").add_local_python_source("checkers_sim")

# Board: 8x8 list of rows. 'r'/'R' move toward row 0, 'b'/'B' toward row 7.
# Uppercase = king. Dark squares are those with (row + col) odd.


def new_board():
    b = [[None] * 8 for _ in range(8)]
    for r in range(8):
        for c in range(8):
            if (r + c) % 2 == 1:
                if r < 3:
                    b[r][c] = "b"
                elif r > 4:
                    b[r][c] = "r"
    return b


def _dirs(piece):
    if piece.isupper():
        return [(-1, -1), (-1, 1), (1, -1), (1, 1)]
    return [(-1, -1), (-1, 1)] if piece == "r" else [(1, -1), (1, 1)]


def _promotes(piece, row):
    return (piece == "r" and row == 0) or (piece == "b" and row == 7)


def _jumps(board, r, c, piece, side, path, caps):
    found = []
    for dr, dc in _dirs(piece):
        mr, mc, tr, tc = r + dr, c + dc, r + 2 * dr, c + 2 * dc
        if not (0 <= tr < 8 and 0 <= tc < 8):
            continue
        mid = board[mr][mc]
        if mid and mid.lower() != side and (mr, mc) not in caps and (board[tr][tc] is None or (tr, tc) == path[0]):
            newcaps = caps + [(mr, mc)]
            if _promotes(piece, tr):
                found.append((path + [(tr, tc)], newcaps))
            else:
                more = _jumps(board, tr, tc, piece, side, path + [(tr, tc)], newcaps)
                found.extend(more or [(path + [(tr, tc)], newcaps)])
    return found


def legal_moves(board, side):
    jumps, steps = [], []
    for r in range(8):
        for c in range(8):
            p = board[r][c]
            if not p or p.lower() != side:
                continue
            jumps.extend(_jumps(board, r, c, p, side, [(r, c)], []))
            for dr, dc in _dirs(p):
                tr, tc = r + dr, c + dc
                if 0 <= tr < 8 and 0 <= tc < 8 and board[tr][tc] is None:
                    steps.append(([(r, c), (tr, tc)], []))
    return jumps or steps  # capturing is mandatory


def apply(board, move):
    path, caps = move
    b = [row[:] for row in board]
    (r0, c0), (r1, c1) = path[0], path[-1]
    p = b[r0][c0]
    b[r0][c0] = None
    for cr, cc in caps:
        b[cr][cc] = None
    b[r1][c1] = p.upper() if _promotes(p, r1) else p
    return b


def material(board, side):
    score = 0
    for row in board:
        for p in row:
            if p:
                v = 3 if p.isupper() else 1
                score += v if p.lower() == side else -v
    return score


def other(side):
    return "b" if side == "r" else "r"


# --- agents: f(board, side, rng) -> move -------------------------------------

def random_agent(board, side, rng):
    return rng.choice(legal_moves(board, side))


def greedy_agent(board, side, rng):
    moves = legal_moves(board, side)
    best = max(material(apply(board, m), side) for m in moves)
    return rng.choice([m for m in moves if material(apply(board, m), side) == best])


def _minimax(board, side, me, depth, alpha, beta):
    moves = legal_moves(board, side)
    if not moves:
        return -100 if side == me else 100
    if depth == 0:
        return material(board, me)
    if side == me:
        v = -1e9
        for m in moves:
            v = max(v, _minimax(apply(board, m), other(side), me, depth - 1, alpha, beta))
            alpha = max(alpha, v)
            if alpha >= beta:
                break
        return v
    v = 1e9
    for m in moves:
        v = min(v, _minimax(apply(board, m), other(side), me, depth - 1, alpha, beta))
        beta = min(beta, v)
        if alpha >= beta:
            break
    return v


def make_minimax(depth):
    def agent(board, side, rng):
        moves = legal_moves(board, side)
        scored = [(_minimax(apply(board, m), other(side), side, depth - 1, -1e9, 1e9), m) for m in moves]
        best = max(s for s, _ in scored)
        return rng.choice([m for s, m in scored if s == best])
    return agent


def get_agent(name):
    if name == "random":
        return random_agent
    if name == "greedy":
        return greedy_agent
    if name.startswith("minimax"):
        return make_minimax(int(name[len("minimax"):]))
    raise ValueError(name)


def play_game(red, black, seed, max_plies=200):
    """Returns (winner 'r'|'b'|'draw', plies). Deterministic for a given seed."""
    rng = random.Random(seed)
    agents = {"r": get_agent(red), "b": get_agent(black)}
    board, side = new_board(), "r"
    for ply in range(max_plies):
        moves = legal_moves(board, side)
        if not moves:
            return other(side), ply
        board = apply(board, agents[side](board, side, rng))
        side = other(side)
    return "draw", max_plies


@app.function(image=image, timeout=600)
def remote_game(red, black, seed):
    t = time.time()
    winner, plies = play_game(red, black, seed)
    return {"red": red, "black": black, "seed": seed, "winner": winner,
            "plies": plies, "secs": time.time() - t}


MATCHUPS_FN = lambda depth: [("random", "greedy"), ("greedy", f"minimax{depth}"), ("random", f"minimax{depth}"),
                              (f"minimax{depth}", f"minimax{depth}")]


def summarize(results):
    table = {}
    for r in results:
        key = (r["red"], r["black"])
        w = table.setdefault(key, {"r": 0, "b": 0, "draw": 0})
        w[r["winner"]] += 1
    for (red, black), w in table.items():
        print(f"  red={red:<9} black={black:<9} red wins {w['r']}, black wins {w['b']}, draws {w['draw']}")


@app.local_entrypoint()
def main(games: int = 6, depth: int = 4, local_games: int = 2):
    jobs = [(red, black, s) for red, black in MATCHUPS_FN(depth) for s in range(games)]
    print(f"{len(jobs)} games ({games} seeds x 4 matchups, minimax depth {depth})")

    # Local reference on a small slice, to compare time and verify determinism.
    local_jobs = [(red, black, s) for red, black in MATCHUPS_FN(depth) for s in range(local_games)]
    t0 = time.time()
    local = [dict(zip(("winner", "plies"), play_game(*j)), red=j[0], black=j[1], seed=j[2]) for j in local_jobs]
    local_wall = time.time() - t0
    print(f"local: {len(local_jobs)} games serial in {local_wall:.1f}s")

    t0 = time.time()
    results = list(remote_game.starmap(jobs))
    wall = time.time() - t0
    cpu = sum(r["secs"] for r in results)
    print(f"modal: {len(jobs)} games in {wall:.1f}s wall (sum of game time {cpu:.1f}s, "
          f"speedup vs serial ~{cpu / wall:.1f}x)")
    summarize(results)

    remote_by_job = {(r["red"], r["black"], r["seed"]): (r["winner"], r["plies"]) for r in results}
    mismatches = [j for j, l in zip(local_jobs, local) if remote_by_job[j] != (l["winner"], l["plies"])]
    print(f"determinism: {len(local_jobs) - len(mismatches)}/{len(local_jobs)} local replays identical on Modal"
          + (f"; mismatches {mismatches}" if mismatches else ""))
