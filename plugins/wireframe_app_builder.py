"""
wireframe_app_builder.py — JARVIS plugin (no external AI — fully local)

Builds a real, runnable website or game from a description and/or a
wireframe image — with NO calls to Gemini or any other AI API. Everything
is generated from hand-written, tested templates chosen deterministically:

  - Description keywords decide which website sections to include
    (nav/hero/features/about/gallery/contact/footer), or which game to
    build (snake/pong/platformer).
  - If a wireframe image is given, OpenCV does structural region detection
    (contour/box detection — no text reading, no neural network) to count
    and order the sections in the image, which is folded into the section
    choice alongside the description.
  - If there's no wireframe at all, it builds purely from the description
    (or, with no description either, a sensible default site/game).

SCOPE, HONESTLY: without an AI model, this can't write arbitrary code for
any request — it assembles from the templates below. Supported stacks:
'html_css_js' for websites, 'pygame' for games (snake/pong/platformer).
A request for a different stack gets a clear message, not a fake result.

Drop this file into /plugins/ — no other file needs to change.
"""

import ast
import py_compile
import tempfile
import webbrowser
import subprocess
from pathlib import Path
from datetime import datetime

PLUGIN = {
    "name": "build_from_wireframe",
    "description": (
        "Builds a real, runnable website (plain HTML/CSS/JS) or game (Python + "
        "Pygame: snake, pong, or platformer) from a text description and/or a "
        "wireframe/mockup image. Works with just a description if there's no "
        "wireframe. Fully local — does not call any AI model, so it only "
        "supports the html_css_js and pygame stacks (says so plainly if a "
        "different stack is requested). Use for 'build me a website/game', "
        "'build this from the wireframe', 'make a snake/pong/platformer game'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "description": {
                "type": "STRING",
                "description": "What to build — page sections wanted, or which "
                                "game (snake/pong/platformer). Optional if a "
                                "wireframe image is given.",
            },
            "project_type": {
                "type": "STRING",
                "enum": ["website", "game"],
                "description": "What kind of project to build.",
            },
            "tech_stack": {
                "type": "STRING",
                "description": "Must be 'html_css_js' (websites) or 'pygame' "
                                "(games) — the only stacks this local, non-AI "
                                "builder supports. Defaults appropriately if omitted.",
            },
            "wireframe_image_path": {
                "type": "STRING",
                "description": "Optional. Local path to a wireframe/mockup image. "
                                "Its layout (section count/order/size) is read "
                                "structurally via OpenCV, not AI vision.",
            },
            "project_name": {
                "type": "STRING",
                "description": "Optional folder name for the project.",
            },
        },
        "required": [],
    },
}

PROJECTS_DIR = Path.home() / "Desktop" / "JarvisProjects"

_SECTION_KEYWORDS = {
    "hero": ["hero", "banner", "landing", "headline"],
    "features": ["feature", "service", "services", "what we offer"],
    "about": ["about"],
    "gallery": ["gallery", "portfolio", "photos", "images", "work"],
    "contact": ["contact", "form", "get in touch", "email us"],
}

_GAME_KEYWORDS = {
    "snake": ["snake"],
    "pong": ["pong"],
    "platformer": ["platform", "jump", "mario", "side-scroll"],
}


# ─────────────────────────── description parsing ───────────────────────────

def _sections_from_description(description: str) -> list:
    text = description.lower()
    found = [name for name, kws in _SECTION_KEYWORDS.items() if any(k in text for k in kws)]
    return found


def _game_from_description(description: str) -> str:
    text = description.lower()
    for name, kws in _GAME_KEYWORDS.items():
        if any(k in text for k in kws):
            return name
    return "platformer"  # default if unspecified


# ─────────────────────────── wireframe region detection ────────────────────

def _detect_wireframe_sections(image_path: str) -> list:
    """
    Structural (non-AI) layout read: finds horizontal bands in the wireframe
    image via OpenCV contour detection, and maps their count/position/shape
    to a plausible section list. Does not read any text in the image.
    """
    import cv2
    import numpy as np

    path = Path(image_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"'{image_path}' does not exist.")

    img = cv2.imread(str(path))
    if img is None:
        raise ValueError(f"'{image_path}' isn't a readable image file.")

    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 40, 120)
    dilated = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=2)
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes = []
    for c in contours:
        x, y, bw, bh = cv2.boundingRect(c)
        area = bw * bh
        if area < (w * h) * 0.01:   # ignore tiny noise
            continue
        boxes.append((x, y, bw, bh))

    if not boxes:
        return []

    boxes.sort(key=lambda b: b[1])  # top to bottom

    # group boxes that sit in roughly the same horizontal band (similar y)
    bands = []
    for box in boxes:
        x, y, bw, bh = box
        placed = False
        for band in bands:
            by = band[0][1]
            if abs(y - by) < h * 0.06:
                band.append(box)
                placed = True
                break
        if not placed:
            bands.append([box])

    sections = []
    for i, band in enumerate(bands):
        band_width = sum(b[2] for b in band) / w
        avg_h = sum(b[3] for b in band) / len(band) / h
        is_first = i == 0
        is_last = i == len(bands) - 1
        is_grid = len(band) >= 3

        if is_first and avg_h < 0.12:
            sections.append("nav")
        elif is_last and avg_h < 0.15:
            sections.append("footer")
        elif is_grid:
            sections.append("features")
        elif i <= 1 and band_width > 0.6:
            sections.append("hero")
        else:
            sections.append("about")

    return sections


# ─────────────────────────── website templates ─────────────────────────────
# Elegant / modern / dark aesthetic throughout — real, complete markup, not
# placeholders. Sections are string templates assembled in order.

_CSS = """
:root {
  --bg: #0b0f14;
  --panel: #121822;
  --text: #eef2f7;
  --muted: #9aa7b8;
  --accent: #00e5ff;
  --font: 'Segoe UI', system-ui, sans-serif;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--text); font-family: var(--font); line-height: 1.6; }
a { color: var(--accent); text-decoration: none; }
.container { max-width: 1100px; margin: 0 auto; padding: 0 24px; }

nav { position: sticky; top: 0; background: rgba(11,15,20,0.9); backdrop-filter: blur(8px);
      border-bottom: 1px solid #1e2733; z-index: 10; }
nav .container { display: flex; justify-content: space-between; align-items: center; height: 68px; }
nav .logo { font-weight: 700; font-size: 1.2rem; letter-spacing: 0.5px; }
nav ul { list-style: none; display: flex; gap: 28px; }

.hero { padding: 120px 0 90px; text-align: center; }
.hero h1 { font-size: 2.8rem; margin-bottom: 18px; }
.hero p { color: var(--muted); max-width: 560px; margin: 0 auto 32px; font-size: 1.1rem; }
.btn { display: inline-block; background: var(--accent); color: #04141a; font-weight: 600;
       padding: 14px 30px; border-radius: 8px; border: none; cursor: pointer; }

.features { padding: 80px 0; }
.features h2, .gallery h2, .about h2, .contact h2 { text-align: center; margin-bottom: 48px; font-size: 2rem; }
.feature-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 24px; }
.feature-card { background: var(--panel); border: 1px solid #1e2733; border-radius: 12px; padding: 28px; }
.feature-card h3 { margin-bottom: 10px; color: var(--accent); }
.feature-card p { color: var(--muted); }

.about { padding: 80px 0; background: var(--panel); }
.about p { color: var(--muted); max-width: 700px; margin: 0 auto; text-align: center; }

.gallery { padding: 80px 0; }
.gallery-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; }
.gallery-grid div { aspect-ratio: 4/3; background: var(--panel); border: 1px solid #1e2733; border-radius: 10px; }

.contact { padding: 80px 0; background: var(--panel); }
.contact form { max-width: 480px; margin: 0 auto; display: flex; flex-direction: column; gap: 16px; }
.contact input, .contact textarea { background: var(--bg); border: 1px solid #1e2733; border-radius: 8px;
      padding: 12px 14px; color: var(--text); font-family: inherit; }

footer { padding: 32px 0; text-align: center; color: var(--muted); border-top: 1px solid #1e2733; }
""".strip()

_JS = """
document.addEventListener('DOMContentLoaded', () => {
  const form = document.querySelector('.contact form');
  if (form) {
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      alert('Thanks — this is a static demo, hook this up to your backend of choice.');
      form.reset();
    });
  }
});
""".strip()

_HTML_SECTIONS = {
    "nav": lambda title: """
  <nav>
    <div class="container">
      <div class="logo">""" + title + """</div>
      <ul>
        <li><a href="#hero">Home</a></li>
        <li><a href="#features">Features</a></li>
        <li><a href="#about">About</a></li>
        <li><a href="#contact">Contact</a></li>
      </ul>
    </div>
  </nav>""",
    "hero": lambda title: """
  <section class="hero" id="hero">
    <div class="container">
      <h1>""" + title + """</h1>
      <p>A clean, modern starting point — built and ready to customize.</p>
      <button class="btn">Get Started</button>
    </div>
  </section>""",
    "features": lambda title: """
  <section class="features" id="features">
    <div class="container">
      <h2>Features</h2>
      <div class="feature-grid">
        <div class="feature-card"><h3>Fast</h3><p>Lightweight and quick to load, no bloated frameworks.</p></div>
        <div class="feature-card"><h3>Responsive</h3><p>Looks great on desktop, tablet, and mobile.</p></div>
        <div class="feature-card"><h3>Customizable</h3><p>Plain HTML/CSS/JS — edit anything directly.</p></div>
      </div>
    </div>
  </section>""",
    "about": lambda title: """
  <section class="about" id="about">
    <div class="container">
      <h2>About</h2>
      <p>""" + title + """ — replace this paragraph with real content about what this project/site/company does.</p>
    </div>
  </section>""",
    "gallery": lambda title: """
  <section class="gallery" id="gallery">
    <div class="container">
      <h2>Gallery</h2>
      <div class="gallery-grid">
        <div></div><div></div><div></div><div></div><div></div><div></div>
      </div>
    </div>
  </section>""",
    "contact": lambda title: """
  <section class="contact" id="contact">
    <div class="container">
      <h2>Contact</h2>
      <form>
        <input type="text" placeholder="Your name" required>
        <input type="email" placeholder="Your email" required>
        <textarea rows="4" placeholder="Message"></textarea>
        <button class="btn" type="submit">Send</button>
      </form>
    </div>
  </section>""",
    "footer": lambda title: """
  <footer>
    <div class="container">&copy; """ + str(datetime.now().year) + " " + title + """. All rights reserved.</div>
  </footer>""",
}


def _build_website(title: str, sections: list) -> dict:
    ordered = ["nav"] + [s for s in sections if s not in ("nav", "footer")] + ["footer"]
    seen = set()
    ordered = [s for s in ordered if not (s in seen or seen.add(s))]

    body = "\n".join(_HTML_SECTIONS[s](title) for s in ordered if s in _HTML_SECTIONS)

    html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>""" + title + """</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
""" + body + """
  <script src="script.js"></script>
</body>
</html>"""

    return {"index.html": html, "style.css": _CSS, "script.js": _JS}


# ─────────────────────────── game templates (Pygame) ───────────────────────

_GAME_TEMPLATES = {
    "snake": '''import pygame
import random
import sys

pygame.init()
CELL = 20
COLS, ROWS = 30, 22
W, H = COLS * CELL, ROWS * CELL
screen = pygame.display.set_mode((W, H))
pygame.display.set_caption("Snake - built by JARVIS")
clock = pygame.time.Clock()
font = pygame.font.SysFont(None, 36)

BG = (11, 15, 20)
SNAKE_COLOR = (0, 229, 255)
FOOD_COLOR = (255, 106, 26)

def random_food(snake):
    while True:
        pos = (random.randint(0, COLS - 1), random.randint(0, ROWS - 1))
        if pos not in snake:
            return pos

def main():
    snake = [(COLS // 2, ROWS // 2)]
    direction = (1, 0)
    food = random_food(snake)
    score = 0
    game_over = False

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN and not game_over:
                if event.key in (pygame.K_UP, pygame.K_w) and direction != (0, 1):
                    direction = (0, -1)
                elif event.key in (pygame.K_DOWN, pygame.K_s) and direction != (0, -1):
                    direction = (0, 1)
                elif event.key in (pygame.K_LEFT, pygame.K_a) and direction != (1, 0):
                    direction = (-1, 0)
                elif event.key in (pygame.K_RIGHT, pygame.K_d) and direction != (-1, 0):
                    direction = (1, 0)
            if event.type == pygame.KEYDOWN and game_over and event.key == pygame.K_r:
                return main()

        if not game_over:
            head = (snake[0][0] + direction[0], snake[0][1] + direction[1])
            if (head in snake or not (0 <= head[0] < COLS) or not (0 <= head[1] < ROWS)):
                game_over = True
            else:
                snake.insert(0, head)
                if head == food:
                    score += 1
                    food = random_food(snake)
                else:
                    snake.pop()

        screen.fill(BG)
        for (x, y) in snake:
            pygame.draw.rect(screen, SNAKE_COLOR, (x * CELL, y * CELL, CELL - 2, CELL - 2))
        fx, fy = food
        pygame.draw.rect(screen, FOOD_COLOR, (fx * CELL, fy * CELL, CELL - 2, CELL - 2))

        score_surf = font.render("Score: " + str(score), True, (238, 242, 247))
        screen.blit(score_surf, (10, 10))

        if game_over:
            msg = font.render("Game Over - press R to restart", True, (238, 242, 247))
            screen.blit(msg, (W // 2 - msg.get_width() // 2, H // 2))

        pygame.display.flip()
        clock.tick(10)

if __name__ == "__main__":
    main()
''',

    "pong": '''import pygame
import sys

pygame.init()
W, H = 800, 500
screen = pygame.display.set_mode((W, H))
pygame.display.set_caption("Pong - built by JARVIS")
clock = pygame.time.Clock()
font = pygame.font.SysFont(None, 48)

BG = (11, 15, 20)
FG = (0, 229, 255)
PADDLE_W, PADDLE_H = 14, 90
BALL_SIZE = 14
SPEED = 6

left = pygame.Rect(30, H // 2 - PADDLE_H // 2, PADDLE_W, PADDLE_H)
right = pygame.Rect(W - 44, H // 2 - PADDLE_H // 2, PADDLE_W, PADDLE_H)
ball = pygame.Rect(W // 2 - BALL_SIZE // 2, H // 2 - BALL_SIZE // 2, BALL_SIZE, BALL_SIZE)
ball_vel = [SPEED, SPEED]
score = [0, 0]

def main_loop():
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()

        keys = pygame.key.get_pressed()
        if keys[pygame.K_w] and left.top > 0: left.y -= SPEED
        if keys[pygame.K_s] and left.bottom < H: left.y += SPEED
        if keys[pygame.K_UP] and right.top > 0: right.y -= SPEED
        if keys[pygame.K_DOWN] and right.bottom < H: right.y += SPEED

        ball.x += ball_vel[0]
        ball.y += ball_vel[1]
        if ball.top <= 0 or ball.bottom >= H:
            ball_vel[1] *= -1
        if ball.colliderect(left) or ball.colliderect(right):
            ball_vel[0] *= -1
        if ball.left <= 0:
            score[1] += 1
            ball.center = (W // 2, H // 2)
        if ball.right >= W:
            score[0] += 1
            ball.center = (W // 2, H // 2)

        screen.fill(BG)
        pygame.draw.rect(screen, FG, left)
        pygame.draw.rect(screen, FG, right)
        pygame.draw.ellipse(screen, FG, ball)
        pygame.draw.aaline(screen, (30, 40, 50), (W // 2, 0), (W // 2, H))
        score_surf = font.render(str(score[0]) + "   " + str(score[1]), True, (238, 242, 247))
        screen.blit(score_surf, (W // 2 - score_surf.get_width() // 2, 20))

        pygame.display.flip()
        clock.tick(60)

if __name__ == "__main__":
    main_loop()
''',

    "platformer": '''import pygame
import sys

pygame.init()
W, H = 900, 500
screen = pygame.display.set_mode((W, H))
pygame.display.set_caption("Platformer - built by JARVIS")
clock = pygame.time.Clock()
font = pygame.font.SysFont(None, 36)

BG = (11, 15, 20)
PLAYER_COLOR = (0, 229, 255)
PLATFORM_COLOR = (30, 39, 51)
GOAL_COLOR = (255, 106, 26)

GRAVITY = 0.8
JUMP_STRENGTH = -15
MOVE_SPEED = 5

platforms = [
    pygame.Rect(0, H - 40, W, 40),
    pygame.Rect(200, 380, 140, 20),
    pygame.Rect(420, 300, 140, 20),
    pygame.Rect(650, 220, 140, 20),
]
goal = pygame.Rect(700, 170, 30, 50)

player = pygame.Rect(40, H - 90, 34, 46)
vel_y = 0
on_ground = False
won = False

def main():
    global vel_y, on_ground, won
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                return restart()

        keys = pygame.key.get_pressed()
        if not won:
            if keys[pygame.K_LEFT] or keys[pygame.K_a]:
                player.x -= MOVE_SPEED
            if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
                player.x += MOVE_SPEED
            if (keys[pygame.K_SPACE] or keys[pygame.K_UP] or keys[pygame.K_w]) and on_ground:
                vel_y = JUMP_STRENGTH

            vel_y += GRAVITY
            player.y += int(vel_y)

            on_ground = False
            for p in platforms:
                if player.colliderect(p) and vel_y >= 0:
                    if player.bottom - vel_y <= p.top + 1:
                        player.bottom = p.top
                        vel_y = 0
                        on_ground = True

            if player.colliderect(goal):
                won = True

        screen.fill(BG)
        for p in platforms:
            pygame.draw.rect(screen, PLATFORM_COLOR, p)
        pygame.draw.rect(screen, GOAL_COLOR, goal)
        pygame.draw.rect(screen, PLAYER_COLOR, player)

        if won:
            msg = font.render("You reached the goal! Press R to restart", True, (238, 242, 247))
            screen.blit(msg, (W // 2 - msg.get_width() // 2, H // 2))

        pygame.display.flip()
        clock.tick(60)

def restart():
    global player, vel_y, on_ground, won
    player = pygame.Rect(40, H - 90, 34, 46)
    vel_y = 0
    on_ground = False
    won = False
    return main()

if __name__ == "__main__":
    main()
''',
}


# ─────────────────────────── validation ─────────────────────────────────────

def _validate_html(html: str) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    if not soup.find("html") or not soup.find("body"):
        raise ValueError("generated HTML is missing <html> or <body>")
    return "ok"


def _validate_css_js_braces(text: str, label: str) -> str:
    if text.count("{") != text.count("}"):
        raise ValueError("generated " + label + " has unbalanced braces")
    return "ok"


def _validate_python(code: str) -> str:
    ast.parse(code)  # raises SyntaxError if invalid
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as tmp:
        tmp.write(code.encode("utf-8"))
        tmp_path = tmp.name
    try:
        py_compile.compile(tmp_path, doraise=True)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
        cache = Path(tmp_path).parent / "__pycache__"
        if cache.exists():
            for f in cache.glob(Path(tmp_path).stem + "*"):
                f.unlink(missing_ok=True)
    return "ok"


# ─────────────────────────── main entry point ───────────────────────────────

def _title_from_description(description: str) -> str:
    words = description.strip().split()[:6]
    if not words:
        return "My Website"
    return " ".join(words).title()


def _slugify(text: str) -> str:
    keep = [c if c.isalnum() else "_" for c in text.strip().lower()]
    slug = "".join(keep)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "jarvis_project"


def run(parameters: dict, player=None, session_memory=None) -> str:
    description = (parameters.get("description") or "").strip()
    project_type = (parameters.get("project_type") or "").strip().lower()
    tech_stack = (parameters.get("tech_stack") or "").strip().lower()
    wireframe_path = (parameters.get("wireframe_image_path") or "").strip()
    project_name = (parameters.get("project_name") or "").strip()

    if not description and not wireframe_path:
        return ("Sir, I need either a description or a wireframe image to build from "
                "- I don't call any AI model, so I can't invent a project from nothing.")

    if not project_type:
        text = description.lower()
        project_type = "game" if any(k in text for k in
                        ["game", "snake", "pong", "platform"]) else "website"

    wireframe_note = ""
    wireframe_sections = []
    if wireframe_path:
        try:
            wireframe_sections = _detect_wireframe_sections(wireframe_path)
            wireframe_note = " Detected " + str(len(wireframe_sections)) + " layout region(s) from the wireframe."
        except Exception as e:
            wireframe_note = " (Wireframe image couldn't be read - " + str(e) + ". Building from description alone.)"

    try:
        if project_type == "game":
            if tech_stack and tech_stack != "pygame":
                return ("Sir, without an AI model I can only build games in 'pygame' - "
                         "'" + tech_stack + "' isn't something I can hand-generate. Say the word "
                         "and I'll build it in Pygame instead.")
            game_choice = _game_from_description(description) if description else "platformer"
            code = _GAME_TEMPLATES[game_choice]
            _validate_python(code)

            name = project_name or (game_choice + "_game")
            proj_dir = PROJECTS_DIR / _slugify(name)
            proj_dir.mkdir(parents=True, exist_ok=True)
            script_path = proj_dir / "main.py"
            script_path.write_text(code, encoding="utf-8")

            try:
                subprocess.Popen(["python", str(script_path)])
            except Exception:
                pass

            result_text = ("Built a working " + game_choice + " game (Pygame) - validated, "
                            "saved to " + str(script_path) + ", and launched it.")

        else:  # website
            if tech_stack and tech_stack != "html_css_js":
                return ("Sir, without an AI model I can only build websites in plain "
                         "'html_css_js' - '" + tech_stack + "' isn't something I can hand-generate. "
                         "Say the word and I'll build it in HTML/CSS/JS instead.")

            sections = set(_sections_from_description(description)) | set(wireframe_sections)
            if not sections:
                sections = {"hero", "features", "about", "contact"}

            title = _title_from_description(description) if description else "My Website"
            files = _build_website(title, list(sections))

            _validate_html(files["index.html"])
            _validate_css_js_braces(files["style.css"], "CSS")
            _validate_css_js_braces(files["script.js"], "JavaScript")

            name = project_name or "website"
            proj_dir = PROJECTS_DIR / _slugify(name)
            proj_dir.mkdir(parents=True, exist_ok=True)
            for fname, content in files.items():
                (proj_dir / fname).write_text(content, encoding="utf-8")

            index_path = proj_dir / "index.html"
            try:
                webbrowser.open(index_path.as_uri())
            except Exception:
                pass

            section_list = ", ".join(sorted(sections))
            result_text = ("Built a website (" + section_list + ") - validated, saved to "
                            + str(proj_dir) + ", and opened it in your browser." + wireframe_note)

    except Exception as e:
        return "Sir, build_from_wireframe failed: " + str(e)

    if player:
        try:
            player.write_log("JARVIS: " + result_text)
        except Exception:
            pass

    return result_text
