#plane_radar.py
"""
Live aircraft detection near a location — drop-in JARVIS plugin.

Uses these free, keyless public APIs:
  - Open-Meteo Geocoding  (place name -> lat/lon)
  - OpenSky Network       (lat/lon box -> live ADS-B aircraft states)
  - adsbdb.com            (icao24 -> aircraft type/model; callsign -> the
                            scheduled route it's flying, i.e. origin/destination)

Honest limits, so nobody expects military radar:
  - Only sees aircraft broadcasting ADS-B. Most commercial and GA traffic
    does; some military and small/older aircraft don't.
  - OpenSky's anonymous tier is rate-limited (~400 requests/day) and can lag
    real positions by several seconds.
  - "Approaching" is worked out from two samples ~8s apart, not a live track.
  - Inbound-traffic detection casts a net out to 3x radius_km (capped at
    300km) so a fast approach shows up before it's technically "nearby" —
    it does not see anything beyond that 300km ceiling, however fast it's
    closing.
  - Type/route enrichment only runs for the handful of aircraft actually
    reported (not every contact in the box), to keep this fast and light on
    adsbdb's free service. A private/GA aircraft or one with no filed route
    just won't have origin/destination — that's reported plainly, not guessed.
  - "Passengers" is NOT a real headcount — nothing public broadcasts how many
    people are actually on a given flight, that's private airline data. What
    this reports is the TYPICAL seating capacity for that aircraft's type
    (from a small built-in reference table of common airliners), and it says
    so explicitly rather than implying a live count.
  - adsbdb's exact response shape wasn't verified against a live call while
    building this (no network access in the build environment) — the parser
    tries several plausible field names and degrades to "unknown" rather
    than crashing if a field is missing, but if it comes back consistently
    empty on your machine, the field names likely need a small tweak.
  - "Scan near me" / no location given uses IP-based geolocation (via free
    keyless services), NOT GPS. That's city-level accuracy at best — often
    fine, sometimes off by tens of km, worse on a VPN or mobile carrier.
    Say a specific place instead when precision matters.
  - Helicopters are included like any other aircraft — no category is
    filtered out — but many light/law-enforcement/news helicopters don't
    broadcast ADS-B at all, so this can only see the ones that do.

No other file needs to change — JARVIS discovers this automatically at startup.
"""
import math
import time

import requests

from memory.config_manager import get_plugin_config, save_plugin_config

PLUGIN = {
    "name": "plane_radar",
    "description": (
        "Finds real aircraft — including helicopters/choppers, not just fixed-wing — "
        "currently flying near a place using live ADS-B data, including aircraft "
        "type/size, typical passenger capacity for that type, and where each one is "
        "flying from/to when that's known. Trigger on things like 'what planes are "
        "overhead', 'any aircraft near [city]', 'what's flying near me', 'scan my "
        "airspace', 'is anything approaching', 'what kind of plane is that', 'where's "
        "it headed', or 'set my home location for plane tracking'. If no place is "
        "named, this scans near the device's current location automatically. This is "
        "about real aircraft physically in the sky right now. Do NOT use this for "
        "flight tickets, prices, or booking — that is flight_finder's job."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "scan | set_home (default: scan)",
            },
            "location": {
                "type": "STRING",
                "description": (
                    "Place name to centre the search on (city, address, landmark). "
                    "Omit to use the saved home location, or say 'here'/'near me'/"
                    "'my current location' to force the device's current location."
                ),
            },
            "use_device_location": {
                "type": "BOOLEAN",
                "description": (
                    "True to scan around the device's current (IP-based) location "
                    "instead of a named place or saved home — use when the user says "
                    "things like 'near me', 'over me', or 'my current location'."
                ),
            },
            "radius_km": {
                "type": "NUMBER",
                "description": (
                    "Search radius in kilometres for the main listing (default 50, max 300). "
                    "Inbound/approaching aircraft are still flagged out to 3x this (capped "
                    "at 300km), even though they're not in the main list yet."
                ),
            },
        },
        "required": [],
    },
    "behavior": "NON_BLOCKING",   # two network round-trips + an 8s sample gap
    "scheduling": "WHEN_IDLE",
}

_NS = "plane_radar"
_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_OPENSKY_URL = "https://opensky-network.org/api/states/all"
_ADSBDB_AIRCRAFT_URL = "https://api.adsbdb.com/v0/aircraft/{icao24}"
_ADSBDB_CALLSIGN_URL = "https://api.adsbdb.com/v0/callsign/{callsign}"

# How many of the reported contacts get the extra type/route lookups (2 HTTP
# calls each). Kept small on purpose — this runs for every scan and adsbdb is
# a free courtesy service, not something to hammer for aircraft nobody asked
# about.
_ENRICH_NEARBY_LIMIT = 4
_ENRICH_FAR_LIMIT = 2

_COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


# ── geo helpers ────────────────────────────────────────────────────────────

def _geocode(place: str) -> tuple[float, float, str] | None:
    try:
        r = requests.get(_GEOCODE_URL, params={"name": place, "count": 1}, timeout=10)
        results = (r.json() or {}).get("results") or []
        if not results:
            return None
        top = results[0]
        label = ", ".join(
            x for x in (top.get("name"), top.get("admin1"), top.get("country")) if x
        )
        return float(top["latitude"]), float(top["longitude"]), label or place
    except Exception as e:
        print(f"[PlaneRadar] ⚠️ Geocode failed: {e}")
        return None


def _bbox(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(0.1, math.cos(math.radians(lat))))
    return lat - dlat, lon - dlon, lat + dlat, lon + dlon


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _bearing(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlmb = math.radians(lon2 - lon1)
    y = math.sin(dlmb) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlmb)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _compass(deg: float) -> str:
    return _COMPASS[round(deg / 22.5) % 16]


# Phrases that mean "use where the device actually is right now" rather than
# a named place or the saved home location.
_HERE_ALIASES = {
    "here", "current location", "my location", "current",
    "my current location", "near me", "over me", "device location",
}

# Free, keyless IP-geolocation services, tried in order. This is city-level
# accuracy (network location, not GPS) — good enough for "what's flying near
# me" without requiring any setup.
_IP_GEOLOCATION_URLS = [
    "https://ipapi.co/json/",
    "http://ip-api.com/json/",
]


def _detect_device_location() -> tuple[float, float, str] | None:
    """Best-effort IP-based geolocation. Returns (lat, lon, label) or None —
    never raises. Tries each service until one gives usable coordinates."""
    for url in _IP_GEOLOCATION_URLS:
        try:
            r = requests.get(url, timeout=6)
            if not r.ok:
                continue
            data = r.json() or {}
            lat = data.get("latitude", data.get("lat"))
            lon = data.get("longitude", data.get("lon"))
            if lat is None or lon is None:
                continue
            city = data.get("city") or ""
            region = data.get("region") or data.get("regionName") or ""
            country = data.get("country_name") or data.get("country") or ""
            label = ", ".join(x for x in (city, region, country) if x) or "your current location"
            return float(lat), float(lon), label
        except Exception as e:
            print(f"[PlaneRadar] ⚠️ Device location lookup failed via {url}: {e}")
            continue
    return None


# ── OpenSky ──────────────────────────────────────────────────────────────

def _fetch_states(bbox: tuple[float, float, float, float]) -> list[dict]:
    lamin, lomin, lamax, lomax = bbox
    try:
        r = requests.get(
            _OPENSKY_URL,
            params={"lamin": lamin, "lomin": lomin, "lamax": lamax, "lomax": lomax},
            timeout=12,
        )
        if r.status_code == 429:
            print("[PlaneRadar] ⚠️ OpenSky rate limit hit.")
            return []
        rows = (r.json() or {}).get("states") or []
    except Exception as e:
        print(f"[PlaneRadar] ⚠️ OpenSky fetch failed: {e}")
        return []

    planes = []
    for s in rows:
        if not s or len(s) < 12:
            continue
        icao24, callsign = s[0], (s[1] or "").strip()
        lon, lat, on_ground = s[5], s[6], s[8]
        if lat is None or lon is None or on_ground:
            continue
        planes.append({
            "icao24":   icao24,
            "callsign": callsign or "Unknown",
            "country":  s[2],
            "lat":      lat,
            "lon":      lon,
            "alt_m":    s[13] if len(s) > 13 and s[13] is not None else s[7],
            "speed_ms": s[9],
            "heading":  s[10],
        })
    return planes


# ── Aircraft type / route enrichment (adsbdb.com) ─────────────────────────
# icao24 rarely changes type/registration and a callsign's route doesn't
# change mid-flight, so both are cached for the life of the process — a
# second scan a minute later costs zero extra lookups for the same aircraft.
_type_cache: dict[str, dict] = {}
_route_cache: dict[str, dict] = {}

# Typical seating/size for common types, keyed by ICAO type designator.
# Deliberately small and conservative: anything not listed here is reported
# as "capacity unknown for this type" rather than guessed at.
#   value = (category, typical_seats, length_m, wingspan_m)
_TYPE_SPECS = {
    "A19N": ("narrowbody airliner", 150, 34.1, 35.8),
    "A20N": ("narrowbody airliner", 165, 39.0, 35.8),
    "A21N": ("narrowbody airliner", 200, 44.5, 35.8),
    "A319": ("narrowbody airliner", 140, 33.8, 35.8),
    "A320": ("narrowbody airliner", 165, 37.6, 35.8),
    "A321": ("narrowbody airliner", 200, 44.5, 35.8),
    "A332": ("widebody airliner", 260, 58.8, 60.3),
    "A333": ("widebody airliner", 290, 63.7, 60.3),
    "A359": ("widebody airliner", 315, 66.8, 64.8),
    "A35K": ("widebody airliner", 350, 73.8, 64.8),
    "A388": ("widebody airliner (double-deck)", 525, 72.7, 79.8),
    "B737": ("narrowbody airliner", 150, 33.6, 35.8),
    "B738": ("narrowbody airliner", 175, 39.5, 35.8),
    "B739": ("narrowbody airliner", 180, 42.1, 35.8),
    "B38M": ("narrowbody airliner", 175, 39.5, 35.9),
    "B39M": ("narrowbody airliner", 185, 42.2, 35.9),
    "B752": ("narrowbody airliner", 200, 47.3, 38.0),
    "B763": ("widebody airliner", 210, 55.0, 47.6),
    "B764": ("widebody airliner", 245, 61.4, 51.9),
    "B772": ("widebody airliner", 305, 63.7, 60.9),
    "B77W": ("widebody airliner", 365, 73.9, 64.8),
    "B788": ("widebody airliner", 240, 56.7, 60.1),
    "B789": ("widebody airliner", 290, 62.8, 60.1),
    "B78X": ("widebody airliner", 330, 68.3, 60.1),
    "B744": ("widebody airliner (four-engine)", 410, 70.7, 64.4),
    "B748": ("widebody airliner (four-engine)", 410, 76.3, 68.4),
    "E170": ("regional jet", 72, 29.9, 26.0),
    "E175": ("regional jet", 80, 31.7, 26.0),
    "E190": ("regional jet", 100, 36.2, 28.7),
    "E195": ("regional jet", 120, 38.6, 28.7),
    "CRJ2": ("regional jet", 50, 26.8, 21.2),
    "CRJ9": ("regional jet", 90, 36.2, 24.9),
    "AT72": ("regional turboprop", 70, 27.2, 27.1),
    "AT76": ("regional turboprop", 70, 27.2, 27.1),
    "DH8D": ("regional turboprop", 78, 32.8, 28.4),
    "C172": ("light general aviation", 4, 8.3, 11.0),
    "C182": ("light general aviation", 4, 8.8, 11.0),
    "SR22": ("light general aviation", 4, 7.9, 11.7),
    "PA28": ("light general aviation", 4, 7.3, 9.1),
    "P28A": ("light general aviation", 4, 7.3, 9.1),
    "BE20": ("light business turboprop", 9, 13.3, 16.6),
    "C525": ("light business jet", 7, 12.9, 13.2),
    "C56X": ("midsize business jet", 9, 16.9, 19.2),
    "GLF6": ("large business jet", 13, 29.4, 31.0),
    "H60": ("helicopter", 4, 19.8, 16.4),
    "EC35": ("helicopter", 6, 12.9, 10.7),
    "EC30": ("helicopter", 8, 11.2, 10.7),
    "R44": ("helicopter", 4, 11.8, 10.1),
    "R66": ("helicopter", 5, 11.9, 10.1),
    "B06": ("helicopter", 5, 11.8, 10.2),
    "B407": ("helicopter", 6, 12.7, 10.7),
    "AS50": ("helicopter", 5, 12.9, 10.7),
    "A139": ("helicopter", 15, 16.7, 13.8),
    "S76": ("helicopter", 12, 16.0, 13.4),
    "H500": ("helicopter", 5, 9.4, 8.0),
}


def _lookup_aircraft_type(icao24: str) -> dict:
    """{'type': str, 'icao_type': str, 'manufacturer': str, 'registration': str}
    Empty dict if unknown/unreachable — never raises."""
    icao24 = (icao24 or "").strip().lower()
    if not icao24:
        return {}
    if icao24 in _type_cache:
        return _type_cache[icao24]

    info: dict = {}
    try:
        r = requests.get(_ADSBDB_AIRCRAFT_URL.format(icao24=icao24), timeout=8)
        if r.status_code == 200:
            body = r.json() or {}
            ac = ((body.get("response") or {}) or {}).get("aircraft")
            if isinstance(ac, dict):
                info = {
                    "type":         ac.get("type") or ac.get("model") or "",
                    "icao_type":    (ac.get("icao_type") or ac.get("type_code")
                                      or ac.get("icaoType") or "").upper(),
                    "manufacturer": ac.get("manufacturer") or "",
                    "registration": ac.get("registration") or ac.get("reg") or "",
                }
    except Exception as e:
        print(f"[PlaneRadar] ⚠️ Aircraft type lookup failed for {icao24}: {e}")

    _type_cache[icao24] = info
    return info


def _lookup_route(callsign: str) -> dict:
    """{'origin': str, 'destination': str, 'airline': str}
    Empty dict if unknown/unfiled/unreachable — never raises."""
    callsign = (callsign or "").strip().upper()
    if not callsign or callsign == "UNKNOWN":
        return {}
    if callsign in _route_cache:
        return _route_cache[callsign]

    info: dict = {}
    try:
        r = requests.get(_ADSBDB_CALLSIGN_URL.format(callsign=callsign), timeout=8)
        if r.status_code == 200:
            body = r.json() or {}
            route = ((body.get("response") or {}) or {}).get("flightroute")
            if isinstance(route, dict):
                origin = route.get("origin") or {}
                dest = route.get("destination") or {}
                airline = route.get("airline") or {}

                def _place(p: dict) -> str:
                    name = p.get("municipality") or p.get("name") or ""
                    code = p.get("iata_code") or p.get("icao_code") or ""
                    if name and code:
                        return f"{name} ({code})"
                    return name or code

                info = {
                    "origin":      _place(origin) if isinstance(origin, dict) else "",
                    "destination": _place(dest) if isinstance(dest, dict) else "",
                    "airline":     airline.get("name", "") if isinstance(airline, dict) else "",
                }
    except Exception as e:
        print(f"[PlaneRadar] ⚠️ Route lookup failed for {callsign}: {e}")

    _route_cache[callsign] = info
    return info


def _enrich(p: dict) -> dict:
    """Adds type/route/size info to a plane dict, in place, best-effort."""
    t = _lookup_aircraft_type(p.get("icao24", ""))
    p["ac_type"] = t.get("type", "")
    p["icao_type"] = t.get("icao_type", "")
    p["registration"] = t.get("registration", "")

    spec = _TYPE_SPECS.get(p["icao_type"]) if p["icao_type"] else None
    if spec:
        category, seats, length_m, wingspan_m = spec
        p["category"] = category
        p["typical_seats"] = seats
        p["length_m"] = length_m
        p["wingspan_m"] = wingspan_m
    else:
        p["category"] = ""
        p["typical_seats"] = None

    route = _lookup_route(p.get("callsign", ""))
    p["origin"] = route.get("origin", "")
    p["destination"] = route.get("destination", "")
    p["airline"] = route.get("airline", "")
    return p


def _describe_plane(p: dict) -> str:
    """One spoken/text line for a single aircraft, built from whatever we
    actually have — nothing here is invented when a field is unknown."""
    alt_ft = round((p["alt_m"] or 0) * 3.28084)
    spd_kt = round((p["speed_ms"] or 0) * 1.94384)

    bits = [f"{p['callsign']}"]
    if p.get("ac_type"):
        article = "an" if p["ac_type"][:1].lower() in "aeiou" else "a"
        bits.append(f"{article} {p['ac_type']}")
    elif p.get("icao_type"):
        bits.append(f"type {p['icao_type']}")
    line = " — ".join([bits[0], bits[1]]) if len(bits) > 1 else bits[0]

    line += (f": {p['dist_km']:.0f} km {p['compass']}, {alt_ft:,} ft, "
             f"{spd_kt} kt, {p['trend']}.")

    if p.get("category"):
        cap = f", typical capacity ~{p['typical_seats']} passengers" if p.get("typical_seats") else ""
        line += f" {p['category'].capitalize()}{cap}."

    if p.get("origin") or p.get("destination"):
        origin = p.get("origin") or "unknown origin"
        dest = p.get("destination") or "unknown destination"
        line += f" Flying {origin} \u2192 {dest}."

    return line


def _resolve_location(params: dict):
    """Returns (lat, lon, label) or an error string to speak."""
    location = (params.get("location") or "").strip()
    wants_here = bool(params.get("use_device_location", False)) or location.lower() in _HERE_ALIASES

    if location and not wants_here:
        geo = _geocode(location)
        if not geo:
            return f"I couldn't find a place called '{location}', sir."
        return geo

    if wants_here:
        dev = _detect_device_location()
        if dev:
            return dev
        return (
            "I couldn't detect your current device location, sir — tell me a "
            "place to scan around instead."
        )

    home = get_plugin_config(_NS)
    if home.get("lat") is not None and home.get("lon") is not None:
        return float(home["lat"]), float(home["lon"]), home.get("label", "your saved home location")

    # No named place, no saved home — fall back to the device's current
    # location so "scan the airspace" works with zero setup.
    dev = _detect_device_location()
    if dev:
        return dev

    return (
        "I don't have a location to scan, sir — tell me a place, say 'scan "
        "near me', or set a home location for plane tracking."
    )


def _handle_set_home(params: dict) -> str:
    location = (params.get("location") or "").strip()
    wants_here = bool(params.get("use_device_location", False)) or location.lower() in _HERE_ALIASES

    if wants_here:
        dev = _detect_device_location()
        if not dev:
            return "I couldn't detect your current device location, sir."
        lat, lon, label = dev
    elif location:
        geo = _geocode(location)
        if not geo:
            return f"I couldn't find a place called '{location}', sir."
        lat, lon, label = geo
    else:
        return (
            "Which place should I use as your plane radar home, sir? You can "
            "also say 'use my current location'."
        )

    save_plugin_config(_NS, {"lat": lat, "lon": lon, "label": label})
    return f"Home location for plane tracking set to {label}, sir."


# ── main entry point ────────────────────────────────────────────────────────

def run(parameters: dict, player=None, session_memory=None) -> str:
    """
    parameters: {action?, location?, use_device_location?, radius_km?}
    player: the JarvisUI instance (may be None). Used for console logging and,
            if present, to push a plain-text listing into the existing content
            panel via player.show_content(title, text) — never required.
    session_memory: reserved, unused here.
    Returns the natural-language string JARVIS speaks back. Never raises.
    """
    params = parameters or {}
    action = (params.get("action") or "scan").strip().lower()

    try:
        if action == "set_home":
            result = _handle_set_home(params)
            if player:
                try:
                    player.write_log(f"[PlaneRadar] {result}")
                except Exception:
                    pass
            return result

        located = _resolve_location(params)
        if isinstance(located, str):
            return located
        home_lat, home_lon, label = located

        try:
            radius_km = max(5.0, min(300.0, float(params.get("radius_km") or 50)))
        except (TypeError, ValueError):
            radius_km = 50.0

        if player:
            try:
                player.write_log(f"[PlaneRadar] Scanning {radius_km:.0f}km around {label}")
            except Exception:
                pass

        # Two bounding boxes: `radius_km` is what the user asked to see listed,
        # but an aircraft heading straight for that circle is worth flagging
        # before it actually crosses into it. So the live query — the only
        # thing that costs an OpenSky request — always casts a wider net
        # (capped at 300km, same ceiling as radius_km itself), and everything
        # inside that gets a trend; we just group the results afterwards by
        # whether they're inside the requested radius or still further out.
        watch_radius_km = min(300.0, radius_km * 3)
        bbox = _bbox(home_lat, home_lon, watch_radius_km)

        first_pass = _fetch_states(bbox)
        if not first_pass:
            return (
                f"No aircraft currently detected near {label}, sir — or the "
                "tracking service is unavailable right now."
            )

        # A second sample a few seconds later lets us tell approaching from
        # departing instead of reporting one frozen snapshot.
        time.sleep(8)
        second_pass = _fetch_states(bbox) or first_pass
        first_by_id = {p["icao24"]: p for p in first_pass}

        planes = []
        for p in second_pass:
            dist = _haversine_km(home_lat, home_lon, p["lat"], p["lon"])
            brg = _bearing(home_lat, home_lon, p["lat"], p["lon"])
            p["dist_km"] = dist
            p["compass"] = _compass(brg)

            prev = first_by_id.get(p["icao24"])
            if prev is not None:
                prev_dist = _haversine_km(home_lat, home_lon, prev["lat"], prev["lon"])
                delta = prev_dist - dist
                p["trend"] = (
                    "approaching" if delta > 0.3 else
                    "departing" if delta < -0.3 else
                    "holding"
                )
            else:
                p["trend"] = "unknown"
            planes.append(p)

        planes.sort(key=lambda p: p["dist_km"])
        nearby = [p for p in planes if p["dist_km"] <= radius_km]
        beyond = [p for p in planes if p["dist_km"] > radius_km]
        top = nearby[:_ENRICH_NEARBY_LIMIT]

        lines = [f"{len(nearby)} aircraft detected within {radius_km:.0f} km of {label}, sir."]
        for p in top:
            _enrich(p)
            lines.append(_describe_plane(p))
        if len(nearby) > len(top):
            lines.append(f"...and {len(nearby) - len(top)} more within range.")

        # The whole point of casting the wider net: an aircraft doesn't have
        # to already be in the nearby list to be worth calling out, as long
        # as it's clearly closing in from further out.
        approaching_far = sorted(
            (p for p in beyond if p["trend"] == "approaching"),
            key=lambda p: p["dist_km"],
        )[:_ENRICH_FAR_LIMIT]
        if approaching_far:
            far_bits = []
            for p in approaching_far:
                _enrich(p)
                kind = f" ({p['ac_type']})" if p.get("ac_type") else ""
                far_bits.append(f"{p['callsign']}{kind}, {p['dist_km']:.0f} km {p['compass']} and closing")
            lines.append(
                f"Also inbound from outside that radius (within {watch_radius_km:.0f} km): "
                + "; ".join(far_bits) + "."
            )

        # Closest approaching contact overall, near or far — not just among
        # the nearest few, which is the bug this rewrite fixes.
        all_approaching = sorted(
            (p for p in planes if p["trend"] == "approaching"),
            key=lambda p: p["dist_km"],
        )
        if all_approaching:
            nearest = all_approaching[0]
            lines.append(
                f"Closest approaching contact overall: {nearest['callsign']}, "
                f"{nearest['dist_km']:.0f} km {nearest['compass']} and closing."
            )

        if player:
            try:
                player.write_log(
                    f"[PlaneRadar] {len(nearby)} nearby, {len(approaching_far)} inbound "
                    f"from beyond {radius_km:.0f}km, near {label}"
                )
                if hasattr(player, "show_content"):
                    player.show_content("PLANE RADAR", "\n".join(lines))
            except Exception:
                pass

        return " ".join(lines)

    except Exception as e:
        print(f"[PlaneRadar] ❌ {e}")
        return f"Plane radar failed, sir: {e}"
