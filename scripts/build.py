"""Build MARK LV into a Windows installer.

    py -3 scripts\\build.py                 full build  ->  dist\\MARK-LV-Setup-<version>.exe
    py -3 scripts\\build.py --stage-only    stage + secret scan + static checks only
                                           (no Windows needed; useful on any machine)

Pipeline
  1  clean            remove build\\stage and dist
  2  stage            copy the app, leaving out secrets / personal data / dev files
  3  secret scan      FAIL the build if a key, token or private key slipped in
  4  runtime          private CPython (embeddable) + every dependency, built once and cached
  5  smoke test       the *bundled* interpreter imports everything the app needs
  6  installer        Inno Setup compiles installer\\MarkLV.iss
  7  validate         size, PE header, SHA-256, build-info.json

Needs on the build machine: Windows 10/11 x64, Python 3.9+ (just to run this
script), Inno Setup 6.3+ (https://jrsoftware.org/isinfo.php), internet access.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
STAGE = BUILD / "stage"
DIST = ROOT / "dist"
INSTALLER = ROOT / "installer"

DEFAULT_PYTHON = "3.14.6"   # last 3.14 with binary installers; all wheels exist for it

# ── what must never ship ──────────────────────────────────────────────────────
GENERIC_SKIP_DIRS = {".git", ".vscode", ".idea", "__pycache__", "venv", ".venv", "node_modules"}
ROOT_SKIP_DIRS = {"installer", "scripts", "build", "dist"}
SKIP_PREFIXES = ("config/certs", "config/whatsapp_web", "cache", "uploads", "logs")
SKIP_FILES = {
    "config/api_keys.json",            # Gemini key + per-plugin credentials
    "memory/long_term.json",           # what the assistant has learned about its user
    "plugins/mail_account_config.json",
    "setup.py", "requirements2.txt", ".gitignore", "INSTALLER_BUILD.md",
}
SKIP_PATTERNS = ("*.pyc", "*.pyo", "*.log", "*.db", "token*.json", "client_secret*.json",
                 "*credentials*.json", ".env", ".env.*")
SKIP_REL_GLOBS = ("plugins/*.zip",)   # e.g. "Hostinger VPS.zip" — not a plugin

SECRET_PATTERNS = {
    "Google/Gemini API key": re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    "Telegram bot token": re.compile(r"\b\d{8,10}:[A-Za-z0-9_\-]{35}\b"),
    "PEM private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    "OpenAI-style key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{32,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Google OAuth client secret": re.compile(r"GOCSPX-[A-Za-z0-9_\-]{20,}"),
    # a credential-looking JSON value that is not an obvious placeholder
    "api key in JSON": re.compile(
        r'"[a-z_]*(?:api_key|secret|password)"\s*:\s*"(?!your|<|example|change|xxx|\.\.\.)[^"\s]{16,}"', re.I),
}

# Files that ship as templates but contain a real-looking value upstream. The build blanks the value in the
# STAGED copy only (your source is never touched) and says so; any other file with a hit still fails the build.
SANITIZE = {
    "plugins/mail_account_config.example.json": [
        (re.compile(r"GOCSPX-[A-Za-z0-9_\-]{20,}"), "your-google-oauth-client-secret"),
    ],
}
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".bmp", ".zip", ".whl", ".dll", ".pyd", ".exe"}


def step(n: int, title: str) -> None:
    print(f"\n[{n}] {title}\n" + "-" * (len(title) + 5))


def die(msg: str) -> None:
    print(f"\nBUILD FAILED: {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd, **kw) -> None:
    print("  $", " ".join(str(c) for c in cmd))
    r = subprocess.run([str(c) for c in cmd], **kw)
    if r.returncode != 0:
        die(f"command failed with exit code {r.returncode}")


# ── 2: staging ────────────────────────────────────────────────────────────────
def skipped(rel: str, is_dir: bool) -> bool:
    name = rel.rsplit("/", 1)[-1]
    parts = rel.split("/")
    if is_dir:
        if name in GENERIC_SKIP_DIRS or (len(parts) == 1 and name in ROOT_SKIP_DIRS):
            return True
        return any(rel == p or rel.startswith(p + "/") for p in SKIP_PREFIXES)
    return (rel in SKIP_FILES
            or any(fnmatch.fnmatch(name, p) for p in SKIP_PATTERNS)
            or any(fnmatch.fnmatch(rel, g) for g in SKIP_REL_GLOBS))


def stage_source() -> list[str]:
    left_out: list[str] = []

    def walk(src: Path, rel: str = "") -> None:
        for item in sorted(src.iterdir()):
            r = f"{rel}/{item.name}" if rel else item.name
            if skipped(r, item.is_dir()):
                left_out.append(r + ("/" if item.is_dir() else ""))
                continue
            dest = STAGE / r
            if item.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
                walk(item, r)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest)

    STAGE.mkdir(parents=True, exist_ok=True)
    walk(ROOT)
    shutil.copy2(INSTALLER / "launcher.pyw", STAGE / "launcher.pyw")
    for rel, rules in SANITIZE.items():
        f = STAGE / rel
        if f.is_file():
            text = f.read_text(encoding="utf-8")
            for rx, repl in rules:
                text, n = rx.subn(repl, text)
                if n:
                    print(f"  SANITIZED {rel}: replaced {n} secret-looking value(s) with a placeholder")
            f.write_text(text, encoding="utf-8")
    return left_out


# ── 3: secret scan ────────────────────────────────────────────────────────────
def scan_for_secrets(tree: Path) -> list[str]:
    hits = []
    for p in tree.rglob("*"):
        if not p.is_file() or p.suffix.lower() in BINARY_EXT or p.stat().st_size > 8_000_000:
            continue
        text = p.read_bytes().decode("latin-1")
        for label, rx in SECRET_PATTERNS.items():
            if rx.search(text):
                hits.append(f"{p.relative_to(tree).as_posix()}  <- {label}")
    return hits


# ── 4: runtime ────────────────────────────────────────────────────────────────
def download(url: str, dest: Path) -> Path:
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  downloading {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.replace(dest)
    return dest


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def merged_requirements() -> Path:
    base = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    extra = (INSTALLER / "requirements-extra.txt").read_text(encoding="utf-8")
    out = BUILD / "requirements-bundle.txt"
    out.write_text(base.rstrip() + "\n\n" + extra, encoding="utf-8")
    return out


def build_runtime(py_version: str, expected_sha: str | None, force: bool) -> Path:
    """Build (or reuse) build/runtime: embeddable CPython + all dependencies."""
    if os.name != "nt":
        die("full runtime/installer builds must run on Windows 10/11 x64; use --stage-only on Linux/macOS")

    req = merged_requirements()
    stamp = hashlib.sha256(
        (py_version + req.read_text(encoding="utf-8")).encode()
    ).hexdigest()

    rt = BUILD / "runtime"
    marker = rt / ".bundle-hash"

    # Reuse the runtime only when the runtime and its build marker both exist.
    # This prevents a partially-created runtime from causing a FileNotFoundError.
    if (
        rt.exists()
        and marker.is_file()
        and marker.read_text(errors="ignore").strip() == stamp
        and not force
    ):
        print("  reusing cached runtime (python + requirements unchanged; --rebuild-runtime to force)")
        return rt

    # Remove an incomplete or outdated runtime.
    if rt.exists():
        print("  removing incomplete/outdated bundled runtime")
        shutil.rmtree(rt)

    cache = BUILD / "cache"

    # Download the requested embedded Python version.
    url = (
        f"https://www.python.org/ftp/python/{py_version}/"
        f"python-{py_version}-embed-amd64.zip"
    )

    zpath = download(
        url,
        cache / f"python-{py_version}-embed-amd64.zip"
    )

    digest = sha256(zpath)
    print(f"  python embeddable sha256: {digest}")

    if expected_sha and digest.lower() != expected_sha.lower():
        die("Python download does not match --python-sha256")

    # Extract the embedded Python runtime.
    shutil.unpack_archive(zpath, rt)

    # Configure the embedded Python so it can import:
    #   - the embedded standard library
    #   - the runtime directory
    #   - the application directory
    #   - installed site-packages
    pth = next(rt.glob("python*._pth"))
    stem = pth.name.split("._pth")[0]

    pth.write_text(
        f"{stem}.zip\n"
        ".\n"
        "..\n"
        "Lib\\site-packages\n"
        "\n"
        "import site\n",
        encoding="ascii"
    )

    py = rt / "python.exe"

    # Bootstrap pip into the bundled Python.
    getpip = download(
        "https://bootstrap.pypa.io/get-pip.py",
        cache / "get-pip.py"
    )

    run([
        py,
        getpip,
        "--no-warn-script-location",
        "--disable-pip-version-check"
    ])

    # IMPORTANT:
    # The embedded Python does not necessarily contain setuptools/wheel.
    # Install them before installing the application's requirements so
    # packages using setuptools.build_meta can build correctly.
    print("  installing packaging build tools: pip, setuptools, wheel")

    run([
        py,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--no-warn-script-location",
        "--disable-pip-version-check",
        "--no-cache-dir",
        "pip",
        "setuptools",
        "wheel",
    ])

    # Install the complete application dependency set.
    print("  installing application requirements")

    run([
        py,
        "-m",
        "pip",
        "install",
        "--no-warn-script-location",
        "--disable-pip-version-check",
        "--no-cache-dir",
        "--prefer-binary",
        "-r",
        req,
    ])

    # Mark the runtime as complete only AFTER every dependency installed
    # successfully. This prevents partially-built runtimes from being
    # mistaken for valid cached runtimes.
    marker.write_text(stamp, encoding="utf-8")

    return rt


# ── 6: Inno Setup ─────────────────────────────────────────────────────────────
def find_iscc() -> Path:
    cands = [os.environ.get("ISCC", ""), shutil.which("ISCC.exe") or ""]
    for var in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if base:
            cands += [os.path.join(base, "Inno Setup 6", "ISCC.exe"),
                      os.path.join(base, "Programs", "Inno Setup 6", "ISCC.exe")]
    for c in cands:
        if c and Path(c).is_file():
            return Path(c)
    die("Inno Setup 6 not found. Install it from https://jrsoftware.org/isdl.php "
        "(or set the ISCC environment variable to ISCC.exe).")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", help="override installer\\version.txt")
    ap.add_argument("--python", default=DEFAULT_PYTHON, help=f"bundled CPython (default {DEFAULT_PYTHON})")
    ap.add_argument("--python-sha256", help="pin the Python download's SHA-256")
    ap.add_argument("--rebuild-runtime", action="store_true", help="ignore the cached runtime")
    ap.add_argument("--stage-only", action="store_true", help="stage + scan + static checks, then stop")
    ap.add_argument("--skip-installer", action="store_true", help="build the runtime + smoke test, no .exe")
    ap.add_argument("--sign-command", help='Inno sign command, e.g. "signtool sign /f my.pfx /fd sha256 $f"')
    args = ap.parse_args()

    version = (args.version or (INSTALLER / "version.txt").read_text().strip())
    if not re.fullmatch(r"\d+\.\d+\.\d+(\.\d+)?", version):
        die(f"version '{version}' must look like 1.2.3")
    print(f"MARK LV installer build — version {version}")

    step(1, "clean")
    for d in (STAGE, DIST):
        if d.exists():
            shutil.rmtree(d)
    BUILD.mkdir(exist_ok=True)

    step(2, "stage application files")
    left_out = stage_source()
    (STAGE / "VERSION").write_text(version + "\n", encoding="utf-8")
    n = sum(1 for p in STAGE.rglob("*") if p.is_file())
    print(f"  staged {n} files; left out {len(left_out)} entries:")
    for item in left_out:
        print("    -", item)

    step(3, "secret scan")
    hits = scan_for_secrets(STAGE)
    if hits:
        die("secrets found in the staged files:\n    " + "\n    ".join(hits))
    print("  clean: no keys, tokens or private keys in the package")

    step(4, "static smoke test")
    run([sys.executable, INSTALLER / "smoke_test.py", STAGE, "--static"])
    if args.stage_only:
        print(f"\nStaged OK at {STAGE}. (--stage-only: stopping before the runtime build.)")
        return

    step(5, "bundled Python runtime")
    rt = build_runtime(args.python, args.python_sha256, args.rebuild_runtime)
    shutil.copytree(rt, STAGE / "runtime")

    step(6, "smoke test with the bundled interpreter")
    run([STAGE / "runtime" / "python.exe", INSTALLER / "smoke_test.py", STAGE])
    for pc in STAGE.rglob("__pycache__"):          # never ship caches we just made in the app tree
        if "runtime" not in pc.relative_to(STAGE).parts:
            shutil.rmtree(pc, ignore_errors=True)
    if args.skip_installer:
        print("\n--skip-installer: done after smoke test.")
        return

    step(7, "preflight installer assets")
    required_assets = [
        INSTALLER / "MarkLV.iss",
        INSTALLER / "launcher.pyw",
        INSTALLER / "version.txt",
        INSTALLER / "assets" / "wizard-large.bmp",
        INSTALLER / "assets" / "wizard-small.bmp",
    ]
    for asset in required_assets:
        if not asset.is_file():
            die(f"missing installer asset: {asset}")
    print("  installer assets: OK")

    step(8, "compile installer (Inno Setup)")
    iscc = find_iscc()
    DIST.mkdir(exist_ok=True)
    info = ".".join((version.split(".") + ["0"] * 4)[:4])      # Inno wants n.n.n.n for the exe's version resource
    cmd = [iscc, f"/DAppVersion={version}", f"/DAppVersionInfo={info}", f"/DStageDir={STAGE}", f"/DOutDir={DIST}"]
    if args.sign_command:
        cmd += [f"/SMarkSign={args.sign_command}", "/DSignToolName=MarkSign"]
    run(cmd + [INSTALLER / "MarkLV.iss"])

    step(9, "validate output")
    exe = DIST / f"MARK-LV-Setup-{version}.exe"
    if not exe.is_file():
        die(f"expected {exe.name} was not produced")
    if exe.stat().st_size < 20_000_000:
        die(f"{exe.name} is only {exe.stat().st_size:,} bytes — the runtime was probably not included")
    if exe.read_bytes()[:2] != b"MZ":
        die("output is not a Windows executable")
    digest = sha256(exe)
    (DIST / "SHA256SUMS.txt").write_text(f"{digest}  {exe.name}\n")
    (DIST / "build-info.json").write_text(json.dumps(
        {"version": version, "python": args.python, "sha256": digest, "size": exe.stat().st_size,
         "signed": bool(args.sign_command)}, indent=2))
    print(f"  {exe}  ({exe.stat().st_size / 1e6:.0f} MB)\n  sha256 {digest}")
    if not args.sign_command:
        print("  NOTE: unsigned — Windows SmartScreen will warn on first run (see INSTALLER_BUILD.md).")
    print("\nBUILD OK")


if __name__ == "__main__":
    main()
