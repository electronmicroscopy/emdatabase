"""Configuration for emdatabase, in the style of dask's (and quantem's) config.

Two keys are shipped, in ``emdatabase/emdatabase.yaml``: ``data_dir``, where
downloads are written (``null`` means pooch's cache directory), and ``stores``, a
name to read-only directory mapping searched before ``data_dir``.

Add and remove locations with :func:`add_location`, :func:`locations` and
:func:`remove_location`, which is the short way to write both keys::

    from emdatabase import config

    config.add_location("/group/example_data")                  # a shared store
    config.add_location("/big/disk/emdatabase", "personal")     # where downloads go
    config.locations()                                          # in search order
    config.remove_location("example_data")

Each of those persists to the config file unless called with ``persist=False``.
A store's name is also what a download writes into, which is how a store is
seeded: ``data.CuZnHAADF().download(destination="example_data")``.

Or read and write the keys directly::

    config.get("data_dir")
    config.set({"data_dir": "/big/disk/emdatabase"})   # for this process
    with config.set({"data_dir": "/scratch"}):         # or for a block
        ...
    config.write()                                     # persist to the yaml file

Or from the environment, prefix ``EMDATABASE_``, double underscore to nest::

    EMDATABASE_DATA_DIR=/scratch/data
    EMDATABASE_STORES__GROUP=/wigeon/shared/example_data

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
from typing import Annotated, Any, Literal, Union

import pooch
import yaml

no_default = "__no_default__"

ENV_PREFIX = "EMDATABASE_"

PATH = Path(os.getenv("EMDATABASE_CONFIG", "~/.config/emdatabase")).expanduser()

config: dict = {}
defaults: list[Mapping] = []
deprecations: dict[str, str | None] = {}


def _config_dir() -> Path:
    """The directory config files are read from, re-read from the environment.

    :data:`PATH` is fixed at import; this is what everything else calls, so
    setting ``EMDATABASE_CONFIG`` and calling :func:`refresh` works.
    """
    return Path(os.getenv("EMDATABASE_CONFIG", PATH)).expanduser()


class set:
    """Temporarily set configuration values within a context manager

    Parameters
    ----------
    arg : mapping or None, optional
        A mapping of configuration key-value pairs to set.
    **kwargs :
        Additional key-value pairs to set. If ``arg`` is provided, values set
        in ``arg`` will be applied before those in ``kwargs``.
        Double-underscores (``__``) in keyword arguments will be replaced with
        ``.``, allowing nested values to be easily set.
    """

    def __init__(
        self,
        arg: Union[Mapping, None] = None,
        config: dict = config,
        **kwargs,
    ):
        self.config: dict = config
        self._record: list[tuple[str, tuple[str, ...], Any]] = []

        if arg is not None:
            if not isinstance(arg, Mapping):
                raise TypeError(f"arg must be a dictionary, got {type(arg).__name__}")
            for key, value in arg.items():
                key, value = check_key_val(key, value)
                self._assign(key.split("."), value, config)
        if kwargs:
            for key, value in kwargs.items():
                key = key.replace("__", ".")
                key, value = check_key_val(key, value)
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
        key = canonical_name(keys[0], d)

        path = path + (key,)

        if len(keys) == 1:
            if record:
                if key in d:
                    self._record.append(("replace", path, d[key]))
                else:
                    self._record.append(("insert", path, None))
            d[key] = value
        else:
            if key not in d:
                if record:
                    self._record.append(("insert", path, None))
                d[key] = {}
                record = False
            self._assign(keys[1:], value, d[key], path, record=record)


def refresh(config: dict = config, defaults: list[Mapping] = defaults, **kwargs) -> None:
    """
    Update configuration by re-reading yaml files and env variables

    This mutates the global emdatabase.config.config, or the config parameter if
    passed in.

    This goes through the following stages:

    1.  Clearing out all old configuration
    2.  Updating from the stored defaults (see update_defaults)
    3.  Updating from yaml files and environment variables

    See Also
    --------
    emdatabase.config.collect: for parameters
    emdatabase.config.update_defaults
    """
    config.clear()

    for d in defaults:
        update(config, d, priority="new")

    update(config, collect(**kwargs))


def get(
    key: str,
    default: Any = no_default,
    config: dict = config,
    override_with: Any = None,
) -> Any:
    """
    Get elements from global config

    If ``override_with`` is not None this value will be passed straight back.

    Use '.' for nested access
    """
    if override_with is not None:
        return override_with
    keys = key.split(".")
    result = config
    for k in keys:
        k = canonical_name(k, result)
        try:
            result = result[k]
        except (TypeError, IndexError, KeyError):
            if default is not no_default:
                return default
            else:
                raise
    return result


def update_defaults(new: dict, config: dict = config, defaults: list[Mapping] = defaults) -> None:
    """Add a new set of defaults to the configuration

    It does two things:

    1.  Add the defaults to a global collection to be used by refresh later
    2.  Updates the global config with the new configuration
        prioritizing older values over newer ones
    """
    current_defaults = merge(*defaults)
    # Registered before the keys are checked: they are what "known key" means.
    defaults.append(new)

    for key, value in list(new.items()):
        key, nval = check_key_val(key, value)
        new[key] = nval

    update(config, new, priority="new-defaults", defaults=current_defaults)


def _initialize() -> None:
    fn = os.path.join(os.path.dirname(__file__), "emdatabase.yaml")

    with open(fn) as f:
        shipped = yaml.safe_load(f)

    update_defaults(shipped)


def canonical_name(k: str, config: dict) -> str:
    """Return the canonical name for a key.

    Handles user choice of '-' or '_' conventions by standardizing on whichever
    version was set first. If a key already exists in either hyphen or
    underscore form, the existing version is the canonical name. If neither
    version exists the original key is used as is.
    """
    try:
        if k in config:
            return k
    except TypeError:
        # config is not a mapping, return the same name as provided
        return k

    altk = k.replace("_", "-") if "_" in k else k.replace("-", "_")

    if altk in config:
        return altk

    return k


def update(
    old: dict,
    new: Mapping,
    priority: Literal["old", "new", "new-defaults"] = "new",
    defaults: Mapping | None = None,
    check: bool = True,
) -> dict:
    """Update a nested dictionary with values from another

    This is like dict.update except that it smoothly merges nested values

    This operates in-place and modifies old

    Parameters
    ----------
    priority: string {'old', 'new', 'new-defaults'}
        If new (default) then the new dictionary has preference.
        Otherwise the old dictionary does.
        If 'new-defaults', a mapping should be given of the current defaults.
        Only if a value in ``old`` matches the current default, it will be
        updated with ``new``.
    check: bool
        Whether to run the keys through :func:`check_key_val`. False on the
        recursive call, because the unknown-key warning is about top-level keys
        and a store's name is not one.

    Examples
    --------
    >>> a = {'x': 1, 'y': {'a': 2}}
    >>> b = {'x': 2, 'y': {'b': 3}}
    >>> update(a, b)  # doctest: +SKIP
    {'x': 2, 'y': {'a': 2, 'b': 3}}

    >>> a = {'x': 1, 'y': {'a': 2}}
    >>> b = {'x': 2, 'y': {'b': 3}}
    >>> update(a, b, priority='old')  # doctest: +SKIP
    {'x': 1, 'y': {'a': 2, 'b': 3}}

    >>> d = {'x': 0, 'y': {'a': 2}}
    >>> a = {'x': 1, 'y': {'a': 2}}
    >>> b = {'x': 2, 'y': {'a': 3, 'b': 3}}
    >>> update(a, b, priority='new-defaults', defaults=d)  # doctest: +SKIP
    {'x': 1, 'y': {'a': 3, 'b': 3}}

    """
    for k, v in new.items():
        if check:
            k, v = check_key_val(k, v)
        k = canonical_name(k, old)

        if isinstance(v, Mapping):
            if k not in old or old[k] is None or not isinstance(old[k], dict):
                old[k] = {}
            update(
                old[k],
                v,
                priority=priority,
                defaults=defaults.get(k) if defaults else None,
                check=False,
            )
        else:
            if (
                priority == "new"
                or k not in old
                or (
                    priority == "new-defaults"
                    and defaults
                    and k in defaults
                    and defaults[k] == old[k]
                )
            ):
                old[k] = v

    return old


def collect(path: Path | str | None = None, env: Mapping[str, str] | None = None) -> dict:
    """
    Collect configuration from the config directory and the environment

    Parameters
    ----------
    path : Path or str, optional
        Directory (or single file) to read yaml config from. Defaults to the
        config directory, ``EMDATABASE_CONFIG`` or ``~/.config/emdatabase``.

    env : Mapping[str, str]
        The system environment variables

    Returns
    -------
    config: dict

    """
    if path is None:
        path = _config_dir()
    if env is None:
        env = os.environ

    configs = [*collect_yaml(path=Path(path)), collect_env(env=env)]
    return merge(*configs)


def collect_yaml(path: Path) -> Iterator[dict]:
    """Collect configuration from the yaml files in a directory

    Every ``*.yaml`` and ``*.yml`` in ``path`` is parsed, in name order; a path
    to a single file is read as itself.
    """
    file_paths = []
    if path.exists():
        if path.is_dir():
            try:
                file_paths.extend(path.glob("*.yaml"))
                file_paths.extend(path.glob("*.yml"))
                file_paths = sorted(file_paths)
            except OSError:
                # Ignore permission errors
                pass
        else:
            file_paths.append(path)
    for p in file_paths:
        loaded = _load_config_file(p)
        if loaded is not None:
            yield loaded


def collect_env(env: Mapping[str, str] | None = None) -> dict:
    """Collect config from environment variables

    This grabs environment variables of the form "EMDATABASE_FOO__BAR_BAZ=123"
    and turns these into config variables of the form ``{"foo": {"bar-baz":
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


def merge(*dicts: Mapping) -> dict:
    """Update a sequence of nested dictionaries

    This prefers the values in the latter dictionaries to those in the former

    Examples
    --------
    >>> a = {'x': 1, 'y': {'a': 2}}
    >>> b = {'y': {'b': 3}}
    >>> merge(a, b)  # doctest: +SKIP
    {'x': 1, 'y': {'a': 2, 'b': 3}}
    """
    result: dict = {}
    for d in dicts:
        update(result, d, check=False)
    return result


def _load_config_file(path: Path) -> dict | None:
    """A helper for loading a config file from a path, and erroring
    appropriately if the file is malformed."""
    try:
        with open(path) as f:
            loaded = yaml.safe_load(f.read())
    except OSError:
        # Ignore permission errors
        return None
    except Exception as exc:
        raise ValueError(
            f"An emdatabase config file at {str(path)!r} is malformed, original error "
            f"message:\n\n{exc}"
        ) from None
    if loaded is not None and not isinstance(loaded, dict):
        raise ValueError(
            f"An emdatabase config file at {str(path)!r} is malformed - config files must "
            f"have a dict as the top level object, got a {type(loaded).__name__} instead"
        )
    return loaded


def check_key_val(key: str, val: Any, deprecations: dict = deprecations) -> tuple[str, Any]:
    """Check whether a key has been renamed, removed, or is not one we ship

    A key that is none of the shipped defaults warns and is still set: config is
    not a schema, and refusing an unknown key would break anything that stores
    its own.

    Parameters
    ----------
    key : str
        The configuration key to check. May be dotted, in which case only the
        part before the first '.' is checked.
    deprecations : Dict[str, str]
        The mapping of aliases

    Returns
    -------
    new: str
        The proper key, whether the original (if no deprecation) or the aliased
        value
    """
    if key in deprecations:
        new = deprecations[key]
        if new:
            warnings.warn(f'Configuration key "{key}" has been deprecated. Please use "{new}" ')
        else:
            raise ValueError(f'Configuration value "{key}" has been removed')

    top = key.split(".")[0]
    # The top-level keys of the registered defaults, not merge(*defaults):
    # merge() goes through update(), which calls back into here.
    known = {k for d in defaults for k in d}
    if top not in known and top not in deprecations:
        warnings.warn(f'Unknown configuration key "{key}"')

    return key, val


def write(path: Path | str | None = None) -> None:
    """Write the current configuration to a yaml file.

    Parameters
    ----------
    path : Path or str, optional
        Path to write the yaml file to. Defaults to ``config.yaml`` in the
        config directory.
    """
    path = Path(path) if path is not None else _config_dir() / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w") as f:
        yaml.dump(config, f)


# ---------------------------------------------------------------------------
# Where the data lives
# ---------------------------------------------------------------------------

_NOTICE_SHOWN = False


def data_dir() -> Path:
    """The directory downloads are written to.

    ``data_dir`` if it is set, otherwise pooch's cache directory for
    emdatabase (``~/.cache/emdatabase`` on Linux).
    """
    configured = get("data_dir", None)
    if configured:
        return Path(str(configured)).expanduser()
    cache = Path(pooch.os_cache("emdatabase"))
    if not cache.exists():
        first_run_notice(cache)
    return cache


StoreName = Annotated[str, "the name of a store configured with add_location"]


def stores() -> dict[str, Path]:
    """The named read-only directories searched before :func:`data_dir`.

    In declaration order. A store's path may be a string (it usually comes from
    yaml or an environment variable); ``~`` is expanded.
    """
    configured = get("stores", None) or {}
    return {str(name): Path(str(path)).expanduser() for name, path in configured.items()}


@dataclass(frozen=True)
class Location:
    """One place datasets are looked for: a shared store, or the personal dir.

    Attributes
    ----------
    name : str
        The store's name, or ``"personal"`` for :func:`data_dir`.
    path : Path
        The directory, with ``~`` expanded.
    kind : str
        ``"shared"`` for a store, ``"personal"`` for the data directory.
    """

    name: str
    path: Path
    kind: str


def locations() -> list[Location]:
    """Every configured location, in search order.

    The stores in declaration order, then the personal data directory last.

    Examples
    --------
    >>> config.locations()  # doctest: +SKIP
    [Location(name='group', path=PosixPath('/group/example_data'), kind='shared'),
     Location(name='personal', path=PosixPath('/big/disk/emdatabase'), kind='personal')]
    """
    found = [Location(name, path, "shared") for name, path in stores().items()]
    found.append(Location("personal", data_dir(), "personal"))
    return found


def data_search_dirs() -> list[Path]:
    """Everywhere to look for an existing dataset: the stores, then
    :func:`data_dir`."""
    dirs: list[Path] = []
    for location in locations():
        if location.path not in dirs:
            dirs.append(location.path)
    return dirs


def resolve_destination(destination: Path | StoreName | None) -> Path | None:
    """The directory a ``destination=`` argument names, or None.

    A string that is exactly the name of a configured store is that store's
    directory; every other string, and every :class:`~pathlib.Path`, is a path,
    with ``~`` expanded. ``None`` stays ``None``, for the caller to fill in with
    whatever its own default is.

    Examples
    --------
    >>> config.resolve_destination("example_data")  # doctest: +SKIP
    PosixPath('/group/example_data')
    >>> config.resolve_destination("data")  # no store of that name  # doctest: +SKIP
    PosixPath('data')
    """
    if destination is None:
        return None
    if isinstance(destination, str):
        configured = stores().get(destination)
        if configured is not None:
            return configured
    return Path(destination).expanduser()


def add_location(
    path: Path | str,
    kind: Literal["shared", "personal"] = "shared",
    name: str | None = None,
    persist: bool = True,
) -> Path:
    """Add a shared store, or set the personal data directory.

    Parameters
    ----------
    path : Path or str
        The directory. ``~`` is expanded. It does not have to exist yet - a
        store may be mounted later - but a warning says so if it does not.
    kind : {"shared", "personal"}, optional
        ``"shared"`` appends a named store, searched before the personal
        directory and never written to. ``"personal"`` sets ``data_dir``, where
        downloads go; there is only one of those, so it is replaced.
    name : str, optional
        The store's name, and its provenance in the widgets and in
        ``filter(location=...)``. Defaults to the last component of ``path``.
        Passing a name already in use repoints that store. Ignored when
        ``kind="personal"``.
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
    >>> config.add_location("/big/disk/emdatabase", "personal")  # doctest: +SKIP
    PosixPath('/big/disk/emdatabase')
    """
    if kind not in ("shared", "personal"):
        raise ValueError(f'kind must be "shared" or "personal", got {kind!r}')

    expanded = Path(str(path)).expanduser()
    if not expanded.exists():
        warnings.warn(
            f"{expanded} does not exist. It is still configured, in case it is mounted "
            "or created later."
        )

    if kind == "personal":
        set({"data_dir": str(expanded)})
    else:
        current = stores()
        if name is None:
            name = expanded.name
            if name in current and current[name] != expanded:
                raise ValueError(
                    f"A store named {name!r} already points at {current[name]}, not "
                    f"{expanded}. Pass name= to add this one under a different name."
                )
        # Assignment, not a merge: an existing name keeps its position, a new
        # one lands last, which is the search order.
        updated = {n: str(p) for n, p in current.items()}
        updated[name] = str(expanded)
        set({"stores": updated})

    if persist:
        write()
    return expanded


def remove_location(path_or_name: Path | str, persist: bool = True) -> None:
    """Remove a shared store, or reset the personal data directory.

    Parameters
    ----------
    path_or_name : Path or str
        A store's name, a store's path, the personal directory's path, or the
        literal ``"personal"``. Names are matched first.
    persist : bool, optional
        As in :func:`add_location`.

    Raises
    ------
    KeyError
        If nothing is configured under that name or path.

    Examples
    --------
    >>> config.remove_location("group")       # doctest: +SKIP
    >>> config.remove_location("/group/example_data")  # doctest: +SKIP
    >>> config.remove_location("personal")    # back to the cache dir  # doctest: +SKIP
    """
    target = str(path_or_name)
    current = stores()

    name = target if target in current else None
    if name is None:
        expanded = Path(target).expanduser()
        name = next((n for n, p in current.items() if p == expanded), None)
        if name is None:
            if target == "personal" or expanded == data_dir():
                set({"data_dir": None})
                if persist:
                    write()
                return
            raise KeyError(
                f"No location named or located at {target!r}. Configured: "
                f"{[(loc.name, str(loc.path)) for loc in locations()]}"
            )

    set({"stores": {n: str(p) for n, p in current.items() if n != name}})
    if persist:
        write()


def first_run_notice(directory: Path | None = None) -> None:
    """Say where downloads will go, once per process.

    Called from :func:`data_dir` when nothing is configured and the default
    directory does not exist yet.
    """
    global _NOTICE_SHOWN
    if _NOTICE_SHOWN:
        return
    _NOTICE_SHOWN = True

    if directory is None:
        directory = Path(pooch.os_cache("emdatabase"))
    lines = [
        f"emdatabase will download datasets to {directory}.",
        'Change it with emdatabase.set_data_dir("/somewhere/else") or by setting '
        "EMDATABASE_DATA_DIR.",
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


_initialize()
refresh()
