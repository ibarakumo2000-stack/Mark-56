"""
JARVIS plugin: earth_viewer
Shows an interactive 3D Earth with satellite imagery (rotate, zoom down to street level).
Drop this file into the JARVIS plugins folder. Nothing else needs to change.

It does NOT search for an image. It starts a tiny local web server on 127.0.0.1, serves a
built-in CesiumJS globe, and opens it in an app-style browser window. Satellite tiles
(Esri World Imagery + NASA GIBS daily composite) stream in live, so zooming stays sharp.
Needs internet access. Uses only the Python standard library.
"""
import json
import os
import shutil
import subprocess
import threading
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PLUGIN = {
    "name": "earth_viewer",
    "description": (
        "Displays an interactive 3D satellite view of the Earth that the user can rotate and "
        "zoom into without quality loss. Use for ANY request like 'display the earth', 'show me "
        "the earth', 'open the globe', 'show earth in 3D', 'zoom into <place>', 'show <place> "
        "from space/satellite', or 'close the earth'. action='open' shows the globe (optionally "
        "flying to a location), action='fly_to' moves an already-open globe to a place or "
        "coordinates, action='reset' zooms back out, action='close' closes it. Do NOT use "
        "web search, image search or a browser tool for Earth/globe/satellite-view requests; "
        "use this tool instead."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "One of: open, fly_to, reset, close. Defaults to open.",
            },
            "location": {
                "type": "STRING",
                "description": "Optional place name to zoom to, e.g. 'Port Harcourt' or 'Eiffel Tower'.",
            },
            "latitude": {"type": "NUMBER", "description": "Optional latitude in degrees."},
            "longitude": {"type": "NUMBER", "description": "Optional longitude in degrees."},
            "altitude_km": {
                "type": "NUMBER",
                "description": "Optional camera height above ground in km (default 15 for places).",
            },
        },
        "required": [],
    },
}

_HTML = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Earth</title>
<style>
  html, body, #globe { margin: 0; width: 100%; height: 100%; background: #02040a; overflow: hidden; }
  .cesium-viewer-bottom, .cesium-widget-credits { opacity: .55; }
  #hud { position: fixed; left: 16px; bottom: 16px; padding: 10px 14px; border: 1px solid rgba(120,200,255,.35);
         background: rgba(2,8,20,.6); backdrop-filter: blur(6px); color: #bfe6ff; border-radius: 6px;
         font: 13px/1.5 system-ui, sans-serif; }
  #hud b { color: #fff; font-weight: 600; }
  #hud button { margin-top: 6px; background: transparent; color: #bfe6ff; border: 1px solid rgba(120,200,255,.5);
         padding: 4px 10px; border-radius: 4px; cursor: pointer; font: inherit; }
  #hud button:focus-visible { outline: 2px solid #7fd4ff; outline-offset: 2px; }
  #hud button[aria-pressed="true"] { background: rgba(120,200,255,.18); }
</style>
</head>
<body>
<div id="globe"></div>
<div id="hud">
  Altitude <b id="alt">--</b><br>
  <span id="src">Esri satellite imagery</span><br>
  <button id="live" aria-pressed="true">Live layer: on</button>
</div>

<div id="err" style="display:none;position:fixed;inset:0;padding:32px;color:#ffb4a8;background:#02040a;font:15px/1.6 system-ui,sans-serif;z-index:10"></div>
<script>
(function () {
  const BASES = [
    'https://cdn.jsdelivr.net/npm/cesium@1.120.0/Build/Cesium/',
    'https://unpkg.com/cesium@1.120.0/Build/Cesium/',
    'https://cdn.jsdelivr.net/npm/cesium@1.115.0/Build/Cesium/'
  ];
  function fail(msg) {
    const e = document.getElementById('err');
    e.style.display = 'block';
    e.innerHTML = '<b>Earth could not start.</b><br>' + msg +
      '<br><br>Open this page through a local server (for example <code>npx serve</code> or VS Code Live Server), not by double-clicking the file, and make sure you are online and WebGL is enabled.';
    console.error(msg);
  }
  function load(i) {
    if (i >= BASES.length) return fail('The Cesium library could not be downloaded from any source (network or content-security blocking).');
    const base = BASES[i];
    window.CESIUM_BASE_URL = base;
    const css = document.createElement('link');
    css.rel = 'stylesheet'; css.href = base + 'Widgets/widgets.css';
    document.head.appendChild(css);
    const sc = document.createElement('script');
    sc.src = base + 'Cesium.js';
    sc.onload = () => { try { start(); } catch (err) { fail('Startup error: ' + (err && err.message || err)); } };
    sc.onerror = () => load(i + 1);
    document.head.appendChild(sc);
  }
  window.addEventListener('error', (ev) => { if (!window.Cesium) return; });
  load(0);

  function start() {
  const viewer = new Cesium.Viewer('globe', {
    baseLayer: false, baseLayerPicker: false, geocoder: false, homeButton: false,
    sceneModePicker: false, navigationHelpButton: false, animation: false, timeline: false,
    fullscreenButton: false, infoBox: false, selectionIndicator: false, requestRenderMode: false
  });
  const scene = viewer.scene, globe = scene.globe, cam = viewer.camera;

  // Sharpness: request finer tiles, keep more of them cached.
  globe.maximumScreenSpaceError = 1;
  globe.tileCacheSize = 1000;
  globe.enableLighting = false;
  scene.skyAtmosphere.show = true;
  scene.highDynamicRange = false;
  scene.fxaa = true;

  // Layer 1: high-resolution satellite imagery. Tiles stream in at finer detail as you zoom,
  // so quality holds up to the imagery's native resolution (zoom level 19, roughly 0.3 m/pixel).
  viewer.imageryLayers.addImageryProvider(new Cesium.UrlTemplateImageryProvider({
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    maximumLevel: 19,
    credit: 'Esri, Maxar, Earthstar Geographics'
  }));

  // Layer 2: NASA GIBS near-real-time satellite composite (VIIRS, updated daily).
  // Shown from space, fades out as you descend where higher-resolution imagery takes over.
  const d = new Date(Date.now() - 24 * 3600 * 1000).toISOString().slice(0, 10);
  const live = viewer.imageryLayers.addImageryProvider(new Cesium.UrlTemplateImageryProvider({
    url: 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_SNPP_CorrectedReflectance_TrueColor/default/' +
         d + '/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg',
    maximumLevel: 9,
    credit: 'NASA GIBS, VIIRS ' + d
  }));
  let liveOn = true;

  // Unlimited-feeling zoom: only stop just above the surface.
  const ctl = scene.screenSpaceCameraController;
  ctl.minimumZoomDistance = 2;
  ctl.maximumZoomDistance = 6e7;
  ctl.enableCollisionDetection = true;
  ctl.inertiaZoom = 0.8;

  cam.setView({ destination: Cesium.Cartesian3.fromDegrees(10, 15, 2.2e7) });

  // Slow idle spin until the user touches the globe.
  let spin = true;
  const stop = () => { spin = false; };
  ['mousedown', 'wheel', 'touchstart', 'keydown'].forEach(e => viewer.canvas.addEventListener(e, stop, { passive: true }));
  scene.preRender.addEventListener(() => {
    const h = cam.positionCartographic.height;
    if (spin) cam.rotate(Cesium.Cartesian3.UNIT_Z, 0.0008);
    live.alpha = liveOn ? Math.min(1, Math.max(0, (h - 1.0e6) / 2.0e6)) : 0;
  });

  // Altitude readout
  const alt = document.getElementById('alt');
  scene.postRender.addEventListener(() => {
    const h = cam.positionCartographic.height;
    alt.textContent = h >= 1000 ? (h / 1000).toFixed(h > 1e5 ? 0 : 1) + ' km' : Math.round(h) + ' m';
  });

  const btn = document.getElementById('live');
  btn.addEventListener('click', () => {
    liveOn = !liveOn;
    btn.setAttribute('aria-pressed', liveOn);
    btn.textContent = 'Live layer: ' + (liveOn ? 'on' : 'off');
  });

  // Jarvis control channel: poll the local plugin server for commands.
  let lastId = 0;
  function apply(m) {
    if (m.cmd === 'flyTo') {
      stop();
      cam.flyTo({ destination: Cesium.Cartesian3.fromDegrees(m.lon, m.lat, m.height || 5000), duration: 3 });
    } else if (m.cmd === 'reset') {
      cam.flyTo({ destination: Cesium.Cartesian3.fromDegrees(10, 15, 2.2e7), duration: 2 });
    } else if (m.cmd === 'close') {
      document.body.innerHTML = '<p style="color:#bfe6ff;font:16px system-ui;padding:32px">Earth closed. You can close this window.</p>';
      window.close();
    }
  }
  setInterval(async () => {
    try {
      const r = await fetch('/cmd', { cache: 'no-store' });
      const m = await r.json();
      if (m.id > lastId) { lastId = m.id; apply(m); }
    } catch (e) { /* server gone */ }
  }, 800);
  }
})();
</script>
</body>
</html>
'''

_lock = threading.Lock()
_server = None
_port = None
_cmd = {"id": 0, "cmd": None}
_proc = None


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, body, ctype):
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/earth.html"):
            self._send(_HTML, "text/html; charset=utf-8")
        elif path == "/cmd":
            with _lock:
                payload = json.dumps(_cmd)
            self._send(payload, "application/json")
        else:
            self.send_response(404)
            self.end_headers()


def _ensure_server():
    global _server, _port
    if _server is not None:
        return _port
    _server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    _port = _server.server_address[1]
    threading.Thread(target=_server.serve_forever, daemon=True).start()
    return _port


def _queue(cmd):
    with _lock:
        _cmd["id"] += 1
        _cmd.update(cmd)


def _find_browser():
    names = ["google-chrome", "chrome", "chromium", "chromium-browser", "msedge", "microsoft-edge"]
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    candidates = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def _launch(url):
    """Open the globe in an app-style window if Chrome/Edge exists, else the default browser."""
    global _proc
    exe = _find_browser()
    if exe:
        try:
            _proc = subprocess.Popen([exe, f"--app={url}", "--window-size=1280,800"])
            return
        except Exception:
            _proc = None
    webbrowser.open(url)


def _geocode(place):
    url = "https://nominatim.openstreetmap.org/search?format=json&limit=1&q=" + urllib.parse.quote(place)
    req = urllib.request.Request(url, headers={"User-Agent": "JARVIS-EarthPlugin/1.0"})
    with urllib.request.urlopen(req, timeout=8) as r:
        data = json.loads(r.read().decode("utf-8"))
    if not data:
        return None
    return float(data[0]["lat"]), float(data[0]["lon"])


def _target(parameters):
    """Returns (lat, lon, height_m, label) or None; raises nothing except via caller's try."""
    lat, lon = parameters.get("latitude"), parameters.get("longitude")
    alt_km = parameters.get("altitude_km")
    height = float(alt_km) * 1000 if alt_km else 15000.0
    place = (parameters.get("location") or "").strip()
    if lat is not None and lon is not None:
        return float(lat), float(lon), height, place or "those coordinates"
    if place:
        found = _geocode(place)
        if found:
            return found[0], found[1], height, place
        return "notfound", place
    return None


def run(parameters: dict, player=None, session_memory=None) -> str:
    global _proc
    try:
        parameters = parameters or {}
        action = (parameters.get("action") or "open").strip().lower()

        if action == "close":
            _queue({"cmd": "close"})
            if _proc is not None:
                try:
                    threading.Timer(1.5, _proc.terminate).start()
                except Exception:
                    pass
            msg = "Closing the Earth view, sir."

        elif action == "reset":
            _queue({"cmd": "reset"})
            msg = "Zooming back out, sir."

        elif action in ("open", "fly_to"):
            target = _target(parameters)
            if target and target[0] == "notfound":
                return f"Sir, I couldn't find {target[1]} on the map."
            port = _ensure_server()
            opened_fresh = action == "open"
            if opened_fresh:
                with _lock:
                    _cmd["cmd"] = None
                _launch(f"http://127.0.0.1:{port}/")
            if target:
                lat, lon, height, label = target
                _queue({"cmd": "flyTo", "lat": lat, "lon": lon, "height": height})
                msg = (f"Showing the Earth and zooming to {label}, sir."
                       if opened_fresh else f"Zooming to {label}, sir.")
            else:
                msg = "Displaying the Earth in 3D satellite view, sir."
        else:
            return "Sir, I didn't recognise that Earth command. Try open, fly to, reset or close."

    except Exception as e:
        return f"Sir, the Earth viewer failed: {e}"

    if player:
        try:
            player.write_log(f"JARVIS: {msg}")
        except Exception:
            pass
    return msg
