"""Local provider-independent static website generator for Mark 56."""
from __future__ import annotations
import html, json, os, re
from pathlib import Path

KINDS = {"portfolio", "business", "landing", "church"}
ACCENTS = {"cyan": "#65e5f0", "violet": "#b6a0ff", "amber": "#ffc36b", "green": "#8be0b0"}

def _root():
    root = Path(os.environ.get("MARK56_WORKSPACE", "").strip() or Path.cwd()).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("Configured workspace directory does not exist.")
    return root

def _clean(value, default, limit=240):
    value = str(value or "").strip()
    return (value or default)[:limit]

def _files(p):
    kind = str(p.get("kind") or "portfolio").lower().strip()
    if kind not in KINDS:
        raise ValueError("kind must be portfolio, business, landing, or church.")
    defaults = {
        "portfolio": ("Studio North", "Independent creative developer crafting thoughtful digital experiences.", "Brand identity,Web design,Creative development"),
        "business": ("Northstar Studio", "Good work. Clear thinking. Results that matter.", "Strategy and planning,Design and delivery,Support and growth"),
        "landing": ("Make Your Next Move", "A better way to bring your next idea to life.", "Simple onboarding,Clear project roadmap,Helpful human support"),
        "church": ("Grace Community", "A place to grow in faith, find community, and serve with purpose.", "Worship and teaching,Youth and family ministry,Community outreach"),
    }[kind]
    title = _clean(p.get("site_title"), defaults[0], 70)
    tagline = _clean(p.get("tagline"), defaults[1], 220)
    about = _clean(p.get("about"), "We bring thoughtful ideas to life through clear planning, careful craft, and a focus on people.", 600)
    email = _clean(p.get("email"), "hello@example.com", 120)
    if not re.fullmatch(r"[^\\s@<>]+@[^\\s@<>]+\\.[^\\s@<>]+", email):
        raise ValueError("Provide a valid-looking contact email.")
    accent_key = str(p.get("accent") or "cyan").lower()
    if accent_key not in ACCENTS:
        raise ValueError("accent must be cyan, violet, amber, or green.")
    services = p.get("services")
    if services is None:
        services = defaults[2].split(",")
    if not isinstance(services, list) or not 1 <= len(services) <= 8:
        raise ValueError("services must be a list of 1–8 items.")
    services = [_clean(x, "", 90) for x in services]
    if any(not x for x in services):
        raise ValueError("Service titles cannot be empty.")
    e = html.escape
    cards = "".join(f'<article class="card"><span>0{i:02d}</span><h3>{e(s)}</h3><p>Thoughtfully planned around your goals, your people, and the details that matter.</p></article>' for i,s in enumerate(services,1))
    nav = "".join(f'<a href="#services">{e(s)}</a>' for s in services[:3])
    safe_title, safe_tagline, safe_about, safe_email = map(e, (title, tagline, about, email))
    index = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{safe_tagline}"><meta name="theme-color" content="#080d16">
<title>{safe_title} — {safe_tagline[:60]}</title><link rel="stylesheet" href="style.css"></head>
<body><a class="skip" href="#main">Skip to content</a>
<header><a class="brand" href="#home"><b>✳</b> {safe_title}</a><button class="menu" aria-expanded="false" aria-controls="nav">Menu</button>
<nav id="nav" aria-label="Main navigation"><a href="#about">About</a><a href="#services">What we do</a><a class="nav-cta" href="#contact">Get in touch ↗</a></nav></header>
<main id="main"><section class="hero" id="home"><div class="orb"></div><p class="eyebrow">✳ INDEPENDENT BY DESIGN</p>
<h1>{safe_tagline}</h1><p class="lead">{safe_about}</p><div class="actions"><a class="button" href="#services">Explore what we do ↘</a><a class="text-link" href="#about">Get to know us →</a></div>
<div class="hero-foot"><span>BUILT WITH PURPOSE</span><span>SCROLL TO EXPLORE ↓</span></div></section>
<section class="intro section" id="about"><div><p class="eyebrow">01 / A LITTLE ABOUT US</p><h2>Good ideas deserve <em>great execution.</em></h2></div><p class="muted">{safe_about}</p></section>
<section class="section" id="services"><div class="heading"><div><p class="eyebrow">02 / WHAT WE DO</p><h2>Made to make<br><em>a difference.</em></h2></div><p class="muted">Practical expertise, considered details, and a process that keeps people at the centre.</p></div><div class="grid">{cards}</div></section>
<section class="contact section" id="contact"><p class="eyebrow">03 / YOUR NEXT CHAPTER</p><h2>Let's make<br><em>something matter.</em></h2><p class="muted">Have an idea, a question, or a project in mind? Start the conversation.</p><a class="button" href="mailto:{safe_email}">Contact us ↗</a><p class="muted">{safe_email}</p></section></main>
<footer><a class="brand" href="#home"><b>✳</b> {safe_title}</a><span>© <span id="year"></span> {safe_title}. Made with intention.</span><a href="#home">Back to top ↑</a></footer><script src="app.js" defer></script></body></html>"""
    css = f""":root{{--bg:#080d16;--panel:#111c2a;--line:#29364a;--text:#f1f5f9;--muted:#a3b0c2;--accent:{ACCENTS[accent_key]};font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth;scroll-padding-top:90px}}body{{margin:0;background:var(--bg);color:var(--text);line-height:1.65}}a{{color:inherit;text-decoration:none}}a:focus-visible,button:focus-visible{{outline:2px solid var(--accent);outline-offset:4px}}.skip{{position:absolute;left:-999px;top:8px;background:var(--accent);color:#071018;padding:8px}}.skip:focus{{left:8px}}header{{height:82px;padding:0 7vw;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #ffffff12;position:sticky;top:0;background:#080d16ed;backdrop-filter:blur(18px);z-index:5}}.brand{{font-weight:800;letter-spacing:-.04em}}.brand b{{color:var(--accent);font-size:1.5rem}}nav{{display:flex;align-items:center;gap:30px;color:var(--muted);font-size:.9rem}}nav a:hover,.text-link:hover{{color:var(--accent)}}.nav-cta{{border:1px solid #ffffff2c;border-radius:7px;padding:9px 14px;color:var(--text)}}.menu{{display:none}}main{{overflow:hidden}}.hero{{min-height:calc(90svh - 82px);padding:100px 12vw 25px;display:flex;flex-direction:column;align-items:flex-start;justify-content:center;position:relative;isolation:isolate}}.orb{{position:absolute;z-index:-1;right:-8%;top:5%;width:480px;height:480px;border-radius:50%;background:radial-gradient(circle at 35% 35%,{ACCENTS[accent_key]}35,transparent 70%)}}.eyebrow{{font-size:.72rem;letter-spacing:.16em;font-weight:800;color:var(--accent);margin:0 0 22px}}h1,h2,h3,p{{margin-top:0}}h1{{font-size:clamp(3rem,7.4vw,7rem);letter-spacing:-.075em;line-height:.99;max-width:1000px;margin-bottom:26px;font-weight:700}}.lead{{color:var(--muted);font-size:clamp(1rem,1.5vw,1.2rem);max-width:640px}}.actions{{display:flex;gap:28px;align-items:center;flex-wrap:wrap;margin-top:24px}}.button{{display:inline-flex;background:var(--accent);color:#071018;padding:13px 18px;border-radius:7px;font-size:.9rem;font-weight:800;transition:transform .2s}}.button:hover{{transform:translateY(-2px)}}.text-link{{font-weight:700;font-size:.9rem}}.hero-foot{{display:flex;justify-content:space-between;gap:18px;width:100%;margin-top:90px;padding-top:18px;border-top:1px solid #ffffff20;color:#8794a7;font-size:.65rem;letter-spacing:.13em}}.section{{padding:105px 12vw;border-top:1px solid #ffffff12}}.intro{{display:grid;grid-template-columns:1fr .8fr;gap:8vw;align-items:end}}h2{{font-size:clamp(2.4rem,5vw,4.8rem);letter-spacing:-.065em;line-height:1.04;margin-bottom:0}}em{{font-style:normal;color:var(--accent)}}.muted{{color:var(--muted);max-width:520px}}.heading{{display:flex;justify-content:space-between;align-items:end;gap:30px;margin-bottom:38px}}.heading>p{{max-width:350px}}.grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:15px}}.card{{background:linear-gradient(145deg,#142031,#0b121d);border:1px solid var(--line);border-radius:12px;padding:25px;min-height:210px;transition:transform .2s,border-color .2s}}.card:hover{{transform:translateY(-4px);border-color:var(--accent)}}.card span{{color:var(--accent);font-size:.75rem;letter-spacing:.12em}}.card h3{{margin:32px 0 10px;font-size:1.25rem}}.card p{{color:var(--muted);font-size:.9rem;margin-bottom:0}}.contact{{background:radial-gradient(ellipse at 90% 60%,{ACCENTS[accent_key]}15,transparent 52%)}}.contact h2{{font-size:clamp(3rem,7vw,6.5rem);margin-bottom:22px}}.contact .button{{margin:12px 0 20px}}footer{{padding:27px 7vw;display:flex;align-items:center;justify-content:space-between;gap:20px;color:var(--muted);font-size:.78rem;border-top:1px solid #ffffff12}}footer .brand,footer>a:last-child{{color:var(--text)}}
@media(max-width:800px){{header{{padding:0 6vw}}.menu{{display:block;background:transparent;color:var(--text);border:1px solid var(--line);border-radius:6px;padding:8px 12px}}nav{{display:none;position:absolute;top:81px;left:0;right:0;padding:22px 6vw;background:#080d16;border-bottom:1px solid var(--line);align-items:flex-start;flex-direction:column;gap:18px}}nav.open{{display:flex}}.hero{{padding:90px 7vw 25px;min-height:660px}}.orb{{right:-260px;top:10%}}.hero-foot{{margin-top:65px}}.section{{padding:78px 7vw}}.intro{{grid-template-columns:1fr;gap:24px}}.heading{{align-items:flex-start;flex-direction:column}}.grid{{grid-template-columns:1fr}}.card{{min-height:160px}}.card h3{{margin-top:22px}}footer{{padding:24px 6vw;flex-wrap:wrap}}}}
@media(prefers-reduced-motion:reduce){{*,*::before,*::after{{scroll-behavior:auto!important;transition:none!important}}}}"""
    js = """const year=document.querySelector("#year");if(year)year.textContent=String(new Date().getFullYear());
const toggle=document.querySelector(".menu"),nav=document.querySelector("#nav");
if(toggle&&nav){toggle.addEventListener("click",()=>{const open=toggle.getAttribute("aria-expanded")!=="true";toggle.setAttribute("aria-expanded",String(open));nav.classList.toggle("open",open);});nav.querySelectorAll("a").forEach(a=>a.addEventListener("click",()=>{nav.classList.remove("open");toggle.setAttribute("aria-expanded","false");}));}"""
    readme = f"""# {title}

Responsive static website created by Mark 56's provider-independent local site builder.

## Run locally
Open index.html in a modern browser. No package install, backend, AI API, or internet connection is required.

## Customize
- index.html: text, page sections, and links.
- style.css: layout, colors, responsive behavior, and typography.
- app.js: small browser interactions.
- Replace the example contact email before publishing.

## Scope and limitations
This is a static frontend. The contact link opens an email application; it is not a server-backed form. No database, authentication, analytics, or deployment is configured. Review links, accessibility, and behavior before publishing.
"""
    return {"index.html": index, "style.css": css, "app.js": js, "README.md": readme}

def run(parameters: dict, **_context) -> str:
    p=parameters or {}
    op=str(p.get("operation") or "catalog").lower().strip()
    if op=="catalog":
        return json.dumps({"ok":True,"kinds":sorted(KINDS),"accents":sorted(ACCENTS),"provider_independent":True})
    if op not in {"preview","create"}:
        return json.dumps({"ok":False,"message":"Use catalog, preview, or create."})
    try:
        name=str(p.get("name") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}",name):
            raise ValueError("Project name must be 1–48 letters, numbers, hyphens, or underscores.")
        files=_files(p); root=_root(); dest=(root/name).resolve()
        if not dest.is_relative_to(root) or dest==root:
            raise ValueError("Project destination escapes the configured workspace.")
        result={"ok":True,"operation":op,"name":name,"kind":p.get("kind") or "portfolio","destination":str(dest),"files":list(files),"requires_provider":False}
        if op=="preview":
            preview_html = files["index.html"].replace('<link rel="stylesheet" href="style.css">', "<style>" + files["style.css"] + "</style>")
            result.update(message="Preview only; no files written.", preview_html=preview_html[:30000])
            return json.dumps(result,ensure_ascii=False)
        if p.get("confirmed") is not True:
            result.update(ok=False,message="Creation requires confirmed=true after reviewing the preview.")
            return json.dumps(result,ensure_ascii=False)
        if dest.exists():
            raise FileExistsError("Destination already exists; nothing was overwritten.")
        dest.mkdir()
        try:
            for filename,content in files.items():
                (dest/filename).write_text(content,encoding="utf-8")
        except Exception:
            for child in dest.iterdir():
                if child.is_file(): child.unlink()
            dest.rmdir()
            raise
        result.update(operation="created",message="Static website created locally.")
        return json.dumps(result,ensure_ascii=False)
    except (ValueError,FileExistsError,OSError) as exc:
        return json.dumps({"ok":False,"message":str(exc)},ensure_ascii=False)

PLUGIN = {
 "name":"static_site_builder",
 "description":"Provider-independent local static website generator. Use catalog, preview, and create. Supports portfolio, business, landing, and church websites; generates responsive HTML, CSS, JS, and README. Preview does not write. Create requires confirmed=true and never overwrites an existing destination.",
 "parameters":{"type":"OBJECT","properties":{
  "operation":{"type":"STRING","description":"catalog | preview | create"},
  "name":{"type":"STRING","description":"New folder name"},
  "kind":{"type":"STRING","description":"portfolio | business | landing | church"},
  "site_title":{"type":"STRING","description":"Brand or site title"},
  "tagline":{"type":"STRING","description":"Hero headline or positioning statement"},
  "about":{"type":"STRING","description":"About paragraph"},
  "email":{"type":"STRING","description":"Contact email"},
  "services":{"type":"ARRAY","items":{"type":"STRING"},"description":"1–8 service or feature titles"},
  "accent":{"type":"STRING","description":"cyan | violet | amber | green"},
  "confirmed":{"type":"BOOLEAN","description":"Explicit approval after reviewing preview"}
 },"required":["operation"]}
}
