"""Aircraft identification helper for JARVIS.

Combines live OpenSky identifiers with the public HexDB aircraft database.
The live feed can reliably provide ICAO24/callsign/origin/category; the
external registry may additionally provide registration, manufacturer and
model when a matching record exists.
"""
from __future__ import annotations

import requests
from urllib.parse import quote

PLUGIN = {
    "name": "aircraft_identifier",
    "description": (
        "Identify an aircraft from an ICAO24 transponder code or callsign. "
        "Returns callsign, registration, aircraft manufacturer/model, owner/operator "
        "when available, country and ADS-B category. Use after plane_radar or when "
        "the user asks 'what aircraft is that', 'identify this plane', or gives an ICAO code."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "icao24": {"type": "STRING", "description": "6-character ICAO24 hex transponder code."},
            "callsign": {"type": "STRING", "description": "Flight callsign, if known."},
        },
        "required": [],
    },
    "behavior": "NON_BLOCKING",
    "scheduling": "WHEN_IDLE",
}

_HEXDB = "https://hexdb.io/api/v1/aircraft/{}"
_ADSBDB_CALLSIGN = "https://api.adsbdb.com/v0/callsign/{}"
_CATEGORY = {
    0: "unknown", 1: "unknown", 2: "light", 3: "small", 4: "large",
    5: "high-vortex large", 6: "heavy", 7: "high-performance", 8: "rotorcraft",
    9: "glider", 10: "lighter-than-air", 11: "parachutist", 12: "ultralight/hang-glider",
    14: "UAV", 15: "space/trans-atmospheric", 16: "surface emergency vehicle",
    17: "surface service vehicle", 18: "point obstacle", 19: "cluster obstacle", 20: "line obstacle",
}


def _lookup_icao(icao24: str) -> dict:
    try:
        r = requests.get(_HEXDB.format(icao24.lower()), timeout=8)
        if r.ok:
            data = r.json() or {}
            return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[AircraftIdentifier] lookup failed: {e}")
    return {}



def _lookup_route(callsign: str) -> dict:
    """Resolve a callsign to a published route when the public route database has it."""
    callsign = str(callsign or "").strip().upper()
    if not callsign:
        return {}
    try:
        r = requests.get(_ADSBDB_CALLSIGN.format(quote(callsign, safe="")), timeout=8)
        if not r.ok:
            return {}
        route = ((r.json() or {}).get("response") or {}).get("flightroute") or {}
        if not route:
            return {}
        def airport(value):
            if not isinstance(value, dict):
                return None
            return {
                "name": value.get("name"),
                "municipality": value.get("municipality"),
                "iata": value.get("iata_code"),
                "icao": value.get("icao_code"),
                "country": value.get("country_name"),
                "latitude": value.get("latitude"),
                "longitude": value.get("longitude"),
            }
        return {
            "airline": ((route.get("airline") or {}).get("name")),
            "origin": airport(route.get("origin")),
            "midpoint": airport(route.get("midpoint")),
            "destination": airport(route.get("destination")),
            "source": "adsbdb",
        }
    except Exception as e:
        print(f"[AircraftIdentifier] route lookup failed: {e}")
        return {}

def run(parameters: dict, player=None, session_memory=None) -> str:
    p = parameters or {}
    icao = str(p.get("icao24") or "").strip().lower().replace(" ", "")
    callsign = str(p.get("callsign") or "").strip().upper()
    if not icao and not callsign:
        return "Give me the aircraft's ICAO24 code or callsign, sir."

    data = _lookup_icao(icao) if icao else {}
    if not callsign:
        callsign = str(data.get("Callsign") or data.get("callsign") or "").strip().upper()

    route = _lookup_route(callsign) if callsign else {}
    fields = [("ICAO24", icao or None),
              ("Callsign", callsign or None),
              ("Registration", data.get("Registration") or data.get("registration")),
              ("Manufacturer", data.get("Manufacturer") or data.get("manufacturer")),
              ("Model", data.get("Type") or data.get("type") or data.get("model")),
              ("Owner/operator", data.get("RegisteredOwners") or data.get("registeredOwners") or data.get("owner")),
              ("Country", data.get("Country") or data.get("country"))]
    clean = [(k, v) for k, v in fields if v]

    origin = route.get("origin") or {}
    destination = route.get("destination") or {}
    if origin:
        clean.append(("Coming from", _airport_label(origin)))
    if destination:
        clean.append(("Going to land at", _airport_label(destination)))
    if route.get("airline"):
        clean.append(("Airline", route["airline"]))

    if not clean:
        return f"I couldn't identify the aircraft from {icao or callsign}, sir."

    text = "Aircraft identification: " + "; ".join(f"{k}: {v}" for k, v in clean) + "."
    if not origin and not destination:
        text += " I could not verify a current published origin and destination for this callsign."
    elif origin and not destination:
        text += " The origin is known, but the destination was not available in the route database."
    elif destination and not origin:
        text += " The destination is known, but the origin was not available in the route database."
    if player:
        try:
            player.show_content("AIRCRAFT IDENTIFICATION", text)
        except Exception:
            pass
    return text


def _airport_label(a: dict) -> str:
    city = str(a.get("municipality") or "").strip()
    name = str(a.get("name") or "").strip()
    iata = str(a.get("iata") or "").strip().upper()
    icao = str(a.get("icao") or "").strip().upper()
    bits = [x for x in (name, city) if x]
    code = "/".join(x for x in (iata, icao) if x)
    if code:
        bits.append(code)
    return ", ".join(bits) if bits else "unknown airport"
