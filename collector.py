"""
collector.py — Polls the OpenSky API every 5 minutes and appends raw
aircraft state snapshots to a JSONL file for the current day.

Run this continuously in the background (e.g. via systemd) so that
summarize.py has data to work with at the end of the day.
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent

CREDENTIALS_FILE = BASE_DIR / "credentials.json"
DATA_DIR = BASE_DIR / "data"
POLL_INTERVAL_SECONDS = 5 * 60  # every 5 minutes

CENTER_LAT = 59.377395
CENTER_LON = 17.910052
OFFSET = 0.25

LAMIN = CENTER_LAT - OFFSET
LAMAX = CENTER_LAT + OFFSET
LOMIN = CENTER_LON - OFFSET
LOMAX = CENTER_LON + OFFSET

TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network"
    "/protocol/openid-connect/token"
)
STATES_URL = (
    f"https://opensky-network.org/api/states/all"
    f"?lamin={LAMIN}&lamax={LAMAX}&lomin={LOMIN}&lomax={LOMAX}"
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def load_credentials() -> tuple[str, str]:
    with open(CREDENTIALS_FILE) as f:
        creds = json.load(f)
    return creds["clientId"], creds["clientSecret"]


def fetch_token(client_id: str, client_secret: str) -> tuple[str, float]:
    """Return (access_token, expiry_epoch)."""
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()
    token = payload["access_token"]
    expires_in = payload.get("expires_in", 1800)
    expiry = time.time() + expires_in - 60  # refresh 1 minute early
    return token, expiry


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

FIELD_NAMES = [
    "icao24",
    "callsign",
    "origin_country",
    "time_position",
    "last_contact",
    "longitude",
    "latitude",
    "baro_altitude",
    "on_ground",
    "velocity",
    "true_track",
    "vertical_rate",
    "sensors",
    "geo_altitude",
    "squawk",
    "spi",
    "position_source",
]


def states_to_records(raw_states: list) -> list[dict]:
    records = []
    for state in raw_states:
        record = dict(zip(FIELD_NAMES, state))
        # Clean up callsign whitespace
        if record.get("callsign"):
            record["callsign"] = record["callsign"].strip()
        records.append(record)
    return records


def snapshot_file_for_today() -> Path:
    DATA_DIR.mkdir(exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    return DATA_DIR / f"{date_str}.jsonl"


# ---------------------------------------------------------------------------
# Main polling loop
# ---------------------------------------------------------------------------


def main() -> None:
    client_id, client_secret = load_credentials()
    token, token_expiry = fetch_token(client_id, client_secret)
    log.info("Access token obtained, expires in ~30 min.")

    while True:
        # Refresh token if it's about to expire
        if time.time() >= token_expiry:
            log.info("Refreshing access token…")
            token, token_expiry = fetch_token(client_id, client_secret)

        try:
            resp = requests.get(
                STATES_URL,
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            log.warning("API request failed: %s — will retry next interval.", exc)
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        raw_states = data.get("states") or []
        timestamp = datetime.now(timezone.utc).isoformat()

        snapshot = {
            "timestamp": timestamp,
            "aircraft_count": len(raw_states),
            "states": states_to_records(raw_states),
        }

        out_file = snapshot_file_for_today()
        with open(out_file, "a") as f:
            f.write(json.dumps(snapshot) + "\n")

        log.info(
            "[%s] Saved %d aircraft to %s",
            timestamp,
            len(raw_states),
            out_file.name,
        )

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
