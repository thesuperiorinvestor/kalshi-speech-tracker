import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "kalshi.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS markets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            speaker TEXT NOT NULL,
            event_name TEXT NOT NULL,
            event_type TEXT NOT NULL CHECK(event_type IN ('rally','presser','teleprompter_address','interview','signing','earnings_call')),
            format_notes TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS picks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id INTEGER NOT NULL REFERENCES markets(id),
            keyword TEXT NOT NULL,
            direction TEXT NOT NULL CHECK(direction IN ('yes','no')),
            kalshi_odds INTEGER NOT NULL,
            historical_hit_rate INTEGER NOT NULL,
            edge INTEGER NOT NULL,
            pick_type TEXT NOT NULL CHECK(pick_type IN ('historical_lock','contextual_override','structural_fade')),
            outcome TEXT NOT NULL DEFAULT 'pending' CHECK(outcome IN ('hit','miss','pending')),
            stake REAL NOT NULL DEFAULT 0,
            payout REAL NOT NULL DEFAULT 0,
            notes TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS speech_transcripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id INTEGER REFERENCES markets(id),
            date TEXT NOT NULL,
            speaker TEXT NOT NULL,
            event_name TEXT NOT NULL,
            event_type TEXT NOT NULL,
            source TEXT DEFAULT 'manual',
            notes TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS transcript_keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transcript_id INTEGER NOT NULL REFERENCES speech_transcripts(id),
            keyword TEXT NOT NULL,
            said INTEGER NOT NULL CHECK(said IN (0, 1))
        );
    """)
    conn.commit()
    conn.close()


def seed_db():
    conn = get_conn()
    c = conn.cursor()

    # Check if already seeded
    c.execute("SELECT COUNT(*) FROM markets")
    if c.fetchone()[0] > 0:
        conn.close()
        return

    markets = [
        # (date, speaker, event_name, event_type, format_notes)
        ("2026-03-27", "Trump", "Trump Farmers Speech", "rally", ""),
        ("2026-03-27", "Trump", "Trump FII Summit", "interview", ""),
        ("2026-03-28", "Bernie", "Bernie No Kings MN", "rally", ""),
        ("2026-03-29", "Bernie", "Bernie Tax the Rich Bronx", "rally", ""),
        ("2026-03-30", "Powell", "Powell Harvard", "interview", ""),
        ("2026-03-30", "Leavitt", "Leavitt Briefing", "presser", ""),
        ("2026-03-30", "Trump", "Trump EO Signing", "signing", ""),
        ("2026-04-01", "Trump", "Trump Address to Nation", "teleprompter_address", ""),
        ("2026-04-02", "RFK", "RFK Microplastics", "presser", ""),
        ("2026-04-03", "Dr. Oz", "Dr. Oz Fox News", "interview", ""),
    ]

    picks_by_market = [
        # Market 1
        [
            ("Biden", "yes", 83, 100, 17, "historical_lock", "hit", 0, 0),
            ("China", "yes", 75, 100, 25, "historical_lock", "hit", 0, 0),
            ("Soybean", "yes", 58, 67, 9, "contextual_override", "hit", 0, 0),
        ],
        # Market 2
        [
            ("Sleepy Joe", "yes", 66, 100, 34, "historical_lock", "hit", 0, 0),
            ("Radical Left", "yes", 49, 100, 51, "structural_fade", "hit", 0, 0),
            ("Drill Baby Drill", "no", 42, 0, 42, "structural_fade", "hit", 0, 0),
            ("Democrat", "yes", 82, 100, 18, "historical_lock", "hit", 0, 0),
            ("Crypto", "yes", 52, 0, -52, "contextual_override", "hit", 0, 0),
        ],
        # Market 3
        [
            ("Tariff", "no", 25, 0, 75, "structural_fade", "hit", 0, 0),
            ("Revolution", "yes", 53, 33, -20, "contextual_override", "hit", 0, 0),
            ("Corrupt", "yes", 72, 100, 28, "historical_lock", "hit", 0, 0),
            ("Robot", "yes", 76, 67, -9, "historical_lock", "hit", 0, 0),
        ],
        # Market 4
        [
            ("Zohran/Mamdani", "yes", 75, 33, -42, "contextual_override", "hit", 0, 0),
            ("Stock Market", "no", 14, 0, 86, "structural_fade", "hit", 0, 0),
            ("Gaza", "no", 24, 0, 76, "structural_fade", "hit", 0, 0),
        ],
        # Market 5
        [
            ("Trump", "no", 57, 0, 57, "structural_fade", "hit", 0, 0),
            ("Kevin/Warsh", "no", 37, 0, 63, "structural_fade", "hit", 0, 0),
        ],
        # Market 6
        [
            ("Iran", "yes", 99, 100, 1, "historical_lock", "hit", 0, 0),
            ("ICE/DHS", "yes", 96, 100, 4, "historical_lock", "hit", 0, 0),
            ("Nuclear", "yes", 91, 80, -11, "historical_lock", "hit", 0, 0),
            ("Hormuz", "yes", 90, 80, -10, "historical_lock", "hit", 0, 0),
            ("Illegal Alien", "yes", 84, 60, -24, "historical_lock", "hit", 0, 0),
            ("TSA", "yes", 89, 60, -29, "historical_lock", "hit", 0, 0),
            ("Biden", "yes", 78, 100, 22, "historical_lock", "hit", 0, 0),
            ("Oil", "yes", 82, 60, -22, "historical_lock", "hit", 0, 0),
            ("Negotiate", "yes", 81, 80, -1, "historical_lock", "hit", 0, 0),
            ("Israel", "yes", 64, 60, -4, "historical_lock", "hit", 0, 0),
            ("Shutdown", "yes", 91, 40, -51, "historical_lock", "hit", 0, 0),
            ("Protest", "yes", 23, 0, -23, "contextual_override", "miss", 15, 0),
        ],
        # Market 7
        [
            ("Biden", "yes", 85, 100, 15, "historical_lock", "hit", 0, 0),
            ("Ballroom", "yes", 69, 0, -69, "contextual_override", "hit", 0, 0),
            ("Supreme Court", "yes", 61, 33, -28, "contextual_override", "hit", 0, 0),
            ("Tariff", "yes", 36, 0, -36, "contextual_override", "miss", 38, 0),
        ],
        # Market 8
        [
            ("Hormuz", "yes", 77, 67, -10, "historical_lock", "hit", 127, 161),
            ("Deal/Settle", "yes", 79, 67, -12, "historical_lock", "hit", 66, 80),
            ("NATO", "yes", 92, 33, -59, "contextual_override", "miss", 21, 0),
            ("Ceasefire", "yes", 41, 0, -41, "contextual_override", "miss", 45, 0),
            ("Withdraw", "yes", 28, 0, -28, "contextual_override", "miss", 11, 0),
        ],
        # Market 9
        [
            ("Endocrine", "yes", 46, 25, -21, "contextual_override", "hit", 0, 0),
            ("Democrat", "no", 15, 0, 85, "structural_fade", "hit", 0, 0),
            ("Forever Chemical", "yes", 45, 25, -20, "contextual_override", "miss", 0, 0),
        ],
        # Market 10
        [
            ("Chronic", "no", 24, 0, 76, "structural_fade", "hit", 20, 26),
            ("Immigrant/Immigration", "no", 19, 0, 81, "structural_fade", "hit", 15, 18),
        ],
    ]

    for i, (market_data, picks) in enumerate(zip(markets, picks_by_market)):
        c.execute(
            "INSERT INTO markets (date, speaker, event_name, event_type, format_notes) VALUES (?,?,?,?,?)",
            market_data,
        )
        market_id = c.lastrowid
        for p in picks:
            c.execute(
                """INSERT INTO picks
                   (market_id, keyword, direction, kalshi_odds, historical_hit_rate, edge,
                    pick_type, outcome, stake, payout)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (market_id, *p),
            )

    conn.commit()
    conn.close()
    print("Database seeded successfully.")


def pick_to_said(direction: str, outcome: str) -> int | None:
    """Convert a pick's direction+outcome into whether the keyword was said.
    Returns 1 (said), 0 (not said), or None (pending/unknown)."""
    if outcome == "pending":
        return None
    if direction == "yes":
        return 1 if outcome == "hit" else 0
    else:  # direction == "no"
        return 0 if outcome == "hit" else 1


def sync_market_to_transcript(conn, market_id: int):
    """Sync a single market's picks into speech_transcripts + transcript_keywords.
    Creates the transcript row if it doesn't exist, then upserts keywords."""
    c = conn.cursor()

    # Check if transcript already exists for this market
    c.execute("SELECT id FROM speech_transcripts WHERE market_id=?", (market_id,))
    row = c.fetchone()

    if row:
        transcript_id = row[0] if isinstance(row, tuple) else row["id"]
    else:
        # Create transcript from market data
        c.execute("SELECT date, speaker, event_name, event_type FROM markets WHERE id=?", (market_id,))
        m = c.fetchone()
        if not m:
            return
        c.execute(
            """INSERT INTO speech_transcripts (market_id, date, speaker, event_name, event_type, source)
               VALUES (?,?,?,?,?,?)""",
            (market_id, m[0], m[1], m[2], m[3], "tracker_sync"),
        )
        transcript_id = c.lastrowid

    # Clear existing keywords for this transcript (re-sync)
    c.execute("DELETE FROM transcript_keywords WHERE transcript_id=?", (transcript_id,))

    # Insert keywords from picks
    c.execute("SELECT keyword, direction, outcome FROM picks WHERE market_id=?", (market_id,))
    for pick in c.fetchall():
        kw = pick[0] if isinstance(pick, tuple) else pick["keyword"]
        direction = pick[1] if isinstance(pick, tuple) else pick["direction"]
        outcome = pick[2] if isinstance(pick, tuple) else pick["outcome"]
        said = pick_to_said(direction, outcome)
        if said is not None:
            conn.execute(
                "INSERT INTO transcript_keywords (transcript_id, keyword, said) VALUES (?,?,?)",
                (transcript_id, kw, said),
            )


def migrate_transcripts():
    """Back-fill speech_transcripts from all existing markets."""
    conn = get_conn()
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM speech_transcripts")
    if c.fetchone()[0] > 0:
        conn.close()
        return  # Already migrated

    c.execute("SELECT id FROM markets")
    market_ids = [r[0] for r in c.fetchall()]
    for mid in market_ids:
        sync_market_to_transcript(conn, mid)

    conn.commit()
    conn.close()
    print(f"Migrated {len(market_ids)} markets to speech_transcripts.")


if __name__ == "__main__":
    init_db()
    seed_db()
    migrate_transcripts()
