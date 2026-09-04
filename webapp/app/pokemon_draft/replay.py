"""Pokemon Showdown replay fetch + parse. Kills/deaths are computed from
the battle's protocol log -- this module only ever produces the same
shape app/pokemon_draft/matches.py's report_match()/resolve_dispute()
already know how to store (entry_method='replay' instead of 'manual');
the confirm/dispute state machine itself is untouched, see
app/routes/pokemon_draft/schedule.py for where the two entry methods
converge back into one report.

Kill attribution heuristic: track each battle position slot (p1a/p1b for
doubles, p1a/p2a for singles) to its current species via
|switch|/|drag|/|replace| lines, and the most recently-moving slot via
|move| lines. Every |-damage| line updates that TARGET slot's "most
recent damager" -- to the current mover, for a plain move hit, or
explicitly to "no one" for anything carrying a "[from]" tag (status,
weather, hazards, recoil, item damage). A |faint| line then credits
whichever damager is on record for that slot at that moment, or credits
no one if the last hit was indirect -- matches how these leagues already
score kills by hand ("who actually landed the finishing blow"), not every
point of chip damage along the way.
"""
import requests

from app.pokemon_draft import pokedex

FETCH_TIMEOUT_SECONDS = 8


class ReplayFetchError(Exception):
    """Raised by fetch_replay_json on any network/HTTP/JSON failure --
    callers catch this and degrade to parse_status='failed', never a
    500."""


def _to_json_url(replay_url):
    url = replay_url.strip()
    base, _, query = url.partition("?")
    if not base.endswith(".json"):
        base = base.rstrip("/") + ".json"
    return f"{base}?{query}" if query else base


def fetch_replay_json(replay_url):
    """The replay's JSON payload ({id, format, p1, p2, log, uploadtime,
    ...}), or raises ReplayFetchError."""
    url = _to_json_url(replay_url)
    try:
        resp = requests.get(url, timeout=FETCH_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as e:
        raise ReplayFetchError(f"Couldn't fetch that replay: {e}") from e


def _slot_of(field):
    """'p1a: Nickname' -> 'p1a'"""
    return field.split(":", 1)[0].strip()


def _species_of(details):
    """'Landorus-Therian, L50, M' -> 'Landorus-Therian'"""
    return details.split(",", 1)[0].strip()


def parse_battle_log(log_text, battle_style=None):
    """{"winner_side": "p1"|"p2"|None, "p1": {species: {"kills":n,
    "deaths":n}}, "p2": {...}}. battle_style is accepted for the caller's
    documentation/validation purposes only -- the slot-tracking algorithm
    itself doesn't need to branch on singles vs doubles, it just tracks
    whatever slots actually appear in the log.

    Never raises on malformed input -- an unparseable line is skipped
    (a battle log always has far more good lines than bad, and a partial
    result beats none); the caller decides whether the overall result
    (e.g. no winner found at all) counts as a parse failure."""
    slot_species = {}     # slot -> currently active species there
    damager_of = {}       # target_slot -> attacker_slot | None, as of the most recent -damage
    most_recent_mover = None
    player_names = {}     # 'p1' | 'p2' -> player display name
    stats = {"p1": {}, "p2": {}}
    winner_side = None

    def bump(side, species, kills=0, deaths=0):
        entry = stats[side].setdefault(species, {"kills": 0, "deaths": 0})
        entry["kills"] += kills
        entry["deaths"] += deaths

    for line in log_text.splitlines():
        if not line.startswith("|"):
            continue
        parts = line.split("|")
        if len(parts) < 2:
            continue
        event = parts[1]

        try:
            if event in ("switch", "drag", "replace") and len(parts) > 3:
                slot = _slot_of(parts[2])
                slot_species[slot] = _species_of(parts[3])

            elif event == "move" and len(parts) > 2:
                most_recent_mover = _slot_of(parts[2])

            elif event == "-damage" and len(parts) > 2:
                target_slot = _slot_of(parts[2])
                indirect = "[from]" in line
                damager_of[target_slot] = None if indirect else most_recent_mover

            elif event == "faint" and len(parts) > 2:
                slot = _slot_of(parts[2])
                species = slot_species.get(slot)
                if species is None:
                    continue
                bump(slot[:2], species, deaths=1)
                attacker_slot = damager_of.get(slot)
                if attacker_slot is not None:
                    attacker_species = slot_species.get(attacker_slot)
                    if attacker_species is not None:
                        bump(attacker_slot[:2], attacker_species, kills=1)

            elif event == "player" and len(parts) > 3 and parts[2] in ("p1", "p2"):
                player_names[parts[2]] = parts[3]

            elif event == "win" and len(parts) > 2:
                for side, name in player_names.items():
                    if name == parts[2]:
                        winner_side = side
        except Exception:
            continue

    return {"winner_side": winner_side, "p1": stats["p1"], "p2": stats["p2"]}


def build_game_from_replay(conn, replay_url, home_coach_id, away_coach_id, home_is_p1):
    """Fetches and parses one game from a Showdown replay link into a
    games-list entry compatible with app/pokemon_draft/matches.py's
    report_match()/resolve_dispute() (entry_method='replay', with parse
    provenance fields set). Returns (game_dict, None) on success or
    (None, error string) on failure -- never raises, and never returns a
    partial game_dict on failure, matching every other function in this
    package's "nothing is saved on error" contract: a bad replay link
    fails the whole report cleanly rather than persisting a half-parsed
    row a coach would have to notice and fix later.

    home_is_p1: whether the season's "home" coach was Player 1 in this
    specific replay -- Showdown's p1/p2 side assignment has no relation
    to our home/away labels, so the reporter says which was which."""
    replay_battle_id = replay_url.strip().rstrip("/").rsplit("/", 1)[-1].split("?")[0]
    try:
        payload = fetch_replay_json(replay_url)
    except ReplayFetchError as e:
        return None, str(e)

    parsed = parse_battle_log(payload.get("log", ""))
    if parsed["winner_side"] is None:
        return None, "Couldn't find a winner in that replay -- check the link and try again."

    p1_coach = home_coach_id if home_is_p1 else away_coach_id
    p2_coach = away_coach_id if home_is_p1 else home_coach_id
    winner_coach_id = p1_coach if parsed["winner_side"] == "p1" else p2_coach

    stats = []
    for side, coach_id in (("p1", p1_coach), ("p2", p2_coach)):
        for species_name, kd in parsed[side].items():
            pokemon_id = pokedex.find_by_species_name(conn, species_name)
            if pokemon_id is None:
                continue  # an unmatched cosmetic form etc. -- skip rather than fail the whole report
            stats.append({
                "coach_id": coach_id, "pokemon_id": pokemon_id,
                "kills": kd["kills"], "deaths": kd["deaths"],
            })

    return {
        "winner_coach_id": winner_coach_id, "stats": stats, "entry_method": "replay",
        "replay_url": replay_url, "replay_battle_id": replay_battle_id,
        "parse_status": "parsed", "parse_error": None,
        "raw_log_uploadtime": payload.get("uploadtime"),
    }, None
