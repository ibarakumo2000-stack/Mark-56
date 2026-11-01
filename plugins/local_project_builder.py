"""Offline project scaffolder; creates starter projects without an AI provider."""
from __future__ import annotations
import json, os
from pathlib import Path

_TEMPLATES = {
 "portfolio": {
  "index.html": "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Portfolio</title><link rel=\"stylesheet\" href=\"style.css\"></head><body><header>YOUR NAME</header><main><section class=\"hero\"><p>DESIGN · BUILD · CREATE</p><h1>Ideas made real.</h1><p>Introduce yourself and your work.</p><a href=\"#projects\">Explore projects</a></section><section id=\"projects\"><h2>Selected work</h2><div class=\"projects\"><article><h3>Project One</h3><p>Describe the problem, approach and result.</p></article><article><h3>Project Two</h3><p>Describe the problem, approach and result.</p></article></div></section></main><footer>© Your Name</footer><script src=\"app.js\"></script></body></html>\n",
  "style.css": ":root{color-scheme:dark;--bg:#071018;--panel:#101e29;--ink:#edf7ff;--accent:#66d9ef}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,sans-serif}header,main,footer{width:min(1080px,92%);margin:auto}header{padding:24px 0}.hero{padding:12vh 0 10vh;max-width:780px}.hero h1{font-size:clamp(3rem,8vw,6rem);line-height:1.02;margin:.2em 0}.hero a{color:var(--accent)}section{padding:40px 0}.projects{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}article{padding:24px;background:var(--panel);border:1px solid #243b4a;border-radius:14px}footer{padding:32px 0;color:#9bb2c0}\n",
  "app.js": "'use strict';\n// Add accessible interactions here as the project grows.\n",
  "README.md": "# Portfolio starter\n\nOpen index.html in a browser. Customize projects, copy and styles. Test mobile layouts, keyboard navigation, contrast, metadata and performance before deployment.\n"},
 "web_app": {
  "index.html": "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Web App Starter</title><link rel=\"stylesheet\" href=\"style.css\"></head><body><main><h1>Web App Starter</h1><p>A small, provider-free browser application.</p><label for=\"task\">Add a task</label><form id=\"form\"><input id=\"task\" required maxlength=\"160\"><button>Add</button></form><ul id=\"tasks\"></ul></main><script src=\"app.js\"></script></body></html>\n",
  "style.css": "body{font:16px/1.5 system-ui,sans-serif;max-width:760px;margin:10vh auto;padding:0 20px;background:#0a1119;color:#edf7ff}input,button{font:inherit;padding:10px;border-radius:8px}input{width:min(70%,440px)}button{cursor:pointer}li{margin:.5rem 0}\n",
  "app.js": "'use strict';\nconst form=document.querySelector('#form');const input=document.querySelector('#task');const list=document.querySelector('#tasks');form.addEventListener('submit',event=>{event.preventDefault();const text=input.value.trim();if(!text)return;const item=document.createElement('li');item.textContent=text;list.append(item);input.value='';input.focus();});\n",
  "README.md": "# Web app starter\n\nStatic HTML/CSS/JavaScript. No AI provider or external runtime dependency. Run a local static server before testing. This is a starter, not a production backend.\n"},
 "game": {
  "index.html": "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Canvas Game</title><link rel=\"stylesheet\" href=\"style.css\"></head><body><main><h1>Catch the Dot</h1><p>Click the target. Score: <output id=\"score\">0</output></p><canvas id=\"game\" width=\"640\" height=\"400\" aria-label=\"Game field\"></canvas><button id=\"reset\">Reset</button></main><script src=\"game.js\"></script></body></html>\n",
  "style.css": "body{font:16px system-ui,sans-serif;background:#071018;color:#edf7ff;text-align:center;margin:32px}canvas{display:block;width:min(100%,640px);height:auto;margin:20px auto;border:1px solid #345;background:#101e29}button{padding:10px 18px;cursor:pointer}\n",
  "game.js": "'use strict';\nconst canvas=document.querySelector('#game');const ctx=canvas.getContext('2d');const score=document.querySelector('#score');let points=0;let target={x:320,y:200,r:18};function draw(){ctx.clearRect(0,0,canvas.width,canvas.height);ctx.beginPath();ctx.arc(target.x,target.y,target.r,0,Math.PI*2);ctx.fillStyle='#66d9ef';ctx.fill();}canvas.addEventListener('click',event=>{const rect=canvas.getBoundingClientRect();const x=(event.clientX-rect.left)*canvas.width/rect.width;const y=(event.clientY-rect.top)*canvas.height/rect.height;if(Math.hypot(x-target.x,y-target.y)<=target.r){points++;score.value=String(points);target.x=target.r+Math.random()*(canvas.width-2*target.r);target.y=target.r+Math.random()*(canvas.height-2*target.r);draw();}});document.querySelector('#reset').addEventListener('click',()=>{points=0;score.value='0';draw();});draw();\n",
  "README.md": "# Canvas game starter\n\nOpen index.html in a browser. Extend with controls, collision logic, levels and accessibility improvements.\n"},
 "python_cli": {
  "main.py": "def main() -> None:\n    print('Hello from your local Python project!')\n\nif __name__ == '__main__':\n    main()\n",
  "test_main.py": "import unittest\nfrom main import main\n\nclass StarterTests(unittest.TestCase):\n    def test_module_imports(self):\n        self.assertTrue(callable(main))\n\nif __name__ == '__main__':\n    unittest.main()\n",
  "README.md": "# Python CLI starter\n\nRun python main.py and test with python -m unittest -v.\n"}
}
def _root() -> Path:
    raw=os.environ.get("MARK56_WORKSPACE","").strip()
    root=Path(raw).expanduser() if raw else Path.cwd()
    root=root.resolve()
    if not root.is_dir(): raise ValueError("Configured workspace directory does not exist.")
    return root

def run(parameters: dict, **_context) -> str:
    p=parameters or {}; kind=str(p.get("template") or "").strip().lower()
    if kind not in _TEMPLATES: return json.dumps({"error":"Choose portfolio, web_app, game, or python_cli."})
    name=str(p.get("project_name") or "").strip()
    if not name or len(name)>48 or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in name):
        return json.dumps({"error":"Project name must use letters, numbers, hyphens or underscores (max 48 chars)."})
    root=_root(); target=(root/name).resolve()
    if not target.is_relative_to(root) or target==root: return json.dumps({"error":"Project path escapes the workspace."})
    if target.exists(): return json.dumps({"error":"Destination already exists; nothing was overwritten.","path":str(target)})
    if p.get("confirmed") is not True:
        return json.dumps({"needs_confirmation":True,"template":kind,"project_name":name,"files":list(_TEMPLATES[kind]),"message":"Confirm to create this project locally. No network or AI provider is used."})
    try:
        target.mkdir(parents=False,exist_ok=False)
        for rel, content in _TEMPLATES[kind].items(): (target/rel).write_text(content,encoding="utf-8")
        return json.dumps({"ok":True,"path":str(target),"template":kind,"files":list(_TEMPLATES[kind]),"provider_required":False,"next_steps":"Open the project, run tests where available, and validate behavior in the target environment."})
    except Exception as exc: return json.dumps({"ok":False,"error":type(exc).__name__,"message":str(exc)[:200]})

PLUGIN={"name":"local_project_builder","description":"Build starter portfolio websites, static web apps, browser games, or Python CLI projects locally without an AI provider. Creates only a new folder inside the configured workspace; requires confirmed=true and never overwrites existing files.","parameters":{"type":"OBJECT","properties":{"template":{"type":"STRING","description":"portfolio | web_app | game | python_cli"},"project_name":{"type":"STRING","description":"New folder name in workspace"},"confirmed":{"type":"BOOLEAN","description":"Explicitly approve creating the new project folder"}},"required":["template","project_name"]}}
