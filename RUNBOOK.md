# AFE2 catalogue extractor runbook

This is the practical guide. The technical design and data contract live in
the [README](README.md).

The commands assume Linux. Do not run the extractor with `sudo`.

Before starting, install the requirements listed below and make sure AFE2 is
installed through Steam. In short: Python 3.10+, Git, Rust/Cargo 1.85+, a C
toolchain with zlib development files, and .NET 9.

## Quick start

If you have not cloned the repository yet:

```bash
git clone https://github.com/CheesyRamen66/AFE2-Build-Planner.git
cd AFE2-Build-Planner
```

If you already have it, open a terminal in the repository:

```bash
cd /path/to/AFE2-Build-Planner
```

Run the setup check once:

```bash
python3 scripts/build_catalogue.py doctor
```

Then build the catalogue:

```bash
python3 scripts/build_catalogue.py extract
```

That is the normal workflow. You do not need to install Python packages or run
`bootstrap-tools` first. Once the system requirements are present, the
project's private `retoc`, `repak`, and reader helpers are downloaded and built
automatically.

The first run needs internet access and can take several minutes. Later runs
take roughly half a minute on the development machine.

## How to tell that it worked

`doctor` should finish with a line similar to:

```text
AES key: validated from executable; value not persisted
```

`extract` should finish with lines similar to:

```text
Wrote catalogue extraction to .../.local/catalogue
Built Collection-filtered planner catalogue: ...
```

Errors begin with `error:`. A failed extraction does not replace the last good
catalogue.

The main result for the frontend is:

```text
.local/catalogue/planner-catalogue.json
```

## After an AFE2 update

Wait for Steam to finish updating, then run:

```bash
python3 scripts/build_catalogue.py extract
```

Do not delete the existing catalogue first. A successful extraction:

1. builds and validates a completely new catalogue;
2. compares it with the previous one;
3. archives the previous one under `.local/catalogue-archive/`; and
4. replaces `.local/catalogue/` only after all checks pass.

Changes to the frontend dataset are in:

```text
.local/catalogue/changes.json
```

Within that file, `recordChanges` is the useful section. `candidateChanges` is
the broader game-file scan and is normally much noisier.

## Files you will actually use

| Path | Purpose |
| --- | --- |
| `.local/catalogue/planner-catalogue.json` | Main build-editor dataset |
| `.local/catalogue/icons/` | Icons referenced by catalogue records |
| `.local/catalogue/grid-assets.json` | Grid-art and layout manifest |
| `.local/catalogue/grid-assets/` | Grid textures and widget information |
| `.local/catalogue/changes.json` | Changes since the previous extraction |
| `.local/catalogue/validation.json` | Validation result, warnings, and counts |
| `.local/catalogue-archive/` | Previous complete catalogues |
| `.local/save-evidence.json` | Optional character-save evidence report |

The other generated JSON files are diagnostic evidence and can normally be
ignored.

Everything under `.local/` is ignored by Git. The `icons/` and `grid-assets/`
directories contain extracted game assets, and the JSON contains authored game
text. Git ignoring them does not grant permission to redistribute them; do not
commit or publish them unless distribution rights have been resolved.

## Check or browse the result

Extraction validates before publishing. If `jq` is installed, this gives a
short view without printing every warning detail:

```bash
jq '{valid, errors, warningCount: (.warnings | length), summary}' \
  .local/catalogue/validation.json
```

To independently rerun all validation checks:

```bash
python3 scripts/build_catalogue.py validate .local/catalogue
```

The important result is `"valid": true`. The independent command prints full
warning details and can be long. Warnings are informational during a normal
run; `--strict` deliberately turns every warning into an error and is not
recommended for routine refreshes.

If `jq` is installed, these optional commands provide shorter views.

Show record counts:

```bash
jq '.coverage.recordsByKind' \
  .local/catalogue/planner-catalogue.json
```

List every human-readable name:

```bash
jq -r '.records[] | [.kind, .displayName] | @tsv' \
  .local/catalogue/planner-catalogue.json | sort
```

List only weapons; replace `weapon` with `kit`, `ability`, `perk`, `mod`,
`trait`, `augment`, or `item` for another type:

```bash
jq -r '.records[] | select(.kind == "weapon") | .displayName' \
  .local/catalogue/planner-catalogue.json | sort
```

Summarize changes from the previous extraction:

```bash
jq '{
  added: (.recordChanges.added | length),
  changed: (.recordChanges.changed | length),
  removed: (.recordChanges.removed | length)
}' .local/catalogue/changes.json
```

## Inspect a readable character save

This is optional and is not needed to build the catalogue. It records assets
observed in one save without changing what the editor may offer.

Pass an already decoded, readable `char.dec` or `char.json`:

```bash
python3 scripts/build_catalogue.py inspect-save \
  "/full/path/to/char.json"
```

It reads the save without modifying it and writes:

```text
.local/save-evidence.json
```

Do not pass the original encoded `char.sav`; this command is not a save
decoder.

When using non-default paths:

```bash
python3 scripts/build_catalogue.py inspect-save \
  "/full/path/to/char.json" \
  --catalogue-dir "/full/path/to/catalogue" \
  --output "/full/path/to/save-evidence.json"
```

Choose a dedicated report filename: `--output` atomically replaces that file on
later runs. Although the report is identity-stripped, it still describes a
player's inventory, loadouts, and progress and should be reviewed before it is
shared.

## If the game is not found

Point at the game folder—not its `Paks` subdirectory—and quote the path:

```bash
python3 scripts/build_catalogue.py doctor \
  --game-dir "/full/path/to/Aliens Fireteam Elite 2"

python3 scripts/build_catalogue.py extract \
  --game-dir "/full/path/to/Aliens Fireteam Elite 2"
```

To reuse that path for the rest of the terminal session:

```bash
export AFE2_GAME_DIR="/full/path/to/Aliens Fireteam Elite 2"
```

## If archive-key discovery fails

Normally no key setup is needed: the extractor scans your installed game
executable, validates a candidate, and never prints or saves it. The helper
programs necessarily receive the validated key in their process arguments, so
it can briefly be visible to other processes owned by the same local OS user.

As a fallback, store the key outside the repository in a private file:

```bash
install -d -m 700 "$HOME/.config/afe2-build-planner"
touch "$HOME/.config/afe2-build-planner/aes.key"
chmod 600 "$HOME/.config/afe2-build-planner/aes.key"
nano "$HOME/.config/afe2-build-planner/aes.key"
```

If `nano` is not installed, open that same file with your usual text editor.

This fallback assumes you already have the key. The file must contain one
64-character hexadecimal key, optionally prefixed by `0x`, and nothing else.
Then use it for both commands:

```bash
python3 scripts/build_catalogue.py doctor \
  --key-file "$HOME/.config/afe2-build-planner/aes.key" \
  --no-executable-key-scan

python3 scripts/build_catalogue.py extract \
  --key-file "$HOME/.config/afe2-build-planner/aes.key" \
  --no-executable-key-scan
```

Never paste the key into an issue, commit it, or place it directly in the
extractor command.

## Requirements

- Python 3.10 or newer
- Git
- Rust and Cargo 1.85 or newer
- a native C compiler/linker and zlib development files
- .NET SDK 9 or newer plus the `Microsoft.NETCore.App` 9 runtime
- a locally installed Steam copy of AFE2

Check the main tool versions with:

```bash
python3 --version
git --version
cargo --version
dotnet --version
dotnet --list-sdks
dotnet --list-runtimes
cc --version
```

The first helper build can consume several gigabytes. Later runs reuse
`.tools/`; old catalogue snapshots accumulate under
`.local/catalogue-archive/`.

## Common problems

| Message or symptom | What to do |
| --- | --- |
| Python cannot open `scripts/build_catalogue.py` | `cd` into the repository first |
| The Steam game is not found | Use `--game-dir` as shown above |
| `git`, `cargo`, a compiler, zlib, or `dotnet` is missing | Install the missing requirement, then rerun `doctor` |
| The .NET runtime is missing | Confirm `dotnet --list-runtimes` includes `Microsoft.NETCore.App 9.` |
| The archive key cannot be validated | Use the private key-file instructions above |
| The computer runs out of memory or the reader is killed | Retry with `python3 scripts/build_catalogue.py extract --jobs 2`, then `--jobs 1` |
| Validation prints warnings | Check `"valid"`; avoid `--strict` during normal use |
| Extraction stops partway through | Fix the reported error and rerun it; the old catalogue is intact |
| The output directory is rejected | Move personal files somewhere safe; if generated files were edited, move the entire directory aside and rerun |
| Disk use keeps growing | Old snapshots are in `.local/catalogue-archive/`; `--no-archive` stops adding rollback copies but does not delete existing archives |

`.local/catalogue/` is wholly managed by the extractor. Do not store notes or
other personal files inside it. A custom `--output` likewise owns and replaces
the complete target directory, so never point it at a general-purpose folder.

## Less-common commands and options

Prepare only the helper programs:

```bash
python3 scripts/build_catalogue.py bootstrap-tools
```

Diagnose a reader problem with one process:

```bash
python3 scripts/build_catalogue.py extract --jobs 1
```

Stop retaining the immediately previous live catalogue on future runs:

```bash
python3 scripts/build_catalogue.py extract --no-archive
```

This does not delete existing `.local/catalogue-archive/` snapshots. After a
successful run, it simply discards the catalogue that was just replaced instead
of adding that copy to the archive.

Compare an archived catalogue with the current one:

```bash
ls -1 .local/catalogue-archive

python3 scripts/build_catalogue.py diff \
  ".local/catalogue-archive/<archived-folder-name>" \
  .local/catalogue \
  --output .local/manual-diff.json
```

Show all commands or the options for one command:

```bash
python3 scripts/build_catalogue.py --help
python3 scripts/build_catalogue.py extract --help
```

Run the maintainer test suite:

```bash
PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest discover -s tests -v
```
