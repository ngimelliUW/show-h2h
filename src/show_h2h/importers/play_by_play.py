"""Turn stored play-by-play text into structured events.

Purely local: it re-reads game_log_text, so re-parsing after a parser change
costs nothing and touches no network. Safe to re-run — each game's rows are
replaced.
"""
from __future__ import annotations

from show_h2h import db, playbyplay


def _result_of(outcome: str) -> str:
    """Classify what a perfect-perfect ball actually became."""
    low = (outcome or "").lower()
    if "homered" in low:
        return "home run"
    if "tripled" in low:
        return "triple"
    if "doubled" in low:
        return "double"
    if "for a single" in low or "singled" in low:
        return "single"
    if " out" in low or "lined into" in low or "grounded into" in low:
        return "out"
    return "other"


def _squad_owners(conn, game_uuid: str) -> dict[str, str]:
    """Squad name -> username, so 'Worms batting.' can be attributed."""
    row = conn.execute(
        "SELECT home_squad, home_username, away_squad, away_username "
        "FROM games WHERE game_uuid = ?", (game_uuid,)).fetchone()
    if not row:
        return {}
    return {
        (row["home_squad"] or "").strip(): row["home_username"],
        (row["away_squad"] or "").strip(): row["away_username"],
    }


def _batter_owners(conn, game_uuid: str) -> dict[str, str | None]:
    """Surname -> username for this game's box score.

    Both players field cards with the same surname, so a name that appears on
    both sides is genuinely ambiguous here and is left unattributed rather than
    guessed.
    """
    owners: dict[str, set] = {}
    for r in conn.execute(
            "SELECT player_name, username FROM batting_lines WHERE game_uuid = ?",
            (game_uuid,)):
        owners.setdefault(r["player_name"], set()).add(r["username"])
    return {name: (next(iter(who)) if len(who) == 1 else None)
            for name, who in owners.items()}


def _import_one(conn, game_uuid: str, text: str) -> tuple[int, int]:
    parsed = playbyplay.parse(text)
    squads = _squad_owners(conn, game_uuid)
    batters = _batter_owners(conn, game_uuid)
    everyone = {u for u in squads.values() if u}

    conn.execute("DELETE FROM pa_events WHERE game_uuid = ?", (game_uuid,))
    conn.execute("DELETE FROM contact_events WHERE game_uuid = ?", (game_uuid,))
    conn.execute("DELETE FROM half_innings WHERE game_uuid = ?", (game_uuid,))

    for idx, h in enumerate(parsed.get("halves", [])):
        batting = squads.get((h["squad"] or "").strip())
        pitching = next((u for u in everyone if u != batting), None) if batting else None
        conn.execute(
            """INSERT INTO half_innings (game_uuid, idx, inning, squad, batting_username,
                   pitching_username, runs, hits, walks, errors, pitches, lob, strikeouts)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (game_uuid, idx, h["inning"], h["squad"], batting, pitching,
             h["runs"], h["hits"], h["walks"], h["errors"], h["pitches"],
             h["lob"], h["strikeouts"]))

    for idx, e in enumerate(parsed["events"]):
        batting = squads.get((e["squad"] or "").strip())
        # The other side of the same game is the pitcher.
        pitching = next((u for u in everyone if u != batting), None) if batting else None
        conn.execute(
            """INSERT INTO pa_events (game_uuid, idx, inning, squad, batting_username,
                   pitching_username, batter, kind, pitch_type, location, timing,
                   distance, direction, critical, scored, go_ahead)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (game_uuid, idx, e["inning"], e["squad"], batting, pitching, e["batter"],
             e["kind"], e["pitch_type"], e["location"], e["timing"], e["distance"],
             e["direction"], e["critical"], e["scored"], e["go_ahead"]))

    for idx, c in enumerate(parsed["perfect"]):
        # Prefer the squad the parser recovered from the narrative; fall back to
        # the box-score surname, which is ambiguous when both sides run a card
        # with the same name.
        owner = squads.get((c.get("squad") or "").strip()) or batters.get(c["batter"])
        conn.execute(
            """INSERT INTO contact_events (game_uuid, idx, batter, username,
                   exit_velo, outcome, result) VALUES (?,?,?,?,?,?,?)""",
            (game_uuid, idx, c["batter"], owner,
             c["exit_velo"], c["outcome"], _result_of(c["outcome"])))

    conn.execute(
        """INSERT INTO game_meta (game_uuid, hitting_difficulty, pitching_difficulty,
               stadium, weather) VALUES (?,?,?,?,?)
           ON CONFLICT(game_uuid) DO UPDATE SET
               hitting_difficulty=excluded.hitting_difficulty,
               pitching_difficulty=excluded.pitching_difficulty,
               stadium=excluded.stadium, weather=excluded.weather""",
        (game_uuid, parsed["hitting_difficulty"], parsed["pitching_difficulty"],
         parsed["stadium"], parsed["weather"]))

    return len(parsed["events"]), len(parsed["perfect"])


def run_import(conn=None) -> dict:
    own = conn is None
    conn = conn or db.connect()
    events = contacts = games = 0
    try:
        rows = conn.execute("SELECT game_uuid, text FROM game_log_text").fetchall()
        for row in rows:
            e, c = _import_one(conn, row["game_uuid"], row["text"])
            events += e
            contacts += c
            games += 1
        conn.commit()
        db.log_import(conn, "play_by_play", None, None, events)
    finally:
        if own:
            conn.close()
    return {"games": games, "events": events, "contacts": contacts}
