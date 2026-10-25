# Mark-56 Ethical Security Assessment

The ethical_security_assessment plugin is a Linux-only, scoped security assessment tool.

## Supported actions

- preflight: check Linux, Nmap availability, and basic local utilities.
- discover: host discovery for an explicitly authorized IP or CIDR containing at most 256 addresses.
- scan: TCP connect scan of the top 1,000 ports by default, with lightweight service/version detection. An explicit port list/range may be supplied.
- safe_checks: the same service scan plus Nmap's safe script category. Review scan impact and target owner authorization before running.
- status: report the latest assessment status.
- explain: show the last recorded command, phase summary, and parsed evidence.

## Safety and evidence

The plugin requires the caller to pass authorized=true after the user explicitly confirms ownership or permission. It rejects shell syntax and multiple target strings, limits CIDR discovery to 256 addresses per run, uses argument-list subprocess execution (never a shell), applies a four-minute timeout, and does not invoke sudo.

This plugin does not execute exploits, brute-force credentials, attempt persistence, evade detection, or automatically attack discovered hosts. A scanner result is evidence of an observed service or script response, not proof that a system is exploitable. Findings should be verified in an isolated lab or with the asset owner's approved process.

## Install requirements

Nmap must be installed separately through the Linux distribution's trusted package manager and available on PATH. The plugin is intentionally unavailable on Windows and other non-Linux operating systems.

## Example voice requests

- "Jarvis, check whether the security assessment tools are ready."
- "Jarvis, discover hosts on this authorized lab subnet 192.168.56.0/24." (Confirm that this is your lab network first.)
- "Jarvis, scan this authorized lab host for ports and service versions."
- "Jarvis, run safe-category checks on this authorized test host."
- "Jarvis, explain the current assessment and show the evidence."

For a real scan, Jarvis must supply the exact target and set the authorization flag only after the user has confirmed permission.
