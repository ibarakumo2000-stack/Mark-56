# MARK LV — Release Installer

This package contains the production installer build system.

## What the end user receives

`MARK-LV-Setup-<version>.exe`

Double-clicking that file opens a normal Windows installation wizard. The wizard installs MARK LV with its private Python runtime and bundled dependencies. The end user does not need Python, pip, VS Code, or a virtual environment.

## Build

Run `BUILD_INSTALLER.cmd` on Windows 10/11 x64.

The first build requires internet access because it downloads the Python embeddable runtime and Python wheels. Later builds reuse the cached runtime when the dependency set has not changed.

Output:

- `dist\MARK-LV-Setup-<version>.exe`
- `dist\SHA256SUMS.txt`
- `distuild-info.json`

## Clean-machine test

Use Windows Sandbox or a clean Windows VM and run:

`powershell -ExecutionPolicy Bypass -File scripts\test_installation.ps1 -Installer dist\MARK-LV-Setup-<version>.exe`

The test checks installation, shortcuts, bundled Python, launch logging, basic runtime errors, Apps/uninstall registration, and uninstall cleanup.

## Important

This repository is the installer/build system. It still expects the actual MARK LV application source (including `main.py`, `requirements.txt`, `config`, `core`, etc.) in the project root next to `installer` and `scripts`.

The installer is currently unsigned unless a code-signing certificate is supplied. Unsigned Windows installers may trigger SmartScreen warnings.

The build intentionally excludes credentials and personal data from the packaged application.
