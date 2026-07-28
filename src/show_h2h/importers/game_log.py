"""Import game_log.json — the full box score for a game.

Also the point at which a game gets its real identity: game_uuid appears here
and nowhere else, so this importer replaces the placeholder natural_key primary
key with the true uuid, and fills in the stable numeric player ids.
"""
from __future__ import annotations

import json
import re

from show_h2h import client, config, db, identity


def _to_int(v, default=None):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def _split_batter(raw_name: str) -> tuple[str, str | None]:
    """'Clement, LF' -> ('Clement', 'LF'). Surname only — the API exposes no
    first name and no player id for batters, so cards can't be told apart."""
    name = (raw_name or "").strip()
    if "," in name:
        surname, _, pos = name.rpartition(",")
        return surname.strip(), pos.strip() or None
    return name, None


_DECISION = re.compile(r"\s*\([A-Z]{1,2}\)\s*$")


def _clean_pitcher(raw_name: str) -> str:
    """'Kluber (W)' -> 'Kluber'.

    The API appends the decision to the name: W, L, S (save), H (hold) and
    BS (blown save). All five must go, because the name is the leaderboard's
    grouping key — leaving any of them in splits one pitcher into several rows
    with partial stats. The decision is already in the win/loss/save/hold
    columns, so nothing is lost.
    """
    return _DECISION.sub("", raw_name or "").strip()


def _side_map(line_score: dict, box_score: list) -> dict:
    """Map each box_score team object to 'home' or 'away'.

    Teams are keyed by team_id, which for Diamond Dynasty games equals the
    owner's player id and for Exhibition is a real MLB team id. Falls back to
    array order (index 0 is home) if the ids don't line up.
    """
    by_id = {
        str(line_score.get("home_mlb_team_id")): "home",
        str(line_score.get("away_mlb_team_id")): "away",
    }
    sides = {}
    for idx, team in enumerate(box_score):
        tid = str(team.get("team_id"))
        sides[idx] = by_id.get(tid) or ("home" if idx == 0 else "away")
    return sides


def _import_one(conn, natural_key: str, api_id: str, username: str) -> None:
    sections = client.game_log(api_id, username)
    ls = sections.get("line_score") or {}
    uuid = ls.get("game_uuid")
    if not uuid:
        raise client.ApiError(f"game {api_id}: no game_uuid in line_score")

    resolved = identity.resolve(ls, username)

    # Promote the placeholder key to the real uuid. If a different natural_key
    # already claimed this uuid, the two history rows were the same game after
    # all — drop this duplicate and keep the promoted one.
    clash = conn.execute(
        "SELECT natural_key FROM games WHERE game_uuid = ? AND natural_key != ?",
        (uuid, natural_key)).fetchone()
    if clash:
        conn.execute("DELETE FROM games WHERE natural_key = ?", (natural_key,))
    else:
        conn.execute("UPDATE games SET game_uuid = ? WHERE natural_key = ?", (uuid, natural_key))
    conn.execute("UPDATE game_source_ids SET game_uuid = ? WHERE natural_key = ?",
                 (uuid, natural_key))

    conn.execute(
        """UPDATE games SET
               innings = ?, ruling = ?, game_mode = COALESCE(?, game_mode),
               home_player_id = ?, away_player_id = ?,
               home_username = CASE WHEN ? != '' THEN ? ELSE home_username END,
               away_username = CASE WHEN ? != '' THEN ? ELSE away_username END,
               has_box_score = 1
           WHERE game_uuid = ?""",
        (_to_int(ls.get("innings")), ls.get("ruling"), ls.get("game_mode"),
         ls.get("home_player_id"), ls.get("away_player_id"),
         resolved["home_username"], resolved["home_username"],
         resolved["away_username"], resolved["away_username"],
         uuid),
    )

    # Stable numeric ids beat usernames, which can be changed.
    for side in ("home", "away"):
        pid, uname = ls.get(f"{side}_player_id"), resolved[f"{side}_username"]
        if pid and uname and uname.upper() != "CPU":
            conn.execute(
                "UPDATE players SET player_id = ? WHERE username = ? AND player_id IS NULL",
                (pid, uname))

    # Line score. Only ever 9 columns exist, even for extra-inning games — the
    # missing runs are unrecoverable, which is why games.*_runs stays the truth.
    conn.execute("DELETE FROM game_innings WHERE game_uuid = ?", (uuid,))
    for i in range(1, 10):
        home, away = ls.get(f"home_runs_{i}"), ls.get(f"away_runs_{i}")
        if (home or "").strip() == "" and (away or "").strip() == "":
            continue  # unplayed inning — the API sends a single space
        conn.execute(
            "INSERT INTO game_innings (game_uuid, inning_no, home_runs, away_runs) VALUES (?,?,?,?)",
            (uuid, i, _to_int(home, 0), _to_int(away, 0)))

    # Box score.
    box = sections.get("box_score") or []
    sides = _side_map(ls, box)
    conn.execute("DELETE FROM batting_lines WHERE game_uuid = ?", (uuid,))
    conn.execute("DELETE FROM pitching_lines WHERE game_uuid = ?", (uuid,))

    for idx, team in enumerate(box):
        side = sides[idx]
        owner = resolved[f"{side}_username"]
        # Stats hide under a dynamic key equal to the team's own id.
        inner = team.get(str(team.get("team_id"))) or {}

        for slot, b in enumerate(inner.get("batting_stats") or []):
            name, pos = _split_batter(b.get("player_name"))
            conn.execute(
                """INSERT INTO batting_lines (game_uuid, side, username, slot, player_name, pos,
                       ab, r, h, rbi, bb, so, doubles, triples, hr, sh, sf, gidp, e, hbp, sb, cs,
                       raw, imported_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (uuid, side, owner, slot, name, pos,
                 _to_int(b.get("ab"), 0), _to_int(b.get("r"), 0), _to_int(b.get("h"), 0),
                 _to_int(b.get("rbi"), 0), _to_int(b.get("bb"), 0), _to_int(b.get("so"), 0),
                 _to_int(b.get("doubles"), 0), _to_int(b.get("triples"), 0), _to_int(b.get("hr"), 0),
                 _to_int(b.get("sh"), 0), _to_int(b.get("sf"), 0), _to_int(b.get("gidp"), 0),
                 _to_int(b.get("e"), 0), _to_int(b.get("hbp"), 0),
                 _to_int(b.get("sb"), 0), _to_int(b.get("cs"), 0),
                 json.dumps(b), db.now_iso()))

        for slot, p in enumerate(inner.get("pitching_stats") or []):
            conn.execute(
                """INSERT INTO pitching_lines (game_uuid, side, username, slot, player_name,
                       ip_text, outs, r, h, er, bb, so, win, loss, save, hold, wp, raw, imported_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (uuid, side, owner, slot, _clean_pitcher(p.get("player_name")),
                 p.get("ip"), identity.outs_from_ip(p.get("ip")),
                 _to_int(p.get("r"), 0), _to_int(p.get("h"), 0), _to_int(p.get("er"), 0),
                 _to_int(p.get("bb"), 0), _to_int(p.get("so"), 0),
                 _to_int(p.get("win"), 0), _to_int(p.get("loss"), 0),
                 _to_int(p.get("save"), 0), _to_int(p.get("hold"), 0), _to_int(p.get("wp"), 0),
                 json.dumps(p), db.now_iso()))

    text = sections.get("game_log")
    if isinstance(text, str):
        conn.execute(
            "INSERT INTO game_log_text (game_uuid, text, imported_at) VALUES (?,?,?) "
            "ON CONFLICT(game_uuid) DO UPDATE SET text=excluded.text",
            (uuid, text, db.now_iso()))


def run_import(conn=None, *, scope: str = "both-played", limit: int | None = None) -> dict:
    """Fetch box scores for games that don't have one yet.

    scope:
      'both-played' (default) — every game we were both in, whether as
                                opponents (head-to-head) or teammates (co-op).
      'h2h'                   — head-to-head only.
      'all'                   — every game either of us played. Several hundred
                                extra requests; the history rows are already
                                stored either way, this only adds box scores.
    """
    where = {
        "both-played": "AND (g.is_h2h = 1 OR g.is_coop = 1)",
        "h2h": "AND g.is_h2h = 1",
        "all": "",
    }[scope]
    own = conn is None
    conn = conn or db.connect()
    done = failed = 0
    try:
        sql = """
            SELECT g.natural_key, s.api_id, s.username
            FROM games g
            JOIN game_source_ids s ON s.natural_key = g.natural_key
            WHERE g.has_box_score = 0 {extra}
            ORDER BY g.played_at DESC
        """.format(extra=where)

        # A game has one source id per participant; either works, but prefer our
        # own account so a friend's platform being wrong can't break the crawl.
        by_game: dict[str, list] = {}
        for row in conn.execute(sql):
            by_game.setdefault(row["natural_key"], []).append(row)
        targets = [
            next((r for r in rows if r["username"].lower() == config.MY_USERNAME.lower()), rows[0])
            for rows in by_game.values()
        ]
        if limit:
            targets = targets[:limit]

        for row in targets:
            try:
                _import_one(conn, row["natural_key"], row["api_id"], row["username"])
                conn.commit()
                done += 1
            except client.ApiError as e:
                failed += 1
                print(f"  ! {row['api_id']} ({row['username']}): {e}")
        db.log_import(conn, "game_log", None, None, done)
    finally:
        if own:
            conn.close()
    return {"imported": done, "failed": failed, "pending": len(targets) - done - failed}
