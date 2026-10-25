"""
Mark-56 Ethical Security Assessment plugin.

Provides scoped Linux security assessment: dependency preflight, host discovery,
service/port inventory, and non-exploitative Nmap safe-category checks. It does
not execute exploit payloads, brute-force credentials, evade detection, or
persistently access discovered hosts.
"""
from __future__ import annotations

import ipaddress
import os
import platform
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET

PLUGIN = {
    "name": "ethical_security_assessment",
    "description": (
        "Jarvis ethical hacking and security assessment skill for Linux. Use for "
        "authorized security work: preflight checks, discover hosts in an explicitly "
        "approved IP/CIDR scope, scan ports/services, run non-exploitative Nmap "
        "safe-category checks, explain the last assessment, and report evidence. "
        "Always ask for explicit authorization and exact target scope before scanning. "
        "Never use this tool to exploit devices, gain access, steal data, evade controls, "
        "or test devices on a shared network without their owner's permission. "
        "Actions: preflight, discover, scan, safe_checks, status, explain. "
        "Windows is intentionally unsupported."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "One of: preflight, discover, scan, safe_checks, status, explain."},
            "target": {"type": "STRING", "description": "Exact authorized hostname, IP address, or CIDR. CIDR is supported for discover only and must be /24 or narrower."},
            "authorized": {"type": "BOOLEAN", "description": "Must be true only after the user explicitly confirms they own the target or have permission to test it."},
            "ports": {"type": "STRING", "description": "Optional explicit port list/range, e.g. 22,80,443 or 1-1024. Nmap validates it."},
            "confirm_intrusive": {"type": "BOOLEAN", "description": "Reserved for future approval-gated checks; this plugin does not perform exploit execution."},
        },
        "required": ["action"],
    },
    "behavior": "NON_BLOCKING",
    "scheduling": "WHEN_IDLE",
}

_LAST_REPORT: dict = {
    "status": "idle", "started_at": None, "finished_at": None, "action": None,
    "target": None, "command": [], "summary": "No assessment has been run in this session.",
    "output": "", "findings": [],
}
_RUNNING = False
_MAX_OUTPUT = 14000
_TIMEOUT_SECONDS = 240


def _log(player, message: str) -> None:
    if player:
        try:
            player.write_log(f"SECURITY: {message}")
        except Exception:
            pass


def _show(player, title: str, body: str) -> None:
    if player:
        try:
            if hasattr(player, "show_content"):
                player.show_content(title, body)
        except Exception:
            pass


def _validate_target(raw: str, allow_cidr: bool = False) -> tuple[str | None, str | None]:
    target = (raw or "").strip()
    if not target or len(target) > 253 or any(c in target for c in " \t\r\n;&|$<>"):
        return None, "Provide one exact hostname, IP address, or approved CIDR; shell syntax and multiple targets are not accepted."
    if target.startswith("-") or ("/" in target and not allow_cidr):
        return None, "CIDR is allowed only for host discovery. Port and safe-check actions require one host."
    try:
        if "/" in target:
            network = ipaddress.ip_network(target, strict=False)
            if network.num_addresses > 256:
                return None, "For safety, discovery is limited to 256 addresses per run (IPv4 /24 or narrower)."
            return str(network), None
        try:
            return str(ipaddress.ip_address(target)), None
        except ValueError:
            pass
        if not re.fullmatch(
            r"(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(?:\.(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?))*\.?",
            target,
        ):
            return None, "Target must be a valid hostname or IP address."
        return target.rstrip("."), None
    except ValueError as exc:
        return None, f"Invalid target scope: {exc}"


def _preflight() -> str:
    if platform.system() != "Linux":
        return f"This feature is unavailable on {platform.system()}. Mark-56's ethical security assessment skill is enabled only on supported Linux systems."
    nmap = shutil.which("nmap")
    if not nmap:
        return "Linux detected, but Nmap is not installed or not on PATH. Install it using your distribution's trusted package manager, then run preflight again. No scan was started."
    try:
        version = subprocess.run([nmap, "--version"], capture_output=True, text=True, timeout=8, check=False)
        first = (version.stdout or version.stderr).splitlines()
        version_line = first[0] if first else "Nmap version could not be read"
    except Exception as exc:
        return f"Nmap was found at {nmap}, but its version check failed: {exc}"
    extras = [f"{binary}: {'available' if shutil.which(binary) else 'not installed'}" for binary in ("ip", "ss", "xdg-open")]
    return f"Preflight passed on Linux. {version_line}. Path: {nmap}. " + "; ".join(extras) + ". Some scan types need elevated privileges; this plugin uses TCP connect/service checks and does not request sudo."


def _parse_nmap(xml_text: str) -> list[str]:
    findings: list[str] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return ["Nmap returned output that could not be parsed as XML; review the raw output."]
    for host in root.findall("host"):
        status = host.find("status")
        state = status.get("state", "unknown") if status is not None else "unknown"
        addresses = [a.get("addr") for a in host.findall("address") if a.get("addr")]
        names = [n.get("name") for n in host.findall("./hostnames/hostname") if n.get("name")]
        label = ", ".join(addresses + names) or "unknown host"
        findings.append(f"Host {label}: {state}")
        for port in host.findall("./ports/port"):
            state_node, service = port.find("state"), port.find("service")
            state_name = state_node.get("state", "unknown") if state_node is not None else "unknown"
            if state_name in ("open", "open|filtered"):
                proto, portid = port.get("protocol", "tcp"), port.get("portid", "?")
                svc = service.get("name", "unknown") if service is not None else "unknown"
                product = service.get("product", "") if service is not None else ""
                version = service.get("version", "") if service is not None else ""
                details = " ".join(p for p in (product, version) if p).strip()
                findings.append(f"  {proto}/{portid} {state_name}: {svc}" + (f" ({details})" if details else ""))
        for script in host.findall(".//script"):
            sid, output = script.get("id", "script"), (script.get("output") or "").strip().replace("\n", " ")
            if output:
                findings.append(f"  Safe check {sid}: {output[:500]}")
    if not findings:
        findings.append("No hosts or open ports were reported in the parsed results.")
    return findings


def _run_nmap(action: str, target: str, ports: str = "", player=None) -> str:
    global _LAST_REPORT, _RUNNING
    if _RUNNING:
        return "A security assessment is already running. Use status or explain to inspect progress; do not start a second scan."
    if platform.system() != "Linux":
        return _preflight()
    nmap = shutil.which("nmap")
    if not nmap:
        return _preflight()
    normalized, error = _validate_target(target, allow_cidr=(action == "discover"))
    if error:
        return error
    if action == "discover":
        command = [nmap, "-sn", "-oX", "-", normalized]
    else:
        command = [nmap, "-sT", "-sV", "--version-light", "-T3", "--reason", "-oX", "-"]
        if ports:
            if len(ports) > 100 or not re.fullmatch(r"[0-9,\-]+", ports) or ports.startswith("-") or ports.endswith("-"):
                return "Invalid port specification. Use a list such as 22,80,443 or a range such as 1-1024."
            command += ["-p", ports]
        else:
            command += ["--top-ports", "1000"]
        if action == "safe_checks":
            command += ["--script", "safe"]
        command.append(normalized)

    _RUNNING = True
    _LAST_REPORT = {
        "status": "running", "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "finished_at": None, "action": action, "target": normalized,
        "command": command, "summary": f"{action} is running against {normalized}.",
        "output": "", "findings": [],
    }
    _log(player, f"Starting {action} against authorized scope {normalized}.")
    _log(player, "Phase 1/3: executing the selected non-exploitative scan and collecting Nmap XML output.")
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=_TIMEOUT_SECONDS, check=False, env={**os.environ, "LC_ALL": "C"})
        stdout, stderr = completed.stdout or "", completed.stderr or ""
        findings = _parse_nmap(stdout) if stdout.strip() else []
        if completed.returncode != 0:
            summary = f"Nmap exited with code {completed.returncode}." + (f" Error: {stderr.strip()[:1200]}" if stderr.strip() else "")
            status = "failed"
        elif not stdout.strip():
            summary, status = "Nmap completed without XML output; no findings can be confirmed.", "failed"
        else:
            summary = f"{action.replace('_', ' ').title()} completed for {normalized}. Parsed {len(findings)} evidence line(s)."
            status = "completed"
        _LAST_REPORT.update({
            "status": status, "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "summary": summary, "output": (stdout + ("\nNMAP STDERR:\n" + stderr if stderr else ""))[-_MAX_OUTPUT:],
            "findings": findings, "returncode": completed.returncode,
        })
        _log(player, f"Phase 2/3: process ended with exit code {completed.returncode}; parsing result evidence.")
        body = summary + "\n\n" + "\n".join(findings[:100])
        if stderr.strip():
            body += "\n\nScanner messages:\n" + stderr.strip()[:1500]
        _show(player, f"SECURITY ASSESSMENT — {action.upper()}", body[:_MAX_OUTPUT])
        _log(player, "Phase 3/3: report prepared. Findings are scanner evidence, not proof of exploitability.")
        return body[:_MAX_OUTPUT]
    except subprocess.TimeoutExpired:
        _LAST_REPORT.update({"status": "timed_out", "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"), "summary": f"Scan timed out after {_TIMEOUT_SECONDS} seconds. It was stopped; results may be incomplete."})
        _log(player, _LAST_REPORT["summary"])
        return _LAST_REPORT["summary"]
    except Exception as exc:
        _LAST_REPORT.update({"status": "failed", "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"), "summary": f"Assessment failed: {type(exc).__name__}: {exc}"})
        _log(player, _LAST_REPORT["summary"])
        return _LAST_REPORT["summary"]
    finally:
        _RUNNING = False


def run(parameters: dict, player=None, session_memory=None) -> str:
    params = parameters or {}
    action = str(params.get("action") or "").strip().lower()
    if action not in {"preflight", "discover", "scan", "safe_checks", "status", "explain"}:
        return "Unknown action. Choose preflight, discover, scan, safe_checks, status, or explain."
    if action == "preflight":
        return _preflight()
    if action in {"status", "explain"}:
        report = _LAST_REPORT
        if action == "status":
            return f"Assessment status: {report.get('status')}. Action: {report.get('action') or 'none'}. Target: {report.get('target') or 'none'}. Summary: {report.get('summary')}"
        if report.get("action") is None:
            return "No assessment has run in this session. Start with preflight, then define an explicitly authorized target and choose discover, scan, or safe_checks."
        return (
            f"Current phase/status: {report.get('status')}. Action: {report.get('action')}. Target: {report.get('target')}. "
            f"Command recorded: {' '.join(report.get('command') or [])}. Result: {report.get('summary')}\nEvidence:\n"
            + "\n".join((report.get("findings") or [])[:40])
        )
    if params.get("authorized") is not True:
        return "Before scanning, explicitly confirm that you own this target or have permission to test it. Set authorized=true only after the user has confirmed; no scan was started."
    target = str(params.get("target") or "")
    if not target:
        return "Give the exact authorized target (IP, hostname, or CIDR for discovery). No scan was started."
    if action == "safe_checks":
        _log(player, "Safe-check mode uses Nmap's safe script category only; it does not execute exploits.")
    return _run_nmap(action, target, str(params.get("ports") or "").strip(), player=player)
