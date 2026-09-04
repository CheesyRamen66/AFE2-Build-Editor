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
git clone https://github.com/CheesyRamen66/AFE2-Build-Editor.git
cd AFE2-Build-Editor
```

The repository's current default branch is `dev`; a normal clone selects it
automatically.

If you already have it, open a terminal in the repository:

```bash
cd /path/to/AFE2-Build-Editor
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

Show the text the editor receives for a component mod, trait, or augment (this
example uses Priming Chamber):

```bash
jq '.records[]
  | select(.kind == "mod" and .displayName == "Priming Chamber")
  | {displayName, description, staticStatLines, conditionalDescriptions}' \
  .local/catalogue/planner-catalogue.json
```

`description` is the ready-to-render picker text. `staticStatLines` exposes the
same rows in a structured form for styling or inspection; their values have
already been interpreted and formatted by the extractor. The frontend should
not calculate attachment stats. Low-level effect definitions and mechanical
operations live only in the diagnostic evidence files, not in the planner
catalogue.

Inspect one weapon-specific augment implementation, including its authored
panel regions and generated stat rows:

```bash
jq '.records[]
  | select(.kind == "augment" and .displayName == "High Explosive Rounds")
  | {id, compatibleWeaponIds, description, descriptionPanel,
     staticStatLines, conditionalDescriptions}' \
  .local/catalogue/planner-catalogue.json
```

Repeated names are expected here: each row is the implementation for a
particular weapon family, and its values can differ. The selected weapon's
augment slot already references only the compatible implementation IDs.
The composed `description` puts every authored section, generated stat, and
trigger on consecutive lines without blank spacer rows. Triggered rows appear
beneath their trigger with a two-space indent, and generated signs are compact,
for example `+20.0%` or `-75%`.

Confirm that every selectable attachment has picker copy (a clean run prints
nothing):

```bash
jq -r '.records[]
  | select(.kind == "mod" or .kind == "trait" or .kind == "augment")
  | select((.description // "") == "")
  | [.kind, .displayName] | @tsv' \
  .local/catalogue/planner-catalogue.json
```

Summarize changes from the previous extraction:

```bash
jq '{
  added: (.recordChanges.added | length),
  changed: (.recordChanges.changed | length),
  removed: (.recordChanges.removed | length)
}' .local/catalogue/changes.json
```

## Locate, decode, and inspect a character save

This is optional and is not needed to build the catalogue. It records assets
observed in one save without changing what the editor may offer.

The Windows location is:

```text
%LOCALAPPDATA%\AFE2\Saved\SaveGames\<SteamID64>\char.sav
```

Under Linux/Proton, the same location is normally:

```text
<Steam-library>/steamapps/compatdata/3448650/pfx/drive_c/users/steamuser/AppData/Local/AFE2/Saved/SaveGames/<SteamID64>/char.sav
```

The numeric `<SteamID64>` directory is account-specific. Replace the
placeholder below with the directory that contains your `char.sav`:

```bash
afe2_save_dir="/full/path/to/SaveGames/<SteamID64>"
test -f "$afe2_save_dir/char.sav"
mkdir -p .local
```

AFE2 applies XOR `0x42` to the save. Decode it into the repository's ignored
`.local/` directory with the following command. It deliberately leaves the
save's final `}` byte unchanged so the result is valid JSON:

```bash
python3 -c 'import sys; d=sys.stdin.buffer.read(); assert d.endswith(b"}"), "unexpected save format"; sys.stdout.buffer.write(bytes(b ^ 0x42 for b in d[:-1]) + d[-1:])' \
  < "$afe2_save_dir/char.sav" \
  > .local/char.json

python3 -m json.tool .local/char.json > /dev/null
chmod 600 .local/char.json
```

Now inspect the decoded file:

```bash
python3 scripts/build_catalogue.py inspect-save .local/char.json
```

It reads the save without modifying it and writes:

```text
.local/save-evidence.json
```

`inspect-save` never modifies either file. Do not pass the encoded `char.sav`
directly; decoding and save inspection are separate steps.

Before editing anything, prove that your decoded file converts back to the
original save:

```bash
python3 -c 'import sys; d=sys.stdin.buffer.read(); assert d.endswith(b"}"), "unexpected decoded save format"; sys.stdout.buffer.write(bytes(b ^ 0x42 for b in d[:-1]) + d[-1:])' \
  < .local/char.json \
  > .local/char.roundtrip.sav

cmp -- "$afe2_save_dir/char.sav" .local/char.roundtrip.sav
```

No output from `cmp` means the files are byte-for-byte identical.

The shorter command that XORs every byte is also reversible, but its decoded
output ends in a literal `?` because AFE2 stores the save's final `}` unencoded.
`inspect-save` accepts that observed form, but ordinary JSON tools do not. Do
not mix the whole-file command with the final-`}`-preserving commands above.

### Write an edited save back

This is separate from catalogue extraction; the extractor itself never writes
to a save. Let Steam Cloud finish syncing, then fully exit AFE2 and Steam.
Make a backup outside the game's save directory every time:

```bash
mkdir -p .local/save-backups
afe2_backup=".local/save-backups/char-$(date +%Y%m%d-%H%M%S-%N).sav"
cp -- "$afe2_save_dir/char.sav" "$afe2_backup"
cmp -- "$afe2_save_dir/char.sav" "$afe2_backup"
```

First validate the edited JSON and remove only trailing whitespace that an
editor may have added. Then encode a staged save and decode it again to verify
the result. Do not redirect output directly over the live `char.sav`:

```bash
python3 -c 'import json, sys; d=sys.stdin.buffer.read().rstrip(b" \t\r\n"); doc=json.loads(d); assert isinstance(doc, dict) and doc.get("_Type") == "CharacterDoc", "expected CharacterDoc JSON"; sys.stdout.buffer.write(d)' \
  < .local/char.json \
  > .local/char.ready.json

python3 -c 'import sys; d=sys.stdin.buffer.read(); assert d.endswith(b"}"), "JSON must end with }"; sys.stdout.buffer.write(bytes(b ^ 0x42 for b in d[:-1]) + d[-1:])' \
  < .local/char.ready.json \
  > "$afe2_save_dir/char.sav.new"

python3 -c 'import sys; d=sys.stdin.buffer.read(); assert d.endswith(b"}"), "unexpected encoded save format"; sys.stdout.buffer.write(bytes(b ^ 0x42 for b in d[:-1]) + d[-1:])' \
  < "$afe2_save_dir/char.sav.new" \
  > .local/char.verify.json

cmp -- .local/char.ready.json .local/char.verify.json &&
chmod --reference="$afe2_save_dir/char.sav" "$afe2_save_dir/char.sav.new" &&
mv -- "$afe2_save_dir/char.sav.new" "$afe2_save_dir/char.sav"
```

The live save is replaced only if `cmp` confirms an exact decoded round trip.
Keep the backup until the edited save has loaded correctly in game. Steam Cloud
may ask which copy to keep after an out-of-game edit; check its timestamps and
do not let it silently restore the older cloud copy.

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
shared. Treat the original save, decoded JSON, and SteamID64 as private; do not
attach them to a public issue.

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
install -d -m 700 "$HOME/.config/afe2-build-editor"
touch "$HOME/.config/afe2-build-editor/aes.key"
chmod 600 "$HOME/.config/afe2-build-editor/aes.key"
nano "$HOME/.config/afe2-build-editor/aes.key"
```

If `nano` is not installed, open that same file with your usual text editor.

This fallback assumes you already have the key. The file must contain one
64-character hexadecimal key, optionally prefixed by `0x`, and nothing else.
Then use it for both commands:

```bash
python3 scripts/build_catalogue.py doctor \
  --key-file "$HOME/.config/afe2-build-editor/aes.key" \
  --no-executable-key-scan

python3 scripts/build_catalogue.py extract \
  --key-file "$HOME/.config/afe2-build-editor/aes.key" \
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
