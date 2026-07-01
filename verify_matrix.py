"""Verify Trump matrix with last 5 speeches for proclamation keywords."""
import sqlite3
import os
from collections import defaultdict

DB = os.path.join(os.path.dirname(__file__), "kalshi.db")
conn = sqlite3.connect(DB)
c = conn.cursor()

# Get Trump's last 5 speeches by date
speeches = c.execute("""
    SELECT id, date, event_name, event_type
    FROM speech_transcripts WHERE speaker='Trump'
    ORDER BY date DESC LIMIT 5
""").fetchall()

print("LAST 5 TRUMP SPEECHES:")
for s in speeches:
    print(f"  {s[1]} | {s[2]} | {s[3]}")

speech_ids = [s[0] for s in speeches]

# Get all keywords for these speeches
placeholders = ",".join("?" * len(speech_ids))
rows = c.execute(f"""
    SELECT tk.keyword, tk.said, st.date, st.event_name
    FROM transcript_keywords tk
    JOIN speech_transcripts st ON st.id = tk.transcript_id
    WHERE tk.transcript_id IN ({placeholders})
    ORDER BY tk.keyword, st.date
""", speech_ids).fetchall()

# Build matrix
kw_data = defaultdict(lambda: {"hits": 0, "total": 0, "details": []})
for r in rows:
    kw = r[0]
    said = r[1]
    kw_data[kw]["total"] += 1
    if said == 1:
        kw_data[kw]["hits"] += 1
    kw_data[kw]["details"].append(f"{'Y' if said else 'N'}({r[2][:5]})")

# Kalshi odds for this event
kalshi = {
    "Iran/Iranian": 90, "Nuclear": 85, "Oil": 78, "Democrat": 74,
    "250": 77, "Biden": 71, "Israel/Israeli": 62, "Tariff": 47,
    "Fake News": 41, "Ceasefire": 53, "Ballroom": 34, "China": 42,
    "Marco/Rubio": 42, "Hottest": 37, "Shabbat/Sabbath": 31,
    "Hamas/Hezbollah": 33, "Fraud": 30, "Bibi/Netanyahu": 28,
    "Cuba/Cuban": 31, "Autopen": 32, "Terrorist/Terrorism": 28,
    "Gaza/Palestine": 26, "Eight War": 23, "AI/Artificial Intelligence": 27,
    "Antisemitism/Antisemitic": 25, "World Cup": 23, "Embargo": 17,
    "Healthcare": 18, "American Dream": 14, "Transgender": 19,
    "Moon": 11, "TrumpRX": 9, "MAHA/Make America Healthy Again": 9,
    "Crypto/Bitcoin": 6, "Negotiate": 63,
}

print("\n" + "=" * 100)
print(f"{'Keyword':35s} | {'Hist':6s} | {'Kalshi':6s} | {'Edge':6s} | Details")
print("-" * 100)

for kw in sorted(kw_data.keys(), key=lambda k: -(kw_data[k]["hits"] / kw_data[k]["total"]) if kw_data[k]["total"] > 0 else 0):
    d = kw_data[kw]
    hist = round(d["hits"] / d["total"] * 100) if d["total"] > 0 else 0
    k_odds = kalshi.get(kw, None)
    edge = hist - k_odds if k_odds is not None else None
    edge_str = f"{edge:+d}" if edge is not None else "  -"
    k_str = f"{k_odds}%" if k_odds is not None else "  -"
    detail_str = " ".join(d["details"])
    print(f"  {kw:33s} | {hist:4d}% | {k_str:>5s} | {edge_str:>5s} | {detail_str}")

conn.close()
