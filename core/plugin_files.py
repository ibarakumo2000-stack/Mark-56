"""Safe local plugin file management for the Jarvis plugin directory.

Plugin source is never imported during validation. A plugin is arbitrary Python
code with the same access as Jarvis, so the UI must warn before installing it.
Removed files are backed up outside plugins/ and recorded in local settings so a
future app update does not silently re-enable a plugin the user removed.
"""
from __future__ import annotations

import ast
import re
import shutil
import time
from pathlib import Path

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_DEFAULT_PARAMETERS = {"type": "OBJECT", "properties": {}}


class PluginFileError(ValueError):
    """Actionable validation or filesystem error shown in the Plugin Manager."""


def get_plugins_dir() -> Path:
    from memory.config_manager import BASE_DIR

    return Path(BASE_DIR) / "plugins"


def _metadata_from_ast(path: Path) -> dict:
    try:
        source = path.read_text(encoding="utf-8")
        compile(source, str(path), "exec")
        tree = ast.parse(source, filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise PluginFileError(f"Plugin source is not readable Python: {exc}") from exc

    metadata = None
    has_run = False
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == "PLUGIN" for target in targets):
                value = node.value
                try:
                    metadata = ast.literal_eval(value)
                except (ValueError, TypeError, SyntaxError):
                    raise PluginFileError(
                        "PLUGIN metadata must be a literal dictionary so Jarvis can validate it without executing the file."
                    ) from None
        elif isinstance(node, ast.FunctionDef) and node.name == "run":
            has_run = True

    if not isinstance(metadata, dict):
        raise PluginFileError("The file must define a top-level PLUGIN dictionary.")
    name = metadata.get("name")
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        raise PluginFileError("PLUGIN['name'] must be a Python-style name (letters, digits, underscores; no spaces).")
    description = metadata.get("description")
    if not isinstance(description, str) or not description.strip():
        raise PluginFileError("PLUGIN['description'] must be a non-empty string.")
    parameters = metadata.get("parameters", _DEFAULT_PARAMETERS)
    if not isinstance(parameters, dict) or parameters.get("type") != "OBJECT":
        raise PluginFileError("PLUGIN['parameters'] must be an object schema (type='OBJECT').")
    if not has_run:
        raise PluginFileError("The file must define a synchronous run(parameters, ...) function.")
    if not isinstance(path, Path):
        raise PluginFileError("Invalid plugin file.")
    return metadata


def validate_plugin_file(source: str | Path) -> dict:
    """Validate a plugin's structure without importing or executing its code."""
    path = Path(source)
    if not path.is_file() or path.suffix.lower() != ".py":
        raise PluginFileError("Choose a single Python plugin file ending in .py.")
    if path.name.startswith("_") or not _NAME_RE.fullmatch(path.stem):
        raise PluginFileError("Name the file with letters, digits, and underscores only; do not start it with '_'.")
    return _metadata_from_ast(path)


def _removed_files(persist_state: bool) -> set[str]:
    if not persist_state:
        return set()
    try:
        from memory.config_manager import get_removed_plugin_files

        return get_removed_plugin_files()
    except Exception:
        return set()


def _backup_destination(backup_dir: Path, filename: str) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / filename
    if not target.exists():
        return target
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"{Path(filename).stem}-{stamp}{Path(filename).suffix}"
    counter = 1
    while target.exists():
        target = backup_dir / f"{Path(filename).stem}-{stamp}-{counter}{Path(filename).suffix}"
        counter += 1
    return target


def install_plugin_file(
    source: str | Path,
    plugins_dir: str | Path | None = None,
    *,
    persist_state: bool = True,
) -> tuple[Path, dict]:
    """Install a user-selected .py plugin, without replacing an active file silently."""
    source_path = Path(source).resolve(strict=True)
    metadata = validate_plugin_file(source_path)
    root = Path(plugins_dir).resolve() if plugins_dir is not None else get_plugins_dir().resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / source_path.name
    removed = _removed_files(persist_state)

    if target.exists() and source_path == target.resolve():
        if target.name not in removed:
            raise PluginFileError(f"'{target.name}' is already installed.")
        if persist_state:
            from memory.config_manager import save_plugin_removed

            save_plugin_removed(target.name, False, plugin_name=metadata["name"])
        return target, metadata

    # A removed stock plugin may be restored by an app update. Permit replacing
    # that inactive file only when its filename is explicitly marked as removed.
    if target.exists():
        if target.name not in removed:
            raise PluginFileError(f"'{target.name}' already exists in the plugin directory; no file was overwritten.")
        backup = _backup_destination(root.parent / ".plugin-backups", target.name)
        shutil.move(str(target), str(backup))

    for existing in sorted(root.glob("*.py")):
        if existing.name == target.name or existing.name in removed or existing.name.startswith("_"):
            continue
        try:
            current_metadata = _metadata_from_ast(existing)
        except PluginFileError:
            continue
        if current_metadata.get("name") == metadata.get("name"):
            raise PluginFileError(
                f"Plugin name '{metadata['name']}' is already provided by '{existing.name}'."
            )

    try:
        shutil.copy2(source_path, target)
    except OSError as exc:
        raise PluginFileError(f"Could not copy the plugin into the Jarvis plugin directory: {exc}") from exc

    if persist_state:
        from memory.config_manager import save_plugin_removed

        save_plugin_removed(target.name, False, plugin_name=metadata["name"])
    return target, metadata


def remove_plugin_file(
    filename: str,
    plugins_dir: str | Path | None = None,
    *,
    plugin_name: str | None = None,
    persist_state: bool = True,
) -> Path:
    """Back up and remove one top-level plugin file, refusing path traversal/helpers."""
    root = Path(plugins_dir).resolve() if plugins_dir is not None else get_plugins_dir().resolve()
    if not filename or Path(filename).name != filename:
        raise PluginFileError("Invalid plugin filename.")
    if not filename.endswith(".py") or filename.startswith("_") or not _NAME_RE.fullmatch(Path(filename).stem):
        raise PluginFileError("Only normal top-level plugin .py files can be removed; helper files are protected.")
    target = root / filename
    if not target.is_file() or target.resolve().parent != root:
        raise PluginFileError(f"Plugin file '{filename}' was not found in the plugin directory.")

    if not plugin_name:
        try:
            plugin_name = str(_metadata_from_ast(target).get("name") or target.stem)
        except PluginFileError:
            plugin_name = target.stem

    backup = _backup_destination(root.parent / ".plugin-backups", filename)
    try:
        shutil.move(str(target), str(backup))
    except OSError as exc:
        raise PluginFileError(f"Could not move the plugin to its backup folder: {exc}") from exc

    if persist_state:
        try:
            from memory.config_manager import save_plugin_removed

            save_plugin_removed(filename, True, plugin_name=plugin_name)
        except Exception:
            try:
                shutil.move(str(backup), str(target))
            except OSError:
                pass
            raise
    return backup
