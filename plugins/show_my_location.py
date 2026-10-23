"""
Show My Location / Nearby / Directions / Favorites — JARVIS plugin

Capabilities:
  1. Pin the user's current location on a map — detected automatically
     (OS-native location services on Windows/macOS, IP geolocation
     elsewhere), never asked of the user.
  2. Search for nearby places with REAL results — actual names and
     distances from OpenStreetMap's Overpass API ("closest eateries",
     "restaurants near me"), not just a blind map search link.
  3. Directions to the nearest X, OR to a specific named destination —
     real road distance/duration via OSRM routing, a short turn-by-turn
     summary, and (for long-distance destinations) a rough flight-time
     estimate — plus the route is still opened/marked on the map.
  4. Radius control for nearby searches.
  5. Save / list / go-to favorite places (persisted locally).
  6. Keeps the plane_radar plugin's scan location in sync with the
     device's real current position automatically, so airspace scans
     center on wherever the user actually is without a separate step.

Trigger examples:
  - "Where am I?" / "Show my location"
  - "Find restaurants near me" / "Closest eateries" / "Coffee shops within 2 km"
  - "Directions to the nearest hospital" / "How do I get to [place]"
  - "Navigate to the closest gas station"
  - "How long would it take to fly to [place]"
  - "Save this place as Home" / "Save my location as Work"
  - "List my favorite places" / "Go to Home"

Honest limits:
  - Nearby search and routing use free public services (Overpass API,
    OSRM's demo router, Nominatim) — no API key needed, but they're
    rate-limited and occasionally slow/unavailable. Every call degrades
    gracefully to the old "just open a map" behavior if they don't answer.
  - Flight time is a rough straight-line estimate (great-circle distance
    / typical cruise speed + a fixed overhead for taxi/climb/descent) —
    it is NOT a real flight search, ignores layovers/routing/booking, and
    shouldn't be treated as more than a ballpark.
  - Precise OS-native location is only attempted on Windows and macOS;
    Linux and anything else goes straight to IP geolocation (city-level
    accuracy).

No other file needs to change — JARVIS discovers this automatically at startup.
"""

from __future__ import annotations

import json
import math
import platform
import re
import subprocess
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus, urlencode

# ── Optional integration: keep plane_radar's scan location in sync ──────────
# Lazy/defensive import — this plugin must keep working even if
# memory.config_manager isn't importable for some reason.
try:
    from memory.config_manager import save_plugin_config as _save_plugin_config
    _CONFIG_MANAGER_AVAILABLE = True
except Exception:
    _CONFIG_MANAGER_AVAILABLE = False

_PLANE_RADAR_NS = "plane_radar"  # must match plane_radar.py's own namespace

# ── Plugin declaration (auto-discovered) ─────────────────────────────────────

PLUGIN = {
    "name": "show_my_location",
    "description": (
        "Location, nearby places with real distances (e.g. closest eateries/"
        "restaurants), driving directions with actual route distance/time (plus a "
        "rough flight-time estimate for long-distance destinations), marking the "
        "route on a map, and favorite places. Also keeps plane_radar's scan "
        "location in sync with the user's real device location automatically. "
        "Use for: "
        "'where am I', 'show my location', "
        "'find restaurants near me', 'closest eateries', 'coffee shops within 1 km', "
        "'directions to the nearest gas station', 'how do I get to [place]', "
        "'how long would it take to fly to [place]', 'navigate to closest hospital', "
        "'save this place as Home', 'save my location as Work', "
        "'list my favorites', 'go to Home'. "
        "Parameters: "
        "query = place TYPE for nearest-X search (restaurants, hospital…); "
        "destination = a specific named place/address (for mode='directions', "
        "instead of a type); "
        "mode = 'location' | 'nearby' | 'directions' | 'save_favorite' | "
        "'list_favorites' | 'go_to_favorite'; "
        "radius_km = search radius in kilometres; "
        "favorite_name = name when saving or going to a favorite. "
        "This routes FROM the user's own current device location — do NOT use it "
        "for directions between two far-off places that aren't the user's current "
        "position; use browser_control for a generic map lookup like that instead."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query": {
                "type": "STRING",
                "description": (
                    "Place TYPE or free-text search term. Examples: 'restaurants', "
                    "'eateries', 'gas station', 'hospital', 'coffee', 'parking', 'ATM'. "
                    "Used for nearby mode, or as a nearest-X target for directions. "
                    "Leave empty for a pure location pin."
                ),
            },
            "destination": {
                "type": "STRING",
                "description": (
                    "A specific named place or address to route to (e.g. 'Lekki "
                    "Phase 1', '221B Baker Street, London'), as opposed to `query` "
                    "which is a place TYPE for a nearest-X search. Used with "
                    "mode='directions'; takes priority over `query` if both are given."
                ),
            },
            "mode": {
                "type": "STRING",
                "description": (
                    "Explicit mode: 'location' (default pin), 'nearby', 'directions', "
                    "'save_favorite', 'list_favorites', 'go_to_favorite'. "
                    "If omitted the plugin infers from other parameters."
                ),
            },
            "radius_km": {
                "type": "NUMBER",
                "description": (
                    "Search radius in kilometres for nearby mode (e.g. 1, 2.5, 5). "
                    "Default 2 km. For directions with a query type, this widens how "
                    "far to search for the nearest match (default 5 km)."
                ),
            },
            "favorite_name": {
                "type": "STRING",
                "description": (
                    "Name of the favorite place. Used with mode='save_favorite' or "
                    "mode='go_to_favorite' (e.g. 'Home', 'Work', 'Gym')."
                ),
            },
            "zoom": {
                "type": "INTEGER",
                "description": "Map zoom 1–21. Sensible defaults are chosen per mode.",
            },
            "provider": {
                "type": "STRING",
                "description": "Map provider: 'google' (default), 'apple', or 'openstreetmap'.",
            },
            "prefer_precise": {
                "type": "BOOLEAN",
                "description": (
                    "If true (default), try OS location services on Windows/macOS first "
                    "before falling back to IP geolocation."
                ),
            },
        },
        "required": [],
    },
    "behavior": "NON_BLOCKING",
    "scheduling": "WHEN_IDLE",
}


# ── Favorites storage ─────────────────────────────────────────────────────────

_FAV_FILE = Path.home() / ".jarvis_location_favorites.json"


def _load_favorites() -> Dict[str, Dict[str, Any]]:
    try:
        if _FAV_FILE.exists():
            data = json.loads(_FAV_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_favorites(favs: Dict[str, Dict[str, Any]]) -> None:
    try:
        _FAV_FILE.write_text(json.dumps(favs, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _normalize_fav_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip()).title()


# ── OS-native location attempts ───────────────────────────────────────────────

def _try_windows_location() -> Tuple[Optional[float], Optional[float], str]:
    if platform.system() != "Windows":
        return None, None, ""
    ps_script = r"""
    $ErrorActionPreference = 'Stop'
    try {
        Add-Type -AssemblyName System.Device
        $watcher = New-Object System.Device.Location.GeoCoordinateWatcher
        $watcher.Start()
        $timeout = (Get-Date).AddSeconds(8)
        while ($watcher.Status -ne 'Ready' -and (Get-Date) -lt $timeout) {
            Start-Sleep -Milliseconds 200
        }
        if ($watcher.Status -eq 'Ready' -and $watcher.Position.Location.IsUnknown -eq $false) {
            $lat = $watcher.Position.Location.Latitude
            $lon = $watcher.Position.Location.Longitude
            Write-Output "$lat|$lon"
        }
        $watcher.Stop()
    } catch {}
    """
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, text=True, timeout=12,
        )
        out = (result.stdout or "").strip()
        if "|" in out:
            lat_s, lon_s = out.split("|", 1)
            return float(lat_s), float(lon_s), "Windows Location"
    except Exception:
        pass
    return None, None, ""


def _try_macos_location() -> Tuple[Optional[float], Optional[float], str]:
    if platform.system() != "Darwin":
        return None, None, ""
    try:
        code = r"""
import sys
try:
    from CoreLocation import CLLocationManager
    from Foundation import NSRunLoop, NSDate, NSObject
    class Delegate(NSObject):
        def locationManager_didUpdateLocations_(self, manager, locations):
            loc = locations[-1]
            print(f"{loc.coordinate().latitude}|{loc.coordinate().longitude}")
            manager.stopUpdatingLocation()
            sys.exit(0)
        def locationManager_didFailWithError_(self, manager, error):
            sys.exit(1)
    manager = CLLocationManager.alloc().init()
    delegate = Delegate.alloc().init()
    manager.setDelegate_(delegate)
    manager.requestWhenInUseAuthorization()
    manager.startUpdatingLocation()
    NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(6.0))
except Exception:
    sys.exit(2)
"""
        result = subprocess.run(
            ["python3", "-c", code],
            capture_output=True, text=True, timeout=10,
        )
        out = (result.stdout or "").strip()
        if "|" in out:
            lat_s, lon_s = out.split("|", 1)
            return float(lat_s), float(lon_s), "macOS CoreLocation"
    except Exception:
        pass
    return None, None, ""


# ── IP geolocation ────────────────────────────────────────────────────────────

_GEO_ENDPOINTS = [
    (
        "https://ipapi.co/json/",
        lambda d: (
            d.get("latitude"), d.get("longitude"),
            d.get("city"), d.get("region"), d.get("country_name"),
        ),
    ),
    (
        "http://ip-api.com/json/?fields=status,message,lat,lon,city,regionName,country",
        lambda d: (
            d.get("lat"), d.get("lon"),
            d.get("city"), d.get("regionName"), d.get("country"),
        ) if d.get("status") == "success" else (None, None, None, None, None),
    ),
    (
        "https://ipinfo.io/json",
        lambda d: (
            float(d["loc"].split(",")[0]) if d.get("loc") else None,
            float(d["loc"].split(",")[1]) if d.get("loc") else None,
            d.get("city"), d.get("region"), d.get("country"),
        ),
    ),
]


def _fetch_ip_location() -> Tuple[Optional[float], Optional[float], str]:
    for url, extractor in _GEO_ENDPOINTS:
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "JARVIS-LocationPlugin/4.0"},
            )
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            lat, lon, city, region, country = extractor(data)
            if lat is None or lon is None:
                continue
            parts = [p for p in (city, region, country) if p]
            place = ", ".join(parts) if parts else f"{lat:.4f}, {lon:.4f}"
            return float(lat), float(lon), place
        except Exception:
            continue
    return None, None, "unknown location"


def _get_best_location(prefer_precise: bool = True) -> Tuple[Optional[float], Optional[float], str, str]:
    if prefer_precise:
        system = platform.system()
        if system == "Windows":
            lat, lon, source = _try_windows_location()
            if lat is not None:
                return lat, lon, f"{lat:.5f}, {lon:.5f}", source
        elif system == "Darwin":
            lat, lon, source = _try_macos_location()
            if lat is not None:
                return lat, lon, f"{lat:.5f}, {lon:.5f}", source

    lat, lon, place = _fetch_ip_location()
    if lat is not None:
        return lat, lon, place, "IP geolocation"
    return None, None, "unknown location", "none"


def _sync_plane_radar_home(lat: float, lon: float, place: str) -> None:
    """Best-effort: keep plane_radar's saved scan location matched to the
    device's actual current position. Never raises, never blocks a response
    on failure."""
    if not _CONFIG_MANAGER_AVAILABLE:
        return
    try:
        _save_plugin_config(_PLANE_RADAR_NS, {"lat": lat, "lon": lon, "label": place})
    except Exception:
        pass


# ── Distance math ─────────────────────────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


_FLIGHT_CRUISE_KMH = 850.0
_FLIGHT_OVERHEAD_MIN = 45.0  # taxi, takeoff, climb/descent, landing buffer
_FLIGHT_TIME_THRESHOLD_KM = 250.0  # below this, "flying" isn't a sensible option


def _estimate_flight_minutes(distance_km: float) -> float:
    return (distance_km / _FLIGHT_CRUISE_KMH) * 60.0 + _FLIGHT_OVERHEAD_MIN


# ── HTTP helpers ───────────────────────────────────────────────────────────────

def _http_get_json(url: str, timeout: int = 8) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "JARVIS-LocationPlugin/4.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _http_post_form(url: str, form: Dict[str, str], timeout: int = 12) -> Any:
    body = urlencode(form).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"User-Agent": "JARVIS-LocationPlugin/4.0"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


# ── Real nearby-place search (Overpass / OpenStreetMap) ────────────────────────

_PLACE_TYPE_MAP = {
    "restaurant": "amenity=restaurant", "restaurants": "amenity=restaurant",
    "eatery": "amenity=restaurant", "eateries": "amenity=restaurant", "food": "amenity=restaurant",
    "cafe": "amenity=cafe", "cafes": "amenity=cafe", "coffee": "amenity=cafe", "coffee shop": "amenity=cafe",
    "fast food": "amenity=fast_food",
    "bar": "amenity=bar", "bars": "amenity=bar", "pub": "amenity=pub", "pubs": "amenity=pub",
    "gas station": "amenity=fuel", "petrol station": "amenity=fuel", "fuel": "amenity=fuel",
    "hospital": "amenity=hospital", "hospitals": "amenity=hospital", "clinic": "amenity=clinic",
    "pharmacy": "amenity=pharmacy", "pharmacies": "amenity=pharmacy", "chemist": "amenity=pharmacy",
    "atm": "amenity=atm", "atms": "amenity=atm", "bank": "amenity=bank", "banks": "amenity=bank",
    "parking": "amenity=parking",
    "hotel": "tourism=hotel", "hotels": "tourism=hotel", "motel": "tourism=motel",
    "supermarket": "shop=supermarket", "supermarkets": "shop=supermarket", "grocery": "shop=supermarket",
    "airport": "aeroway=aerodrome", "airports": "aeroway=aerodrome",
    "police": "amenity=police", "police station": "amenity=police",
    "school": "amenity=school", "schools": "amenity=school",
}

_OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]


def _osm_tag_for_query(query: str) -> str:
    q = query.strip().lower()
    if q in _PLACE_TYPE_MAP:
        return _PLACE_TYPE_MAP[q]
    if q.endswith("s") and q[:-1] in _PLACE_TYPE_MAP:
        return _PLACE_TYPE_MAP[q[:-1]]
    return ""


def _overpass_nearby(lat: float, lon: float, radius_km: float, query: str, limit: int = 8) -> List[Dict[str, Any]]:
    """Real nearby places from OpenStreetMap data. Returns [] on any failure
    or if nothing matched — callers must handle that gracefully."""
    radius_m = int(max(0.1, radius_km) * 1000)
    tag = _osm_tag_for_query(query)
    if tag:
        k, v = tag.split("=", 1)
        filt = f'["{k}"="{v}"]'
    else:
        safe_q = re.sub(r'["\\]', "", query.strip())
        if not safe_q:
            return []
        filt = f'["name"~"{safe_q}",i]'

    ql = (
        f"[out:json][timeout:10];"
        f"(node{filt}(around:{radius_m},{lat},{lon});"
        f"way{filt}(around:{radius_m},{lat},{lon});"
        f"relation{filt}(around:{radius_m},{lat},{lon}););"
        f"out center {limit * 3};"
    )

    for endpoint in _OVERPASS_ENDPOINTS:
        try:
            data = _http_post_form(endpoint, {"data": ql}, timeout=12)
            results: List[Dict[str, Any]] = []
            for el in data.get("elements", []):
                if el.get("type") == "node":
                    elat, elon = el.get("lat"), el.get("lon")
                else:
                    center = el.get("center") or {}
                    elat, elon = center.get("lat"), center.get("lon")
                if elat is None or elon is None:
                    continue
                tags = el.get("tags") or {}
                name = tags.get("name")
                if not name:
                    continue
                dist = _haversine_km(lat, lon, elat, elon)
                addr_bits = []
                if tags.get("addr:street"):
                    hn = tags.get("addr:housenumber", "")
                    addr_bits.append(f"{hn} {tags['addr:street']}".strip())
                results.append(
                    {
                        "name": name,
                        "lat": elat,
                        "lon": elon,
                        "distance_km": dist,
                        "address": ", ".join(addr_bits) if addr_bits else "",
                    }
                )

            # de-dup (OSM often has the same POI as a node + a way)
            seen = set()
            deduped = []
            for r in sorted(results, key=lambda r: r["distance_km"]):
                key = (r["name"], round(r["lat"], 4), round(r["lon"], 4))
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(r)

            if deduped:
                return deduped[:limit]
        except Exception:
            continue
    return []


def _geocode_place(text: str) -> Optional[Tuple[float, float, str]]:
    """Resolve a named place/address to coordinates via Nominatim."""
    text = text.strip()
    if not text:
        return None
    url = f"https://nominatim.openstreetmap.org/search?q={quote_plus(text)}&format=json&limit=1"
    try:
        data = _http_get_json(url, timeout=8)
        if data:
            item = data[0]
            return float(item["lat"]), float(item["lon"]), item.get("display_name", text)
    except Exception:
        pass
    return None


def _osrm_route(lat1: float, lon1: float, lat2: float, lon2: float) -> Optional[dict]:
    """Real driving route (distance/duration/steps) via OSRM's public router."""
    url = (
        f"https://router.project-osrm.org/route/v1/driving/"
        f"{lon1},{lat1};{lon2},{lat2}?overview=false&steps=true&alternatives=false"
    )
    try:
        data = _http_get_json(url, timeout=12)
        if data.get("code") == "Ok" and data.get("routes"):
            return data["routes"][0]
    except Exception:
        pass
    return None


def _summarize_steps(route: dict, max_steps: int = 6) -> List[str]:
    out: List[str] = []
    try:
        for s in route["legs"][0]["steps"]:
            maneuver = s.get("maneuver", {})
            mtype = maneuver.get("type", "")
            modifier = maneuver.get("modifier", "")
            name = s.get("name") or ""
            dist_m = s.get("distance", 0) or 0

            if mtype == "depart":
                text = "Head out" + (f" onto {name}" if name else "")
            elif mtype == "arrive":
                text = "Arrive at your destination"
            else:
                bit = f"{mtype} {modifier}".strip()
                text = bit.capitalize() + (f" onto {name}" if name else "")

            if dist_m and mtype != "arrive":
                text += f" ({dist_m / 1000:.1f} km)" if dist_m >= 1000 else f" ({int(dist_m)} m)"
            out.append(text)
    except Exception:
        pass
    return out[:max_steps]


# ── URL builders ──────────────────────────────────────────────────────────────

def _build_location_url(lat: float, lon: float, zoom: int, provider: str) -> str:
    provider = (provider or "google").strip().lower()
    if provider in ("apple", "apple maps"):
        return f"https://maps.apple.com/?ll={lat},{lon}&q=My+Location&z={zoom}"
    if provider in ("osm", "openstreetmap", "open street map"):
        return f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map={zoom}/{lat}/{lon}"
    return f"https://www.google.com/maps?q={lat},{lon}&z={zoom}"


def _build_nearby_url(
    query: str,
    lat: float,
    lon: float,
    zoom: int,
    provider: str,
    radius_km: Optional[float] = None,
) -> str:
    provider = (provider or "google").strip().lower()
    q = query.strip()

    if radius_km and radius_km > 0:
        if radius_km < 1:
            radius_m = int(radius_km * 1000)
            q = f"{q} within {radius_m} meters"
        else:
            q = f"{q} within {radius_km:g} km"

    if provider in ("apple", "apple maps"):
        return f"https://maps.apple.com/?q={quote_plus(q)}&ll={lat},{lon}&z={zoom}"
    if provider in ("osm", "openstreetmap", "open street map"):
        return (
            f"https://www.openstreetmap.org/search?query={quote_plus(q)}"
            f"#map={zoom}/{lat}/{lon}"
        )
    return (
        f"https://www.google.com/maps/search/{quote_plus(q)}"
        f"/@{lat},{lon},{zoom}z"
    )


def _build_directions_url(query: str, lat: float, lon: float, provider: str) -> str:
    """Text-based fallback directions (origin fixed, destination is a text
    search like 'nearest X') — used only when we couldn't resolve a concrete
    destination point ourselves."""
    provider = (provider or "google").strip().lower()
    dest = f"nearest {query.strip()}"

    if provider in ("apple", "apple maps"):
        return f"https://maps.apple.com/?saddr={lat},{lon}&daddr={quote_plus(dest)}&dirflg=d"
    if provider in ("osm", "openstreetmap", "open street map"):
        return (
            f"https://www.openstreetmap.org/directions?engine=fossgis_osrm_car"
            f"&route={lat}%2C{lon}%3B0%2C0#map=14/{lat}/{lon}"
        )
    return (
        f"https://www.google.com/maps/dir/?api=1"
        f"&origin={lat},{lon}"
        f"&destination={quote_plus(dest)}"
        f"&travelmode=driving"
    )


def _build_directions_url_to_point(
    lat: float, lon: float, dlat: float, dlon: float, provider: str
) -> str:
    """Directions to a concrete resolved point — precise, no text guessing."""
    provider = (provider or "google").strip().lower()
    if provider in ("apple", "apple maps"):
        return f"https://maps.apple.com/?saddr={lat},{lon}&daddr={dlat},{dlon}&dirflg=d"
    if provider in ("osm", "openstreetmap", "open street map"):
        return (
            f"https://www.openstreetmap.org/directions?engine=fossgis_osrm_car"
            f"&route={lat}%2C{lon}%3B{dlat}%2C{dlon}#map=14/{lat}/{lon}"
        )
    return (
        f"https://www.google.com/maps/dir/?api=1"
        f"&origin={lat},{lon}"
        f"&destination={dlat},{dlon}"
        f"&travelmode=driving"
    )


def _build_favorite_url(lat: float, lon: float, name: str, zoom: int, provider: str) -> str:
    provider = (provider or "google").strip().lower()
    label = quote_plus(name)
    if provider in ("apple", "apple maps"):
        return f"https://maps.apple.com/?ll={lat},{lon}&q={label}&z={zoom}"
    if provider in ("osm", "openstreetmap", "open street map"):
        return f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map={zoom}/{lat}/{lon}"
    return f"https://www.google.com/maps?q={lat},{lon}({label})&z={zoom}"


def _open_url(url: str) -> bool:
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(
                ["open", url],
                check=True, timeout=10,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return True
        if system == "Windows":
            import os
            os.startfile(url)  # type: ignore[attr-defined]
            return True
        try:
            subprocess.run(
                ["xdg-open", url],
                check=True, timeout=10,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return True
        except Exception:
            return bool(webbrowser.open(url))
    except Exception:
        try:
            return bool(webbrowser.open(url))
        except Exception:
            return False


# ── Mode inference & helpers ──────────────────────────────────────────────────

def _infer_mode(parameters: dict) -> str:
    explicit = (parameters.get("mode") or "").strip().lower()
    if explicit in {
        "location", "nearby", "directions",
        "save_favorite", "list_favorites", "go_to_favorite",
    }:
        return explicit

    query = (parameters.get("query") or "").strip()
    destination = (parameters.get("destination") or "").strip()
    fav = (parameters.get("favorite_name") or "").strip()

    if destination:
        return "directions"

    if fav and not query:
        favs = _load_favorites()
        key = _normalize_fav_name(fav)
        if key in favs:
            return "go_to_favorite"
        return "save_favorite"

    if query:
        q_lower = query.lower()
        if any(w in q_lower for w in ("direction", "navigate", "route to", "take me to")):
            return "directions"
        return "nearby"

    return "location"


def _log(player, msg: str) -> None:
    if player:
        try:
            player.write_log(f"JARVIS: {msg}")
        except Exception:
            pass


# ── Entry point ───────────────────────────────────────────────────────────────

def run(parameters: dict, player=None, session_memory=None) -> str:
    try:
        parameters = parameters or {}
        mode = _infer_mode(parameters)
        query = (parameters.get("query") or "").strip()
        destination = (parameters.get("destination") or "").strip()
        favorite_name = (parameters.get("favorite_name") or "").strip()
        provider = str(parameters.get("provider") or "google").strip().lower()

        prefer_precise = parameters.get("prefer_precise")
        prefer_precise = True if prefer_precise is None else bool(prefer_precise)

        radius_km = parameters.get("radius_km")
        try:
            radius_km = float(radius_km) if radius_km is not None else None
            if radius_km is not None and radius_km <= 0:
                radius_km = None
        except (TypeError, ValueError):
            radius_km = None

        default_zoom = {
            "location": 15, "nearby": 14, "directions": 14,
            "go_to_favorite": 16, "save_favorite": 16, "list_favorites": 14,
        }.get(mode, 15)
        zoom = parameters.get("zoom", default_zoom)
        try:
            zoom = max(1, min(21, int(zoom)))
        except (TypeError, ValueError):
            zoom = default_zoom

        # ── list_favorites (no location needed) ───────────────────────────────
        if mode == "list_favorites":
            favs = _load_favorites()
            if not favs:
                msg = "You have no saved favorite places yet, sir."
                _log(player, msg)
                return msg
            msg = f"Your favorite places: {', '.join(sorted(favs.keys()))}."
            _log(player, msg)
            return msg

        # ── go_to_favorite (uses the SAVED coords — no device location lookup
        #    needed, so skip the potentially-slow OS location probe entirely) ──
        if mode == "go_to_favorite":
            name = _normalize_fav_name(favorite_name or query)
            if not name:
                return "Sir, which favorite place should I open?"
            favs = _load_favorites()
            entry = favs.get(name)
            if not entry:
                available = ", ".join(sorted(favs.keys())) or "none"
                return f"I don't have a favorite called '{name}'. Your favorites: {available}."
            flat, flon = float(entry["lat"]), float(entry["lon"])
            url = _build_favorite_url(flat, flon, name, zoom, provider)
            opened = _open_url(url)
            if not opened:
                return f"Sir, I found '{name}' but couldn't open the map."
            msg = f"Opening favorite place '{name}'."
            _log(player, msg)
            return msg

        # ── Everything else needs the device's actual current location ────────
        lat, lon, place, source = _get_best_location(prefer_precise=prefer_precise)

        if lat is None or lon is None:
            if mode == "directions" and (destination or query):
                target = destination or f"nearest {query}"
                fallback = (
                    f"https://www.google.com/maps/dir/?api=1"
                    f"&destination={quote_plus(target)}&travelmode=driving"
                )
            elif query:
                fallback = f"https://www.google.com/maps/search/{quote_plus(query)}+near+me"
            else:
                fallback = "https://www.google.com/maps"
            opened = _open_url(fallback)
            msg = (
                "I couldn't determine your location automatically, so I opened the map. "
                "Allow location access in the browser for better results, sir."
                if opened else
                "Sir, location lookup failed and I couldn't open a map."
            )
            _log(player, msg)
            return msg

        # Device location resolved — keep plane_radar's scan point matched to it.
        _sync_plane_radar_home(lat, lon, place)

        # ── save_favorite ─────────────────────────────────────────────────────
        if mode == "save_favorite":
            name = _normalize_fav_name(favorite_name or query or "Favorite")
            if not name:
                return "Sir, please give the favorite a name, for example 'Home' or 'Work'."
            favs = _load_favorites()
            favs[name] = {"lat": lat, "lon": lon, "place": place, "source": source}
            _save_favorites(favs)
            url = _build_favorite_url(lat, lon, name, zoom, provider)
            _open_url(url)
            msg = f"Saved current location as '{name}' ({place})."
            _log(player, msg)
            return msg

        # ── directions: named destination OR nearest-X, with a real route ─────
        if mode == "directions":
            if not destination and not query:
                return "Sir, directions to where? Give me a destination or a place type like 'gas station'."

            dest_lat = dest_lon = None
            dest_label = ""
            resolution_note = ""

            if destination:
                geocoded = _geocode_place(destination)
                if geocoded:
                    dest_lat, dest_lon, dest_label = geocoded
                else:
                    resolution_note = "couldn't pin down exact coordinates for that address"
            elif query:
                candidates = _overpass_nearby(lat, lon, radius_km or 5.0, query, limit=1)
                if candidates:
                    c = candidates[0]
                    dest_lat, dest_lon, dest_label = c["lat"], c["lon"], c["name"]
                else:
                    resolution_note = f"couldn't find a specific nearby {query} in the map data"

            if dest_lat is not None and dest_lon is not None:
                url = _build_directions_url_to_point(lat, lon, dest_lat, dest_lon, provider)
                opened = _open_url(url)
                route = _osrm_route(lat, lon, dest_lat, dest_lon)

                if route:
                    distance_km = route["distance"] / 1000.0
                    duration_min = route["duration"] / 60.0
                    steps = _summarize_steps(route)
                    step_text = " Then: " + "; ".join(steps) + "." if steps else ""
                    msg = (
                        f"Route to {dest_label}: {distance_km:.1f} km, about "
                        f"{duration_min:.0f} minutes by road.{step_text}"
                    )
                    straight_km = _haversine_km(lat, lon, dest_lat, dest_lon)
                    if straight_km >= _FLIGHT_TIME_THRESHOLD_KM:
                        flight_min = _estimate_flight_minutes(straight_km)
                        hrs, mins = divmod(int(round(flight_min)), 60)
                        msg += (
                            f" That's far enough that flying would take roughly {hrs}h "
                            f"{mins}m in the air, sir — a rough straight-line estimate, "
                            f"not counting check-in or layovers."
                        )
                else:
                    msg = (
                        f"Heading to {dest_label} from your location ({place}). I couldn't "
                        "fetch exact distance/time this time, but I've marked the route on the map."
                    )
                if not opened:
                    msg += " (I couldn't open the map automatically though.)"
                _log(player, f"{msg} [source: {source}]")
                return msg

            # Couldn't resolve a concrete point — fall back to a text-based
            # directions URL so the user still gets something useful.
            target = destination or f"nearest {query}"
            url = (
                f"https://www.google.com/maps/dir/?api=1&origin={lat},{lon}"
                f"&destination={quote_plus(target)}&travelmode=driving"
            )
            opened = _open_url(url)
            if not opened:
                return f"Sir, I {resolution_note or 'had trouble finding that destination'} and couldn't open the map either."
            msg = f"I {resolution_note}, so I opened directions toward '{target}' for you to confirm, sir."
            _log(player, msg)
            return msg

        # ── nearby search, with real names/distances when available ───────────
        if mode == "nearby":
            if not query:
                return "Sir, what kind of places should I look for nearby?"
            eff_radius = radius_km or 2.0
            places = _overpass_nearby(lat, lon, eff_radius, query, limit=6)
            url = _build_nearby_url(query, lat, lon, zoom, provider, radius_km)
            opened = _open_url(url)

            if places:
                listing = "; ".join(f"{p['name']} ({p['distance_km']:.1f} km)" for p in places)
                msg = f"Nearest {query} within {eff_radius:g} km: {listing}."
                if not opened:
                    msg += " (Couldn't open the map view though.)"
                _log(player, f"{msg} [source: {source}]")
                return msg

            if not opened:
                return f"Sir, I searched for {query} nearby but couldn't open the map, and didn't get specific results either."
            radius_txt = f" within {radius_km:g} km" if radius_km else ""
            msg = f"Showing {query} near you{radius_txt} ({place}). I couldn't pull specific names this time — check the map."
            _log(player, f"{msg} [source: {source}]")
            return msg

        # ── pure location pin (default) ───────────────────────────────────────
        url = _build_location_url(lat, lon, zoom, provider)
        opened = _open_url(url)
        if not opened:
            return f"Sir, I found you near {place} but couldn't open the map."
        msg = f"Showing your location on the map, sir. You appear to be near {place}."
        if _CONFIG_MANAGER_AVAILABLE:
            msg += " I've also updated the plane radar's scan location to match."
        _log(player, f"{msg} [source: {source}]")
        return msg

    except Exception as e:
        return f"Sir, show_my_location failed: {e}"
