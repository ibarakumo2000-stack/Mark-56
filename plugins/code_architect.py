"""
code_architect — JARVIS plugin.

Drop this file straight into the `plugins/` folder of your Mark-LII (JARVIS)
install. No other file needs to change; `core/plugin_loader.py` discovers it
automatically at startup (any *.py file in plugins/ that doesn't start with
an underscore, and doesn't collide with an existing tool name).

What it does
------------
Give it a one-line goal and it will:
  1. Optionally look at a wireframe image (screenshot / sketch / mockup) and
     describe its layout using Gemini vision.
  2. Plan a complete file structure for the requested project — website,
     game, or general app/script — in the tech stack YOU choose (or a
     sensible default if you don't specify one).
  3. Write every file with Gemini, in any programming language.
  4. Install dependencies (pip and/or npm, whichever the plan needs).
  5. Run the project and auto-fix errors for a few rounds (Python and
     Node projects get a real run+fix loop; static websites get spun up
     on a local server; stacks JARVIS can't execute headlessly — e.g.
     Unity/Godot/Flutter — are written to disk and reported, not run).
  6. Opens the project folder in VS Code if it's installed.

This is deliberately a *separate* tool from the built-in `dev_agent` /
`code_helper` tools — it does not replace them, it specializes in the two
things they don't cover well: wireframe-driven websites and games, across
any tech stack. Gemini picks whichever tool fits the request; the
descriptions below tell it when that's this one.

Requirements
------------
Nothing extra beyond what Mark-LII already needs: a valid
`config/api_keys.json` with a `"gemini_api_key"` entry (same file every
other action already uses), and the `google-genai` and `pillow` packages
that are already in requirements.txt. Node/npm are only needed if you ask
for a Node/React/etc. tech stack — if they're missing the plugin says so
and still leaves you the generated source.
"""

from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

# --------------------------------------------------------------------------
# Config / paths — same convention as actions/dev_agent.py and friends.
# --------------------------------------------------------------------------

def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR         = _get_base_dir()
API_CONFIG_PATH  = BASE_DIR / "config" / "api_keys.json"
PROJECTS_DIR     = Path.home() / "Desktop" / "JarvisProjects"
MAX_FIX_ATTEMPTS = 5
MODEL_PLANNER    = "gemini-flash-latest"
MODEL_WRITER     = "gemini-flash-latest"
MODEL_VISION     = "gemini-flash-latest"


class RateLimitError(Exception):
    pass


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        key = json.load(f).get("gemini_api_key", "")
    if not key:
        raise RuntimeError("gemini_api_key not found in config/api_keys.json")
    return key


def _get_model(model_name: str):
    from google import genai
    _c = genai.Client(api_key=_get_api_key())

    class _W:
        def generate_content(self, contents):
            return _c.models.generate_content(model=model_name, contents=contents)

    return _W()


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z0-9_+\-]*\r?\n?", "", text)
    text = re.sub(r"\r?\n?```\s*$", "", text)
    return text.strip()


def _is_rate_limit(error: Exception) -> bool:
    msg = str(error).lower()
    return "429" in msg or "quota" in msg or "resource_exhausted" in msg


def _find_free_port(start: int = 8000) -> int:
    for port in range(start, start + 40):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start


# --------------------------------------------------------------------------
# PLUGIN declaration — read by core/plugin_loader.py and handed to Gemini.
# --------------------------------------------------------------------------

PLUGIN = {
    "name": "code_architect",
    "description": (
        "Builds and runs a real, multi-file coding project from a one-line goal, in "
        "ANY programming language or tech stack the user names. Use this for: "
        "(1) building a WEBSITE or web app, especially when the user describes or "
        "gives a WIREFRAME/mockup/layout/sketch/screenshot for it and/or names a "
        "specific tech stack (React, Vue, Flask, plain HTML/CSS/JS, etc.); "
        "(2) building a GAME in any engine or library (pygame, JavaScript/HTML5 "
        "canvas, Unity C# scripts, Godot, etc.); "
        "(3) writing complex, complete, multi-file code in any language on request. "
        "It plans the file structure, writes every file, installs dependencies, runs "
        "the project, and auto-fixes errors. "
        "Do NOT use this for a single quick snippet or one-off script (use "
        "'code_helper' instead) and do NOT use this for a generic, non-website, "
        "non-game multi-file build with no wireframe/stack preference (use "
        "'dev_agent' instead). Do NOT use this for Steam/Epic game "
        "installs/updates — that is 'game_updater'."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "description": {
                "type": "STRING",
                "description": "What to build — the one-line goal, plus any details the user gave.",
            },
            "project_type": {
                "type": "STRING",
                "description": "website | game | app | script. Leave blank to auto-detect from the description.",
            },
            "tech_stack": {
                "type": "STRING",
                "description": (
                    "The stack/framework the user wants, e.g. 'React + Tailwind', "
                    "'plain HTML/CSS/JS', 'Python + pygame', 'Node + Express', "
                    "'Unity C#'. Leave blank to let JARVIS pick a sensible default."
                ),
            },
            "language": {
                "type": "STRING",
                "description": "Primary programming language, if the user named one directly (overrides inference from tech_stack).",
            },
            "wireframe": {
                "type": "STRING",
                "description": "Text description of the wireframe/layout: pages, sections, components, what goes where.",
            },
            "wireframe_image_path": {
                "type": "STRING",
                "description": "Local path to a wireframe/mockup image file, if the user provided one. Optional.",
            },
            "pages": {
                "type": "STRING",
                "description": "Comma-separated list of pages/screens for a website (e.g. 'home, about, contact').",
            },
            "features": {
                "type": "STRING",
                "description": "Comma-separated key features/mechanics (e.g. for a game: 'jumping, scoring, 3 levels').",
            },
            "project_name": {
                "type": "STRING",
                "description": "Optional project folder name.",
            },
            "timeout": {
                "type": "INTEGER",
                "description": "Per-run timeout in seconds (default: 30).",
            },
            "open_editor": {
                "type": "BOOLEAN",
                "description": "Open the finished project in VS Code if available (default: true).",
            },
        },
        "required": ["description"],
    },
}


# --------------------------------------------------------------------------
# Error classification / traceback parsing — covers Python AND JS/Node.
# --------------------------------------------------------------------------

def _classify_error(output: str) -> str:
    low = output.lower()

    if any(x in low for x in (
        "no module named", "modulenotfounderror", "cannot find module",
        "err_module_not_found", "npm err",
    )):
        return "dependency_error"

    if "syntaxerror" in low or "invalid syntax" in low or "unexpected token" in low:
        return "syntax_error"

    if "cannot import" in low or "importerror" in low:
        return "import_error"

    if any(x in low for x in (
        "traceback", "exception", "error:", "nameerror", "typeerror",
        "attributeerror", "valueerror", "keyerror", "indexerror",
        "zerodivisionerror", "filenotfounderror", "permissionerror",
        "referenceerror", "rangeerror", "eaddrinuse", "unhandled",
    )):
        return "runtime_error"

    return "none"


def _has_error(output: str, run_command: str) -> bool:
    low = output.lower()
    if "timed out" in low:
        # A server / GUI / game loop that's still running when the timeout
        # hits is a SUCCESS signal, not a failure — same convention dev_agent
        # uses for long-running processes.
        return False
    if "address already in use" in low or "eaddrinuse" in low:
        return False
    if not output.strip():
        return False
    return _classify_error(output) != "none"


def _parse_traceback(output: str, project_files: list[str]) -> tuple[str | None, int | None]:
    patterns = [
        re.compile(r'File ["\']([^"\']+\.(?:py))["\'],\s+line\s+(\d+)', re.IGNORECASE),
        re.compile(r'([^\s(:]+\.(?:js|ts|jsx|tsx)):(\d+):\d+', re.IGNORECASE),
        re.compile(r'at .*\(([^():]+\.(?:js|ts)):(\d+):\d+\)', re.IGNORECASE),
    ]
    for pattern in patterns:
        matches = pattern.findall(output)
        for raw_path, line_str in reversed(matches):
            raw_name = Path(raw_path).name
            for pf in project_files:
                if Path(pf).name == raw_name or pf == raw_path or raw_path.endswith(pf):
                    try:
                        return pf, int(line_str)
                    except ValueError:
                        return pf, None
    return None, None


# --------------------------------------------------------------------------
# Wireframe vision analysis
# --------------------------------------------------------------------------

def _analyze_wireframe_image(image_path: str) -> str:
    try:
        import PIL.Image
    except ImportError:
        return ""

    path = Path(image_path).expanduser()
    if not path.exists():
        return ""

    try:
        img = PIL.Image.open(path)
        model = _get_model(MODEL_VISION)
        prompt = (
            "This image is a website/app wireframe or mockup. Describe its layout "
            "precisely for a developer who cannot see it: header/nav, sections in "
            "top-to-bottom order, sidebars, key components (buttons, forms, cards, "
            "images), and roughly how many pages/screens it implies. Be concrete "
            "and structured, plain text, no markdown."
        )
        response = model.generate_content([prompt, img])
        return _strip_fences(response.text).strip()
    except Exception as e:
        return f"(Could not analyze wireframe image: {e})"


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------

def _infer_project_type(description: str) -> str:
    low = description.lower()
    if any(w in low for w in ("game", "platformer", "shooter", "puzzle game", "arcade")):
        return "game"
    if any(w in low for w in ("website", "web app", "webpage", "landing page", "web site", "webapp")):
        return "website"
    return "app"


def _default_tech_stack(project_type: str) -> str:
    return {
        "website": "plain HTML, CSS and JavaScript (no build step, runs by opening a static file server)",
        "game": "Python with the pygame library",
        "app": "Python",
        "script": "Python",
    }.get(project_type, "Python")


def _plan_project(
    description: str,
    project_type: str,
    tech_stack: str,
    language_hint: str,
    wireframe_text: str,
    pages: str,
    features: str,
) -> dict:
    model = _get_model(MODEL_PLANNER)

    context_bits = []
    if wireframe_text:
        context_bits.append(f"Wireframe / layout to follow:\n{wireframe_text}")
    if pages:
        context_bits.append(f"Pages/screens requested: {pages}")
    if features:
        context_bits.append(f"Key features/mechanics requested: {features}")
    context = ("\n\n".join(context_bits)) if context_bits else "(none given — use good judgement)"

    prompt = f"""You are a senior software architect and tech lead. Create a minimal, complete
file plan for this project.

Project type: {project_type}
Requested tech stack: {tech_stack}
{f"Language override: {language_hint}" if language_hint else ""}
Goal: {description}

Additional context:
{context}

Return ONLY valid JSON — no markdown, no explanation:
{{
  "project_name": "snake_case_name",
  "language": "primary programming language, e.g. python / javascript / csharp",
  "run_type": "python | node | static_web | none",
  "entry_point": "path to the main/entry file",
  "files": [
    {{
      "path": "relative/path.ext",
      "description": "what this file contains and does",
      "imports": ["dotted.or.relative module names this file imports from OTHER project files"]
    }}
  ],
  "run_command": "shell command to run the entry point, e.g. 'python main.py' or 'node server.js'; use 'none' if run_type is none",
  "dependencies": ["pip package names, empty list if none"],
  "npm_dependencies": ["npm package names, empty list if none"]
}}

Critical rules:
1. Pick "run_type" honestly based on the tech stack:
   - "python" for pure Python projects (including pygame games) — runnable with `python <entry_point>`.
   - "node" for Node/JS/TS backend or build-tool projects runnable with `node`/`npm`.
   - "static_web" for a plain HTML/CSS/JS site with NO backend and NO build step (just files opened via a static server).
   - "none" for stacks JARVIS cannot execute headlessly here (Unity, Godot, Flutter, native mobile, etc.) — still produce the full file plan, just mark run_type "none".
2. List files in DEPENDENCY ORDER — files with no project-internal imports first, entry point last.
3. "imports" lists other PROJECT files only (dot or relative notation), never third-party packages.
4. Keep the file count minimal but complete — no placeholders, this must be a real working project.
5. Use relative paths only.
6. Standard-library modules do NOT go in "dependencies".
7. For a website: include an index.html (or framework equivalent) and cover every page/section named in the context.
8. For a game: include a clear game loop, win/lose or scoring logic if implied, and any assets should be generated procedurally in code (no binary asset files).

JSON:"""

    try:
        response = model.generate_content(prompt)
        raw = _strip_fences(response.text)
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Planner returned invalid JSON: {e}\nRaw: {response.text[:300]}")
    except Exception as e:
        if _is_rate_limit(e):
            raise RateLimitError(str(e))
        raise


# --------------------------------------------------------------------------
# Writing files
# --------------------------------------------------------------------------

_LANG_RULES = {
    "python": (
        "- Use type hints for all function signatures.\n"
        "- Add docstrings for all public functions and classes.\n"
        "- Use `if __name__ == \"__main__\":` guard in the entry point.\n"
        "- For project-internal imports, match the file structure exactly "
        "(e.g. from utils.helpers import foo).\n"
        "- Create __init__.py files for any package subdirectory."
    ),
    "javascript": (
        "- Use ES modules (import/export) unless the plan clearly needs CommonJS (require) for a Node script.\n"
        "- Add JSDoc comments for exported functions.\n"
        "- Handle promise rejections with try/catch in async functions."
    ),
    "typescript": (
        "- Use explicit types on all function signatures and exported values.\n"
        "- Use ES modules (import/export).\n"
        "- Handle promise rejections with try/catch in async functions."
    ),
    "html": (
        "- Write complete, valid, semantic HTML5.\n"
        "- Link CSS/JS files with the exact relative paths used elsewhere in the plan.\n"
        "- Make it responsive with plain CSS (flexbox/grid), no external framework unless the tech stack names one."
    ),
    "css": "- Write clean, organized CSS. Use CSS variables for repeated colors/spacing. Make the layout responsive.",
    "csharp": (
        "- Follow standard C#/Unity conventions (PascalCase for methods/classes, camelCase for locals).\n"
        "- Add XML doc comments on public members.\n"
        "- If this is a Unity MonoBehaviour, use the standard Unity lifecycle methods correctly."
    ),
}


def _lang_rules_for(path: str, language: str) -> str:
    ext = Path(path).suffix.lower().lstrip(".")
    ext_map = {
        "py": "python", "js": "javascript", "jsx": "javascript",
        "ts": "typescript", "tsx": "typescript",
        "html": "html", "htm": "html", "css": "css",
        "cs": "csharp",
    }
    key = ext_map.get(ext, language.lower())
    return _LANG_RULES.get(key, "- Write complete, idiomatic, production-quality code with no placeholders.")


def _write_file(
    file_info: dict,
    project_description: str,
    all_files: list[dict],
    project_type: str,
    tech_stack: str,
    language: str,
    wireframe_text: str,
    project_dir: Path,
    already_written: dict[str, str],
) -> str:
    model = _get_model(MODEL_WRITER)

    file_path = file_info["path"]
    file_desc = file_info.get("description", "")
    file_imports = file_info.get("imports", [])

    file_list = "\n".join(
        f"  [{i+1}] {f['path']}: {f.get('description', '')}"
        for i, f in enumerate(all_files)
    )

    dependency_context = ""
    for dep in file_imports:
        dep_path = dep.replace(".", "/")
        for candidate in already_written:
            if candidate.startswith(dep_path) or Path(candidate).stem == Path(dep_path).stem:
                snippet = already_written[candidate][:2000]
                dependency_context += f"\n\n--- {candidate} (you must be consistent with this) ---\n{snippet}"
                break

    wireframe_block = f"\n\nWireframe/layout to follow for this file (if relevant):\n{wireframe_text}" if wireframe_text else ""

    prompt = f"""You are a senior {language} developer writing production-quality code for a real {project_type}.

Project goal: {project_description}
Tech stack: {tech_stack}

Complete project file structure (dependency order):
{file_list}
{f"Files this one depends on:{dependency_context}" if dependency_context else ""}
{wireframe_block}

Your task: write the complete, working code for: {file_path}
Purpose of this file: {file_desc}
{f"This file imports from: {', '.join(file_imports)}" if file_imports else "This file has no project-internal imports."}

{_lang_rules_for(file_path, language)}

General rules:
- Output ONLY raw code. No explanation, no markdown, no triple backticks.
- Write COMPLETE, RUNNABLE code — no placeholders, no "# TODO", no stub functions.
- Match import/link paths EXACTLY to the file paths in the project structure above.
- Use proper error handling wherever I/O, network, or user input is involved.
- The code must work when the entry point is run from the project root directory.

Code for {file_path}:"""

    try:
        response = model.generate_content(prompt)
        code = _strip_fences(response.text)

        full_path = project_dir / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(code, encoding="utf-8")
        return code
    except Exception as e:
        if _is_rate_limit(e):
            raise RateLimitError(str(e))
        raise


# --------------------------------------------------------------------------
# Dependencies
# --------------------------------------------------------------------------

def _install_pip(dependencies: list[str], project_dir: Path, log) -> None:
    if not dependencies:
        return
    to_install = []
    for dep in dependencies:
        pkg_name = re.split(r"[>=<!]", dep)[0].strip()
        if not pkg_name:
            continue
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", pkg_name],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            to_install.append(dep)
    if not to_install:
        log("All pip dependencies already installed.")
        return
    log(f"Installing pip packages: {', '.join(to_install)}")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install"] + to_install,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=180, cwd=str(project_dir),
        )
        log("pip install complete." if result.returncode == 0
            else f"pip install warning (non-fatal): {result.stderr[:200]}")
    except Exception as e:
        log(f"pip install error (non-fatal): {e}")


def _install_npm(npm_dependencies: list[str], project_dir: Path, log) -> bool:
    """Returns True if npm is usable, False if not found."""
    if not npm_dependencies:
        return shutil.which("npm") is not None
    npm = shutil.which("npm")
    if not npm:
        log("npm dependencies were requested but npm is not installed/found on PATH — "
            "install Node.js to install them and run this project.")
        return False
    log(f"Installing npm packages: {', '.join(npm_dependencies)}")
    try:
        result = subprocess.run(
            [npm, "install"] + npm_dependencies,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=180, cwd=str(project_dir), shell=(sys.platform == "win32"),
        )
        log("npm install complete." if result.returncode == 0
            else f"npm install warning (non-fatal): {result.stderr[:200]}")
    except Exception as e:
        log(f"npm install error (non-fatal): {e}")
    return True


# --------------------------------------------------------------------------
# Running / auto-fix loop
# --------------------------------------------------------------------------

def _open_vscode(project_dir: Path) -> bool:
    candidates = [
        "code",
        rf"C:\Users\{Path.home().name}\AppData\Local\Programs\Microsoft VS Code\bin\code.cmd",
        r"C:\Program Files\Microsoft VS Code\bin\code.cmd",
    ]
    for cmd in candidates:
        try:
            subprocess.Popen([cmd, str(project_dir)], shell=True,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1.0)
            return True
        except Exception:
            continue
    return False


def _run_project(run_command: str, project_dir: Path, timeout: int) -> str:
    try:
        parts = run_command.split()
        if parts and parts[0].lower() == "python":
            parts[0] = sys.executable

        result = subprocess.run(
            parts, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, cwd=str(project_dir),
        )
        stdout, stderr = result.stdout.strip(), result.stderr.strip()
        parts_out = []
        if stdout:
            parts_out.append(f"STDOUT:\n{stdout}")
        if stderr:
            parts_out.append(f"STDERR:\n{stderr}")
        return "\n\n".join(parts_out) if parts_out else "Ran with no output."
    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s — long-running app (server/game loop) is likely working."
    except FileNotFoundError as e:
        return f"Command not found: {e}"
    except Exception as e:
        return f"Run error: {e}"


def _try_auto_install_pip(error_output: str, project_dir: Path) -> bool:
    match = re.search(r"No module named ['\"]([a-zA-Z0-9_\-\.]+)['\"]", error_output, re.IGNORECASE)
    if not match:
        return False
    pkg = match.group(1).replace("_", "-").split(".")[0]
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", pkg],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, cwd=str(project_dir),
        )
        return result.returncode == 0
    except Exception:
        return False


def _fix_files(
    error_output: str,
    project_description: str,
    all_files: list[dict],
    file_codes: dict[str, str],
    language: str,
    project_dir: Path,
    entry_point: str,
) -> dict[str, str]:
    model = _get_model(MODEL_PLANNER)

    error_file, error_line = _parse_traceback(error_output, list(file_codes.keys()))
    error_type = _classify_error(error_output)

    files_to_fix: list[str] = []
    if error_file:
        files_to_fix.append(error_file)
        if error_type in ("import_error", "dependency_error"):
            for fi in all_files:
                if error_file.replace("/", ".").rsplit(".", 1)[0] in fi.get("imports", []):
                    if fi["path"] not in files_to_fix:
                        files_to_fix.append(fi["path"])
    else:
        files_to_fix.append(entry_point)

    updated: dict[str, str] = {}
    for fix_path in files_to_fix:
        current_code = file_codes.get(fix_path, "")
        other_ctx = ""
        for fp, code in file_codes.items():
            if fp != fix_path and code:
                snippet = code[:1500] + ("..." if len(code) > 1500 else "")
                other_ctx += f"\n--- {fp} ---\n{snippet}\n"

        line_hint = f"\nError appears near line {error_line} in this file." if (
            error_line and fix_path == error_file) else ""

        prompt = f"""You are an expert {language} debugger. Fix the broken file below.

Project goal: {project_description}

All project files:
{chr(10).join(f"  - {f['path']}: {f.get('description', '')}" for f in all_files)}

Other files for context (read-only — fix only the target file):
{other_ctx[:3500]}

File to fix: {fix_path}{line_hint}
Error type: {error_type}

Error output:
{error_output[:2500]}

Current (broken) code:
{current_code}

Rules:
- Output ONLY the complete fixed code. No explanation, no markdown, no backticks.
- Fix ALL errors visible in the error output.
- Keep all existing correct logic — do not remove working features.
- Ensure import/link paths match the actual project file structure exactly.

Fixed code for {fix_path}:"""

        try:
            response = model.generate_content(prompt)
            fixed = _strip_fences(response.text)
            full_path = project_dir / fix_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(fixed, encoding="utf-8")
            updated[fix_path] = fixed
        except Exception as e:
            if _is_rate_limit(e):
                raise RateLimitError(str(e))

    return updated


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def _build(
    description: str,
    project_type: str,
    tech_stack: str,
    language_hint: str,
    wireframe: str,
    wireframe_image_path: str,
    pages: str,
    features: str,
    project_name: str,
    timeout: int,
    open_editor: bool,
    player=None,
) -> str:

    def log(msg: str):
        print(f"[CodeArchitect] {msg}")
        if player:
            try:
                player.write_log(f"[CodeArchitect] {msg}")
            except Exception:
                pass

    project_type = (project_type or _infer_project_type(description)).strip().lower()
    if project_type not in ("website", "game", "app", "script"):
        project_type = "app"
    tech_stack = tech_stack.strip() if tech_stack else _default_tech_stack(project_type)

    wireframe_text = wireframe.strip() if wireframe else ""
    if wireframe_image_path:
        log("Analyzing wireframe image...")
        vision_desc = _analyze_wireframe_image(wireframe_image_path)
        if vision_desc:
            wireframe_text = (wireframe_text + "\n\n" + vision_desc).strip() if wireframe_text else vision_desc

    log(f"Planning {project_type} — stack: {tech_stack}")
    try:
        plan = _plan_project(description, project_type, tech_stack, language_hint,
                              wireframe_text, pages, features)
    except RateLimitError:
        return "Rate limit reached, sir. Please try again in a moment."
    except ValueError as e:
        return f"Planning failed: {e}"

    proj_name   = project_name or plan.get("project_name", "jarvis_project")
    proj_name   = re.sub(r"[^\w\-]", "_", proj_name)
    project_dir = PROJECTS_DIR / proj_name
    project_dir.mkdir(parents=True, exist_ok=True)

    files        = plan.get("files", [])
    entry_point  = plan.get("entry_point", "")
    run_command  = plan.get("run_command", "")
    run_type     = plan.get("run_type", "none")
    language     = plan.get("language", language_hint or "python")
    dependencies = plan.get("dependencies", [])
    npm_deps     = plan.get("npm_dependencies", [])

    if not files:
        return "I couldn't come up with a file plan for that, sir. Try adding more detail."

    log(f"Project: {proj_name} | Files: {len(files)} | run_type: {run_type}")

    sorted_files = sorted(files, key=lambda fi: len(fi.get("imports", [])))
    file_codes: dict[str, str] = {}

    for file_info in sorted_files:
        file_path = file_info.get("path", "")
        if not file_path:
            continue
        log(f"Writing {file_path}...")
        for attempt in range(2):
            try:
                code = _write_file(
                    file_info=file_info, project_description=description,
                    all_files=files, project_type=project_type, tech_stack=tech_stack,
                    language=language, wireframe_text=wireframe_text,
                    project_dir=project_dir, already_written=file_codes,
                )
                file_codes[file_path] = code
                time.sleep(0.3)
                break
            except RateLimitError:
                if attempt == 0:
                    log("Rate limit — waiting 20s...")
                    time.sleep(20)
            except Exception as e:
                log(f"Failed to write {file_path}: {e}")
                break

    if not file_codes:
        return "I could not write any project files, sir."

    if dependencies:
        _install_pip(dependencies, project_dir, log)
    npm_ok = True
    if run_type == "node" or npm_deps:
        npm_ok = _install_npm(npm_deps, project_dir, log)

    if open_editor:
        _open_vscode(project_dir)

    # --- run_type: none -> can't execute headlessly here, just report ---
    if run_type == "none" or not entry_point:
        return (
            f"'{proj_name}' is built, sir — {len(file_codes)} files written to "
            f"{project_dir}. This stack ({tech_stack}) needs its own editor/engine "
            f"to run, so I've written the full source and opened the folder rather "
            f"than executing it."
        )

    # --- static website: just prove the server boots, don't hunt for JS bugs ---
    if run_type == "static_web":
        port = _find_free_port()
        static_cmd = f"{sys.executable} -m http.server {port}"
        log(f"Starting a local server on port {port} to verify the site...")
        output = _run_project(static_cmd, project_dir, min(timeout, 5))
        if _has_error(output, static_cmd):
            return (
                f"'{proj_name}' is built ({len(file_codes)} files) but the local "
                f"server hit an issue starting:\n{output[:400]}\n"
                f"Files are saved at {project_dir} — check {entry_point} in VS Code."
            )
        return (
            f"'{proj_name}' is built and running, sir. Open http://localhost:{port} "
            f"to view it (run `python -m http.server {port}` from {project_dir} any "
            f"time to serve it again). Saved to: {project_dir}"
        )

    # --- python / node: real run + auto-fix loop ---
    if run_type == "node" and not npm_ok:
        return (
            f"'{proj_name}' is built ({len(file_codes)} files) at {project_dir}, but "
            f"Node.js/npm isn't installed here so I can't run or verify it. Install "
            f"Node.js and run `{run_command}` from that folder."
        )

    if not run_command or run_command.lower() == "none":
        run_command = f"{'node' if run_type == 'node' else 'python'} {entry_point}"

    last_output = ""
    auto_installs = 0
    for attempt in range(1, MAX_FIX_ATTEMPTS + 1):
        log(f"Running project (attempt {attempt}/{MAX_FIX_ATTEMPTS})...")
        last_output = _run_project(run_command, project_dir, timeout)

        if not _has_error(last_output, run_command):
            return (
                f"'{proj_name}' is working, sir. Built in {attempt} attempt"
                f"{'s' if attempt > 1 else ''}. Saved to: {project_dir}\n\n"
                f"Output:\n{last_output}"
            )

        if attempt == MAX_FIX_ATTEMPTS:
            break

        error_type = _classify_error(last_output)
        if error_type == "dependency_error" and run_type == "python" and auto_installs < 3:
            if _try_auto_install_pip(last_output, project_dir):
                auto_installs += 1
                log("Missing dependency installed, retrying...")
                time.sleep(1)
                continue

        log(f"Fixing errors (type: {error_type})...")
        try:
            updated = _fix_files(
                error_output=last_output, project_description=description,
                all_files=files, file_codes=file_codes, language=language,
                project_dir=project_dir, entry_point=entry_point,
            )
            file_codes.update(updated)
            time.sleep(1)
        except RateLimitError:
            return "Rate limit reached during fix. Project saved, check it manually in VS Code."
        except Exception as e:
            log(f"Fix step failed: {e}")

    return (
        f"I couldn't fully fix '{proj_name}' after {MAX_FIX_ATTEMPTS} attempts, sir. "
        f"Project is saved at {project_dir} — open it in VS Code and check manually.\n\n"
        f"Last error:\n{last_output[:600]}"
    )


# --------------------------------------------------------------------------
# Plugin entry point
# --------------------------------------------------------------------------

def run(parameters: dict, player=None, session_memory=None) -> str:
    p = parameters or {}
    description = (p.get("description") or "").strip()
    if not description:
        return "Tell me what to build, sir — a website, a game, or a project — and I'll get started."

    try:
        return _build(
            description=description,
            project_type=(p.get("project_type") or "").strip(),
            tech_stack=(p.get("tech_stack") or "").strip(),
            language_hint=(p.get("language") or "").strip(),
            wireframe=(p.get("wireframe") or "").strip(),
            wireframe_image_path=(p.get("wireframe_image_path") or "").strip(),
            pages=(p.get("pages") or "").strip(),
            features=(p.get("features") or "").strip(),
            project_name=(p.get("project_name") or "").strip(),
            timeout=int(p.get("timeout") or 30),
            open_editor=bool(p.get("open_editor", True)),
            player=player,
        )
    except Exception as e:
        return f"Sir, code_architect ran into a problem: {e}"
