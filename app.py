import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from init_db import init_db, seed_db, migrate_transcripts, sync_market_to_transcript, DB_PATH
from datetime import datetime, timedelta
import re
import os

# ── Bootstrap ────────────────────────────────────────────────────────────────
init_db()
seed_db()
migrate_transcripts()

st.set_page_config(page_title="Kalshi Speech Tracker", layout="wide")

# ── Helpers ──────────────────────────────────────────────────────────────────

def load_picks() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        """
        SELECT p.*, m.date, m.speaker, m.event_name, m.event_type
        FROM picks p
        JOIN markets m ON p.market_id = m.id
        """,
        conn,
    )
    conn.close()
    return df


def load_markets() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM markets ORDER BY date DESC", conn)
    conn.close()
    return df


def pnl(row) -> float:
    """Net P&L for a single pick row. payout - stake works universally:
    hit → positive, miss (payout=0) → -stake, sold early → partial return - stake."""
    if row["outcome"] == "pending":
        return 0.0
    return float(row["payout"]) - float(row["stake"])


def calc_roi(pnl_sum: float, stake_sum: float) -> float | None:
    """ROI % on deployed capital. None if no real money wagered."""
    return (pnl_sum / stake_sum * 100) if stake_sum > 0 else None


def fmt_roi(roi) -> str:
    return f"{roi:+.1f}%" if roi is not None else "—"


def edge_bucket(edge: int) -> str:
    if edge > 50:
        return ">50"
    if edge >= 20:
        return "20–50"
    if edge >= 0:
        return "0–20"
    return "Negative"


PICK_TYPE_ORDER = ["historical_lock", "contextual_override", "structural_fade"]
EVENT_TYPE_ORDER = ["rally", "presser", "teleprompter_address", "interview", "signing", "earnings_call"]
EDGE_ORDER = [">50", "20–50", "0–20", "Negative"]

# ── Sidebar nav ──────────────────────────────────────────────────────────────
st.sidebar.title("Kalshi Speech Tracker")
page = st.sidebar.radio(
    "Navigate",
    [
        "Overview",
        "Word Matrix",
        "Insights",
        "By Speaker",
        "By Event Type",
        "By Pick Type",
        "By Edge Bucket",
        "Recent Markets",
    ],
)

df_all = load_picks()
df_settled = df_all[df_all["outcome"].isin(["hit", "miss"])].copy()
df_settled["net"] = df_settled.apply(pnl, axis=1)
df_settled["win"] = (df_settled["outcome"] == "hit").astype(int)
df_settled["edge_bucket"] = df_settled["edge"].apply(edge_bucket)

# ── Overview ─────────────────────────────────────────────────────────────────
if page == "Overview":
    st.title("Overview")

    total = len(df_settled)
    wins = df_settled["win"].sum()
    win_rate = wins / total * 100 if total else 0
    total_pnl = df_settled["net"].sum()
    total_stake = df_settled["stake"].sum()
    total_roi = calc_roi(total_pnl, total_stake)
    pending = len(df_all[df_all["outcome"] == "pending"])

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Record", f"{wins}–{total - wins}")
    c2.metric("Win Rate", f"{win_rate:.1f}%")
    c3.metric("Total P&L", f"${total_pnl:+.2f}")
    c4.metric("ROI", fmt_roi(total_roi))
    c5.metric("Pending Picks", pending)

    st.divider()

    # Picks by type breakdown
    st.subheader("Picks by Type")
    type_stats = (
        df_settled.groupby("pick_type")
        .agg(picks=("win", "count"), wins=("win", "sum"), pnl=("net", "sum"))
        .reindex(PICK_TYPE_ORDER)
        .reset_index()
    )
    type_stats["win_rate"] = type_stats["wins"] / type_stats["picks"] * 100

    fig = px.bar(
        type_stats,
        x="pick_type",
        y="win_rate",
        color="pick_type",
        text=type_stats["win_rate"].map("{:.1f}%".format),
        labels={"pick_type": "Pick Type", "win_rate": "Win Rate %"},
        title="Win Rate by Pick Type",
        color_discrete_map={
            "historical_lock": "#2196F3",
            "contextual_override": "#FF9800",
            "structural_fade": "#4CAF50",
        },
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(showlegend=False, yaxis_range=[0, 110])
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Hypothesis Check")
    st.info(
        "**Key hypothesis:** Structural fades should have the highest win rate. "
        "Contextual overrides on formal/teleprompter formats should have the most misses."
    )

    tele_co = df_settled[
        (df_settled["event_type"] == "teleprompter_address")
        & (df_settled["pick_type"] == "contextual_override")
    ]
    tele_total = len(tele_co)
    tele_misses = (tele_co["outcome"] == "miss").sum()
    col1, col2 = st.columns(2)
    with col1:
        sf = type_stats[type_stats["pick_type"] == "structural_fade"]
        sf_rate = sf["win_rate"].values[0] if len(sf) else 0
        co = type_stats[type_stats["pick_type"] == "contextual_override"]
        co_rate = co["win_rate"].values[0] if len(co) else 0
        hl = type_stats[type_stats["pick_type"] == "historical_lock"]
        hl_rate = hl["win_rate"].values[0] if len(hl) else 0
        is_sf_highest = sf_rate >= max(co_rate, hl_rate)
        st.metric(
            "Structural Fade Win Rate",
            f"{sf_rate:.1f}%",
            delta="Highest ✓" if is_sf_highest else "Not highest yet",
        )
    with col2:
        miss_rate = tele_misses / tele_total * 100 if tele_total else 0
        st.metric(
            "Contextual Override Miss Rate (Teleprompter)",
            f"{miss_rate:.1f}%",
            delta=f"{tele_misses}/{tele_total} misses",
        )

# ── Word Matrix ──────────────────────────────────────────────────────────────
elif page == "Word Matrix":
    st.title("Word Matrix")
    st.caption("Keyword frequency matrix across past speeches. Upload Kalshi screenshots or select a speaker manually.")

    conn_matrix = sqlite3.connect(DB_PATH)

    # ── OCR Helper ────────────────────────────────────────────────────────
    def parse_kalshi_screenshot(image_bytes):
        """OCR a Kalshi screenshot and extract keywords + odds."""
        try:
            import pytesseract
            from PIL import Image
            import io

            # Set tesseract path for Windows
            tess_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
            if os.path.exists(tess_path):
                pytesseract.pytesseract.tesseract_cmd = tess_path

            img = Image.open(io.BytesIO(image_bytes))
            text = pytesseract.image_to_string(img)
            return text
        except ImportError:
            return None
        except Exception as e:
            return f"ERROR: {e}"

    def extract_keywords_from_text(ocr_text):
        """Parse OCR text to find Kalshi keyword markets and odds.

        Kalshi mentions markets typically show patterns like:
        - 'Will [Speaker] say "[Keyword]"?' with Yes/No prices
        - Keyword names followed by prices like '85¢' or '85%' or 'Yes 85'
        - Simple lines with keyword and a number
        """
        results = []
        lines = ocr_text.split("\n")
        full_text = ocr_text

        # Pattern 1: "Will ... say "keyword"" or "say 'keyword'"
        say_pattern = re.findall(
            r"""(?:Will|will)\s+\w+\s+say\s+[\"'“”‘’]([^\"'“”‘’]+)[\"'“”‘’]""",
            full_text,
        )
        for kw in say_pattern:
            kw = kw.strip().rstrip("?")
            if len(kw) > 1 and len(kw) < 60:
                results.append({"keyword": kw, "odds": None})

        # Pattern 2: Lines that look like "Keyword  XX¢" or "Keyword  XX%"
        for line in lines:
            line = line.strip()
            if not line or len(line) < 3:
                continue

            # Match: text followed by a number (price/odds)
            m = re.match(
                r'^(.+?)\s+(\d{1,2})[¢%¢c]?\s*$', line
            )
            if m:
                kw = m.group(1).strip().rstrip(".")
                odds = int(m.group(2))
                if 1 <= odds <= 99 and len(kw) > 1 and len(kw) < 60:
                    # Check not already found
                    if not any(r["keyword"].lower() == kw.lower() for r in results):
                        results.append({"keyword": kw, "odds": odds})
                continue

            # Match: "Yes XX¢" or "XX¢ Yes" patterns near keyword text
            m2 = re.match(r'^(.+?)\s+[Yy]es\s+(\d{1,2})[¢%c]?\s*$', line)
            if m2:
                kw = m2.group(1).strip()
                odds = int(m2.group(2))
                if 1 <= odds <= 99 and len(kw) > 1:
                    if not any(r["keyword"].lower() == kw.lower() for r in results):
                        results.append({"keyword": kw, "odds": odds})

        # Deduplicate
        seen = set()
        deduped = []
        for r in results:
            key = r["keyword"].lower().strip()
            if key not in seen:
                seen.add(key)
                deduped.append(r)
        return deduped

    def detect_speaker_from_text(ocr_text, known_speakers):
        """Try to detect the speaker from OCR text."""
        text_lower = ocr_text.lower()
        for spk in known_speakers:
            if spk.lower() in text_lower:
                return spk
        # Check for common patterns like "Will Trump say..."
        m = re.search(r'[Ww]ill\s+(\w+)\s+say', ocr_text)
        if m:
            return m.group(1).title()
        return None

    # ── Screenshot Upload ─────────────────────────────────────────────────
    with st.expander("📸 Upload Kalshi Screenshots to Build Matrix", expanded=False):
        uploaded_files = st.file_uploader(
            "Upload one or more Kalshi event screenshots",
            type=["png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True,
            key="kalshi_screenshots",
        )

        if uploaded_files:
            all_ocr_text = []
            st.caption(f"Processing {len(uploaded_files)} screenshot(s)...")

            img_cols = st.columns(min(len(uploaded_files), 3))
            for i, f in enumerate(uploaded_files):
                with img_cols[i % 3]:
                    st.image(f, caption=f.name, use_container_width=True)

            # Run OCR on all images
            for f in uploaded_files:
                raw = parse_kalshi_screenshot(f.getvalue())
                if raw and not raw.startswith("ERROR"):
                    all_ocr_text.append(raw)
                elif raw and raw.startswith("ERROR"):
                    st.warning(f"OCR error on {f.name}: {raw}")

            if all_ocr_text:
                combined_text = "\n".join(all_ocr_text)

                # Show raw OCR for debugging
                with st.expander("🔍 Raw OCR Text (debug)", expanded=False):
                    st.code(combined_text)

                # Extract keywords
                parsed = extract_keywords_from_text(combined_text)

                # Detect speaker
                all_speakers = pd.read_sql_query(
                    "SELECT DISTINCT speaker FROM speech_transcripts UNION SELECT DISTINCT speaker FROM markets",
                    conn_matrix
                )["speaker"].tolist()
                detected_speaker = detect_speaker_from_text(combined_text, all_speakers)

                if detected_speaker:
                    st.success(f"Detected speaker: **{detected_speaker}**")

                if parsed:
                    st.subheader(f"Parsed {len(parsed)} Keywords")
                    st.caption("Edit keywords and odds below, then click 'Build Matrix' to generate.")

                    # Editable table for parsed keywords
                    edit_data = pd.DataFrame(parsed)
                    edit_data.columns = ["Keyword", "Kalshi Odds (%)"]
                    edited = st.data_editor(
                        edit_data,
                        num_rows="dynamic",
                        use_container_width=True,
                        key="parsed_kw_editor",
                    )

                    # Store in session state for matrix building
                    if st.button("✅ Build Matrix with These Keywords", type="primary"):
                        st.session_state["screenshot_keywords"] = edited.to_dict("records")
                        st.session_state["screenshot_speaker"] = detected_speaker
                        st.rerun()
                else:
                    st.warning("Couldn't auto-parse keywords. Try the manual entry below, or paste the text.")
                    manual_text = st.text_area(
                        "Paste Kalshi keywords (one per line, optionally with odds: 'Keyword 85')",
                        height=200,
                        key="manual_kw_paste",
                    )
                    if manual_text.strip():
                        manual_parsed = []
                        for line in manual_text.strip().split("\n"):
                            line = line.strip()
                            if not line:
                                continue
                            m = re.match(r'^(.+?)\s+(\d{1,2})$', line)
                            if m:
                                manual_parsed.append({"Keyword": m.group(1).strip(), "Kalshi Odds (%)": int(m.group(2))})
                            else:
                                manual_parsed.append({"Keyword": line, "Kalshi Odds (%)": None})
                        if manual_parsed:
                            mp_df = pd.DataFrame(manual_parsed)
                            edited_manual = st.data_editor(mp_df, num_rows="dynamic", use_container_width=True, key="manual_kw_editor")
                            if st.button("✅ Build Matrix with These Keywords", type="primary", key="manual_build"):
                                st.session_state["screenshot_keywords"] = edited_manual.to_dict("records")
                                st.session_state["screenshot_speaker"] = detected_speaker
                                st.rerun()
            else:
                st.error("OCR failed on all screenshots. Make sure Tesseract is installed.")

    # ── Speaker Selection ─────────────────────────────────────────────────
    # Get all speakers from speech_transcripts
    speakers_df = pd.read_sql_query(
        "SELECT DISTINCT speaker FROM speech_transcripts ORDER BY speaker", conn_matrix
    )
    speakers = speakers_df["speaker"].tolist()

    # Auto-select speaker from screenshot if available
    screenshot_speaker = st.session_state.get("screenshot_speaker")
    screenshot_keywords = st.session_state.get("screenshot_keywords")

    if not speakers:
        st.warning("No speech transcript data yet. Add markets and outcomes to populate.")
    else:
        col_sp, col_et = st.columns([2, 2])
        with col_sp:
            default_idx = 0
            if screenshot_speaker and screenshot_speaker in speakers:
                default_idx = speakers.index(screenshot_speaker)
            selected_speaker = st.selectbox("Speaker", speakers, index=default_idx)
        with col_et:
            et_options = ["All"] + EVENT_TYPE_ORDER
            selected_et = st.selectbox("Event Type Filter", et_options)

        # ── Comparable event algorithm ──────────────────────────────────
        def find_comparables(speaker, event_type_filter, n=5):
            """Find the most comparable past speeches using weighted scoring."""
            query = "SELECT * FROM speech_transcripts WHERE speaker=?"
            params = [speaker]
            if event_type_filter != "All":
                query += " AND event_type=?"
                params.append(event_type_filter)
            transcripts = pd.read_sql_query(query, conn_matrix, params=params)
            if len(transcripts) == 0:
                return transcripts

            # Score each transcript
            scores = []
            today = datetime.now().strftime("%Y-%m-%d")
            for _, t in transcripts.iterrows():
                score = 0
                # Event type match bonus (only relevant when filter is "All")
                if event_type_filter == "All":
                    score += 1  # base score for existing
                else:
                    score += 3  # matched filter

                # Recency bonus
                try:
                    days_ago = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(t["date"], "%Y-%m-%d")).days
                    if days_ago <= 30:
                        score += 2
                    elif days_ago <= 90:
                        score += 1
                except (ValueError, TypeError):
                    pass

                scores.append(score)

            transcripts["_score"] = scores
            transcripts = transcripts.sort_values(["_score", "date"], ascending=[False, False]).head(n)
            return transcripts.drop(columns=["_score"])

        comparables = find_comparables(selected_speaker, selected_et)

        if len(comparables) == 0:
            st.info(f"No speeches found for {selected_speaker}" +
                    (f" ({selected_et})" if selected_et != "All" else "") + ".")
        else:
            # Let user toggle which speeches to include
            st.subheader("Comparable Speeches")
            selected_ids = []
            cols_per_row = min(len(comparables), 3)
            check_cols = st.columns(cols_per_row)
            for i, (_, t) in enumerate(comparables.iterrows()):
                with check_cols[i % cols_per_row]:
                    label = f"{t['event_name']} ({t['date']})"
                    if st.checkbox(label, value=True, key=f"cmp_{t['id']}"):
                        selected_ids.append(int(t["id"]))

            if not selected_ids:
                st.info("Select at least one speech to build the matrix.")
            else:
                # Load keywords for selected transcripts
                placeholders = ",".join("?" * len(selected_ids))
                kw_data = pd.read_sql_query(
                    f"""SELECT tk.transcript_id, tk.keyword, tk.said,
                               st.event_name, st.date
                        FROM transcript_keywords tk
                        JOIN speech_transcripts st ON tk.transcript_id = st.id
                        WHERE tk.transcript_id IN ({placeholders})""",
                    conn_matrix,
                    params=selected_ids,
                )

                if len(kw_data) == 0 and not screenshot_keywords:
                    st.info("No keyword data for selected speeches.")
                else:
                    # Get all unique keywords from DB
                    db_keywords = sorted(kw_data["keyword"].unique()) if len(kw_data) > 0 else []

                    # Build kalshi odds lookup from screenshot
                    kalshi_odds_map = {}
                    screenshot_extra_kws = []
                    if screenshot_keywords:
                        for item in screenshot_keywords:
                            kw_name = str(item.get("Keyword") or item.get("keyword", "")).strip()
                            odds_val = item.get("Kalshi Odds (%)") or item.get("odds")
                            if kw_name:
                                try:
                                    kalshi_odds_map[kw_name] = int(odds_val) if odds_val and not pd.isna(odds_val) else None
                                except (ValueError, TypeError):
                                    kalshi_odds_map[kw_name] = None
                                # Add keywords from screenshot that aren't in DB
                                if kw_name not in db_keywords:
                                    screenshot_extra_kws.append(kw_name)

                    all_keywords = db_keywords + screenshot_extra_kws

                    if not all_keywords:
                        st.info("No keywords to display.")
                    else:
                        # Get speech labels (ordered by date)
                        if len(kw_data) > 0:
                            speech_info = (kw_data[["transcript_id", "event_name", "date"]]
                                           .drop_duplicates()
                                           .sort_values("date"))
                            speech_labels = {
                                row["transcript_id"]: f"{row['event_name']}\n{row['date']}"
                                for _, row in speech_info.iterrows()
                            }
                            speech_ids_ordered = list(speech_info["transcript_id"])
                        else:
                            speech_labels = {}
                            speech_ids_ordered = []

                        # ── Matrix Header ─────────────────────────────────────
                        has_kalshi = bool(kalshi_odds_map)
                        if has_kalshi:
                            st.subheader("Matrix (with Kalshi Odds)")
                            st.caption("Screenshot keywords merged — Kalshi %, Hist %, and Edge shown.")
                        else:
                            st.subheader("Matrix")
                            st.caption("Upload Kalshi screenshots above to add odds + edge columns.")

                        # Build matrix data
                        matrix_rows = []
                        for kw in all_keywords:
                            row = {"Keyword": kw}
                            hits = 0
                            total = 0
                            for sid in speech_ids_ordered:
                                match = kw_data[(kw_data["keyword"] == kw) & (kw_data["transcript_id"] == sid)]
                                if len(match) > 0:
                                    said = int(match.iloc[0]["said"])
                                    row[speech_labels[sid]] = said
                                    hits += said
                                    total += 1
                                else:
                                    row[speech_labels[sid]] = None
                            row["Hist %"] = round(hits / total * 100) if total > 0 else None

                            if has_kalshi:
                                k_odds = kalshi_odds_map.get(kw)
                                row["Kalshi %"] = k_odds
                                if k_odds is not None and row["Hist %"] is not None:
                                    row["Edge"] = row["Hist %"] - k_odds
                                else:
                                    row["Edge"] = None

                            matrix_rows.append(row)

                        matrix_df = pd.DataFrame(matrix_rows)

                        # Sort: if we have edge, sort by absolute edge desc; otherwise by hist%
                        if has_kalshi and "Edge" in matrix_df.columns:
                            matrix_df = matrix_df.sort_values("Hist %", ascending=False, na_position="last")
                        else:
                            matrix_df = matrix_df.sort_values("Hist %", ascending=False, na_position="last")

                        # Format for display
                        display_df = matrix_df.copy()
                        summary_cols = ["Keyword", "Hist %"]
                        if has_kalshi:
                            summary_cols += ["Kalshi %", "Edge"]
                        speech_cols = [c for c in display_df.columns if c not in summary_cols]

                        # Replace 1/0/None with symbols for display
                        display_map = {1: "✔", 0: "✘", None: "—"}
                        for col in speech_cols:
                            display_df[col] = display_df[col].map(
                                lambda v: display_map.get(v, "—")
                            )
                        display_df["Hist %"] = display_df["Hist %"].apply(
                            lambda v: f"{int(v)}%" if pd.notna(v) and v is not None else "—"
                        )
                        if has_kalshi:
                            display_df["Kalshi %"] = display_df["Kalshi %"].apply(
                                lambda v: f"{int(v)}%" if pd.notna(v) and v is not None else "—"
                            )
                            display_df["Edge"] = display_df["Edge"].apply(
                                lambda v: f"{int(v):+d}" if pd.notna(v) and v is not None else "—"
                            )

                        st.dataframe(
                            display_df,
                            use_container_width=True,
                            hide_index=True,
                            height=min(800, 50 + 35 * len(display_df)),
                        )

                        # ── Edge-Sorted Picks Table ───────────────────────────
                        if has_kalshi:
                            edge_df = matrix_df[matrix_df["Edge"].notna()].copy()
                            if len(edge_df) > 0:
                                st.subheader("📊 Edge-Ranked Picks")
                                st.caption("Keywords sorted by edge (hist% - Kalshi%). Positive = underpriced YES, negative = consider NO.")

                                edge_sorted = edge_df.sort_values("Edge", ascending=False)
                                picks_display = edge_sorted[["Keyword", "Hist %", "Kalshi %", "Edge"]].copy()
                                picks_display["Signal"] = picks_display["Edge"].apply(
                                    lambda e: "🟢 YES (underpriced)" if e >= 20
                                    else "🔴 NO (overpriced)" if e <= -20
                                    else "🟡 Marginal"
                                )
                                picks_display["Hist %"] = picks_display["Hist %"].apply(lambda v: f"{int(v)}%" if pd.notna(v) else "—")
                                picks_display["Kalshi %"] = picks_display["Kalshi %"].apply(lambda v: f"{int(v)}%" if pd.notna(v) else "—")
                                picks_display["Edge"] = picks_display["Edge"].apply(lambda v: f"{int(v):+d}" if pd.notna(v) else "—")

                                st.dataframe(picks_display, use_container_width=True, hide_index=True)

                                # Top picks callout
                                strong_yes = edge_df[edge_df["Edge"] >= 20]
                                strong_no = edge_df[edge_df["Edge"] <= -20]
                                if len(strong_yes) > 0 or len(strong_no) > 0:
                                    st.subheader("🎯 Top Picks")
                                    for _, r in strong_yes.sort_values("Edge", ascending=False).head(3).iterrows():
                                        st.markdown(
                                            f"✅ **{r['Keyword']}** — YES at {int(r['Kalshi %'])}¢ "
                                            f"(Hist {int(r['Hist %'])}%, Edge **+{int(r['Edge'])}**)"
                                        )
                                    for _, r in strong_no.sort_values("Edge").head(3).iterrows():
                                        st.markdown(
                                            f"🚫 **{r['Keyword']}** — NO at {100-int(r['Kalshi %'])}¢ "
                                            f"(Hist {int(r['Hist %'])}%, Edge **{int(r['Edge'])}**)"
                                        )

                        # ── Clear screenshot data button ──────────────────────
                        if screenshot_keywords:
                            if st.button("🗑️ Clear Screenshot Data"):
                                del st.session_state["screenshot_keywords"]
                                if "screenshot_speaker" in st.session_state:
                                    del st.session_state["screenshot_speaker"]
                                st.rerun()

                        # ── Summary stats ─────────────────────────────────────
                        st.subheader("Quick Stats")
                        hist_vals = matrix_df["Hist %"].dropna()
                        if len(hist_vals) > 0:
                            locks = hist_vals[hist_vals >= 67]
                            mid = hist_vals[(hist_vals >= 34) & (hist_vals < 67)]
                            fades = hist_vals[hist_vals < 34]
                            c1, c2, c3, c4 = st.columns(4)
                            c1.metric("Total Keywords", len(all_keywords))
                            c2.metric("Locks (67%+)", len(locks))
                            c3.metric("Mid-range", len(mid))
                            c4.metric("Fades (<34%)", len(fades))

            # ── Add Manual Speech ──────────────────────────────────────
            st.divider()
            with st.expander("+ Add Speech Manually (not from tracker)"):
                with st.form("add_speech_form"):
                    s_col1, s_col2 = st.columns(2)
                    with s_col1:
                        s_date = st.date_input("Speech Date", key="speech_date_input")
                        s_event = st.text_input("Event Name", key="speech_event_input")
                    with s_col2:
                        s_etype = st.selectbox("Event Type", EVENT_TYPE_ORDER, key="speech_etype_input")
                        s_source = st.selectbox("Source", ["manual", "web_research"], key="speech_source_input")

                    st.caption("Keywords (one per line, prefix with + if said, - if not said):")
                    st.caption("Example: +Nuclear  -Bitcoin  +Biden")
                    s_keywords = st.text_area("Keywords", height=120, key="speech_kw_input")

                    if st.form_submit_button("Save Speech"):
                        if not s_event:
                            st.error("Event name required.")
                        else:
                            c = conn_matrix.cursor()
                            c.execute(
                                """INSERT INTO speech_transcripts
                                   (date, speaker, event_name, event_type, source)
                                   VALUES (?,?,?,?,?)""",
                                (str(s_date), selected_speaker, s_event, s_etype, s_source),
                            )
                            tid = c.lastrowid
                            count = 0
                            for line in s_keywords.strip().split("\n"):
                                line = line.strip()
                                if not line:
                                    continue
                                if line.startswith("+"):
                                    c.execute(
                                        "INSERT INTO transcript_keywords (transcript_id, keyword, said) VALUES (?,?,?)",
                                        (tid, line[1:].strip(), 1),
                                    )
                                    count += 1
                                elif line.startswith("-"):
                                    c.execute(
                                        "INSERT INTO transcript_keywords (transcript_id, keyword, said) VALUES (?,?,?)",
                                        (tid, line[1:].strip(), 0),
                                    )
                                    count += 1
                            conn_matrix.commit()
                            st.success(f"Saved speech with {count} keywords.")
                            st.rerun()

    conn_matrix.close()

# ── Insights ─────────────────────────────────────────────────────────────────
elif page == "Insights":
    st.title("Insights & Recommendations")
    st.caption("Data-driven analysis of what's working, what's not, and how to size bets going forward.")

    staked = df_settled[df_settled["stake"] > 0].copy()

    def segment_stats(df, col):
        g = (df.groupby(col)
             .agg(picks=("win","count"), wins=("win","sum"),
                  stake=("stake","sum"), pnl=("net","sum"))
             .reset_index())
        g["win_rate"] = g["wins"] / g["picks"] * 100
        g["roi"] = g.apply(lambda r: calc_roi(r["pnl"], r["stake"]), axis=1)
        return g

    # ── 1. What's working ────────────────────────────────────────────────────
    st.header("🟢 What's Working")
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Top Event Types")
        et = segment_stats(staked, "event_type").dropna(subset=["roi"])
        et_top = et[et["picks"] >= 3].sort_values("roi", ascending=False).head(5)
        for _, r in et_top.iterrows():
            emoji = "🔥" if r["roi"] > 30 else "✅" if r["roi"] > 10 else "➖"
            st.markdown(
                f"{emoji} **{r['event_type'].replace('_',' ')}** — "
                f"ROI {r['roi']:+.1f}% · {int(r['wins'])}/{int(r['picks'])} "
                f"({r['win_rate']:.0f}%) · P&L ${r['pnl']:+.2f}"
            )

    with col2:
        st.subheader("Top Pick Types (on real money)")
        pt = segment_stats(staked, "pick_type").dropna(subset=["roi"])
        for _, r in pt.sort_values("roi", ascending=False).iterrows():
            emoji = "🔥" if r["roi"] > 30 else "✅" if r["roi"] > 10 else "⚠️"
            st.markdown(
                f"{emoji} **{r['pick_type'].replace('_',' ')}** — "
                f"ROI {r['roi']:+.1f}% · {int(r['wins'])}/{int(r['picks'])} "
                f"({r['win_rate']:.0f}%) · P&L ${r['pnl']:+.2f}"
            )

    st.subheader("Best Event × Pick Type Combos")
    combo = (staked.groupby(["event_type","pick_type"])
             .agg(picks=("win","count"), wins=("win","sum"),
                  stake=("stake","sum"), pnl=("net","sum"))
             .reset_index())
    combo["roi"] = combo.apply(lambda r: calc_roi(r["pnl"], r["stake"]), axis=1)
    combo_good = combo[(combo["picks"] >= 2) & (combo["roi"] > 0)].sort_values("roi", ascending=False).head(5)
    if len(combo_good):
        for _, r in combo_good.iterrows():
            st.markdown(
                f"- **{r['event_type'].replace('_',' ')} + {r['pick_type'].replace('_',' ')}** — "
                f"ROI {r['roi']:+.1f}% · {int(r['wins'])}/{int(r['picks'])} · P&L ${r['pnl']:+.2f}"
            )

    # ── 2. What's not working ────────────────────────────────────────────────
    st.divider()
    st.header("🔴 What's Not Working")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Worst Event Types")
        et_bad = et[et["picks"] >= 2].sort_values("roi").head(5)
        for _, r in et_bad.iterrows():
            if r["roi"] < 0:
                st.markdown(
                    f"❌ **{r['event_type'].replace('_',' ')}** — "
                    f"ROI {r['roi']:+.1f}% · {int(r['wins'])}/{int(r['picks'])} · P&L ${r['pnl']:+.2f}"
                )

    with col2:
        st.subheader("Biggest Losing Combos")
        combo_bad = combo[(combo["picks"] >= 2) & (combo["roi"] < -20)].sort_values("roi").head(5)
        if len(combo_bad):
            for _, r in combo_bad.iterrows():
                st.markdown(
                    f"🚫 **{r['event_type'].replace('_',' ')} + {r['pick_type'].replace('_',' ')}** — "
                    f"ROI {r['roi']:+.1f}% · {int(r['wins'])}/{int(r['picks'])} · P&L ${r['pnl']:+.2f}"
                )
        else:
            st.caption("No combos with ≥2 picks and <-20% ROI.")

    st.subheader("Worst Speakers / Events (sample ≥2)")
    spk = segment_stats(staked, "speaker").dropna(subset=["roi"])
    spk_bad = spk[(spk["picks"] >= 2) & (spk["roi"] < 0)].sort_values("roi").head(5)
    for _, r in spk_bad.iterrows():
        st.markdown(
            f"- **{r['speaker']}** — ROI {r['roi']:+.1f}% · {int(r['wins'])}/{int(r['picks'])} · P&L ${r['pnl']:+.2f}"
        )

    # ── 3. Sizing Recommendations ────────────────────────────────────────────
    st.divider()
    st.header("💰 Sizing Recommendations")

    st.markdown("""
    **Framework:** size is a function of observed ROI in that segment, sample size (discount small-sample signal),
    and edge. Caps prevent concentration risk.
    """)

    def recommend_size(roi, picks, max_size=50):
        if roi is None or pd.isna(roi):
            return 10, "insufficient data — track at $10"
        # confidence multiplier based on sample size
        conf = min(1.0, picks / 10)
        if roi > 40 and picks >= 5:
            return round(max_size * conf), "high conviction — full size"
        if roi > 15 and picks >= 3:
            return round(30 * conf), "good edge — 60% size"
        if roi > 0:
            return round(15 * conf), "marginal — starter size"
        if roi > -20:
            return 5, "skeptical — tracker only"
        return 0, "SKIP — negative expected value"

    # Sizing table by event_type
    st.subheader("By Event Type")
    sizing_rows = []
    for _, r in et.sort_values("roi", ascending=False).iterrows():
        size, note = recommend_size(r["roi"], r["picks"])
        sizing_rows.append({
            "Event Type": r["event_type"].replace("_"," "),
            "Picks": int(r["picks"]),
            "Win %": f"{r['win_rate']:.0f}%",
            "ROI": f"{r['roi']:+.1f}%",
            "Suggested Size": f"${size}",
            "Rationale": note,
        })
    st.dataframe(pd.DataFrame(sizing_rows), use_container_width=True, hide_index=True)

    # Sizing by pick_type
    st.subheader("By Pick Type")
    sizing_rows = []
    for _, r in pt.sort_values("roi", ascending=False).iterrows():
        size, note = recommend_size(r["roi"], r["picks"])
        sizing_rows.append({
            "Pick Type": r["pick_type"].replace("_"," "),
            "Picks": int(r["picks"]),
            "Win %": f"{r['win_rate']:.0f}%",
            "ROI": f"{r['roi']:+.1f}%",
            "Suggested Size": f"${size}",
            "Rationale": note,
        })
    st.dataframe(pd.DataFrame(sizing_rows), use_container_width=True, hide_index=True)

    # ── 4. Focus / Avoid ─────────────────────────────────────────────────────
    st.divider()
    st.header("🎯 Focus & Avoid")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Focus On")
        focus_items = []
        if len(et_top):
            best_et = et_top.iloc[0]
            focus_items.append(f"**{best_et['event_type'].replace('_',' ')}** events — {best_et['roi']:+.1f}% ROI")
        best_pt = pt.sort_values("roi", ascending=False).iloc[0] if len(pt) else None
        if best_pt is not None:
            focus_items.append(f"**{best_pt['pick_type'].replace('_',' ')}** picks — {best_pt['roi']:+.1f}% ROI")
        if len(combo_good):
            top_combo = combo_good.iloc[0]
            focus_items.append(
                f"**{top_combo['event_type'].replace('_',' ')} × {top_combo['pick_type'].replace('_',' ')}** "
                f"combo — {top_combo['roi']:+.1f}% ROI ({int(top_combo['wins'])}/{int(top_combo['picks'])})"
            )
        # speaker focus
        spk_good = spk[(spk["picks"] >= 3) & (spk["roi"] > 20)].sort_values("roi", ascending=False)
        if len(spk_good):
            s = spk_good.iloc[0]
            focus_items.append(f"**{s['speaker']}** — {s['roi']:+.1f}% ROI over {int(s['picks'])} picks")
        for item in focus_items:
            st.markdown(f"✅ {item}")

    with col2:
        st.subheader("Avoid")
        avoid_items = []
        et_neg = et[(et["picks"] >= 3) & (et["roi"] < 0)].sort_values("roi")
        for _, r in et_neg.iterrows():
            avoid_items.append(
                f"**{r['event_type'].replace('_',' ')}** — {r['roi']:+.1f}% ROI over {int(r['picks'])} picks"
            )
        pt_neg = pt[(pt["picks"] >= 3) & (pt["roi"] < 0)].sort_values("roi")
        for _, r in pt_neg.iterrows():
            avoid_items.append(
                f"**{r['pick_type'].replace('_',' ')}** picks — {r['roi']:+.1f}% ROI"
            )
        # specific event pattern: NAN fireside chats
        nan_picks = staked[staked["event_name"].str.contains("NAN", case=False, na=False)]
        if len(nan_picks) > 0:
            nan_pnl = nan_picks["net"].sum()
            nan_stake = nan_picks["stake"].sum()
            nan_roi = calc_roi(nan_pnl, nan_stake)
            avoid_items.append(
                f"**NAN Fireside Chats** — {nan_roi:+.1f}% ROI "
                f"({int(nan_picks['win'].sum())}/{len(nan_picks)} hit)"
            )
        for item in avoid_items:
            st.markdown(f"❌ {item}")

    # ── 5. Keyword-level patterns ────────────────────────────────────────────
    st.divider()
    st.header("🔑 Keyword Patterns")
    kw_stats = (staked.groupby("keyword")
                .agg(picks=("win","count"), wins=("win","sum"),
                     stake=("stake","sum"), pnl=("net","sum"))
                .reset_index())
    kw_stats = kw_stats[kw_stats["picks"] >= 2].copy()
    kw_stats["roi"] = kw_stats.apply(lambda r: calc_roi(r["pnl"], r["stake"]), axis=1)
    kw_stats["win_rate"] = kw_stats["wins"] / kw_stats["picks"] * 100

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Keywords That Cash")
        for _, r in kw_stats.sort_values("roi", ascending=False).head(8).iterrows():
            st.markdown(
                f"**{r['keyword']}** — {r['roi']:+.1f}% ROI · {int(r['wins'])}/{int(r['picks'])} · ${r['pnl']:+.2f}"
            )
    with col2:
        st.subheader("Keywords That Burn")
        for _, r in kw_stats[kw_stats["roi"] < 0].sort_values("roi").head(8).iterrows():
            st.markdown(
                f"**{r['keyword']}** — {r['roi']:+.1f}% ROI · {int(r['wins'])}/{int(r['picks'])} · ${r['pnl']:+.2f}"
            )

    # ── 6. Pattern Signals (from speech_transcripts) ───────────────────────
    st.divider()
    st.header("🧠 Pattern Signals")
    st.caption("Keywords that always/never get said, based on full transcript history.")

    try:
        conn_ps = sqlite3.connect(DB_PATH)
        conn_ps.row_factory = sqlite3.Row
        ps_query = """
            SELECT st.speaker, tk.keyword, tk.said, COUNT(*) as cnt
            FROM transcript_keywords tk
            JOIN speech_transcripts st ON st.id = tk.transcript_id
            GROUP BY st.speaker, tk.keyword, tk.said
        """
        ps_rows = conn_ps.execute(ps_query).fetchall()
        conn_ps.close()

        # Build {(speaker, keyword): {said_count, not_said_count}}
        from collections import defaultdict
        kw_map = defaultdict(lambda: {"said": 0, "not_said": 0})
        for r in ps_rows:
            key = (r["speaker"], r["keyword"])
            if r["said"] == 1:
                kw_map[key]["said"] += r["cnt"]
            else:
                kw_map[key]["not_said"] += r["cnt"]

        locks_100 = []  # always said
        fades_0 = []    # never said
        for (spk, kw), counts in kw_map.items():
            total = counts["said"] + counts["not_said"]
            if total >= 3:
                rate = counts["said"] / total * 100
                if rate == 100:
                    locks_100.append((spk, kw, total))
                elif rate == 0:
                    fades_0.append((spk, kw, total))

        c1, c2 = st.columns(2)
        with c1:
            st.subheader("🔒 100% Locks (always said)")
            if locks_100:
                for spk, kw, n in sorted(locks_100, key=lambda x: -x[2]):
                    st.markdown(f"**{spk}** — *{kw}* ({n}/{n} speeches)")
            else:
                st.caption("No keywords with 100% hit rate across 3+ speeches yet.")
        with c2:
            st.subheader("🚫 0% Fades (never said)")
            if fades_0:
                for spk, kw, n in sorted(fades_0, key=lambda x: -x[2]):
                    st.markdown(f"**{spk}** — *{kw}* (0/{n} speeches)")
            else:
                st.caption("No keywords with 0% hit rate across 3+ speeches yet.")
    except Exception:
        st.caption("Pattern signals unavailable — run transcript migration first.")

    # ── 7. Static heuristics ─────────────────────────────────────────────────
    st.divider()
    st.header("📋 Heuristic Rules (from observed patterns)")
    st.markdown("""
    1. **Structural fades are your edge.** Mis-priced No bets on terms that the market overprices are the most consistent winner. Lean in.
    2. **Historical locks at <90¢ are fine; at >90¢ the juice isn't worth it.** You pay for near-certainty and lose outsized on the rare miss (see: Tailwind, Headwind on earnings calls).
    3. **Contextual overrides on formal formats fail.** Teleprompter addresses, NAN fireside chats, Vaisakhi cultural events — the speaker's script overrides your contextual read.
    4. **Earnings calls need company-specific base rates.** Generic "this banking term will be said" logic has lost. Build per-ticker keyword frequencies before sizing up.
    5. **"Headwind/Tailwind" are traps on bank earnings.** Both have missed in sample — they sound inevitable but aren't uttered verbatim.
    6. **Fade Democrat speakers talking about Democrat policy wonkery at academic venues** (Harris/Buttigieg NAN, Pelosi GWU partially) — keyword density is lower than political-rally base rates.
    7. **Max position on a single pick: cap at 15% of weekly stake.** The Trump Address NATO miss ($21) and JPM Tariff miss ($15) both came from over-sizing on "obvious" contextual overrides.
    """)

# ── By Speaker ───────────────────────────────────────────────────────────────
elif page == "By Speaker":
    st.title("By Speaker")

    speaker_stats = (
        df_settled.groupby("speaker")
        .agg(picks=("win", "count"), wins=("win", "sum"), pnl=("net", "sum"), stake=("stake", "sum"))
        .reset_index()
    )
    speaker_stats["win_rate"] = speaker_stats["wins"] / speaker_stats["picks"] * 100
    speaker_stats["roi"] = speaker_stats.apply(lambda r: calc_roi(r["pnl"], r["stake"]), axis=1)
    speaker_stats = speaker_stats.sort_values("win_rate", ascending=False)

    fig = px.bar(
        speaker_stats,
        x="speaker",
        y="win_rate",
        color="roi",
        text=speaker_stats["win_rate"].map("{:.1f}%".format),
        labels={"speaker": "Speaker", "win_rate": "Win Rate %", "roi": "ROI (%)"},
        title="Win Rate by Speaker (color = ROI)",
        color_continuous_scale="RdYlGn",
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(yaxis_range=[0, 110])
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Detail Table")
    display = speaker_stats.copy()
    display["win_rate"] = display["win_rate"].map("{:.1f}%".format)
    display["pnl"] = display["pnl"].map("${:+.2f}".format)
    display["roi"] = display["roi"].apply(fmt_roi)
    st.dataframe(
        display[["speaker", "picks", "wins", "win_rate", "pnl", "roi"]].rename(columns={
            "speaker": "Speaker", "picks": "Picks", "wins": "Wins",
            "win_rate": "Win Rate", "pnl": "P&L", "roi": "ROI"
        }),
        use_container_width=True,
    )

# ── By Event Type ─────────────────────────────────────────────────────────────
elif page == "By Event Type":
    st.title("By Event Type")

    et_stats = (
        df_settled.groupby("event_type")
        .agg(picks=("win", "count"), wins=("win", "sum"), pnl=("net", "sum"), stake=("stake", "sum"))
        .reindex(EVENT_TYPE_ORDER)
        .dropna()
        .reset_index()
    )
    et_stats["win_rate"] = et_stats["wins"] / et_stats["picks"] * 100
    et_stats["roi"] = et_stats.apply(lambda r: calc_roi(r["pnl"], r["stake"]), axis=1)

    fig = px.bar(
        et_stats,
        x="event_type",
        y="win_rate",
        color="event_type",
        text=et_stats["win_rate"].map("{:.1f}%".format),
        labels={"event_type": "Event Type", "win_rate": "Win Rate %"},
        title="Win Rate by Event Type",
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(showlegend=False, yaxis_range=[0, 110])
    st.plotly_chart(fig, use_container_width=True)

    # Miss analysis for teleprompter + contextual_override
    st.subheader("Contextual Override Performance by Format")
    st.caption("Key hypothesis: contextual overrides fail most on formal/scripted formats.")
    co_by_format = (
        df_settled[df_settled["pick_type"] == "contextual_override"]
        .groupby("event_type")
        .agg(picks=("win", "count"), wins=("win", "sum"))
        .reset_index()
    )
    co_by_format["win_rate"] = co_by_format["wins"] / co_by_format["picks"] * 100
    co_by_format["miss_rate"] = 100 - co_by_format["win_rate"]

    fig2 = px.bar(
        co_by_format,
        x="event_type",
        y=["win_rate", "miss_rate"],
        barmode="stack",
        labels={"event_type": "Event Type", "value": "%", "variable": ""},
        title="Contextual Override: Hit vs Miss by Format",
        color_discrete_map={"win_rate": "#4CAF50", "miss_rate": "#F44336"},
    )
    st.plotly_chart(fig2, use_container_width=True)

    st.subheader("Detail Table")
    display = et_stats.copy()
    display["win_rate"] = display["win_rate"].map("{:.1f}%".format)
    display["pnl"] = display["pnl"].map("${:+.2f}".format)
    display["roi"] = display["roi"].apply(fmt_roi)
    st.dataframe(display.rename(columns={
        "event_type": "Event Type", "picks": "Picks", "wins": "Wins",
        "pnl": "P&L", "win_rate": "Win Rate", "roi": "ROI"
    })[["Event Type", "Picks", "Wins", "Win Rate", "P&L", "ROI"]], use_container_width=True)

# ── By Pick Type ─────────────────────────────────────────────────────────────
elif page == "By Pick Type":
    st.title("By Pick Type")

    pt_stats = (
        df_settled.groupby("pick_type")
        .agg(picks=("win", "count"), wins=("win", "sum"), pnl=("net", "sum"), stake=("stake", "sum"))
        .reindex(PICK_TYPE_ORDER)
        .reset_index()
    )
    pt_stats["win_rate"] = pt_stats["wins"] / pt_stats["picks"] * 100
    pt_stats["miss_rate"] = 100 - pt_stats["win_rate"]
    pt_stats["roi"] = pt_stats.apply(lambda r: calc_roi(r["pnl"], r["stake"]), axis=1)

    fig = go.Figure()
    fig.add_bar(
        x=pt_stats["pick_type"],
        y=pt_stats["win_rate"],
        name="Hit",
        marker_color="#4CAF50",
        text=pt_stats["win_rate"].map("{:.1f}%".format),
        textposition="inside",
    )
    fig.add_bar(
        x=pt_stats["pick_type"],
        y=pt_stats["miss_rate"],
        name="Miss",
        marker_color="#F44336",
        text=pt_stats["miss_rate"].map("{:.1f}%".format),
        textposition="inside",
    )
    fig.update_layout(
        barmode="stack",
        title="Hit vs Miss Rate by Pick Type",
        yaxis_title="%",
        xaxis_title="Pick Type",
    )
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Hypothesis Panel")
    sf_row = pt_stats[pt_stats["pick_type"] == "structural_fade"]
    co_row = pt_stats[pt_stats["pick_type"] == "contextual_override"]
    hl_row = pt_stats[pt_stats["pick_type"] == "historical_lock"]

    c1, c2, c3 = st.columns(3)
    for col, row, label in [
        (c1, hl_row, "Historical Lock"),
        (c2, co_row, "Contextual Override"),
        (c3, sf_row, "Structural Fade"),
    ]:
        if len(row):
            roi_val = fmt_roi(row["roi"].values[0])
            col.metric(
                label,
                f"{row['win_rate'].values[0]:.1f}%",
                f"{int(row['wins'].values[0])}W / {int(row['picks'].values[0] - row['wins'].values[0])}L  |  P&L ${row['pnl'].values[0]:+.2f}  |  ROI {roi_val}",
            )

    st.subheader("Misses by Pick Type")
    misses = df_settled[df_settled["outcome"] == "miss"][
        ["date", "speaker", "event_type", "keyword", "pick_type", "kalshi_odds", "edge", "stake"]
    ].sort_values("date")
    st.dataframe(misses, use_container_width=True)

# ── By Edge Bucket ────────────────────────────────────────────────────────────
elif page == "By Edge Bucket":
    st.title("By Edge Bucket")

    eb_stats = (
        df_settled.groupby("edge_bucket")
        .agg(picks=("win", "count"), wins=("win", "sum"), pnl=("net", "sum"), stake=("stake", "sum"))
        .reindex(EDGE_ORDER)
        .dropna()
        .reset_index()
    )
    eb_stats["win_rate"] = eb_stats["wins"] / eb_stats["picks"] * 100
    eb_stats["roi"] = eb_stats.apply(lambda r: calc_roi(r["pnl"], r["stake"]), axis=1)

    fig = px.bar(
        eb_stats,
        x="edge_bucket",
        y="win_rate",
        color="edge_bucket",
        text=eb_stats["win_rate"].map("{:.1f}%".format),
        labels={"edge_bucket": "Edge Bucket", "win_rate": "Win Rate %"},
        title="Win Rate by Edge Bucket",
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(showlegend=False, yaxis_range=[0, 110])
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Edge vs Outcome Scatter")
    fig2 = px.strip(
        df_settled,
        x="edge",
        y="outcome",
        color="pick_type",
        hover_data=["keyword", "speaker", "event_type", "kalshi_odds"],
        labels={"edge": "Edge (pp)", "outcome": "Outcome", "pick_type": "Pick Type"},
        title="All Picks: Edge vs Outcome",
        color_discrete_map={
            "historical_lock": "#2196F3",
            "contextual_override": "#FF9800",
            "structural_fade": "#4CAF50",
        },
    )
    st.plotly_chart(fig2, use_container_width=True)

    st.subheader("Detail Table")
    display = eb_stats.copy()
    display["win_rate"] = display["win_rate"].map("{:.1f}%".format)
    display["pnl"] = display["pnl"].map("${:+.2f}".format)
    display["roi"] = display["roi"].apply(fmt_roi)
    st.dataframe(display.rename(columns={
        "edge_bucket": "Edge Bucket", "picks": "Picks", "wins": "Wins",
        "pnl": "P&L", "win_rate": "Win Rate", "roi": "ROI"
    })[["Edge Bucket", "Picks", "Wins", "Win Rate", "P&L", "ROI"]], use_container_width=True)

# ── Recent Markets ────────────────────────────────────────────────────────────
elif page == "Recent Markets":
    st.title("Recent Markets")

    markets = load_markets().head(10)

    for _, mkt in markets.iterrows():
        picks = df_all[df_all["market_id"] == mkt["id"]].copy()
        settled = picks[picks["outcome"].isin(["hit", "miss"])]
        wins = (settled["outcome"] == "hit").sum()
        total = len(settled)
        pending_cnt = (picks["outcome"] == "pending").sum()
        net = settled.apply(pnl, axis=1).sum()

        label = f"**{mkt['event_name']}** — {mkt['date']} | {mkt['speaker']} | {mkt['event_type'].replace('_',' ')}"
        record = f"{wins}W/{total-wins}L" + (f" +{pending_cnt}P" if pending_cnt else "")
        rate = f"{wins/total*100:.0f}%" if total else "—"
        mkt_stake = settled["stake"].sum()
        mkt_roi = fmt_roi(calc_roi(net, mkt_stake))

        with st.expander(f"{label}  |  {record}  {rate}  P&L: ${net:+.2f}  ROI: {mkt_roi}"):
            if len(picks) == 0:
                st.write("No picks recorded.")
                continue

            display = picks[
                ["keyword", "direction", "kalshi_odds", "historical_hit_rate", "edge",
                 "pick_type", "outcome", "stake", "payout"]
            ].copy()

            def color_outcome(val):
                if val == "hit":
                    return "background-color: #1b5e20; color: white"
                if val == "miss":
                    return "background-color: #b71c1c; color: white"
                return ""

            styled = display.style.applymap(color_outcome, subset=["outcome"])
            st.dataframe(styled, use_container_width=True)

            # View in Matrix link
            st.markdown(f"🔗 *Switch to **Word Matrix** page and select **{mkt['speaker']}** to see this speaker's keyword history.*")

            # mini pick-type breakdown
            if len(settled) > 0:
                pt_counts = settled.groupby(["pick_type", "outcome"]).size().unstack(fill_value=0)
                st.caption("Pick type breakdown:")
                st.dataframe(pt_counts, use_container_width=True)
