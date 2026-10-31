"""
summarize.py — Reads the day's JSONL snapshot file collected by collector.py
and produces a human-readable Markdown summary saved to reports/.

Usage:
    python summarize.py              # summarise today
    python summarize.py 2026-10-30  # summarise a specific date
"""

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = BASE_DIR / "reports"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_snapshots(date_str: str) -> list[dict]:
    path = DATA_DIR / f"{date_str}.jsonl"
    if not path.exists():
        raise FileNotFoundError(
            f"No data file found for {date_str}. "
            f"Make sure collector.py ran that day."
        )
    snapshots = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                snapshots.append(json.loads(line))
    return snapshots


def fmt_speed(mps: float | None) -> str:
    if mps is None:
        return "N/A"
    return f"{mps:.0f} m/s ({mps * 3.6:.0f} km/h)"


def fmt_alt(meters: float | None) -> str:
    if meters is None:
        return "N/A"
    return f"{meters:.0f} m ({meters * 3.281:.0f} ft)"


def hour_label(ts: str) -> str:
    """Extract the UTC hour from an ISO timestamp string."""
    dt = datetime.fromisoformat(ts)
    return dt.astimezone(timezone.utc).strftime("%H:00")


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------


def build_summary(date_str: str, snapshots: list[dict]) -> str:
    # --- Unique aircraft across all snapshots ---
    all_icao: set[str] = set()
    all_callsigns: Counter = Counter()
    all_countries: Counter = Counter()
    hourly_counts: dict[str, list[int]] = {}
    altitudes: list[float] = []
    speeds: list[float] = []

    for snap in snapshots:
        hour = hour_label(snap["timestamp"])
        hourly_counts.setdefault(hour, []).append(snap["aircraft_count"])

        for ac in snap["states"]:
            icao = ac.get("icao24", "")
            if icao:
                all_icao.add(icao)

            cs = ac.get("callsign", "")
            if cs:
                all_callsigns[cs] += 1

            country = ac.get("origin_country", "")
            if country:
                all_countries[country] += 1

            alt = ac.get("baro_altitude")
            if alt is not None and not ac.get("on_ground"):
                altitudes.append(alt)

            vel = ac.get("velocity")
            if vel is not None and not ac.get("on_ground"):
                speeds.append(vel)

    total_unique = len(all_icao)
    total_snapshots = len(snapshots)

    # Hourly average aircraft in bounding box
    hourly_avg = {h: mean(counts) for h, counts in sorted(hourly_counts.items())}
    busiest_hour = max(hourly_avg, key=hourly_avg.get) if hourly_avg else "N/A"
    quietest_hour = min(hourly_avg, key=hourly_avg.get) if hourly_avg else "N/A"

    top_callsigns = all_callsigns.most_common(10)
    top_countries = all_countries.most_common(10)

    avg_alt = mean(altitudes) if altitudes else None
    med_alt = median(altitudes) if altitudes else None
    max_alt = max(altitudes) if altitudes else None
    avg_spd = mean(speeds) if speeds else None
    max_spd = max(speeds) if speeds else None

    # --- Format ---
    lines = [
        f"# ✈️ Daily Aircraft Summary — {date_str}",
        "",
        f"> Generated at {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M UTC')} "
        f"from **{total_snapshots} snapshots** (≈5 min intervals)",
        "",
        "---",
        "",
        "## 📊 Overview",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Unique aircraft seen | **{total_unique}** |",
        f"| Snapshots collected  | {total_snapshots} |",
        f"| Busiest hour (UTC)   | **{busiest_hour}** (~{hourly_avg.get(busiest_hour, 0):.1f} aircraft) |",
        f"| Quietest hour (UTC)  | {quietest_hour} (~{hourly_avg.get(quietest_hour, 0):.1f} aircraft) |",
        "",
        "---",
        "",
        "## 🕐 Hourly Traffic (avg aircraft in area)",
        "",
        "| Hour (UTC) | Avg aircraft |",
        "|------------|--------------|",
    ]

    for hour, avg in hourly_avg.items():
        bar = "█" * int(avg)
        lines.append(f"| {hour} | {avg:.1f}  {bar} |")

    lines += [
        "",
        "---",
        "",
        "## 🛫 Top 10 Callsigns",
        "",
        "| Callsign | Sightings |",
        "|----------|-----------|",
    ]
    for cs, count in top_callsigns:
        lines.append(f"| `{cs}` | {count} |")

    lines += [
        "",
        "---",
        "",
        "## 🌍 Top 10 Countries of Origin",
        "",
        "| Country | Sightings |",
        "|---------|-----------|",
    ]
    for country, count in top_countries:
        lines.append(f"| {country} | {count} |")

    lines += [
        "",
        "---",
        "",
        "## 📐 Altitude & Speed Stats (airborne only)",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Avg altitude  | {fmt_alt(avg_alt)} |",
        f"| Median altitude | {fmt_alt(med_alt)} |",
        f"| Max altitude  | {fmt_alt(max_alt)} |",
        f"| Avg speed     | {fmt_speed(avg_spd)} |",
        f"| Max speed     | {fmt_speed(max_spd)} |",
        "",
        "---",
        "",
        f"*Bounding box: lat [{59.377395 - 0.25:.4f}, {59.377395 + 0.25:.4f}] "
        f"× lon [{17.910052 - 0.25:.4f}, {17.910052 + 0.25:.4f}]*",
    ]

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m-%d")

    print(f"Loading snapshots for {date_str}…")
    snapshots = load_snapshots(date_str)
    print(f"  → {len(snapshots)} snapshots found.")

    summary = build_summary(date_str, snapshots)

    REPORTS_DIR.mkdir(exist_ok=True)
    out_path = REPORTS_DIR / f"{date_str}.md"
    out_path.write_text(summary, encoding="utf-8")

    print(f"Summary saved to: {out_path}")
    print()
    print(summary)


if __name__ == "__main__":
    main()
