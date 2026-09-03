"""Discover an AFE2 Steam installation and inventory its archive files.

This module deliberately stops at filesystem metadata.  It reads Steam VDF
metadata, but it never opens a game archive or handles archive encryption keys.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Iterable, Iterator, Mapping, TypeAlias


APP_ID = "3448650"
GAME_DIR_ENV = "AFE2_GAME_DIR"
PAKS_RELATIVE_PATH = Path("AFE2/Content/Paks")
SHIPPING_EXE_RELATIVE_PATH = Path(
    "AFE2/Binaries/Win64/AFE2-Win64-Shipping.exe"
)

PathInput: TypeAlias = str | os.PathLike[str]
VdfValue: TypeAlias = str | dict[str, "VdfValue"]


class DiscoveryError(RuntimeError):
    """Raised when Steam metadata or a candidate game installation is invalid."""


@dataclass(frozen=True, slots=True)
class SteamAppManifest:
    """The small appmanifest subset required for catalogue provenance."""

    path: Path
    app_id: str
    build_id: str
    install_dir: str


@dataclass(frozen=True, slots=True)
class GameInstallation:
    """A validated game installation discovered from one supported source."""

    root: Path
    paks_dir: Path
    shipping_executable: Path
    discovery_source: str
    manifest: SteamAppManifest | None

    @property
    def build_id(self) -> str | None:
        """Return the Steam build ID when an adjacent manifest was available."""

        return self.manifest.build_id if self.manifest else None


@dataclass(frozen=True, slots=True)
class ArchiveFile:
    """Filesystem metadata for one archive-related file.

    ``container_name`` is the POSIX relative path without the final extension.
    A ``.utoc`` and ``.ucas`` with the same value form an IoStore container.
    ``.ucas`` files have no independent scan status because their ``.utoc`` is
    the index that an archive adapter scans.
    """

    relative_path: str
    size_bytes: int
    archive_type: str
    container_name: str
    scan_status: str | None


@dataclass(frozen=True, slots=True)
class SourceInventory:
    """A validated installation and its deterministically ordered archives."""

    installation: GameInstallation
    archives: tuple[ArchiveFile, ...]


def _tokenize_vdf(text: str) -> Iterator[str]:
    """Yield the KeyValues tokens needed by Steam's metadata files."""

    index = 0
    length = len(text)
    while index < length:
        character = text[index]

        if character.isspace():
            index += 1
            continue
        if text.startswith("//", index):
            newline = text.find("\n", index + 2)
            index = length if newline == -1 else newline + 1
            continue
        if character in "{}":
            yield character
            index += 1
            continue
        if character == '"':
            index += 1
            value: list[str] = []
            while index < length:
                character = text[index]
                if character == '"':
                    index += 1
                    yield "".join(value)
                    break
                if character == "\\" and index + 1 < length:
                    escaped = text[index + 1]
                    if escaped in {'"', "\\"}:
                        value.append(escaped)
                        index += 2
                        continue
                value.append(character)
                index += 1
            else:
                raise DiscoveryError("unterminated quoted value in Steam VDF")
            continue

        start = index
        while index < length and not text[index].isspace() and text[index] not in "{}":
            index += 1
        yield text[start:index]


def _parse_vdf(text: str) -> dict[str, VdfValue]:
    tokens = iter(_tokenize_vdf(text))

    def parse_object(*, nested: bool) -> dict[str, VdfValue]:
        result: dict[str, VdfValue] = {}
        while True:
            try:
                key = next(tokens)
            except StopIteration:
                if nested:
                    raise DiscoveryError("unterminated object in Steam VDF") from None
                return result

            if key == "}":
                if not nested:
                    raise DiscoveryError("unexpected closing brace in Steam VDF")
                return result
            if key == "{":
                raise DiscoveryError("unexpected opening brace in Steam VDF")

            try:
                value = next(tokens)
            except StopIteration:
                raise DiscoveryError(
                    f"missing value for Steam VDF key {key!r}"
                ) from None

            if value == "{":
                parsed_value: VdfValue = parse_object(nested=True)
            elif value == "}":
                raise DiscoveryError(f"missing value for Steam VDF key {key!r}")
            else:
                parsed_value = value

            if key in result:
                raise DiscoveryError(f"duplicate Steam VDF key {key!r}")
            result[key] = parsed_value

    return parse_object(nested=False)


def _read_vdf(path: Path) -> dict[str, VdfValue]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as error:
        raise DiscoveryError(f"cannot read Steam metadata {path}: {error}") from error
    try:
        return _parse_vdf(text)
    except DiscoveryError as error:
        raise DiscoveryError(f"cannot parse Steam metadata {path}: {error}") from error


def _casefolded_value(
    values: Mapping[str, VdfValue], key: str
) -> VdfValue | None:
    wanted = key.casefold()
    matches = [value for name, value in values.items() if name.casefold() == wanted]
    if len(matches) > 1:
        raise DiscoveryError(f"ambiguous Steam VDF key {key!r}")
    return matches[0] if matches else None


def _required_string(values: Mapping[str, VdfValue], key: str, path: Path) -> str:
    value = _casefolded_value(values, key)
    if not isinstance(value, str) or not value:
        raise DiscoveryError(f"Steam metadata {path} has no valid {key!r} value")
    return value


def parse_app_manifest(path: PathInput) -> SteamAppManifest:
    """Parse and validate app ID, build ID, and install directory.

    Only the required KeyValues subset is interpreted; no archive is touched.
    """

    manifest_path = Path(path).expanduser()
    root = _read_vdf(manifest_path)
    app_state = _casefolded_value(root, "AppState")
    if not isinstance(app_state, dict):
        raise DiscoveryError(f"Steam metadata {manifest_path} has no AppState object")

    app_id = _required_string(app_state, "appid", manifest_path)
    if app_id != APP_ID:
        raise DiscoveryError(
            f"Steam metadata {manifest_path} is for app {app_id}, expected {APP_ID}"
        )
    build_id = _required_string(app_state, "buildid", manifest_path)
    install_dir = _required_string(app_state, "installdir", manifest_path)
    if install_dir in {".", ".."} or "/" in install_dir or "\\" in install_dir:
        raise DiscoveryError(
            f"Steam metadata {manifest_path} has unsafe installdir {install_dir!r}"
        )

    return SteamAppManifest(
        path=manifest_path.resolve(),
        app_id=app_id,
        build_id=build_id,
        install_dir=install_dir,
    )


def parse_library_folders(path: PathInput) -> tuple[Path, ...]:
    """Return library roots from old or current ``libraryfolders.vdf`` forms."""

    metadata_path = Path(path).expanduser()
    root = _read_vdf(metadata_path)
    folders = _casefolded_value(root, "libraryfolders")
    if not isinstance(folders, dict):
        raise DiscoveryError(
            f"Steam metadata {metadata_path} has no libraryfolders object"
        )

    library_paths: set[Path] = set()
    for index, value in folders.items():
        if not index.isdecimal():
            continue
        if isinstance(value, str):
            path_value = value
        elif isinstance(value, dict):
            nested_path = _casefolded_value(value, "path")
            if not isinstance(nested_path, str) or not nested_path:
                continue
            path_value = nested_path
        else:  # pragma: no cover - VdfValue narrows this, retained defensively.
            continue
        library_paths.add(Path(path_value).expanduser())

    return tuple(sorted(library_paths, key=lambda item: item.as_posix()))


def common_libraryfolders_paths(home: PathInput | None = None) -> tuple[Path, ...]:
    """Return deterministic Linux locations where Steam stores library metadata."""

    home_path = Path(home).expanduser() if home is not None else Path.home()
    candidates = (
        home_path / ".local/share/Steam/steamapps/libraryfolders.vdf",
        home_path / ".steam/root/steamapps/libraryfolders.vdf",
        home_path / ".steam/steam/steamapps/libraryfolders.vdf",
        home_path
        / (
            ".var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/"
            "libraryfolders.vdf"
        ),
    )
    return tuple(dict.fromkeys(candidates))


def validate_game_directory(game_dir: PathInput) -> tuple[Path, Path, Path]:
    """Validate the game root and return root, Paks, and shipping executable paths."""

    root = Path(game_dir).expanduser().resolve()
    if not root.is_dir():
        raise DiscoveryError(f"game directory does not exist: {root}")

    paks_dir = root / PAKS_RELATIVE_PATH
    if not paks_dir.is_dir():
        raise DiscoveryError(f"game Paks directory does not exist: {paks_dir}")

    shipping_executable = root / SHIPPING_EXE_RELATIVE_PATH
    if not shipping_executable.is_file():
        raise DiscoveryError(
            f"game shipping executable does not exist: {shipping_executable}"
        )

    return root, paks_dir, shipping_executable


def _adjacent_manifest(root: Path) -> SteamAppManifest | None:
    if root.parent.name.casefold() != "common":
        return None
    steamapps_dir = root.parent.parent
    manifest_path = steamapps_dir / f"appmanifest_{APP_ID}.acf"
    if not manifest_path.is_file():
        return None

    manifest = parse_app_manifest(manifest_path)
    expected_root = (steamapps_dir / "common" / manifest.install_dir).resolve()
    if expected_root != root:
        raise DiscoveryError(
            f"Steam metadata {manifest_path} points to {expected_root}, not {root}"
        )
    return manifest


def _installation_from_directory(
    game_dir: PathInput, discovery_source: str
) -> GameInstallation:
    root, paks_dir, shipping_executable = validate_game_directory(game_dir)
    return GameInstallation(
        root=root,
        paks_dir=paks_dir,
        shipping_executable=shipping_executable,
        discovery_source=discovery_source,
        manifest=_adjacent_manifest(root),
    )


def _steam_library_roots(libraryfolders_paths: Iterable[PathInput]) -> tuple[Path, ...]:
    roots: list[Path] = []
    seen: set[Path] = set()

    def add(root: Path) -> None:
        normalized = root.expanduser().resolve()
        if normalized not in seen:
            seen.add(normalized)
            roots.append(normalized)

    for input_path in libraryfolders_paths:
        metadata_path = Path(input_path).expanduser()
        if not metadata_path.is_file():
            continue
        # The VDF belongs to the primary Steam library itself.
        if metadata_path.parent.name.casefold() == "steamapps":
            add(metadata_path.parent.parent)
        for root in parse_library_folders(metadata_path):
            add(root)

    return tuple(roots)


def discover_game_installation(
    game_dir: PathInput | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    home: PathInput | None = None,
    libraryfolders_paths: Iterable[PathInput] | None = None,
) -> GameInstallation:
    """Discover and validate AFE2 using deterministic source precedence.

    Precedence is an explicit ``game_dir``, ``AFE2_GAME_DIR`` from ``environ``,
    then Steam manifests reachable through common Linux ``libraryfolders.vdf``
    locations.  An explicitly selected invalid path is reported rather than
    silently falling back to another installation.
    """

    if game_dir is not None:
        return _installation_from_directory(game_dir, "explicit")

    environment = os.environ if environ is None else environ
    environment_game_dir = environment.get(GAME_DIR_ENV)
    if environment_game_dir:
        return _installation_from_directory(environment_game_dir, "environment")

    metadata_paths = (
        tuple(libraryfolders_paths)
        if libraryfolders_paths is not None
        else common_libraryfolders_paths(home)
    )
    failures: list[str] = []
    found_manifest = False
    for library_root in _steam_library_roots(metadata_paths):
        steamapps_dir = library_root / "steamapps"
        manifest_path = steamapps_dir / f"appmanifest_{APP_ID}.acf"
        if not manifest_path.is_file():
            continue
        found_manifest = True
        try:
            manifest = parse_app_manifest(manifest_path)
            candidate = steamapps_dir / "common" / manifest.install_dir
            installation = _installation_from_directory(candidate, "steam")
        except DiscoveryError as error:
            failures.append(str(error))
            continue
        return installation

    if failures:
        details = "; ".join(failures)
        raise DiscoveryError(
            f"found AFE2 Steam metadata but no valid install: {details}"
        )
    # Defensive: a manifest always either succeeds or records a failure.
    if found_manifest:
        raise DiscoveryError("found AFE2 Steam metadata but no valid install")
    raise DiscoveryError(
        f"could not find Steam app {APP_ID}; provide game_dir or set {GAME_DIR_ENV}"
    )


def _inventory_paks(paks_dir: Path) -> tuple[ArchiveFile, ...]:
    records: list[ArchiveFile] = []
    supported_extensions = {".utoc", ".ucas", ".pak"}

    for path in paks_dir.rglob("*"):
        if not path.is_file() or path.suffix.casefold() not in supported_extensions:
            continue
        relative_path = path.relative_to(paks_dir).as_posix()
        archive_type = path.suffix[1:].casefold()
        if archive_type == "utoc":
            scan_status: str | None = "pending"
        elif archive_type == "pak":
            scan_status = "unscanned"
        else:
            scan_status = None
        records.append(
            ArchiveFile(
                relative_path=relative_path,
                size_bytes=path.stat().st_size,
                archive_type=archive_type,
                container_name=relative_path[: -len(path.suffix)],
                scan_status=scan_status,
            )
        )

    return tuple(sorted(records, key=lambda record: record.relative_path))


def inventory_archives(game_dir: PathInput) -> tuple[ArchiveFile, ...]:
    """Return archive file metadata without opening any archive contents."""

    _, paks_dir, _ = validate_game_directory(game_dir)
    return _inventory_paks(paks_dir)


def discover_source_inventory(
    game_dir: PathInput | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    home: PathInput | None = None,
    libraryfolders_paths: Iterable[PathInput] | None = None,
) -> SourceInventory:
    """Discover a game install and collect filesystem-only archive metadata."""

    installation = discover_game_installation(
        game_dir,
        environ=environ,
        home=home,
        libraryfolders_paths=libraryfolders_paths,
    )
    return SourceInventory(
        installation=installation,
        archives=_inventory_paks(installation.paks_dir),
    )


__all__ = [
    "APP_ID",
    "GAME_DIR_ENV",
    "ArchiveFile",
    "DiscoveryError",
    "GameInstallation",
    "SourceInventory",
    "SteamAppManifest",
    "common_libraryfolders_paths",
    "discover_game_installation",
    "discover_source_inventory",
    "inventory_archives",
    "parse_app_manifest",
    "parse_library_folders",
    "validate_game_directory",
]
