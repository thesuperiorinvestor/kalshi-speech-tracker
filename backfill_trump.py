"""Backfill Trump's last 5 speeches (beyond tracker bets) into speech_transcripts."""
import sqlite3
import os

DB = os.path.join(os.path.dirname(__file__), "kalshi.db")
conn = sqlite3.connect(DB)
c = conn.cursor()

# Trump's last 5 real speeches (most recent first), sourced from transcripts:
#
# 1. Apr 26 - 60 Minutes CBS Interview (interview)
# 2. Apr 17 - TPUSA Build the Red Wall Phoenix (rally)
# 3. Apr 16 - Tax Day Las Vegas Roundtable (presser)
# 4. Apr 10 - Fox News Interview [ALREADY IN DB as market 23]
# 5. Apr 6  - Iran Press Conference [ALREADY IN DB as market 14]
# 6. Apr 1  - Address to Nation [ALREADY IN DB as market 8]
#
# We need to add #1, #2, #3. The rest are already in the DB.

new_speeches = [
    {
        "date": "2026-04-26",
        "speaker": "Trump",
        "event_name": "Trump 60 Minutes CBS Interview",
        "event_type": "interview",
        "source": "web_research",
        "keywords": {
            # From full transcript analysis
            "Iran/Iranian": 0,
            "Nuclear": 0,
            "Oil": 0,
            "Biden": 0,
            "Israel/Israeli": 0,
            "Ceasefire": 0,
            "Tariff": 0,
            "China": 0,
            "Democrat": 1,
            "Fake News": 1,
            "Ballroom": 1,
            "Hamas/Hezbollah": 0,
            "Terrorist/Terrorism": 0,
            "Gaza/Palestine": 0,
            "Shabbat/Sabbath": 0,
            "250": 0,
            "Antisemitism/Antisemitic": 0,
            "Cuba/Cuban": 0,
            "Fraud": 0,
            "Crypto/Bitcoin": 0,
            "Marco/Rubio": 0,
            "Healthcare": 0,
            "AI/Artificial Intelligence": 0,
            "World Cup": 0,
            "Embargo": 0,
            "Negotiate": 0,
            "Hottest": 0,
            "Autopen": 0,
        },
    },
    {
        "date": "2026-04-17",
        "speaker": "Trump",
        "event_name": "Trump TPUSA Build the Red Wall Phoenix",
        "event_type": "rally",
        "source": "web_research",
        "keywords": {
            # From Rev transcript analysis
            "Iran/Iranian": 1,
            "Nuclear": 1,
            "Oil": 1,
            "Biden": 1,
            "Israel/Israeli": 1,
            "Ceasefire": 1,
            "Tariff": 1,
            "China": 1,
            "Democrat": 1,
            "Fake News": 1,
            "Ballroom": 0,
            "Hamas/Hezbollah": 1,  # Hezbollah said
            "Terrorist/Terrorism": 0,
            "Gaza/Palestine": 0,
            "Shabbat/Sabbath": 0,
            "250": 1,
            "Antisemitism/Antisemitic": 0,
            "Cuba/Cuban": 1,
            "Fraud": 1,
            "Crypto/Bitcoin": 0,
            "Marco/Rubio": 0,
            "Healthcare": 1,
            "AI/Artificial Intelligence": 0,
            "World Cup": 0,
            "Embargo": 0,
            "Negotiate": 1,
            "Hottest": 1,
            "Autopen": 0,
        },
    },
    {
        "date": "2026-04-16",
        "speaker": "Trump",
        "event_name": "Trump Tax Day Las Vegas Roundtable",
        "event_type": "presser",
        "source": "web_research",
        "keywords": {
            # From SingjuPost transcript analysis
            "Iran/Iranian": 1,
            "Nuclear": 1,
            "Oil": 1,
            "Biden": 1,
            "Israel/Israeli": 0,
            "Ceasefire": 0,
            "Tariff": 1,
            "China": 0,
            "Democrat": 1,
            "Fake News": 1,
            "Ballroom": 0,
            "Hamas/Hezbollah": 0,
            "Terrorist/Terrorism": 1,
            "Gaza/Palestine": 0,
            "Shabbat/Sabbath": 0,
            "250": 0,
            "Antisemitism/Antisemitic": 0,
            "Cuba/Cuban": 0,
            "Fraud": 0,
            "Crypto/Bitcoin": 0,
            "Marco/Rubio": 0,
            "Healthcare": 0,
            "AI/Artificial Intelligence": 0,
            "World Cup": 0,
            "Embargo": 0,
            "Negotiate": 0,
            "Hottest": 1,
            "Autopen": 0,
        },
    },
]

added = 0
for speech in new_speeches:
    # Check if already exists
    c.execute(
        "SELECT id FROM speech_transcripts WHERE speaker=? AND date=? AND event_name=?",
        (speech["speaker"], speech["date"], speech["event_name"]),
    )
    if c.fetchone():
        print(f"  SKIP (exists): {speech['event_name']}")
        continue

    c.execute(
        """INSERT INTO speech_transcripts (date, speaker, event_name, event_type, source)
           VALUES (?,?,?,?,?)""",
        (speech["date"], speech["speaker"], speech["event_name"], speech["event_type"], speech["source"]),
    )
    tid = c.lastrowid
    for kw, said in speech["keywords"].items():
        c.execute(
            "INSERT INTO transcript_keywords (transcript_id, keyword, said) VALUES (?,?,?)",
            (tid, kw, said),
        )
    added += 1
    print(f"  ADDED: {speech['event_name']} ({len(speech['keywords'])} keywords)")

conn.commit()

# Verify
c.execute("SELECT COUNT(*) FROM speech_transcripts WHERE speaker='Trump'")
total_t = c.fetchone()[0]
c.execute("""
    SELECT COUNT(*) FROM transcript_keywords tk
    JOIN speech_transcripts st ON st.id=tk.transcript_id
    WHERE st.speaker='Trump'
""")
total_k = c.fetchone()[0]
print(f"\nTrump totals: {total_t} speeches, {total_k} keyword records")

conn.close()
