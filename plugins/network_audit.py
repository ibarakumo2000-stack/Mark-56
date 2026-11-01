"""Linux-only, explicitly scoped defensive network inventory.

This plugin performs bounded host discovery and TCP service inventory only.
It does not run exploit scripts, brute force credentials, evade monitoring, or
attempt access to discovered devices. Only private/local IPv4 CIDRs are accepted.
"""
from __future__ import annotations

import ipaddress
import json
import platform
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

TIMEOUT_SECONDS = 120
MAX_HOSTS = 256


def _scope(raw: str):
    if platform.system() != "Linux":
        raise ValueError("Network audit is available only on Linux.")
    try:
        net = ipaddress.ip_network(str(raw).strip(), strict=False)
    except ValueError as exc:
        raise ValueError("Provide a valid IPv4 CIDR, e.g. 192.168.1.0/24.") from exc
    if net.version != 4 or not (net.is_private or net.is_loopback or net.is_link_local):
        raise ValueError("Only private, loopback, or link-local IPv4 scopes are allowed.")
    if net.num_addresses > MAX_HOSTS:
        raise ValueError(f"Scope is too large; maximum is {MAX_HOSTS} addresses.")
    return net


def _run_nmap(args: list[str]) -> str:
    binary = shutil.which("nmap")
    if not binary:
        return json.dumps({"ok": False, "error": "nmap_not_installed",
                           "message": "Install Nmap from your Linux distribution package manager, then retry."})
    with tempfile.TemporaryDirectory(prefix="mark56-net-audit-") as tmp:
        output = Path(tmp) / "scan.xml"
        command = [binary, *args, "-oX", str(output)]
        try:
            result = subprocess.run(command, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, timeout=TIMEOUT_SECONDS, check=False,
                                    shell=False, close_fds=True)
        except subprocess.TimeoutExpired:
            return json.dumps({"ok": False, "error": "timeout",
                               "message": f"Nmap exceeded {TIMEOUT_SECONDS} seconds; scan stopped."})
        if result.returncode != 0 or not output.is_file():
            return json.dumps({"ok": False, "error": "scan_failed",
                               "message": (result.stderr or "Nmap did not produce a result.")[:1000]})
        try:
            root = ET.parse(output).getroot()
        except (ET.ParseError, OSError):
            return json.dumps({"ok": False, "error": "invalid_output",
                               "message": "Nmap output could not be parsed; no findings reported."})
        hosts = []
        for host in root.findall("host"):
            addr = next((a.get("addr") for a in host.findall("address")
                         if a.get("addrtype") == "ipv4"), None)
            if not addr:
                continue
            status = host.find("status")
            item = {"address": addr, "state": status.get("state") if status is not None else "unknown",
                    "hostnames": [n.get("name") for n in host.findall("./hostnames/hostname") if n.get("name")],
                    "open_ports": []}
            for port in host.findall("./ports/port"):
                state = port.find("state")
                if state is None or state.get("state") != "open":
                    continue
                service = port.find("service")
                item["open_ports"].append({
                    "port": int(port.get("portid", "0")),
                    "protocol": port.get("protocol", "tcp"),
                    "service": service.get("name") if service is not None else "unknown",
                    "product": service.get("product") if service is not None else None,
                    "version": service.get("version") if service is not None else None,
                })
            hosts.append(item)
        return json.dumps({"ok": result.returncode == 0, "command": command[:-2],
                           "hosts_found": len(hosts), "hosts": hosts,
                           "limitations": ["Service/version identification is indicative, not proof of a vulnerability.",
                                           "No exploit, brute force, or intrusive vulnerability scripts were run."]},
                          ensure_ascii=False)


def run(parameters: dict, **_context) -> str:
    p = parameters or {}
    operation = str(p.get("operation") or "status").lower().strip()
    if operation == "status":
        return json.dumps({"available": platform.system() == "Linux",
                           "nmap_installed": shutil.which("nmap") is not None,
                           "supported_operations": ["discover", "ports"],
                           "safety": "Private/local IPv4 scope only; explicit confirmation required."})
    if operation not in {"discover", "ports"}:
        return json.dumps({"ok": False, "message": "Use status, discover, or ports."})
    if p.get("confirmed") is not True:
        return json.dumps({"ok": False, "message": "Blocked: explicitly confirm you own or are authorized to test this network."})
    try:
        net = _scope(p.get("target") or "")
    except ValueError as exc:
        return json.dumps({"ok": False, "message": str(exc)})
    target = str(net)
    if operation == "discover":
        return _run_nmap(["-sn", "-n", "-T3", "--host-timeout", "20s", target])
    # Deliberately excludes NSE vulnerability/exploit scripts and UDP scans.
    return _run_nmap(["-sT", "-sV", "--version-light", "--top-ports", "100",
                      "-T3", "--max-retries", "1", "--host-timeout", "30s", target])


PLUGIN = {
    "name": "network_audit",
    "description": (
        "Linux-only defensive network inventory for explicitly authorized private/local IPv4 CIDRs. "
        "Supports bounded host discovery and common TCP open-port/service reporting. Requires confirmed=true. "
        "No exploitation, credential attacks, stealth, or intrusive vulnerability scripts."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "operation": {"type": "STRING", "description": "status | discover | ports"},
            "target": {"type": "STRING", "description": "Authorized private/local IPv4 CIDR, at most 256 addresses"},
            "confirmed": {"type": "BOOLEAN", "description": "Confirm ownership or explicit authorization"},
        },
        "required": ["operation"],
    },
}
