"""In-memory mock data + scoring for the NFL Pick'em game.

This is a mockup: games, spreads, scores, friends, and picks all live in
module-level state (reset on every app restart). Nothing here reads or
writes app.db/analytics.duckdb -- unlike the rest of the app, this feature
needs writes (picks), which the real read-only pipeline doesn't support
yet. A real version would need a small SQLite store (weeks, games,
picks, settings) instead of these module globals.

Scoring rule (see docs on the /games/pickem page for the settings that
drive it):
  - pick_mode "straight_up": 1 point for picking the game's actual winner.
  - pick_mode "spread": 1 point for picking the team that covered the
    spread that was live when the pick was made.
  - confidence_enabled: instead of 1 point, the pick is worth however many
    confidence points the user assigned it (1..N, each used once across
    the week's N games -- their most confident pick is worth N, least
    confident is worth 1).
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

TEAM_NAMES = {
    "BUF": "Bills", "MIA": "Dolphins", "NE": "Patriots", "NYJ": "Jets",
    "BAL": "Ravens", "CIN": "Bengals", "CLE": "Browns", "PIT": "Steelers",
    "HOU": "Texans", "IND": "Colts", "JAX": "Jaguars", "TEN": "Titans",
    "DEN": "Broncos", "KC": "Chiefs", "LV": "Raiders", "LAC": "Chargers",
    "DAL": "Cowboys", "NYG": "Giants", "PHI": "Eagles", "WAS": "Commanders",
    "CHI": "Bears", "DET": "Lions", "GB": "Packers", "MIN": "Vikings",
    "ATL": "Falcons", "CAR": "Panthers", "NO": "Saints", "TB": "Buccaneers",
    "ARI": "Cardinals", "LAR": "Rams", "SF": "49ers", "SEA": "Seahawks",
}

FRIENDS = ["Ian", "Jake", "Maria", "Chris"]

SETTINGS = {
    "pick_mode": "straight_up",  # "straight_up" or "spread"
    "confidence_enabled": False,
}


@dataclass
class Game:
    id: int
    away: str
    home: str
    spread: float  # points added to the home score; negative means home favored
    kickoff: str
    final: bool = False
    away_score: Optional[int] = None
    home_score: Optional[int] = None

    def favorite(self) -> str:
        return self.home if self.spread < 0 else self.away

    def spread_display(self) -> str:
        if self.spread == 0:
            return "Pick'em"
        fav = self.favorite()
        return f"{fav} -{abs(self.spread):g}"

    def winner(self) -> Optional[str]:
        if not self.final:
            return None
        if self.home_score == self.away_score:
            return "push"
        return self.home if self.home_score > self.away_score else self.away

    def cover(self) -> Optional[str]:
        if not self.final:
            return None
        margin = (self.home_score + self.spread) - self.away_score
        if margin > 0:
            return self.home
        if margin < 0:
            return self.away
        return "push"


WEEKS: Dict[int, Dict] = {
    1: {
        "label": "Week 1",
        "note": "Final -- sample results, used to demo standings/scoring.",
        "games": [
            Game(1, "BUF", "NYJ", 3.0, "Thu 8:20p", final=True, away_score=24, home_score=17),
            Game(2, "PIT", "BAL", -6.5, "Sun 1:00p", final=True, away_score=20, home_score=27),
            Game(3, "CLE", "CIN", -4.0, "Sun 1:00p", final=True, away_score=13, home_score=23),
            Game(4, "TEN", "HOU", -7.5, "Sun 1:00p", final=True, away_score=17, home_score=30),
            Game(5, "IND", "JAX", 2.5, "Sun 1:00p", final=True, away_score=27, home_score=24),
            Game(6, "NE", "MIA", -1.0, "Sun 1:00p", final=True, away_score=16, home_score=20),
            Game(7, "NYG", "WAS", -3.5, "Sun 1:00p", final=True, away_score=14, home_score=24),
            Game(8, "CAR", "ATL", -5.0, "Sun 1:00p", final=True, away_score=10, home_score=31),
            Game(9, "CHI", "GB", -2.5, "Sun 1:00p", final=True, away_score=21, home_score=20),
            Game(10, "MIN", "DET", -6.0, "Sun 1:00p", final=True, away_score=23, home_score=27),
            Game(11, "NO", "TB", -3.0, "Sun 1:00p", final=True, away_score=16, home_score=19),
            Game(12, "ARI", "SF", -8.0, "Sun 4:05p", final=True, away_score=13, home_score=33),
            Game(13, "LAR", "SEA", 1.5, "Sun 4:05p", final=True, away_score=24, home_score=21),
            Game(14, "DEN", "LAC", -1.5, "Sun 4:25p", final=True, away_score=20, home_score=17),
            Game(15, "LV", "KC", -9.5, "Sun 4:25p", final=True, away_score=17, home_score=31),
            Game(16, "DAL", "PHI", -3.5, "Sun 8:20p", final=True, away_score=21, home_score=24),
        ],
    },
    2: {
        "label": "Week 2",
        "note": "Open for picks -- lines below are live and lock at kickoff. "
                "4 teams on bye, so only 14 games this week.",
        "games": [
            Game(17, "MIA", "BUF", -6.5, "Thu 8:15p"),
            Game(18, "BAL", "CLE", -7.0, "Sun 1:00p"),
            Game(19, "CIN", "PIT", -2.5, "Sun 1:00p"),
            Game(20, "JAX", "HOU", -3.0, "Sun 1:00p"),
            Game(21, "NE", "NYJ", 1.0, "Sun 1:00p"),
            Game(22, "WAS", "NYG", -2.0, "Sun 1:00p"),
            Game(23, "ATL", "CAR", -6.0, "Sun 1:00p"),
            Game(24, "GB", "MIN", -3.5, "Sun 1:00p"),
            Game(25, "DET", "CHI", -5.5, "Sun 1:00p"),
            Game(26, "TB", "NO", -1.0, "Sun 1:00p"),
            Game(27, "SEA", "ARI", -2.5, "Sun 4:05p"),
            Game(28, "LAC", "LV", -4.5, "Sun 4:05p"),
            Game(29, "KC", "DEN", -7.5, "Sun 4:25p"),
            Game(30, "PHI", "DAL", -1.5, "Sun 8:20p"),
        ],
    },
}

OPEN_WEEK = 2
CLOSED_WEEKS = [w for w in WEEKS if w != OPEN_WEEK]

# picks[week][friend][game_id] = {"team": "KC", "confidence": 12}
PICKS: Dict[int, Dict[str, Dict[int, Dict]]] = {1: {}, 2: {}}


def _seed_week1_picks():
    # Deterministic mock picks so standings have something to show.
    week1 = WEEKS[1]["games"]
    plans = {
        "Ian": lambda i, g: g.home if i % 3 else g.away,
        "Jake": lambda i, g: g.favorite(),
        "Maria": lambda i, g: g.away if i % 2 else g.home,
        "Chris": lambda i, g: g.home,
    }
    for friend, pick_fn in plans.items():
        confidences = list(range(len(week1), 0, -1))
        for i, g in enumerate(week1):
            PICKS[1].setdefault(friend, {})[g.id] = {
                "team": pick_fn(i, g),
                "confidence": confidences[i],
            }


_seed_week1_picks()


def get_week(week: int) -> Dict:
    return WEEKS[week]


def get_picks(week: int, friend: str) -> Dict[int, Dict]:
    return PICKS.get(week, {}).get(friend, {})


def save_picks(week: int, friend: str, picks: Dict[int, Dict]):
    PICKS.setdefault(week, {})[friend] = picks


def score_pick(game: Game, pick: Optional[Dict]) -> Optional[int]:
    """Points earned for one game, or None if the game hasn't finished
    (or the friend has no pick recorded for it)."""
    if not game.final or not pick or not pick.get("team"):
        return None
    target = game.cover() if SETTINGS["pick_mode"] == "spread" else game.winner()
    if target == "push":
        return 0
    correct = pick["team"] == target
    if not SETTINGS["confidence_enabled"]:
        return 1 if correct else 0
    return pick.get("confidence") or 0 if correct else 0


@dataclass
class FriendWeekResult:
    friend: str
    points: int
    max_points: int
    correct: int
    total: int


def week_results(week: int) -> List[FriendWeekResult]:
    games = {g.id: g for g in WEEKS[week]["games"]}
    results = []
    for friend in FRIENDS:
        picks = get_picks(week, friend)
        points = 0
        correct = 0
        total = 0
        for gid, game in games.items():
            if not game.final:
                continue
            total += 1
            pts = score_pick(game, picks.get(gid))
            if pts:
                points += pts
                correct += 1
        results.append(FriendWeekResult(friend, points, len(games), correct, total))
    results.sort(key=lambda r: r.points, reverse=True)
    return results


def season_standings() -> List[Dict]:
    totals = {friend: {"friend": friend, "points": 0, "correct": 0, "played": 0} for friend in FRIENDS}
    for week in CLOSED_WEEKS:
        for r in week_results(week):
            totals[r.friend]["points"] += r.points
            totals[r.friend]["correct"] += r.correct
            totals[r.friend]["played"] += r.total
    rows = sorted(totals.values(), key=lambda r: r["points"], reverse=True)
    for i, row in enumerate(rows, start=1):
        row["rank"] = i
    return rows
