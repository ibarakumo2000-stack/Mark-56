"""Linux-only authorized private-network discovery and service enumeration."""
from __future__ import annotations
import ipaddress, json, platform, shutil, subprocess

_TIMEOUT=180
_PRIVATE_NETS=tuple(ipaddress.ip_network(x) for x in ("10.0.0.0/8","172.16.0.0/12","192.168.0.0/16","127.0.0.0/8"))

def _validate_target(raw: str) -> str:
    raw=str(raw or "").strip()
    if not raw or len(raw)>64: raise ValueError("Provide a single IP address or CIDR network.")
    network=ipaddress.ip_network(raw,strict=False)
    if not any(network.subnet_of(allowed) for allowed in _PRIVATE_NETS):
        raise ValueError("Only private/loopback targets are allowed in this safe scan mode.")
    if network.num_addresses>4096: raise ValueError("Network too large; narrow scope to at most 4096 addresses.")
    return str(network)

def run(parameters: dict, **_context) -> str:
    p=parameters or {}
    if platform.system()!="Linux":
        return json.dumps({"ok":False,"available":False,"message":"Network assessment is available only on Linux."})
    if p.get("confirmed") is not True:
        return json.dumps({"ok":False,"needs_confirmation":True,"message":"Confirm ownership or explicit authorization before scanning this private network."})
    mode=str(p.get("mode") or "ports").lower().strip()
    if mode not in {"hosts","ports"}: return json.dumps({"ok":False,"message":"Mode must be hosts or ports."})
    try: target=_validate_target(p.get("target"))
    except ValueError as exc: return json.dumps({"ok":False,"message":str(exc)})
    nmap=shutil.which("nmap")
    if not nmap: return json.dumps({"ok":False,"missing_dependency":"nmap","install_hint":"On Ubuntu: sudo apt install nmap"})
    command=[nmap,"-sn","-n",target] if mode=="hosts" else [nmap,"-sT","-sV","--version-light","--top-ports","1000","-T3","-n",target]
    try:
        result=subprocess.run(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=_TIMEOUT,check=False,shell=False,close_fds=True)
        return json.dumps({"ok":result.returncode==0,"mode":mode,"target":target,"command":command,"exit_code":result.returncode,"output":(result.stdout or "")[-18000:],"scope":"Private-network discovery/service enumeration only; no exploitation performed."},ensure_ascii=False)
    except subprocess.TimeoutExpired:
        return json.dumps({"ok":False,"mode":mode,"target":target,"message":f"Scan timed out after {_TIMEOUT} seconds."})
    except OSError as exc:
        return json.dumps({"ok":False,"message":f"Could not start nmap ({type(exc).__name__})."})

PLUGIN={"name":"linux_network_audit","description":"Linux-only authorized private-network discovery and TCP port/service enumeration using nmap. Requires confirmed=true, rejects public targets and large ranges, has a timeout, and does not run exploits or credential attacks.","parameters":{"type":"OBJECT","properties":{"mode":{"type":"STRING","description":"hosts | ports"},"target":{"type":"STRING","description":"Authorized private IP or CIDR, e.g. 192.168.1.0/24"},"confirmed":{"type":"BOOLEAN","description":"Confirm ownership or explicit authorization for this target"}},"required":["mode","target","confirmed"]}}
