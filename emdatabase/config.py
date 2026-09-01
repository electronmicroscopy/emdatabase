"""Runtime settings for emdatabase, in the style of matplotlib's ``rcParams``.

``emdatabase.settings`` is a live dict, seeded at import from a YAML file (or
the built-in defaults). Change it in memory::

    import emdatabase
    emdatabase.settings["data_dir"] = "/big/disk/emdatabase"

and it takes effect immediately. To remember the choice across sessions, persist
it::

    emdatabase.settings.save()

Settings live in a ``~/.emdatabase`` folder (``~/.emdatabase/settings.yaml``),
or wherever ``EM_DATABASE_CONFIG`` points. No environment variable is *needed* to
configure emdatabase - the settings object is the source of truth; the old
``EM_DATABASE_DATA_DIR`` is still honored as a seed for backward compatibility.

Data can also be installed **system-wide** and shared by every user. When
resolving where a dataset lives, emdatabase looks in the shared/system
locations first, then the user's own data directory, and only downloads (into
the user directory) if it is nowhere to be found. Shared locations come from a
system config file (see :func:`system_config_path`), the ``EM_DATABASE_SHARED_DIR``
environment variable (an ``os.pathsep``-separated list), or a ``shared_data_dirs``
list in the user's settings.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml


def _default_data_dir() -> Path:
    return Path.home() / "emdatabase"


#: Built-in defaults - the fallback when nothing is configured. Values here are
#: the serialized (string) form, so they compare equal to what the YAML holds.
DEFAULTS: dict = {
    "data_dir": str(_default_data_dir()),
}


def config_dir() -> Path:
    """The ``~/.emdatabase`` folder that holds the settings file."""
    return Path.home() / ".emdatabase"


def config_path() -> Path:
    """Path to the YAML settings file.

    ``EM_DATABASE_CONFIG`` overrides the location; otherwise it is
    ``~/.emdatabase/settings.yaml``.
    """
    override = os.environ.get("EM_DATABASE_CONFIG")
    if override:
        return Path(override)
    return config_dir() / "settings.yaml"


def system_config_path() -> Path | None:
    """Path to the machine-wide settings file (for system-wide installs).

    ``EM_DATABASE_SYSTEM_CONFIG`` overrides it; otherwise it is
    ``/etc/emdatabase/settings.yaml`` (POSIX) or
    ``%PROGRAMDATA%\\emdatabase\\settings.yaml`` (Windows).
    """
    override = os.environ.get("EM_DATABASE_SYSTEM_CONFIG")
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("PROGRAMDATA")
        return Path(base) / "emdatabase" / "settings.yaml" if base else None
    return Path("/etc/emdatabase/settings.yaml")


def _read_yaml(path: Path | None) -> dict:
    """Parse a YAML file into a dict, or ``{}`` if missing/unreadable/malformed."""
    if path is None:
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        # A malformed settings file must not break importing the package.
        return {}


def _read_file() -> dict:
    """The user settings stored on disk, or ``{}``."""
    return _read_yaml(config_path())


def _read_system() -> dict:
    """The machine-wide settings, or ``{}``."""
    return _read_yaml(system_config_path())


def _write_file(data: dict) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(dict(data), handle, default_flow_style=False, sort_keys=True)


def _seed(settings: "Settings") -> None:
    """(Re)seed a settings object: defaults < file < legacy env var."""
    settings.clear()
    settings.update(DEFAULTS)
    settings.update(_read_file())  # the file overrides the defaults
    # Backward compatibility: seed from the old env var if it is set.
    env_dir = os.environ.get("EM_DATABASE_DATA_DIR")
    if env_dir:
        settings["data_dir"] = env_dir


class Settings(dict):
    """A live settings mapping that can persist itself to the YAML file."""

    def save(self) -> None:
        """Persist the settings to the YAML file.

        Only values that DIFFER from the built-in defaults are written, so a
        default (like the data directory) is never frozen into the file: it stays
        dynamic and keeps being obeyed across sessions, machines, or a change to
        the default itself. When nothing differs, any stale file is removed.
        """
        delta = {key: value for key, value in self.items() if DEFAULTS.get(key) != value}
        path = config_path()
        if delta:
            _write_file(delta)
        elif path.exists():
            path.unlink()

    def reload(self) -> None:
        """Re-seed from the built-in defaults and the on-disk file, discarding
        any in-memory changes."""
        _seed(self)

    def reset(self, key: str | None = None) -> None:
        """Reset a key (or everything) to its default, in memory and on disk."""
        if key is None:
            self.clear()
            self.update(DEFAULTS)
        elif key in DEFAULTS:
            self[key] = DEFAULTS[key]
        else:
            self.pop(key, None)
        self.save()  # delta-save drops the now-default key from the file

    def widget(self):
        """Return an interactive widget for editing the settings (Jupyter)."""
        from emdatabase.widget import settings_widget

        return settings_widget()

    def _repr_mimebundle_(self, **kwargs):
        """Render as an editable settings widget in Jupyter (falls back to the
        plain dict repr if anywidget is not installed)."""
        try:
            from emdatabase.widget import settings_widget

            widget = settings_widget()
        except Exception:
            return {"text/plain": repr(dict(self))}
        return widget._repr_mimebundle_(**kwargs)


#: The live settings object (seeded once at import).
settings = Settings()
_seed(settings)


def data_dir() -> Path:
    """The user's data directory - where downloads are written."""
    return Path(settings.get("data_dir") or _default_data_dir())


def shared_data_dirs() -> list[Path]:
    """System-wide / shared data locations, checked before the user's dir.

    Order: ``EM_DATABASE_SHARED_DIR`` (an ``os.pathsep`` list), then the user's
    ``shared_data_dirs`` setting, then the system config file's ``data_dir`` and
    ``shared_data_dirs``. Duplicates are removed, order preserved.
    """
    dirs: list[str] = []
    env = os.environ.get("EM_DATABASE_SHARED_DIR")
    if env:
        dirs += [d for d in env.split(os.pathsep) if d]
    dirs += [str(d) for d in (settings.get("shared_data_dirs") or [])]
    system = _read_system()
    if system.get("data_dir"):
        dirs.append(str(system["data_dir"]))
    dirs += [str(d) for d in (system.get("shared_data_dirs") or [])]
    seen: set[str] = set()
    unique: list[Path] = []
    for d in dirs:
        if d not in seen:
            seen.add(d)
            unique.append(Path(d))
    return unique


def data_search_dirs() -> list[Path]:
    """Everywhere to look for an existing dataset: shared/system dirs first,
    then the user's data directory."""
    dirs = shared_data_dirs()
    user = data_dir()
    if user not in dirs:
        dirs.append(user)
    return dirs
