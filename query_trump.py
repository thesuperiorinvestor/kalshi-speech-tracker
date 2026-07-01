import sqlite3, os
from collections import defaultdict

DB = os.path.join(os.path.dirname(__file__), "kalshi.db")
conn = sqlite3.connect(DB)
c = conn.cursor()

rows = c.execute("""
    SELECT tk.keyword, tk.said, st.event_name, st.event_type, st.date
    FROM transcript_keywords tk
    JOIN speech_transcripts st ON st.id = tk.transcript_id
    WHERE st.speaker = 'Trump'
    ORDER BY st.date DESC, tk.keyword
""").fetchall()

print("TRUMP TRANSCRIPT KEYWORDS")
for r in rows:
    sym = "Y" if r[1] == 1 else "N"
    print(f"  {r[4]} | {r[2]:35s} | {r[0]:30s} | {sym}")

print()
print("KEYWORD HIT RATES")
kw_stats = defaultdict(lambda: {"said": 0, "total": 0})
for r in rows:
    kw_stats[r[0]]["total"] += 1
    if r[1] == 1:
        kw_stats[r[0]]["said"] += 1

for kw in sorted(kw_stats.keys(), key=lambda k: -kw_stats[k]["said"] / kw_stats[k]["total"]):
    s = kw_stats[kw]
    pct = s["said"] / s["total"] * 100
    said = s["said"]
    total = s["total"]
    print(f"  {kw:30s} | {said}/{total} = {pct:.0f}%")

conn.close()
