"""Configuration for emdatabase, in the style of dask's (and quantem's) config.

Two keys are shipped, in ``emdatabase/emdatabase.yaml``. ``locations`` is a
mapping of name to directory: ``personal`` is the reserved name for the one
writable location, where downloads go (``null`` means pooch's cache directory);
every other entry is a read-only directory, searched before it::

    locations:
      example_data: /group/example_data
      personal: /big/disk/emdatabase

``check_updates`` (true by default) is whether downloading a weights family's
``latest`` asks the index on the project's ``main`` branch whether newer
weights have been published, and warns if they have.

Add and remove entries with :func:`add_location`, :func:`locations` and
:func:`remove_location`::

    from emdatabase import config

    config.add_location("/group/example_data")                       # read-only
    config.add_location("/big/disk/emdatabase", name="personal")     # downloads
    config.locations()                                               # search order
    config.remove_location("example_data")

Each of those persists to the config file unless called with ``persist=False``.
A location's name is also what a download writes into, which is how a shared
location is seeded: ``data.CuZnHAADF().download(destination="example_data")``.

Or read and write the key directly::

    config.get("locations")
    config.set({"locations.personal": "/big/disk/emdatabase"})  # for this process
    with config.set({"locations.personal": "/scratch"}):        # or for a block
        ...
    config.write()                                              # persist to the yaml

Or from the environment, prefix ``EMDATABASE_``, double underscore to nest::

    EMDATABASE_LOCATIONS__PERSONAL=/scratch/data
    EMDATABASE_LOCATIONS__GROUP=/wigeon/shared/example_data

Files live in ``~/.config/emdatabase`` (or wherever ``EMDATABASE_CONFIG``
points); every ``*.yaml`` and ``*.yml`` in that directory is merged, in name
order. Precedence, lowest first: shipped defaults, config files, environment
variables, :class:`set`.
"""

from __future__ import annotations

import ast
import logging
import os
import warnings
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import pooch
import yaml

no_default = "__no_default__"

ENV_PREFIX = "EMDATABASE_"

PATH = Path(os.getenv("EMDATABASE_CONFIG", "~/.config/emdatabase")).expanduser()

config: dict = {}
defaults: dict = yaml.safe_load(Path(__file__).with_name("emdatabase.yaml").read_text())


def _config_dir() -> Path:
    """The directory config files are read from, re-read from the environment.

    :data:`PATH` is fixed at import; this is what everything else calls, so
    setting ``EMDATABASE_CONFIG`` and calling :func:`refresh` works.
    """
    return Path(os.getenv("EMDATABASE_CONFIG", PATH)).expanduser()


class set:
    """Set configuration values, for the process or, as a context manager, for a block

    Parameters
    ----------
    arg : mapping
        Configuration key-value pairs to set. A dotted key such as
        ``"locations.personal"`` sets a nested value.
    """

    def __init__(self, arg: Mapping, config: dict = config):
        self.config: dict = config
        self._record: list[tuple[str, tuple[str, ...], Any]] = []
        for key, value in arg.items():
            _warn_if_unknown(key)
            self._assign(key.split("."), value, config)

    def __enter__(self):
        return self.config

    def __exit__(self, type, value, traceback):
        for op, path, value in reversed(self._record):
            d = self.config
            for key in path[:-1]:
                d = d[key]
            if op == "replace":
                d[path[-1]] = value
            else:
                d.pop(path[-1], None)

    def _assign(
        self,
        keys: Sequence[str],
        value: Any,
        d: dict,
        path: tuple[str, ...] = (),
        record: bool = True,
    ) -> None:
        """Assign value into a nested configuration dictionary

        Parameters
        ----------
        keys : Sequence[str]
            The nested path of keys to assign the value.
        value : object
        d : dict
            The part of the nested dictionary into which we want to assign the
            value
        path : tuple[str], optional
            The path history up to this point.
        record : bool, optional
            Whether this operation needs to be recorded to allow for rollback.
        """
        key = keys[0]
        path = path + (key,)

        if len(keys) == 1:
            if record:
                if key in d:
                    self._record.append(("replace", path, d[key]))
                else:
                    self._record.append(("insert", path, None))
            d[key] = value
        else:
            if key not in d or not isinstance(d[key], dict):
                if record:
                    if key in d:
                        self._record.append(("replace", path, d[key]))
                    else:
                        self._record.append(("insert", path, None))
                d[key] = {}
                record = False
            self._assign(keys[1:], value, d[key], path, record=record)


def refresh() -> None:
    """Re-read the configuration: the shipped defaults, then the config files,
    then the environment. Anything changed with :class:`set` is dropped."""
    config.clear()
    update(config, defaults)
    for document in collect_yaml(_config_dir()):
        for key in document:
            _warn_if_unknown(key)
        update(config, document)
    update(config, collect_env())  # collect_env builds through set, which warns


def get(key: str, default: Any = no_default) -> Any:
    """Get a configuration value. Use '.' for nested access."""
    result = config
    for k in key.split("."):
        try:
            result = result[k]
        except (TypeError, IndexError, KeyError):
            if default is not no_default:
                return default
            raise
    return result


def update(old: dict, new: Mapping) -> None:
    """Merge ``new`` into ``old`` in place; ``new`` wins, and a nested mapping is
    merged key by key rather than replacing the one in ``old``."""
    for k, v in new.items():
        if isinstance(v, Mapping):
            if not isinstance(old.get(k), dict):
                old[k] = {}
            update(old[k], v)
        else:
            old[k] = v


def collect_yaml(path: Path) -> Iterator[dict]:
    """Collect configuration from the yaml files in a directory

    Every ``*.yaml`` and ``*.yml`` in ``path`` is parsed, in name order; a path
    to a single file is read as itself.
    """
    if not path.exists():
        return
    file_paths = sorted([*path.glob("*.yaml"), *path.glob("*.yml")]) if path.is_dir() else [path]
    for p in file_paths:
        yield _load_config_file(p)


def collect_env(env: Mapping[str, str] | None = None) -> dict:
    """Collect config from environment variables

    This grabs environment variables of the form "EMDATABASE_FOO__BAR_BAZ=123"
    and turns these into config variables of the form ``{"foo": {"bar_baz":
    123}}``. It transforms the key and value in the following way:

    -  Strips the ``EMDATABASE_`` prefix and lower-cases the rest
    -  Treats ``__`` (double-underscore) as nested access
    -  Calls ``ast.literal_eval`` on the value
    """

    if env is None:
        env = os.environ

    d = {}

    for name, value in env.items():
        # EMDATABASE_CONFIG says where the config files are; it is not one of
        # the keys they hold.
        if name.startswith(ENV_PREFIX) and name != "EMDATABASE_CONFIG":
            varname = name[len(ENV_PREFIX) :].lower().replace("__", ".")
            d[varname] = interpret_value(value)

    result: dict = {}
    set(d, config=result)
    return result


def interpret_value(value: str) -> Any:
    try:
        return ast.literal_eval(value)
    except (SyntaxError, ValueError):
        pass

    # Avoid confusion of YAML vs. Python syntax
    hardcoded_map = {"none": None, "null": None, "false": False, "true": True}
    return hardcoded_map.get(value.lower(), value)


def _load_config_file(path: Path) -> dict:
    """Parse a config file, which has to hold a mapping or nothing.

    A yaml syntax error already names the file and line, given the open file.
    """
    with open(path) as f:
        loaded = yaml.safe_load(f)
    if loaded is not None and not isinstance(loaded, dict):
        raise ValueError(
            f"An emdatabase config file at {str(path)!r} is malformed - config files must "
            f"have a dict as the top level object, got a {type(loaded).__name__} instead"
        )
    return loaded or {}


def _warn_if_unknown(key: str) -> None:
    """Warn about a key whose top level is none of the shipped ones.

    It is still set: config is not a schema, and refusing an unknown key would
    break anything that stores its own.
    """
    if key.split(".")[0] not in defaults:
        warnings.warn(f'Unknown configuration key "{key}"')


def _dump(document: Mapping, path: Path | str | None = None) -> None:
    """Write ``document`` to a yaml file, creating the config directory."""
    path = Path(path) if path is not None else _config_dir() / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(dict(document), f)


def write(path: Path | str | None = None) -> None:
    """Write the current configuration to a yaml file.

    Parameters
    ----------
    path : Path or str, optional
        Path to write the yaml file to. Defaults to ``config.yaml`` in the
        config directory.
    """
    _dump(config, path)


def _persist_locations(updates: Mapping[str, str | None], remove: str | None = None) -> None:
    """Merge these ``locations`` entries into the config file, and only these.

    Writing the whole live mapping would bake whatever the environment or an
    open :class:`set` block is supplying into the file alongside the change the
    caller asked for.
    """
    path = _config_dir() / "config.yaml"
    document = _load_config_file(path) if path.exists() else {}
    configured = document.get("locations")
    if not isinstance(configured, dict):
        configured = {}
    if remove is not None:
        configured.pop(remove, None)
    configured.update(updates)
    document["locations"] = configured
    _dump(document, path)


# ---------------------------------------------------------------------------
# Where the data lives
# ---------------------------------------------------------------------------

_NOTICE_SHOWN = False

LocationName = Annotated[str, "the name of a location configured with add_location"]


@dataclass(frozen=True)
class Location:
    """One place datasets are looked for.

    Attributes
    ----------
    name : str
        The entry's name in the ``locations`` mapping.
    path : Path
        The directory, with ``~`` expanded.
    kind : str
        ``"personal"`` for the location named ``personal``, ``"shared"`` for
        every other one.
    """

    name: str
    path: Path
    kind: str


def _configured() -> dict[str, Path | None]:
    """The ``locations`` mapping, in declaration order, with ``~`` expanded.

    A path may be ``None``: that is what ``personal: null`` means, and a user's
    yaml could leave any other entry empty the same way.
    """
    configured = get("locations", None) or {}
    if not isinstance(configured, Mapping):
        raise TypeError(
            f"The locations config must be a mapping of name to directory, not "
            f"{configured!r}. Set one entry at a time: "
            f"{ENV_PREFIX}LOCATIONS__PERSONAL=/scratch, or "
            'config.set({"locations.personal": "/scratch"}).'
        )
    return {
        str(name): (Path(str(path)).expanduser() if path else None)
        for name, path in configured.items()
    }


def data_dir() -> Path:
    """The directory downloads are written to.

    The ``personal`` location if it is set, otherwise pooch's cache directory
    for emdatabase (``~/.cache/emdatabase`` on Linux).
    """
    configured = _configured().get("personal")
    if configured is not None:
        return configured
    cache = Path(pooch.os_cache("emdatabase"))
    if not cache.exists():
        first_run_notice(cache)
    return cache


def locations() -> list[Location]:
    """Every configured location, in search order.

    The shared locations in declaration order, then ``personal`` last. Entries
    with no path are skipped; ``personal`` is always present, falling back to
    the cache directory.

    Examples
    --------
    >>> config.locations()  # doctest: +SKIP
    [Location(name='group', path=PosixPath('/group/example_data'), kind='shared'),
     Location(name='personal', path=PosixPath('/big/disk/emdatabase'), kind='personal')]
    """
    found = [
        Location(name, path, "shared")
        for name, path in _configured().items()
        if name != "personal" and path is not None
    ]
    found.append(Location("personal", data_dir(), "personal"))
    return found


def data_search_dirs() -> list[Path]:
    """Everywhere to look for an existing dataset: the shared locations, then
    :func:`data_dir`."""
    dirs: list[Path] = []
    for location in locations():
        if location.path not in dirs:
            dirs.append(location.path)
    return dirs


def resolve_destination(destination: Path | LocationName | None) -> Path | None:
    """The directory a ``destination=`` argument names, or None.

    A string that is exactly the name of a configured location (``"personal"``
    included) is that location's directory; every other string, and every
    :class:`~pathlib.Path`, is a path, with ``~`` expanded. ``None`` stays
    ``None``, for the caller to fill in with whatever its own default is.

    Examples
    --------
    >>> config.resolve_destination("example_data")  # doctest: +SKIP
    PosixPath('/group/example_data')
    >>> config.resolve_destination("data")  # no location of that name  # doctest: +SKIP
    PosixPath('data')
    """
    if destination is None:
        return None
    if isinstance(destination, str):
        for location in locations():
            if location.name == destination:
                return location.path
    return Path(destination).expanduser()


def add_location(path: Path | str, name: str | None = None, persist: bool = True) -> Path:
    """Add a location, or repoint one that is already configured.

    Parameters
    ----------
    path : Path or str
        The directory. ``~`` is expanded. It does not have to exist yet - a
        share may be mounted later - but a warning says so if it does not.
    name : str, optional
        The entry's name, and its provenance in the widgets and in
        ``filter(location=...)``. Defaults to the last component of ``path``.
        ``"personal"`` is the writable location downloads go to; every other
        name is read-only and searched before it. Passing a name already in use
        repoints that entry.
    persist : bool, optional
        Write the configuration to ``~/.config/emdatabase/config.yaml`` (see
        :func:`write`) so the location survives the session. ``False`` changes
        this process only; :class:`set` as a context manager is the way to make
        a change that lasts for a block.

    Returns
    -------
    Path
        The expanded path.

    Raises
    ------
    ValueError
        If ``name`` was not given and the name derived from ``path`` is already
        taken by a different directory. Pass ``name=`` to choose another.

    Examples
    --------
    >>> config.add_location("/group/example_data")  # doctest: +SKIP
    PosixPath('/group/example_data')
    >>> config.add_location("/big/disk/emdatabase", name="personal")  # doctest: +SKIP
    PosixPath('/big/disk/emdatabase')
    """
    expanded = Path(str(path)).expanduser()
    if not expanded.exists():
        warnings.warn(
            f"{expanded} does not exist. It is still configured, in case it is mounted "
            "or created later."
        )

    current = _configured()
    if name is None:
        name = expanded.name
        if name in current and current[name] != expanded:
            raise ValueError(
                f"A location named {name!r} already points at {current[name]}, not "
                f"{expanded}. Pass name= to add this one under a different name."
            )
    # Assignment, not a merge: an existing name keeps its position, a new one
    # lands last, which is the search order.
    updated = {n: (str(p) if p is not None else None) for n, p in current.items()}
    updated[name] = str(expanded)
    set({"locations": updated})

    if persist:
        _persist_locations({name: str(expanded)})
    return expanded


def remove_location(name_or_path: Path | str, persist: bool = True) -> None:
    """Remove a location, or reset ``personal`` to the cache directory.

    Parameters
    ----------
    name_or_path : Path or str
        A location's name or its path. Names are matched first. ``"personal"``
        is not deleted but set back to ``null``, so downloads go to pooch's
        cache directory again.
    persist : bool, optional
        As in :func:`add_location`.

    Raises
    ------
    KeyError
        If nothing is configured under that name or path.

    Examples
    --------
    >>> config.remove_location("group")                # doctest: +SKIP
    >>> config.remove_location("/group/example_data")  # the same thing, by path  # doctest: +SKIP
    >>> config.remove_location("personal")             # back to the cache dir  # doctest: +SKIP
    """
    target = str(name_or_path)
    expanded = Path(target).expanduser()
    current = _configured()

    name = target if target in current else None
    if name is None:
        name = next((n for n, p in current.items() if p == expanded), None)
    if name is None:
        if target == "personal" or expanded == data_dir():
            name = "personal"
        else:
            raise KeyError(
                f"No location named or located at {target!r}. Configured: "
                f"{[(loc.name, str(loc.path)) for loc in locations()]}"
            )

    updated = {n: (str(p) if p is not None else None) for n, p in current.items() if n != name}
    if name == "personal":
        updated["personal"] = None
    set({"locations": updated})
    if persist:
        _persist_locations({"personal": None} if name == "personal" else {}, remove=name)


def first_run_notice(directory: Path) -> None:
    """Say where downloads will go, once per process.

    Called from :func:`data_dir` when nothing is configured and the default
    directory does not exist yet.
    """
    global _NOTICE_SHOWN
    if _NOTICE_SHOWN:
        return
    _NOTICE_SHOWN = True

    lines = [
        f"emdatabase will download datasets to {directory}.",
        'Change it with emdatabase.add_location("/somewhere/else", name="personal") or by '
        "setting EMDATABASE_LOCATIONS__PERSONAL.",
    ]
    old = [d for d in (Path.home() / "em_database", Path.home() / "emdatabase") if d.exists()]
    if old:
        lines.append(
            f"An earlier version downloaded to {old[0]}, which still exists; nothing there "
            "is read or moved."
        )

    from emdatabase.widget import _in_notebook

    if _in_notebook():
        from IPython.display import HTML, display

        body = "<br>".join(lines)
        display(
            HTML(
                '<div style="padding:10px 12px;border:1px solid #ccc;border-radius:8px;'
                'font-size:13px;line-height:1.5">' + body + "</div>"
            )
        )
    else:
        logging.getLogger("emdatabase").info(" ".join(lines))


refresh()
