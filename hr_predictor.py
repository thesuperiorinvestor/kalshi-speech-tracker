"""
HR Predictor
------------
Combines Optimal player props/projections, Baseball Savant park factors,
Open-Meteo weather, and pybaseball pitcher stats to surface HR value plays.
"""
import json
import math
import time
from datetime import date, datetime

import pandas as pd
import requests
import streamlit as st

try:
    import pybaseball
    pybaseball.cache.enable()
    HAS_PYBASEBALL = True
except ImportError:
    HAS_PYBASEBALL = False

# ─────────────────────────────────────────────────────────────────────────────
# STATIC DATA  — update park factors from baseballsavant.mlb.com each season
# ─────────────────────────────────────────────────────────────────────────────

# HR park index (100 = league avg). Source: Baseball Savant.
PARK_HR = {
    "Yankee Stadium":            118,
    "Fenway Park":               104,
    "Wrigley Field":             105,
    "Dodger Stadium":            111,
    "Oracle Park":                86,
    "Coors Field":               118,
    "Truist Park":               105,
    "T-Mobile Park":              90,
    "Globe Life Field":          105,
    "Angel Stadium":              93,
    "Petco Park":                 87,
    "American Family Field":     112,
    "Target Field":               97,
    "Busch Stadium":              92,
    "Kauffman Stadium":           96,
    "PNC Park":                   96,
    "Great American Ball Park":  113,
    "Citizens Bank Park":        110,
    "Citi Field":                 96,
    "Nationals Park":            100,
    "Camden Yards":              108,
    "Rate Field":                 96,
    "Progressive Field":          97,
    "Tropicana Field":            99,
    "Rogers Centre":             116,
    "Chase Field":               105,
    "loanDepot park":             93,
    "Minute Maid Park":          107,
    "Oakland Coliseum":           95,
    "Comerica Park":              92,
}

# Stadium lat/lon for Open-Meteo weather
STADIUM_COORDS = {
    "Yankee Stadium":            (40.8296, -73.9262),
    "Fenway Park":               (42.3467, -71.0972),
    "Wrigley Field":             (41.9484, -87.6553),
    "Dodger Stadium":            (34.0739, -118.2400),
    "Oracle Park":               (37.7786, -122.3893),
    "Coors Field":               (39.7559, -104.9942),
    "Truist Park":               (33.8908, -84.4677),
    "T-Mobile Park":             (47.5914, -122.3325),
    "Globe Life Field":          (32.7473, -97.0820),
    "Angel Stadium":             (33.8003, -117.8827),
    "Petco Park":                (32.7073, -117.1573),
    "American Family Field":     (43.0280, -87.9712),
    "Target Field":              (44.9817, -93.2786),
    "Busch Stadium":             (38.6226, -90.1928),
    "Kauffman Stadium":          (39.0517, -94.4803),
    "PNC Park":                  (40.4469, -80.0057),
    "Great American Ball Park":  (39.0979, -84.5082),
    "Citizens Bank Park":        (39.9061, -75.1665),
    "Citi Field":                (40.7571, -73.8458),
    "Nationals Park":            (38.8730, -77.0074),
    "Camden Yards":              (39.2838, -76.6217),
    "Rate Field":                (41.8299, -87.6338),
    "Progressive Field":         (41.4960, -81.6852),
    "Tropicana Field":           (27.7683, -82.6534),
    "Rogers Centre":             (43.6414, -79.3894),
    "Chase Field":               (33.4453, -112.0667),
    "loanDepot park":            (25.7781, -80.2197),
    "Minute Maid Park":          (29.7573, -95.3555),
    "Oakland Coliseum":          (37.7516, -122.2005),
    "Comerica Park":             (42.3390, -83.0485),
}

# Direction from home plate toward CF (degrees, 0=N 90=E).
# Wind blowing IN this direction = tailwind = HR boost.
STADIUM_CF_DEG = {
    "Yankee Stadium":            50,
    "Fenway Park":               60,
    "Wrigley Field":             60,
    "Dodger Stadium":           330,
    "Oracle Park":               10,
    "Coors Field":               90,
    "Truist Park":               15,
    "T-Mobile Park":            345,
    "Globe Life Field":           5,
    "Angel Stadium":             10,
    "Petco Park":               290,
    "American Family Field":    340,
    "Target Field":              45,
    "Busch Stadium":             20,
    "Kauffman Stadium":          20,
    "PNC Park":                 285,
    "Great American Ball Park": 355,
    "Citizens Bank Park":        10,
    "Citi Field":                10,
    "Nationals Park":           335,
    "Camden Yards":              35,
    "Rate Field":                10,
    "Progressive Field":         30,
    "Tropicana Field":            0,
    "Rogers Centre":            350,
    "Chase Field":              355,
    "loanDepot park":           350,
    "Minute Maid Park":          45,
    "Oakland Coliseum":         340,
    "Comerica Park":            355,
}

INDOOR_STADIUMS = {
    "Tropicana Field", "Rogers Centre", "Chase Field",
    "loanDepot park", "Minute Maid Park", "Globe Life Field", "Rate Field",
}

LEAGUE_AVG_HR9 = 1.35  # update each season

# ─────────────────────────────────────────────────────────────────────────────
# OPTIMAL MCP CLIENT
# ─────────────────────────────────────────────────────────────────────────────

class OptimalClient:
    URL = "https://mcp.tangiers.ai/"

    def __init__(self):
        self.session_id = None
        self._init_session()

    def _headers(self):
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        return h

    def _init_session(self):
        try:
            r = requests.post(self.URL, headers=self._headers(), json={
                "jsonrpc": "2.0", "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "hr-predictor", "version": "1.0"},
                },
                "id": 1,
            }, timeout=15)
            self.session_id = r.headers.get("Mcp-Session-Id")
            requests.post(self.URL, headers=self._headers(), json={
                "jsonrpc": "2.0", "method": "notifications/initialized", "params": {}
            }, timeout=10)
        except Exception as e:
            st.warning(f"Optimal connection issue: {e}")

    def call(self, tool: str, **kwargs):
        payload = {
            "jsonrpc": "2.0", "method": "tools/call",
            "params": {"name": tool, "arguments": kwargs},
            "id": 2,
        }
        for attempt in range(5):
            try:
                r = requests.post(
                    self.URL, headers=self._headers(),
                    json=payload, timeout=30
                )
                if r.status_code == 429:
                    time.sleep(2 ** attempt)
                    continue
                r.raise_for_status()

                ct = r.headers.get("content-type", "")
                raw = self._parse_sse(r.text) if "text/event-stream" in ct else r.json()

                result = raw.get("result", {})
                content = result.get("content", [])
                if content and content[0].get("type") == "text":
                    try:
                        return json.loads(content[0]["text"])
                    except json.JSONDecodeError:
                        return content[0]["text"]
                return result
            except (requests.exceptions.ConnectionError, requests.exceptions.HTTPError):
                # Connection was reset — reinitialize session and retry
                time.sleep(2 ** attempt)
                self.session_id = None
                self._init_session()
        return None

    @staticmethod
    def _parse_sse(text: str):
        for line in text.splitlines():
            if line.startswith("data: "):
                try:
                    return json.loads(line[6:])
                except Exception:
                    pass
        return {}


@st.cache_resource
def get_client() -> OptimalClient:
    return OptimalClient()


# ─────────────────────────────────────────────────────────────────────────────
# DATA FETCHERS
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def fetch_games(game_date: str):
    return get_client().call("get_events", league="mlb", date=game_date) or []


@st.cache_data(ttl=300)
def fetch_game_props(event_id: str):
    """Return (batters_with_hr_props, pitcher_map {team: name})."""
    players = get_client().call("get_game_player_props", event_id=event_id) or []
    batters, pitchers = [], {}
    for p in players:
        if p.get("position") == "P":
            pitchers[p["team"]] = p["full_name"]
        elif "home runs" in p.get("prop_types", []):
            batters.append({
                "player_id": p["player_id"],
                "full_name":  p["full_name"],
                "team":       p["team"],
                "position":   p.get("position", ""),
            })
    return batters, pitchers


@st.cache_data(ttl=600)
def fetch_hr_rate(player_id: str, season: str):
    """(recent_hr_per_pa, season_hr_per_pa) from gamelogs."""
    logs = get_client().call("get_player_gamelogs", player_id=player_id, season=season) or []
    if not logs:
        return None, None

    def rate(games):
        hrs = sum(g["stats"].get("batting_homeRuns", 0) for g in games)
        pa  = sum(
            g["stats"].get("batting_atBats", 0)
            + g["stats"].get("batting_baseOnBalls", 0)
            + g["stats"].get("batting_hitByPitch", 0)
            for g in games
        )
        return hrs / pa if pa > 0 else 0.0

    return rate(logs[:15]), rate(logs)


@st.cache_data(ttl=300)
def fetch_hr_odds(player_id: str, event_id: str):
    """(implied_prob, best_over_price) for the HR prop."""
    data = get_client().call(
        "get_player_prop_odds", player_id=player_id,
        event_id=event_id, prop_type="home runs"
    )
    if not data:
        return None, None

    # Normalise: data may be a dict or a list
    odds_by_book = {}
    if isinstance(data, dict):
        odds_by_book = data.get("oddsBySportsbook", {})
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                odds_by_book = item.get("odds", {}).get("oddsBySportsbook", {})
                if odds_by_book:
                    break

    over_prices = [
        line["price"]
        for lines in odds_by_book.values()
        for line in lines
        if line.get("side") == "over"
    ]
    if not over_prices:
        return None, None

    best_price       = max(over_prices)
    consensus_price  = sorted(over_prices)[len(over_prices) // 2]
    implied_prob     = american_to_prob(consensus_price)
    return implied_prob, best_price


@st.cache_data(ttl=300)
def fetch_hr_projection(player_id: str, event_id: str):
    """Return the HR projection row (dict with p50/p75/p90/…) or {}."""
    data = get_client().call(
        "get_player_projections", player_id=player_id, event_id=event_id
    )
    rows = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
    for row in rows:
        for proj in row.get("projections", []):
            if proj.get("propType") == "home runs":
                return proj
    return {}


@st.cache_data(ttl=3600)
def fetch_pitcher_hr9(pitcher_name: str, year: int) -> float:
    """Look up pitcher HR/9 from FanGraphs via pybaseball."""
    if not HAS_PYBASEBALL or not pitcher_name or pitcher_name == "Unknown":
        return LEAGUE_AVG_HR9
    try:
        df = pybaseball.pitching_stats(year, year, qual=0)
        match = df[df["Name"].str.lower() == pitcher_name.lower()]
        if match.empty:
            last = pitcher_name.split()[-1].lower()
            match = df[df["Name"].str.lower().str.contains(last, na=False)]
        if not match.empty and "HR/9" in match.columns:
            val = float(match.iloc[0]["HR/9"])
            return val if val > 0 else LEAGUE_AVG_HR9
    except Exception:
        pass
    return LEAGUE_AVG_HR9


@st.cache_data(ttl=900)
def fetch_weather(venue: str, start_date: str):
    """Open-Meteo weather at game time. Returns dict or None."""
    if venue in INDOOR_STADIUMS:
        return {"temp_f": 72, "wind_speed": 0, "wind_deg": 0, "indoor": True}

    coords = STADIUM_COORDS.get(venue)
    if not coords:
        return None

    lat, lon = coords
    try:
        dt       = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        hour     = dt.hour
        date_str = dt.strftime("%Y-%m-%d")
    except Exception:
        return None

    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&hourly=temperature_2m,wind_speed_10m,wind_direction_10m"
        f"&temperature_unit=fahrenheit&wind_speed_unit=mph"
        f"&timezone=auto&start_date={date_str}&end_date={date_str}"
    )
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        d = r.json()["hourly"]
        h = min(hour, len(d["temperature_2m"]) - 1)
        return {
            "temp_f":     d["temperature_2m"][h],
            "wind_speed": d["wind_speed_10m"][h],
            "wind_deg":   d["wind_direction_10m"][h],
            "indoor":     False,
        }
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# MODEL
# ─────────────────────────────────────────────────────────────────────────────

def american_to_prob(price: float) -> float:
    if price < 0:
        return abs(price) / (abs(price) + 100)
    return 100 / (price + 100)


def wind_multiplier(weather: dict, venue: str) -> float:
    if not weather or weather.get("indoor") or weather.get("wind_speed", 0) < 3:
        return 1.0
    cf_deg   = STADIUM_CF_DEG.get(venue, 0)
    angle    = math.radians(weather["wind_deg"] - cf_deg)
    tailwind = math.cos(angle)                         # +1 = full out, -1 = full in
    effect   = tailwind * (weather["wind_speed"] / 10) * 0.12
    return round(max(0.75, min(1.30, 1.0 + effect)), 3)


def temp_multiplier(weather: dict) -> float:
    if not weather or weather.get("indoor"):
        return 1.0
    effect = (weather.get("temp_f", 70) - 70) / 10 * 0.03
    return round(max(0.88, min(1.12, 1.0 + effect)), 3)


def calc_hr_prob(
    recent_rate: float | None,
    season_rate: float | None,
    park_factor: int,
    pitcher_hr9: float,
    weather: dict | None,
    venue: str,
) -> float | None:
    if recent_rate is None and season_rate is None:
        return None
    r = recent_rate or 0.0
    s = season_rate or 0.0
    base = (0.6 * r + 0.4 * s) if (r and s) else (r or s)
    if base == 0:
        return None

    prob = (
        base
        * (park_factor / 100)
        * (pitcher_hr9 / LEAGUE_AVG_HR9)
        * wind_multiplier(weather or {}, venue)
        * temp_multiplier(weather or {})
    )
    return round(prob, 4)


def fmt_price(price) -> str:
    if price is None:
        return "—"
    return f"+{int(price)}" if price > 0 else str(int(price))


# ─────────────────────────────────────────────────────────────────────────────
# STREAMLIT UI
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="HR Predictor", layout="wide")
st.title("HR Predictor")

col1, col2, col3 = st.columns([2, 2, 4])
with col1:
    selected_date = st.date_input("Date", value=date.today())
with col2:
    min_edge_pct = st.slider("Min edge (%)", 0, 20, 3)
with col3:
    st.caption(
        "Model: base HR/PA (recent + season) × park factor × pitcher HR/9 × wind × temp. "
        "Edge = model prob − market implied prob."
    )

game_date_code = selected_date.strftime("%Y%m%d")
run = st.button("Run Model", type="primary")

if run:
    with st.spinner("Fetching games…"):
        games = fetch_games(game_date_code)

    scheduled = [g for g in games if g.get("status") in ("Scheduled", "scheduled")]
    if not scheduled:
        st.warning("No scheduled MLB games found for this date.")
        st.stop()

    st.caption(f"{len(scheduled)} scheduled games")
    results = []
    progress = st.progress(0, text="Processing games…")

    for i, game in enumerate(scheduled):
        progress.progress((i + 1) / len(scheduled), text=f"{game['away_display']} @ {game['home_display']}")

        event_id   = game["id"]
        venue      = game.get("venue", "")
        park_factor = PARK_HR.get(venue, 100)
        weather    = fetch_weather(venue, game["start_date"])

        batters, pitcher_map = fetch_game_props(event_id)

        # Pitcher HR/9: away pitcher faces home batters, home pitcher faces away batters
        away_sp      = pitcher_map.get(game["away_team"], "Unknown")
        home_sp      = pitcher_map.get(game["home_team"], "Unknown")
        away_sp_hr9  = fetch_pitcher_hr9(away_sp, selected_date.year)
        home_sp_hr9  = fetch_pitcher_hr9(home_sp, selected_date.year)

        for batter in batters:
            pid  = batter["player_id"]
            team = batter["team"]

            # Pitcher this batter faces
            opp_sp   = away_sp   if team == game["home_team"] else home_sp
            opp_hr9  = away_sp_hr9 if team == game["home_team"] else home_sp_hr9

            recent_rate, season_rate = fetch_hr_rate(pid, str(selected_date.year))
            time.sleep(0.5)
            implied_prob, best_price = fetch_hr_odds(pid, event_id)
            time.sleep(0.5)
            proj = fetch_hr_projection(pid, event_id)
            time.sleep(0.5)

            if implied_prob is None:
                continue

            model_prob = calc_hr_prob(
                recent_rate, season_rate, park_factor, opp_hr9, weather, venue
            )
            if model_prob is None:
                continue

            edge = model_prob - implied_prob
            w    = weather or {}

            results.append({
                "Player":          batter["full_name"],
                "Team":            team.upper(),
                "Matchup":         f"{game['away_display']} @ {game['home_display']}",
                "Venue":           venue,
                "Opp Pitcher":     opp_sp,
                "Park (idx)":      park_factor,
                "Wind":            f"{w.get('wind_speed', 0):.0f} mph" if not w.get("indoor") else "Indoor",
                "Temp (°F)":       f"{w.get('temp_f', '—'):.0f}" if not w.get("indoor") else "Indoor",
                "Wind Adj":        wind_multiplier(w, venue),
                "Pitcher HR/9":    round(opp_hr9, 2),
                "Recent HR/PA":    f"{recent_rate:.3f}" if recent_rate is not None else "—",
                "Season HR/PA":    f"{season_rate:.3f}" if season_rate is not None else "—",
                "Model Prob":      model_prob,
                "Market Prob":     implied_prob,
                "Edge":            edge,
                "Best Price":      fmt_price(best_price),
                "Proj p50":        proj.get("p50", "—"),
                "Proj p75":        proj.get("p75", "—"),
                "Proj p90":        proj.get("p90", "—"),
            })

    progress.empty()

    if not results:
        st.info("No HR props with enough data found for today's scheduled games.")
        st.stop()

    df = pd.DataFrame(results).sort_values("Edge", ascending=False)
    df["Edge %"]       = df["Edge"].map("{:+.1%}".format)
    df["Model Prob %"] = df["Model Prob"].map("{:.1%}".format)
    df["Market Prob %"] = df["Market Prob"].map("{:.1%}".format)

    min_edge = min_edge_pct / 100
    value_df = df[df["Edge"] >= min_edge]

    # ── Value plays ──────────────────────────────────────────────────────────
    st.subheader(f"Value Plays  (edge ≥ {min_edge_pct}%)")
    if value_df.empty:
        st.info("No value plays at this threshold.")
    else:
        display_cols = [
            "Player", "Team", "Opp Pitcher", "Venue",
            "Park (idx)", "Wind", "Temp (°F)", "Pitcher HR/9",
            "Model Prob %", "Market Prob %", "Edge %", "Best Price",
            "Proj p75", "Proj p90",
        ]
        st.dataframe(
            value_df[display_cols].reset_index(drop=True),
            use_container_width=True,
        )

    # ── Full table ───────────────────────────────────────────────────────────
    with st.expander("All players"):
        all_cols = [
            "Player", "Team", "Matchup", "Opp Pitcher",
            "Park (idx)", "Wind Adj", "Pitcher HR/9",
            "Recent HR/PA", "Season HR/PA",
            "Model Prob %", "Market Prob %", "Edge %",
            "Proj p50", "Proj p75", "Proj p90",
        ]
        st.dataframe(df[all_cols].reset_index(drop=True), use_container_width=True)

    # ── Factor breakdown ─────────────────────────────────────────────────────
    with st.expander("Factor breakdown (top 20 by edge)"):
        factor_cols = [
            "Player", "Team", "Park (idx)", "Wind Adj",
            "Pitcher HR/9", "Recent HR/PA", "Season HR/PA",
            "Model Prob %", "Market Prob %", "Edge %",
        ]
        st.dataframe(
            df.head(20)[factor_cols].reset_index(drop=True),
            use_container_width=True,
        )
