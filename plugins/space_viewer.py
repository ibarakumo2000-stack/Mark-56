"""
JARVIS plugin: space_viewer  (replaces earth_viewer.py -- delete that file)

An interactive 3D Earth, Moon, Mars and Solar System shown INSIDE the JARVIS window, in the
same panel where the avatar / camera / video appear. No browser window is opened.

  Earth   : streamed satellite imagery (Esri + NASA GIBS), rotate, zoom to street level.
  Moon    : NASA LRO imagery.        Mars : NASA Viking imagery.
  Solar system : live planet positions (Keplerian orbital elements) you can rotate and zoom.
  Overlays on Earth: live ISS position + trail, live earthquakes (USGS), rain (NASA IMERG).

Requirements
  pip install PyQt6-WebEngine
  ui.py needs the small startup patch shipped with this plugin (QtWebEngine must be imported
  before the QApplication is created). Needs internet for tiles and live data.

Optional true-3D (terrain / buildings / photorealistic cities): put
  {"cesium_ion_token": "...", "google_maps_key": "..."}  in ~/.jarvis_earth.json
or set JARVIS_CESIUM_TOKEN / JARVIS_GOOGLE_MAPS_KEY.
"""
import json
import os
import sys
import threading
import time
import types
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PLUGIN = {
    "name": "space_viewer",
    "description": (
        "Shows an interactive 3D globe INSIDE the JARVIS interface that the user can rotate and zoom "
        "without quality loss. Use for ANY request to display/show/open the Earth, the globe, the Moon, "
        "Mars, the solar system or planets; to zoom into or fly to a place ('zoom into Lagos', 'show "
        "the Eiffel Tower from space'); to show the International Space Station / ISS (live position, "
        "track or follow it); to show live earthquakes; to show rain / weather; or to close/reset the "
        "view. action: open (default), fly_to, overlay, track_iss, reset, close. body: earth, moon, "
        "mars, solar_system. overlay: iss, earthquakes, rain, clouds (set enabled=false to hide). "
        "For the solar system, 'location' can be a planet name to focus on. "
        "Do NOT use web search, image search or a browser for these requests; use this tool."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "open, fly_to, overlay, track_iss, reset or close. Default open."},
            "body": {"type": "STRING", "description": "earth (default), moon, mars or solar_system."},
            "location": {"type": "STRING", "description": "Place name to zoom to (Earth), a crater/landmark (Moon/Mars) or a planet (solar system)."},
            "latitude": {"type": "NUMBER", "description": "Optional latitude in degrees."},
            "longitude": {"type": "NUMBER", "description": "Optional longitude in degrees."},
            "altitude_km": {"type": "NUMBER", "description": "Optional camera height above the surface in km."},
            "overlay": {"type": "STRING", "description": "iss, earthquakes, rain or clouds."},
            "enabled": {"type": "BOOLEAN", "description": "With overlay: true to show (default), false to hide."},
            "time_speed": {"type": "NUMBER", "description": "Solar system only: simulated days per second (0 pauses, default 5)."},
        },
        "required": [],
    },
}

# --------------------------------------------------------------------------------------
# The page (CesiumJS globe + canvas solar system). Served from a localhost-only server.
# --------------------------------------------------------------------------------------
_HTML = r'''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Space</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{--pri:#00d4ff}
html,body{margin:0;height:100%;background:#00060a;overflow:hidden;font-family:"Courier New",monospace}
#globe,#orrery{position:absolute;left:0;top:0;width:100%;height:100%}
#orrery{display:none;cursor:grab;touch-action:none}
.cesium-widget-credits{opacity:.5}
#hud{position:fixed;left:12px;bottom:12px;padding:8px 12px;border:1px solid var(--pri);border-color:color-mix(in srgb,var(--pri) 40%,transparent);
 background:rgba(0,6,10,.68);color:#bfefff;font-size:12px;line-height:1.55;border-radius:4px;pointer-events:none;max-width:70%}
#hud b{color:#fff}
#st{color:#ffcc00}
#err{display:none;position:fixed;left:0;top:0;right:0;padding:24px;color:#ffb4a8;background:#00060a;font-size:14px;line-height:1.6;z-index:10}
</style></head><body>
<div id="globe"></div><canvas id="orrery"></canvas>
<div id="hud"><span id="title">SPACE</span><span id="altwrap"> &middot; altitude <b id="alt">--</b></span><br>
<span id="live"></span><span id="st"></span></div>
<div id="err"></div>
<script>
(function () {
'use strict';
const CFG = __CONFIG__;
const $ = (id) => document.getElementById(id);
if (CFG.accent) document.documentElement.style.setProperty('--pri', CFG.accent);
let cesiumOK = false, stT = 0;
function status(m) { $('st').textContent = m || ''; }
function flash(m, ms) { status(m); clearTimeout(stT); stT = setTimeout(() => status(''), ms || 7000); }
function fail(m) { const e = $('err'); e.style.display = 'block'; e.textContent = m; console.error(m); }

/* ============================ SOLAR SYSTEM (no external libs) ============================ */
const Orrery = (function () {
  const cv = $('orrery'), ctx = cv.getContext('2d');
  const RAD = Math.PI / 180;
  // JPL approximate Keplerian elements, 1800-2050: [a, e, I, L, long.peri, long.node] and rates per century
  const PL = [
    { n: 'Mercury', c: '#b9b9b9', s: 3, e: [0.38709927, 0.20563593, 7.00497902, 252.25032350, 77.45779628, 48.33076593], r: [0.00000037, 0.00001906, -0.00594749, 149472.67411175, 0.16047689, -0.12534081] },
    { n: 'Venus', c: '#e8cf93', s: 5, e: [0.72333566, 0.00677672, 3.39467605, 181.97909950, 131.60246718, 76.67984255], r: [0.00000390, -0.00004107, -0.00078890, 58517.81538729, 0.00268329, -0.27769418] },
    { n: 'Earth', c: '#4da3ff', s: 5, e: [1.00000261, 0.01671123, -0.00001531, 100.46457166, 102.93768193, 0.0], r: [0.00000562, -0.00004392, -0.01294668, 35999.37244981, 0.32327364, 0.0] },
    { n: 'Mars', c: '#ff7a4d', s: 4, e: [1.52371034, 0.09339410, 1.84969142, -4.55343205, -23.94362959, 49.55953891], r: [0.00001847, 0.00007882, -0.00813131, 19140.30268499, 0.44441088, -0.29257343] },
    { n: 'Jupiter', c: '#e3b784', s: 11, e: [5.20288700, 0.04838624, 1.30439695, 34.39644051, 14.72847983, 100.47390909], r: [-0.00011607, -0.00013253, -0.00183714, 3034.74612775, 0.21252668, 0.20469106] },
    { n: 'Saturn', c: '#ead9a0', s: 9, ring: true, e: [9.53667594, 0.05386179, 2.48599187, 49.95424423, 92.59887831, 113.66242448], r: [-0.00125060, -0.00050991, 0.00193609, 1222.49362201, -0.41897216, -0.28867794] },
    { n: 'Uranus', c: '#9be3e6', s: 7, e: [19.18916464, 0.04725744, 0.77263783, 313.23810451, 170.95427630, 74.01692503], r: [-0.00196176, -0.00004397, -0.00242939, 428.48202785, 0.40805281, 0.04240589] },
    { n: 'Neptune', c: '#5a7bff', s: 7, e: [30.06992276, 0.00859048, 1.77004347, -55.12002969, 44.96476227, 131.78422574], r: [0.00026291, 0.00005105, 0.00035372, 218.45945325, -0.32241464, -0.00508664] }
  ];
  function elAt(p, T) { return p.e.map((v, i) => v + p.r[i] * T); }
  function solveE(el) {
    const e = el[1]; let M = ((el[3] - el[4]) % 360 + 540) % 360 - 180; M *= RAD;
    let E = M + e * Math.sin(M);
    for (let k = 0; k < 15; k++) { const d = (M - (E - e * Math.sin(E))) / (1 - e * Math.cos(E)); E += d; if (Math.abs(d) < 1e-10) break; }
    return E;
  }
  function xyz(el, E) {
    const a = el[0], e = el[1], i = el[2] * RAD, O = el[5] * RAD, w = (el[4] - el[5]) * RAD;
    const xp = a * (Math.cos(E) - e), yp = a * Math.sqrt(1 - e * e) * Math.sin(E);
    const cw = Math.cos(w), sw = Math.sin(w), cO = Math.cos(O), sO = Math.sin(O), ci = Math.cos(i), si = Math.sin(i);
    return [(cw * cO - sw * sO * ci) * xp + (-sw * cO - cw * sO * ci) * yp,
            (cw * sO + sw * cO * ci) * xp + (-sw * sO + cw * cO * ci) * yp,
            (sw * si) * xp + (cw * si) * yp];
  }
  function comp(v) { const r = Math.hypot(v[0], v[1], v[2]); if (r < 1e-9) return [0, 0, 0]; const k = Math.pow(r, 0.55) / r; return [v[0] * k, v[1] * k, v[2] * k]; }

  let on = false, raf = 0, yaw = 0.6, tilt = 0.85, zoom = 1, speed = 5, simDays = 0, last = 0, focus = -1;
  let drag = false, px = 0, py = 0, W = 0, H = 0;
  const stars = [], belt = [];
  let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  for (let i = 0; i < 260; i++) stars.push([rnd(), rnd(), 0.4 + rnd() * 1.1, 0.25 + rnd() * 0.6]);
  for (let i = 0; i < 700; i++) { const a = rnd() * Math.PI * 2, r = 2.1 + rnd() * 1.2; belt.push([Math.cos(a) * r, Math.sin(a) * r, (rnd() - 0.5) * 0.25]); }

  function resize() {
    const d = Math.min(window.devicePixelRatio || 1, 2); W = cv.clientWidth || 800; H = cv.clientHeight || 600;
    cv.width = Math.round(W * d); cv.height = Math.round(H * d); ctx.setTransform(d, 0, 0, d, 0, 0);
  }
  function dateNow() { return new Date(Date.now() + simDays * 864e5); }
  function project(v, off, u) {
    const x = v[0] - off[0], y = v[1] - off[1], z = v[2] - off[2];
    const cy = Math.cos(yaw), sy = Math.sin(yaw), x1 = x * cy - y * sy, y1 = x * sy + y * cy;
    const ct = Math.cos(tilt), st = Math.sin(tilt);
    const depth = y1 * st - z * ct, f = 1 / (1 + depth * 0.035);
    return [W / 2 + x1 * u * f, H / 2 - (y1 * ct + z * st) * u * f, depth, f];
  }
  function draw() {
    const d = dateNow(), jd = d.getTime() / 864e5 + 2440587.5, T = (jd - 2451545) / 36525;
    const u = 0.46 * Math.min(W, H) / Math.pow(32, 0.55) * zoom;
    ctx.fillStyle = '#00060a'; ctx.fillRect(0, 0, W, H);
    for (const s of stars) { ctx.globalAlpha = s[3]; ctx.fillStyle = '#cfefff'; ctx.fillRect(s[0] * W, s[1] * H, s[2], s[2]); }
    ctx.globalAlpha = 1;
    const els = PL.map(p => elAt(p, T)), pos = els.map(el => xyz(el, solveE(el))), cp = pos.map(comp);
    const off = focus >= 0 ? cp[focus] : [0, 0, 0];
    ctx.fillStyle = '#7a6a55';
    for (const b of belt) { const q = project(comp(b), off, u); ctx.globalAlpha = 0.5; ctx.fillRect(q[0], q[1], 1.2, 1.2); }
    ctx.globalAlpha = 1; ctx.lineWidth = 1;
    PL.forEach((p, i) => {
      ctx.strokeStyle = 'rgba(0,212,255,0.22)'; ctx.beginPath();
      for (let k = 0; k <= 180; k++) { const q = project(comp(xyz(els[i], k / 180 * Math.PI * 2)), off, u); k ? ctx.lineTo(q[0], q[1]) : ctx.moveTo(q[0], q[1]); }
      ctx.stroke();
    });
    const sun = project([0, 0, 0], off, u), gr = ctx.createRadialGradient(sun[0], sun[1], 0, sun[0], sun[1], 46);
    gr.addColorStop(0, 'rgba(255,240,170,1)'); gr.addColorStop(0.25, 'rgba(255,190,70,0.55)'); gr.addColorStop(1, 'rgba(255,150,0,0)');
    ctx.fillStyle = gr; ctx.beginPath(); ctx.arc(sun[0], sun[1], 46, 0, 7); ctx.fill();
    ctx.fillStyle = '#fff4c2'; ctx.beginPath(); ctx.arc(sun[0], sun[1], 7, 0, 7); ctx.fill();
    const order = PL.map((p, i) => [i, project(cp[i], off, u)]).sort((a, b) => b[1][2] - a[1][2]);
    ctx.font = '11px "Courier New", monospace';
    for (const [i, q] of order) {
      const p = PL[i], rad = p.s * (0.8 + 0.2 * q[3]) * Math.min(zoom, 3) ** 0.35;
      if (p.ring) { ctx.strokeStyle = 'rgba(234,217,160,0.7)'; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.ellipse(q[0], q[1], rad * 2, rad * 0.7, -0.35, 0, 7); ctx.stroke(); }
      ctx.fillStyle = p.c; ctx.beginPath(); ctx.arc(q[0], q[1], rad, 0, 7); ctx.fill();
      ctx.fillStyle = i === focus ? '#ffffff' : '#9fe8ff';
      ctx.fillText(p.n + '  ' + Math.hypot(pos[i][0], pos[i][1], pos[i][2]).toFixed(2) + ' AU', q[0] + rad + 6, q[1] + 4);
    }
    $('live').textContent = 'Date ' + d.toISOString().slice(0, 10) + '  \u00b7  ' + (speed === 0 ? 'paused' : speed + ' days/s') + '  \u00b7  drag to rotate, scroll to zoom, double-click to reset  ';
  }
  function frame(ts) {
    if (!on) return; raf = requestAnimationFrame(frame);
    const dt = last ? Math.min((ts - last) / 1000, 0.1) : 0; last = ts; simDays += dt * speed; draw();
  }
  cv.addEventListener('pointerdown', (e) => { drag = true; px = e.clientX; py = e.clientY; cv.style.cursor = 'grabbing'; try { cv.setPointerCapture(e.pointerId); } catch (x) {} });
  cv.addEventListener('pointermove', (e) => { if (!drag) return; yaw += (e.clientX - px) * 0.007; tilt = Math.max(0, Math.min(1.5, tilt + (e.clientY - py) * 0.006)); px = e.clientX; py = e.clientY; });
  cv.addEventListener('pointerup', () => { drag = false; cv.style.cursor = 'grab'; });
  cv.addEventListener('wheel', (e) => { e.preventDefault(); zoom = Math.max(0.35, Math.min(60, zoom * Math.exp(-e.deltaY * 0.0015))); }, { passive: false });
  cv.addEventListener('dblclick', () => { yaw = 0.6; tilt = 0.85; zoom = 1; focus = -1; });
  window.addEventListener('resize', () => { if (on) resize(); });
  return {
    start() { on = true; cv.style.display = 'block'; resize(); last = 0; cancelAnimationFrame(raf); raf = requestAnimationFrame(frame); },
    stop() { on = false; cancelAnimationFrame(raf); cv.style.display = 'none'; },
    setSpeed(v) { const n = Number(v); speed = isFinite(n) ? n : 5; },
    focusOn(name) {
      const i = PL.findIndex(p => p.n.toLowerCase() === String(name || '').toLowerCase());
      if (i < 0) { focus = -1; zoom = 1; return false; } focus = i; zoom = i < 4 ? 14 : 4; return true;
    },
    reset() { yaw = 0.6; tilt = 0.85; zoom = 1; focus = -1; },
    _test: { elAt, solveE, xyz, PL }
  };
})();
window.__Orrery = Orrery;

/* ================================= GLOBE (CesiumJS) ================================= */
const BASES = ['https://cdn.jsdelivr.net/npm/cesium@1.120.0/Build/Cesium/', 'https://unpkg.com/cesium@1.120.0/Build/Cesium/', 'https://cdn.jsdelivr.net/npm/cesium@1.115.0/Build/Cesium/'];
function load(i) {
  if (i >= BASES.length) { cesiumOK = false; boot(); return; }
  window.CESIUM_BASE_URL = BASES[i];
  const css = document.createElement('link'); css.rel = 'stylesheet'; css.href = BASES[i] + 'Widgets/widgets.css'; document.head.appendChild(css);
  const sc = document.createElement('script'); sc.src = BASES[i] + 'Cesium.js';
  sc.onload = () => { cesiumOK = !!window.Cesium; boot(); };
  sc.onerror = () => load(i + 1);
  document.head.appendChild(sc);
}

let viewer = null, cur = null, spin = true, seq = 0, followIss = false;
const want = { iss: false, earthquakes: false, rain: false, clouds: true };
let issDS = null, quakeDS = null, rainLayer = null, liveLayer = null, issPos = null, issEnt = null, lastIssTs = 0, issLine = '', quakeLine = '', lastErr = 0;
const BODIES = {
  earth: { name: 'EARTH', h: 2.2e7, min: 2 },
  moon: { name: 'MOON', h: 7e6, min: 300, max: 7, credit: 'NASA/GSFC/ASU LRO WAC',
          url: 'https://trek.nasa.gov/tiles/Moon/EQ/LRO_WAC_Mosaic_Global_303ppd_v02/1.0.0/default/default028mm/{z}/{y}/{x}.jpg' },
  mars: { name: 'MARS', h: 1.2e7, min: 300, max: 7, credit: 'NASA/JPL Viking MDIM',
          url: 'https://trek.nasa.gov/tiles/Mars/EQ/Mars_Viking_MDIM21_ClrMosaic_global_232m/1.0.0/default/default028mm/{z}/{y}/{x}.jpg' }
};
function ellipsoidOf(b) {
  const C = window.Cesium;
  if (b === 'moon') return C.Ellipsoid.MOON || new C.Ellipsoid(1737400, 1737400, 1737400);
  if (b === 'mars') return C.Ellipsoid.MARS || new C.Ellipsoid(3396190, 3396190, 3376200);
  return C.Ellipsoid.WGS84;
}
function destroyViewer() {
  if (viewer) { try { viewer.destroy(); } catch (e) {} }
  viewer = null; issDS = quakeDS = rainLayer = liveLayer = issPos = issEnt = null; lastIssTs = 0; followIss = false;
}
function addTiles(url, max, credit, quiet, extra) {
  const C = window.Cesium;
  const prov = new C.UrlTemplateImageryProvider(Object.assign({ url: url, maximumLevel: max, credit: credit }, extra || {}));
  prov.errorEvent.addEventListener((e) => { e.retry = false; if (!quiet && Date.now() - lastErr > 8000) { lastErr = Date.now(); flash('Some ' + credit + ' tiles could not load'); } });
  return viewer.imageryLayers.addImageryProvider(prov);
}
function makeViewer(b) {
  const C = window.Cesium, B = BODIES[b], ell = ellipsoidOf(b);
  destroyViewer();
  const opt = { baseLayer: false, baseLayerPicker: false, geocoder: false, homeButton: false, sceneModePicker: false, navigationHelpButton: false,
                animation: false, timeline: false, fullscreenButton: false, infoBox: false, selectionIndicator: false, scene3DOnly: true };
  if (b !== 'earth') { opt.globe = new C.Globe(ell); opt.mapProjection = new C.GeographicProjection(ell); opt.skyAtmosphere = false; }
  viewer = new C.Viewer('globe', opt);
  const scene = viewer.scene, globe = scene.globe, cam = viewer.camera;
  viewer.useBrowserRecommendedResolution = false;
  viewer.resolutionScale = Math.min(window.devicePixelRatio || 1, 2);
  scene.msaaSamples = 4; scene.fog.enabled = (b === 'earth');
  globe.maximumScreenSpaceError = 0.75; globe.tileCacheSize = 2500; globe.preloadSiblings = true;
  globe.enableLighting = false; globe.showGroundAtmosphere = (b === 'earth');
  globe.baseColor = C.Color.fromCssColorString('#0a0f18');
  if (b !== 'earth') { if (scene.sun) scene.sun.show = false; if (scene.moon) scene.moon.show = false; }
  viewer.clock.shouldAnimate = true; viewer.clock.clockRange = C.ClockRange.UNBOUNDED;
  const ctl = scene.screenSpaceCameraController;
  ctl.minimumZoomDistance = B.min; ctl.maximumZoomDistance = B.h * 3; ctl.enableCollisionDetection = true; ctl.inertiaZoom = 0.8;
  spin = true;
  ['pointerdown', 'wheel', 'touchstart', 'keydown'].forEach(ev => viewer.canvas.addEventListener(ev, () => { spin = false; }, { passive: true }));
  if (b === 'earth') {
    addTiles('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', 19, 'Esri World Imagery', false);
    addTiles('https://clarity.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', 19, 'Esri Clarity', true);
    const d = new Date(Date.now() - 24 * 3600 * 1000).toISOString().slice(0, 10);
    liveLayer = addTiles('https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_SNPP_CorrectedReflectance_TrueColor/default/' + d + '/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg', 9, 'NASA GIBS VIIRS ' + d, true);
    rainLayer = addTiles('https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/IMERG_Precipitation_Rate/default/default/GoogleMapsCompatible_Level6/{z}/{y}/{x}.png', 6, 'NASA IMERG rain', false);
    rainLayer.alpha = 0.85; rainLayer.show = false;
    issDS = new C.CustomDataSource('iss'); quakeDS = new C.CustomDataSource('quakes');
    viewer.dataSources.add(issDS); viewer.dataSources.add(quakeDS); issDS.show = false; quakeDS.show = false;
    initIss();
    if (CFG.ion) {
      C.Ion.defaultAccessToken = CFG.ion;
      C.createWorldTerrainAsync({ requestVertexNormals: true }).then(t => { if (viewer) { viewer.terrainProvider = t; globe.depthTestAgainstTerrain = true; } }).catch(e => console.warn('terrain', e));
      C.createOsmBuildingsAsync().then(bl => { if (viewer) scene.primitives.add(bl); }).catch(e => console.warn('buildings', e));
    }
    if (CFG.google) {
      let g3d = null;
      C.Cesium3DTileset.fromUrl('https://tile.googleapis.com/v1/3dtiles/root.json?key=' + encodeURIComponent(CFG.google), { showCreditsOnScreen: true, maximumScreenSpaceError: 8 })
        .then(ts => { if (viewer) { g3d = ts; scene.primitives.add(ts); } }).catch(e => console.warn('google 3d', e));
      scene.preRender.addEventListener(() => { if (!g3d) return; const near = cam.positionCartographic.height < 2.5e6; g3d.show = near; globe.show = !near; });
    }
  } else {
    addTiles(B.url, B.max, B.credit, false, { tilingScheme: new C.GeographicTilingScheme({ ellipsoid: ell }) });
  }
  scene.preRender.addEventListener(() => {
    const h = cam.positionCartographic.height;
    if (spin && !viewer.trackedEntity) cam.rotate(C.Cartesian3.UNIT_Z, 0.0008);
    if (liveLayer) liveLayer.alpha = want.clouds ? Math.min(1, Math.max(0, (h - 1.0e6) / 2.0e6)) : 0;
  });
  let lastTxt = '';
  scene.postRender.addEventListener(() => {
    const h = cam.positionCartographic.height;
    const t = h >= 1000 ? (h / 1000).toFixed(h > 1e5 ? 0 : 1) + ' km' : Math.round(h) + ' m';
    if (t !== lastTxt) { lastTxt = t; $('alt').textContent = t; }
  });
  cam.setView({ destination: C.Cartesian3.fromDegrees(10, 15, B.h, ell) });
}

function initIss() {
  const C = window.Cesium;
  issPos = new C.SampledPositionProperty();
  issPos.setInterpolationOptions({ interpolationDegree: 1, interpolationAlgorithm: C.LinearApproximation });
  issPos.forwardExtrapolationType = C.ExtrapolationType.EXTRAPOLATE; issPos.forwardExtrapolationDuration = 40;
  issPos.backwardExtrapolationType = C.ExtrapolationType.HOLD;
  issEnt = issDS.entities.add({
    position: issPos,
    point: { pixelSize: 11, color: C.Color.fromCssColorString('#00ff88'), outlineColor: C.Color.WHITE, outlineWidth: 2 },
    label: { text: 'ISS', font: 'bold 14px Courier New', fillColor: C.Color.WHITE, outlineColor: C.Color.BLACK, outlineWidth: 3,
             style: C.LabelStyle.FILL_AND_OUTLINE, pixelOffset: new C.Cartesian2(0, -22) },
    path: { resolution: 5, trailTime: 2700, leadTime: 0, width: 2, material: new C.PolylineGlowMaterialProperty({ glowPower: 0.25, color: C.Color.fromCssColorString('#00ff88') }) }
  });
}
async function pollIss() {
  if (!viewer || cur !== 'earth' || !want.iss) return;
  try {
    const d = await (await fetch('/api/iss', { cache: 'no-store' })).json();
    if (!d || d.error) { flash('ISS data unavailable right now'); return; }
    if (d.ts > lastIssTs && issPos) { lastIssTs = d.ts; issPos.addSample(window.Cesium.JulianDate.fromDate(new Date(d.ts * 1000)), window.Cesium.Cartesian3.fromDegrees(d.lon, d.lat, d.alt * 1000)); }
    issLine = 'ISS  ' + Math.round(d.alt) + ' km up, ' + Math.round(d.vel).toLocaleString() + ' km/h, ' + Math.abs(d.lat).toFixed(1) + (d.lat >= 0 ? 'N ' : 'S ') + Math.abs(d.lon).toFixed(1) + (d.lon >= 0 ? 'E' : 'W') + '   ';
    renderLive();
  } catch (e) { flash('ISS data unavailable right now'); }
}
function colorFor(m) { const C = window.Cesium; return m >= 5 ? C.Color.fromCssColorString('#ff3355') : m >= 4 ? C.Color.fromCssColorString('#ff8c1a') : C.Color.fromCssColorString('#ffd23f'); }
async function pollQuakes() {
  if (!viewer || cur !== 'earth' || !want.earthquakes) return;
  try {
    const g = await (await fetch('/api/quakes', { cache: 'no-store' })).json();
    if (!g || !g.quakes) { flash('Earthquake feed unavailable right now'); return; }
    const C = window.Cesium; quakeDS.entities.suspendEvents(); quakeDS.entities.removeAll();
    for (const q of g.quakes) {
      const ent = { position: C.Cartesian3.fromDegrees(q.lon, q.lat, 1000),
        point: { pixelSize: Math.max(5, q.m * 3), color: colorFor(q.m).withAlpha(0.8), outlineColor: C.Color.WHITE.withAlpha(0.6), outlineWidth: 1 } };
      if (q.m >= 5) ent.label = { text: 'M' + q.m.toFixed(1) + '  ' + q.place, font: '13px Courier New', fillColor: C.Color.WHITE, outlineColor: C.Color.BLACK, outlineWidth: 3,
                                  style: C.LabelStyle.FILL_AND_OUTLINE, pixelOffset: new C.Cartesian2(0, -18), distanceDisplayCondition: new C.DistanceDisplayCondition(0, 2.6e7) };
      quakeDS.entities.add(ent);
    }
    quakeDS.entities.resumeEvents();
    quakeLine = g.count + ' quakes M2.5+ in 24h' + (g.top ? ', strongest M' + g.top.m.toFixed(1) + ' ' + g.top.place : '') + '   ';
    renderLive();
  } catch (e) { flash('Earthquake feed unavailable right now'); }
}
function renderLive() { $('live').textContent = (want.iss ? issLine : '') + (want.earthquakes ? quakeLine : ''); if (cur === 'earth' && !(want.iss || want.earthquakes)) $('live').textContent = ''; }

function stopFollow() { followIss = false; if (viewer) { try { viewer.trackedEntity = undefined; } catch (e) {} } }
function startFollow(tries) {
  if (!viewer || cur !== 'earth' || !issEnt) return;
  followIss = true; spin = false;
  if (lastIssTs === 0) { if ((tries || 0) < 14) setTimeout(() => startFollow((tries || 0) + 1), 700); else flash('ISS position not available yet'); return; }
  viewer.flyTo(issEnt, { duration: 3, offset: new window.Cesium.HeadingPitchRange(0, -1.4, 2.5e6) }).then((ok) => { if (ok && followIss && viewer) viewer.trackedEntity = issEnt; });
}
function setOverlay(name, on) {
  want[name] = !!on;
  if (cur !== 'earth' || !viewer) return;
  if (name === 'iss') { issDS.show = want.iss; if (want.iss) pollIss(); else stopFollow(); }
  else if (name === 'earthquakes') { quakeDS.show = want.earthquakes; if (want.earthquakes) pollQuakes(); }
  else if (name === 'rain') { rainLayer.show = want.rain; }
  renderLive();
}
function flyTo(lat, lon, h) {
  if (!viewer) return; stopFollow(); spin = false;
  viewer.camera.flyTo({ destination: window.Cesium.Cartesian3.fromDegrees(lon, lat, h || 5000, viewer.scene.globe.ellipsoid), duration: 3 });
}
function setBody(b) {
  stopFollow();
  if (b === 'solar') {
    destroyViewer(); cur = 'solar'; $('globe').style.display = 'none'; $('altwrap').style.display = 'none';
    $('title').textContent = 'SOLAR SYSTEM'; $('live').textContent = ''; Orrery.start(); return;
  }
  Orrery.stop(); $('globe').style.display = 'block'; $('altwrap').style.display = '';
  if (!cesiumOK) { cur = null; fail('The map engine could not be downloaded. Check the internet connection.'); return; }
  if (cur !== b || !viewer) { try { makeViewer(b); } catch (e) { fail('Could not start the 3D view: ' + (e && e.message || e)); return; } }
  cur = b; $('title').textContent = BODIES[b].name; $('live').textContent = ''; status('');
  if (b === 'earth') { for (const k of ['iss', 'earthquakes', 'rain']) if (want[k]) setOverlay(k, true); }
  else if (b === 'moon' || b === 'mars') flash((b === 'moon' ? 'Lunar' : 'Martian') + ' imagery is lower resolution than Earth (data limit of the source)', 9000);
}
function apply(m) {
  try {
    switch (m.cmd) {
      case 'body': setBody(m.body); break;
      case 'flyTo': if (cur === 'solar') Orrery.focusOn(m.planet); else flyTo(m.lat, m.lon, m.height); break;
      case 'reset':
        if (cur === 'solar') Orrery.reset();
        else if (viewer) { stopFollow(); viewer.camera.flyTo({ destination: window.Cesium.Cartesian3.fromDegrees(10, 15, BODIES[cur].h, viewer.scene.globe.ellipsoid), duration: 2 }); }
        break;
      case 'overlay': setOverlay(m.name, m.on); break;
      case 'follow': startFollow(0); break;
      case 'focus': Orrery.focusOn(m.planet); break;
      case 'speed': Orrery.setSpeed(m.value); break;
    }
  } catch (e) { console.error(e); flash('Command failed: ' + (e && e.message || e)); }
}
async function poll() {
  try {
    const r = await (await fetch('/cmd?since=' + seq, { cache: 'no-store' })).json();
    for (const c of r.cmds) { seq = Math.max(seq, c.id); apply(c); }
  } catch (e) { /* server gone */ }
}
function boot() {
  poll().then(() => { if (!cur) setBody('earth'); });
  setInterval(poll, 700);
  setInterval(pollIss, 5000);
  setInterval(pollQuakes, 120000);
}
window.__space = { apply, setBody, Orrery };
load(0);
})();
</script></body></html>'''

# --------------------------------------------------------------------------------------
# Local data/command server (127.0.0.1 only)
# --------------------------------------------------------------------------------------
_lock = threading.Lock()
_server = None
_port = None
_seq = 0
_cmds = []
_cache = {}
_S = {"cont": None, "view": None, "lbl": None, "win": None, "body": "earth"}
_bridge = None


def _config():
    cfg = {"ion": os.environ.get("JARVIS_CESIUM_TOKEN", ""), "google": os.environ.get("JARVIS_GOOGLE_MAPS_KEY", ""), "accent": ""}
    try:
        with open(os.path.join(os.path.expanduser("~"), ".jarvis_earth.json"), encoding="utf-8") as f:
            data = json.load(f)
        cfg["ion"] = cfg["ion"] or data.get("cesium_ion_token", "")
        cfg["google"] = cfg["google"] or data.get("google_maps_key", "")
    except Exception:
        pass
    cfg["accent"] = _palette()[1]
    return cfg


def _palette():
    """(bg, primary, dim, text-dim) taken from the running JARVIS UI so the panel matches its theme."""
    for name in ("ui", "__main__"):
        C = getattr(sys.modules.get(name), "C", None)
        if C is not None and hasattr(C, "PRI"):
            try:
                return C.BG, C.PRI, C.PRI_DIM, C.TEXT_DIM
            except Exception:
                pass
    return "#00060a", "#00d4ff", "#007a99", "#3a8a9a"


def _http_json(url, timeout=6):
    req = urllib.request.Request(url, headers={"User-Agent": "JARVIS-SpaceViewer/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _cached(key, ttl, fn):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (now, val)
    return val


def _iss_now():
    def fetch():
        try:
            d = _http_json("https://api.wheretheiss.at/v1/satellites/25544")
            return {"lat": float(d["latitude"]), "lon": float(d["longitude"]), "alt": float(d["altitude"]),
                    "vel": float(d["velocity"]), "ts": int(d["timestamp"])}
        except Exception:
            d = _http_json("http://api.open-notify.org/iss-now.json")
            p = d["iss_position"]
            return {"lat": float(p["latitude"]), "lon": float(p["longitude"]), "alt": 420.0, "vel": 27600.0, "ts": int(d["timestamp"])}
    try:
        return _cached("iss", 2.0, fetch)
    except Exception:
        return {"error": "unavailable"}


def _quakes_now():
    def fetch():
        g = _http_json("https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson", timeout=8)
        out = []
        for f in g.get("features", []):
            try:
                c = f["geometry"]["coordinates"]
                m = f["properties"].get("mag")
                if m is None:
                    continue
                out.append({"m": float(m), "lon": float(c[0]), "lat": float(c[1]), "place": str(f["properties"].get("place") or "unknown")})
            except Exception:
                continue
        out.sort(key=lambda q: -q["m"])
        return {"quakes": out, "count": len(out), "top": out[0] if out else None}
    try:
        return _cached("quakes", 120.0, fetch)
    except Exception:
        return {"error": "unavailable"}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
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
        u = urllib.parse.urlparse(self.path)
        try:
            if u.path in ("/", "/index.html"):
                self._send(_HTML.replace("__CONFIG__", json.dumps(_config())), "text/html; charset=utf-8")
            elif u.path == "/cmd":
                since = int((urllib.parse.parse_qs(u.query).get("since") or ["0"])[0])
                with _lock:
                    payload = {"cmds": [c for c in _cmds if c["id"] > since], "seq": _seq}
                self._send(json.dumps(payload), "application/json")
            elif u.path == "/api/iss":
                self._send(json.dumps(_iss_now()), "application/json")
            elif u.path == "/api/quakes":
                self._send(json.dumps(_quakes_now()), "application/json")
            else:
                self.send_response(404)
                self.end_headers()
        except Exception:
            try:
                self.send_response(500)
                self.end_headers()
            except Exception:
                pass


def _ensure_server():
    global _server, _port
    with _lock:
        if _server is None:
            _server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
            _port = _server.server_address[1]
            threading.Thread(target=_server.serve_forever, daemon=True).start()
    return _port


def _push(cmd):
    global _seq
    with _lock:
        _seq += 1
        cmd = dict(cmd)
        cmd["id"] = _seq
        _cmds.append(cmd)
        del _cmds[:-200]


def _reset_cmds():
    with _lock:
        _cmds.clear()


# --------------------------------------------------------------------------------------
# Qt side: embeds the page in JARVIS's HUD stack (needs PyQt6-WebEngine)
# --------------------------------------------------------------------------------------
class _NoWebEngine(Exception):
    pass


def _qt():
    try:
        from PyQt6 import QtCore, QtGui, QtWidgets
        from PyQt6.QtWebEngineCore import QWebEngineSettings
        from PyQt6.QtWebEngineWidgets import QWebEngineView
    except Exception as exc:
        raise _NoWebEngine(str(exc))
    return types.SimpleNamespace(
        QObject=QtCore.QObject, QThread=QtCore.QThread, QTimer=QtCore.QTimer, QUrl=QtCore.QUrl, Qt=QtCore.Qt,
        pyqtSignal=QtCore.pyqtSignal, pyqtSlot=QtCore.pyqtSlot, QColor=QtGui.QColor, QFont=QtGui.QFont,
        QApplication=QtWidgets.QApplication, QHBoxLayout=QtWidgets.QHBoxLayout, QLabel=QtWidgets.QLabel,
        QPushButton=QtWidgets.QPushButton, QVBoxLayout=QtWidgets.QVBoxLayout, QWidget=QtWidgets.QWidget,
        QWebEngineSettings=QWebEngineSettings, QWebEngineView=QWebEngineView)


def _get_bridge(q):
    global _bridge
    if _bridge is None:
        class Bridge(q.QObject):
            call = q.pyqtSignal(object)

            @q.pyqtSlot(object)
            def invoke(self, fn):
                try:
                    fn()
                except Exception:
                    pass
        b = Bridge()
        b.moveToThread(q.QApplication.instance().thread())
        b.call.connect(b.invoke)
        _bridge = b
    return _bridge


def _on_main(q, fn, timeout=15.0):
    app = q.QApplication.instance()
    if app is None:
        raise RuntimeError("no Qt application")
    if q.QThread.currentThread() is app.thread():
        return fn()
    box, done = {}, threading.Event()

    def call():
        try:
            box["r"] = fn()
        except Exception as e:
            box["e"] = e
        finally:
            done.set()
    _get_bridge(q).call.emit(call)
    if not done.wait(timeout):
        raise TimeoutError("the interface did not respond")
    if "e" in box:
        raise box["e"]
    return box.get("r")


def _widget_alive():
    cont, win = _S["cont"], _S["win"]
    if cont is None or win is None:
        return False
    try:
        return win._hud_cam_stack.indexOf(cont) >= 0
    except Exception:
        return False


def _build_widget(q, win, url):
    bg, pri, dim, tdim = _palette()
    cont = q.QWidget()
    cont.setStyleSheet(f"background: {bg};")
    v = q.QVBoxLayout(cont)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(0)
    hdr = q.QHBoxLayout()
    hdr.setContentsMargins(8, 5, 8, 5)
    lbl = q.QLabel("\u25c8  EARTH")
    lbl.setFont(q.QFont("Courier New", 8, q.QFont.Weight.Bold))
    lbl.setStyleSheet(f"color: {pri}; background: transparent;")
    btn = q.QPushButton("\u2715  CLOSE")
    btn.setFont(q.QFont("Courier New", 8, q.QFont.Weight.Bold))
    btn.setCursor(q.Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(f"QPushButton {{ color: {tdim}; background: transparent; border: none; padding: 2px 6px; }}"
                      f"QPushButton:hover {{ color: {pri}; }}")
    hdr.addWidget(lbl)
    hdr.addStretch(1)
    hdr.addWidget(btn)
    v.addLayout(hdr)
    view = q.QWebEngineView(cont)
    s = view.settings()
    s.setAttribute(q.QWebEngineSettings.WebAttribute.WebGLEnabled, True)
    s.setAttribute(q.QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)
    view.setContextMenuPolicy(q.Qt.ContextMenuPolicy.NoContextMenu)
    page = view.page()
    page.setBackgroundColor(q.QColor(bg))
    page.renderProcessTerminated.connect(lambda *a: q.QTimer.singleShot(800, view.reload))
    view.setUrl(q.QUrl(url))
    v.addWidget(view, 1)
    stack = win._hud_cam_stack
    stack.addWidget(cont)
    stack.setCurrentWidget(cont)
    btn.clicked.connect(lambda *a: _close_main(q))
    _S.update(cont=cont, view=view, lbl=lbl, win=win)


def _show_main(q):
    _S["win"]._hud_cam_stack.setCurrentWidget(_S["cont"])


def _close_main(q):
    cont, win = _S["cont"], _S["win"]
    if cont is None or win is None:
        return
    try:
        stack = win._hud_cam_stack
        if stack.currentWidget() is cont:
            stack.setCurrentWidget(win.hud)
        stack.removeWidget(cont)
        cont.deleteLater()
    finally:
        _S.update(cont=None, view=None, lbl=None, body="earth")


# --------------------------------------------------------------------------------------
# Language helpers
# --------------------------------------------------------------------------------------
_BODY = {"earth": "earth", "globe": "earth", "world": "earth", "planet earth": "earth", "moon": "moon", "lunar": "moon",
         "mars": "mars", "red planet": "mars", "solar system": "solar", "solar_system": "solar", "solar": "solar",
         "planets": "solar", "orrery": "solar"}
_OVL = {"iss": "iss", "space station": "iss", "international space station": "iss", "earthquakes": "earthquakes",
        "earthquake": "earthquakes", "quakes": "earthquakes", "seismic": "earthquakes", "rain": "rain",
        "precipitation": "rain", "weather": "rain", "storms": "rain", "clouds": "clouds", "cloud": "clouds"}
_ACTIONS = {"open", "show", "display", "fly_to", "flyto", "zoom", "overlay", "track_iss", "follow_iss", "reset", "close", "hide"}
_SITES = {
    "moon": {"apollo 11": (0.67, 23.47), "tranquility": (0.67, 23.47), "apollo 17": (20.19, 30.77), "tycho": (-43.31, -11.36),
             "copernicus": (9.62, -20.08), "shackleton": (-89.9, 129.8), "south pole": (-89.9, 0.0), "north pole": (89.9, 0.0)},
    "mars": {"olympus mons": (18.65, -133.8), "valles marineris": (-14.0, -59.0), "jezero": (18.38, 77.58),
             "gale": (-5.4, 137.8), "hellas": (-42.7, 70.0), "south pole": (-89.9, 0.0), "north pole": (89.9, 0.0)},
}


def _norm(table, v):
    v = (v or "").strip().lower().replace("-", " ")
    if not v:
        return None
    if v in table:
        return table[v]
    for k, val in table.items():
        if k in v:
            return val
    return None


def _geocode(place):
    url = "https://nominatim.openstreetmap.org/search?format=json&limit=1&q=" + urllib.parse.quote(place)
    d = _http_json(url, timeout=8)
    return (float(d[0]["lat"]), float(d[0]["lon"])) if d else None


def _where(lat, lon):
    return f"{abs(lat):.1f} degrees {'north' if lat >= 0 else 'south'}, {abs(lon):.1f} degrees {'east' if lon >= 0 else 'west'}"


def _label(body):
    return {"earth": "EARTH", "moon": "MOON", "mars": "MARS", "solar": "SOLAR SYSTEM"}[body]


def _spoken(body):
    return {"earth": "the Earth", "moon": "the Moon", "mars": "Mars", "solar": "the solar system"}[body]


_OVL_NAME = {"iss": "space station", "earthquakes": "earthquake", "rain": "rainfall", "clouds": "cloud cover"}


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------
def run(parameters: dict, player=None, session_memory=None) -> str:
    try:
        p = parameters or {}
        raw_action = (p.get("action") or "").strip().lower().replace(" ", "_")
        overlay = _norm(_OVL, p.get("overlay"))
        body_in = _norm(_BODY, p.get("body"))
        if raw_action and raw_action not in _ACTIONS:
            return "Sir, I didn't recognise that space view command."
        action = {"show": "open", "display": "open", "flyto": "fly_to", "zoom": "fly_to", "follow_iss": "track_iss", "hide": "close"}.get(raw_action, raw_action)
        if not action:
            action = "overlay" if overlay else "open"
        win = getattr(player, "_win", None)
        if win is None or not hasattr(win, "_hud_cam_stack"):
            return "Sir, I can't find the interface panel to show the view in."

        try:
            q = _qt()
        except _NoWebEngine:
            return ("Sir, the embedded globe needs the PyQt6 WebEngine package. "
                    "Please run: pip install PyQt6-WebEngine, then restart me.")
        if q.QApplication.instance() is None:
            return "Sir, the interface is not running yet."

        if action == "close":
            if not _on_main(q, _widget_alive):
                return "The space view is not open, sir."
            _on_main(q, lambda: _close_main(q))
            return "Closing the space view, sir."

        # ---- decide the body this command ends on
        open_now = bool(_on_main(q, _widget_alive))
        body = body_in or (_S["body"] if open_now else "earth")
        if action in ("track_iss",) or overlay:
            if body != "earth":
                body = "earth"          # overlays live on the Earth view
        if action == "reset" and not open_now:
            return "The space view is not open, sir."

        cmds = []
        if (not open_now) or body != _S["body"]:
            cmds.append({"cmd": "body", "body": body})

        # ---- overlays
        enabled = p.get("enabled")
        enabled = True if enabled is None else bool(enabled)
        if action == "track_iss":
            overlay, enabled = "iss", True
        if overlay:
            cmds.append({"cmd": "overlay", "name": overlay, "on": enabled})

        # ---- location / focus
        lat, lon = p.get("latitude"), p.get("longitude")
        place = (p.get("location") or "").strip()
        alt_km = p.get("altitude_km")
        target_label = None
        if body == "solar":
            if place:
                cmds.append({"cmd": "focus", "planet": place})
                target_label = place
            if p.get("time_speed") is not None:
                cmds.append({"cmd": "speed", "value": float(p["time_speed"])})
        elif lat is not None and lon is not None:
            h = float(alt_km) * 1000 if alt_km else (15000.0 if body == "earth" else 80000.0)
            cmds.append({"cmd": "flyTo", "lat": float(lat), "lon": float(lon), "height": h})
            target_label = place or "those coordinates"
        elif place and action != "track_iss":
            found = None
            if body == "earth":
                try:
                    found = _geocode(place)
                except Exception:
                    return f"Sir, I couldn't look up {place} right now. Please check the internet connection."
            else:
                found = _norm(_SITES[body], place)
            if not found:
                if body == "earth":
                    return f"Sir, I couldn't find {place} on the map."
                return f"Sir, I don't have {place} on {_spoken(body)}. Give me coordinates, or try a famous site."
            h = float(alt_km) * 1000 if alt_km else (15000.0 if body == "earth" else 80000.0)
            cmds.append({"cmd": "flyTo", "lat": found[0], "lon": found[1], "height": h})
            target_label = place
        if action == "reset":
            cmds.append({"cmd": "reset"})
        if action == "track_iss":
            cmds.append({"cmd": "follow"})

        # ---- queue commands BEFORE the page loads so it never builds the wrong view first
        if not open_now:
            _reset_cmds()
            _ensure_server()
        for c in cmds:
            _push(c)
        _S["body"] = body

        def apply_ui():
            if not _widget_alive():
                _build_widget(q, win, f"http://127.0.0.1:{_port}/")
            else:
                _show_main(q)
            _S["lbl"].setText("\u25c8  " + _label(body))
        _on_main(q, apply_ui)

        # ---- spoken answer
        if action == "reset":
            msg = "Resetting the view, sir."
        elif action == "track_iss" or (overlay == "iss" and enabled):
            d = _iss_now()
            if "error" in d:
                msg = "Tracking the International Space Station on the globe, sir, though I can't read its position right now."
            else:
                msg = (f"Tracking the International Space Station, sir. It is over {_where(d['lat'], d['lon'])}, "
                       f"{round(d['alt'])} kilometres up, travelling at about {round(d['vel']):,} kilometres per hour.")
        elif overlay == "earthquakes" and enabled:
            d = _quakes_now()
            if "error" in d or not d.get("count"):
                msg = "Showing live earthquakes on the globe, sir, though the feed isn't answering right now."
            else:
                t = d["top"]
                msg = (f"Live earthquakes are on the globe, sir. There have been {d['count']} of magnitude 2.5 or higher "
                       f"in the past day; the strongest was magnitude {t['m']:.1f} near {t['place']}.")
        elif overlay == "rain" and enabled:
            msg = "Showing live rainfall from NASA satellites over the globe, sir."
        elif overlay:
            msg = f"The {_OVL_NAME[overlay]} layer is {'on' if enabled else 'off'}, sir."
        elif target_label:
            msg = (f"Zooming to {target_label}, sir." if open_now else f"Showing {_spoken(body)} and flying to {target_label}, sir.")
        elif body == "solar":
            msg = "Displaying the solar system with the planets' current positions, sir."
        else:
            msg = f"Displaying {_spoken(body)} in 3D, sir." if body != "earth" else "Displaying the Earth in 3D satellite view, sir."
    except Exception as e:
        return f"Sir, the space viewer failed: {e}"
    if player:
        try:
            player.write_log(f"JARVIS: {msg}")
        except Exception:
            pass
    return msg
