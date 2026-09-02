"""Team Colors feature -- re-themes the Solaris design system's three
dynamic accent tokens (--yellow/--green/--sky) to a user's chosen NFL
team's brand colors. Ported directly from the design spec's JS (see
docs/solaris-design-spec.md if present) rather than reinterpreted --
same fallback-tertiary and text-contrast rules, same team color table.

Hex values are drawn from common public team-color references, not
pulled programmatically from an official source -- spot-check against
your own source of truth if pixel-perfect brand accuracy matters.

Logo URLs point at nflverse's github-hosted squared_logos (from
teams_colors_logos.csv, the same dataset family used elsewhere in this
project) -- github.com/raw.githubusercontent.com is reachable from every
environment this app has run in, unlike ESPN's CDN or Wikipedia's, both
of which are blocked from the dev sandbox (confirmed via curl: espncdn.com
and upload.wikimedia.org both return nothing, raw.githubusercontent.com
returns 200 for all 32 teams).
"""

DEFAULT_YELLOW = "oklch(82% 0.15 95)"
DEFAULT_GREEN = "oklch(52% 0.11 145)"
DEFAULT_SKY = "oklch(74% 0.08 230)"

_LOGO_BASE = "https://raw.githubusercontent.com/nflverse/nflverse-pbp/master/squared_logos"

TEAMS = [
    {"id": "ari", "name": "Arizona Cardinals", "primary": "#97233F", "secondary": "#000000", "tertiary": "#FFB612"},
    {"id": "atl", "name": "Atlanta Falcons", "primary": "#A71930", "secondary": "#000000", "tertiary": "#A5ACAF"},
    {"id": "bal", "name": "Baltimore Ravens", "primary": "#241773", "secondary": "#000000", "tertiary": "#9E7C0C"},
    {"id": "buf", "name": "Buffalo Bills", "primary": "#00338D", "secondary": "#C60C30", "tertiary": None},
    {"id": "car", "name": "Carolina Panthers", "primary": "#0085CA", "secondary": "#101820", "tertiary": "#BFC0BF"},
    {"id": "chi", "name": "Chicago Bears", "primary": "#0B162A", "secondary": "#C83803", "tertiary": None},
    {"id": "cin", "name": "Cincinnati Bengals", "primary": "#FB4F14", "secondary": "#000000", "tertiary": None},
    {"id": "cle", "name": "Cleveland Browns", "primary": "#311D00", "secondary": "#FF3C00", "tertiary": None},
    {"id": "dal", "name": "Dallas Cowboys", "primary": "#041E42", "secondary": "#869397", "tertiary": None},
    {"id": "den", "name": "Denver Broncos", "primary": "#FB4F14", "secondary": "#002244", "tertiary": None},
    {"id": "det", "name": "Detroit Lions", "primary": "#0076B6", "secondary": "#B0B7BC", "tertiary": "#000000"},
    {"id": "gb", "name": "Green Bay Packers", "primary": "#203731", "secondary": "#FFB612", "tertiary": None},
    {"id": "hou", "name": "Houston Texans", "primary": "#03202F", "secondary": "#A71930", "tertiary": None},
    {"id": "ind", "name": "Indianapolis Colts", "primary": "#002C5F", "secondary": "#FFFFFF", "tertiary": None},
    {"id": "jax", "name": "Jacksonville Jaguars", "primary": "#006778", "secondary": "#000000", "tertiary": "#D7A22A"},
    {"id": "kc", "name": "Kansas City Chiefs", "primary": "#E31837", "secondary": "#FFB81C", "tertiary": None},
    {"id": "lv", "name": "Las Vegas Raiders", "primary": "#000000", "secondary": "#A5ACAF", "tertiary": None},
    {"id": "lac", "name": "Los Angeles Chargers", "primary": "#0080C6", "secondary": "#FFC20E", "tertiary": "#002244"},
    {"id": "la", "name": "Los Angeles Rams", "primary": "#003594", "secondary": "#FFA300", "tertiary": None},
    {"id": "mia", "name": "Miami Dolphins", "primary": "#008E97", "secondary": "#FC4C02", "tertiary": "#005778"},
    {"id": "min", "name": "Minnesota Vikings", "primary": "#4F2683", "secondary": "#FFC62F", "tertiary": None},
    {"id": "ne", "name": "New England Patriots", "primary": "#002244", "secondary": "#C60C30", "tertiary": "#B0B7BC"},
    {"id": "no", "name": "New Orleans Saints", "primary": "#D3BC8D", "secondary": "#101820", "tertiary": None},
    {"id": "nyg", "name": "New York Giants", "primary": "#0B2265", "secondary": "#A71930", "tertiary": "#A5ACAF"},
    {"id": "nyj", "name": "New York Jets", "primary": "#125740", "secondary": "#000000", "tertiary": None},
    {"id": "phi", "name": "Philadelphia Eagles", "primary": "#004C54", "secondary": "#A5ACAF", "tertiary": "#000000"},
    {"id": "pit", "name": "Pittsburgh Steelers", "primary": "#101820", "secondary": "#FFB612", "tertiary": "#C60C30"},
    {"id": "sf", "name": "San Francisco 49ers", "primary": "#AA0000", "secondary": "#B3995D", "tertiary": None},
    {"id": "sea", "name": "Seattle Seahawks", "primary": "#69BE28", "secondary": "#002244", "tertiary": "#A5ACAF"},
    {"id": "tb", "name": "Tampa Bay Buccaneers", "primary": "#D50A0A", "secondary": "#34302B", "tertiary": "#FF7900"},
    {"id": "ten", "name": "Tennessee Titans", "primary": "#0C2340", "secondary": "#4B92DB", "tertiary": "#C8102E"},
    {"id": "was", "name": "Washington Commanders", "primary": "#5A1414", "secondary": "#FFB612", "tertiary": None},
]

for _t in TEAMS:
    _t["logo"] = f"{_LOGO_BASE}/{_t['id'].upper()}.png"

TEAMS_BY_ID = {t["id"]: t for t in TEAMS}


def logo_for(team_code):
    """Logo URL for a standard team abbreviation (any case), or None if
    unrecognized. team_code is expected in this project's standard scheme
    (matches TEAMS' id uppercased) -- see coach_table/pickem_games."""
    team = TEAMS_BY_ID.get(team_code.lower()) if team_code else None
    return team["logo"] if team else None


def hex_luminance(hex_color):
    c = hex_color.lstrip("#")
    r = int(c[0:2], 16) / 255
    g = int(c[2:4], 16) / 255
    b = int(c[4:6], 16) / 255
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def fallback_tertiary(primary, secondary):
    """When a team has no third brand color: white or black, whichever
    contrasts better. If either primary/secondary is already light, fall
    back to black to avoid a near-duplicate; otherwise white."""
    has_light_color = hex_luminance(primary) > 0.7 or hex_luminance(secondary) > 0.7
    return "#000000" if has_light_color else "#FFFFFF"


def text_for(color):
    """Contrast-safe text/icon color for something sitting on top of
    `color`. Only meaningful for hex team colors -- the oklch defaults
    always get black (resolve() never calls this for them)."""
    if isinstance(color, str) and color.startswith("#"):
        return "#000000" if hex_luminance(color) > 0.55 else "#FFFFFF"
    return "#000000"


def resolve(user):
    """The three dynamic accent values (+ their contrast-safe text colors)
    for the current request, given the logged-in user dict (or None).
    Toggling team_colors_enabled off reverts to the defaults immediately
    even if a favorite_team is still set -- nothing destructive."""
    team = TEAMS_BY_ID.get(user.get("favorite_team")) if user else None
    use_team = bool(user and user.get("team_colors_enabled") and team)

    if use_team:
        primary = team["primary"]
        secondary = team["secondary"]
        tertiary = team["tertiary"] or fallback_tertiary(team["primary"], team["secondary"])
        return {
            "yellow": primary, "green": secondary, "sky": tertiary,
            "text_on_primary": text_for(primary),
            "text_on_secondary": text_for(secondary),
            "text_on_tertiary": text_for(tertiary),
        }

    return {
        "yellow": DEFAULT_YELLOW, "green": DEFAULT_GREEN, "sky": DEFAULT_SKY,
        "text_on_primary": "#000000", "text_on_secondary": "#000000", "text_on_tertiary": "#000000",
    }
