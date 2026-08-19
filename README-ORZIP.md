# ORZIP 1.0.3

ORZIP is a standalone modern Python tool for the MSTS/Open Rails `SIMISA@F` compressed-binary container used by `.s` shape files.

It replaces the old FFEDITC compression wrapper without using `ffeditc_unicode.exe`, `ffedit.exe`, `.tok`, `.bnf`, or `.hdr` files.

## What it supports now

- Detect SIMISA compressed, Unicode text, ASCII/unwrapped, and raw `JINX0...` payload files.
- Verify compressed files by inflating zlib and checking the header's declared payload length.
- Unpack compressed `SIMISA@F` files to raw `JINX0...` binary payloads.
- Pack raw `JINX0...` binary payloads back into MSTS-compatible `SIMISA@F` compressed files.
- Normalize/repack existing compressed files with modern zlib.
- Batch folder processing with `-r` and `.s` filtering with `-s/--only-s`.
- Atomic in-place replacement with versioned backups.
- Mirrored output trees for directory and multiple-file conversion.
- Preflight protection against output/output, output/input, symlink, and hard-link collisions.
- Strict zlib validation, including truncation, trailing-data, and declared-length checks.
- Inspect embedded MSTS/FFEDIT token and shape grammar definitions with `defs`.
- Dump binary `s1b` block headers/hierarchy from compressed or raw files with `blocks`.
- Decode binary `s1b` block contents into grammar-named values with `values`.
- Export compressed/raw binary `s1b` shape data to UTF-16 textual `s1t` files with `text`.
- Convert textual `s1t` shape files back to compressed binary `.s` files with `binary`.

## Important format note

FFEDITC does two different jobs:

1. zlib container compression/decompression:
   `SIMISA@F + length + @@@@ + zlib(JINX0...s1b...)`
2. token/grammar conversion:
   binary/tokenized `s1b` <-> textual UTF-16 `s1t`

ORZIP implements both jobs for the supported shape grammar. The low-level `raw`, `wrap`, and `repack` commands operate on the container layer; `text`, `binary`, and `convert` also perform grammar-guided `s1b`/`s1t` conversion.

ORZIP's text formatting is normalized and is not intended to reproduce FFEDITC whitespace byte-for-byte. Binary -> text -> binary tests compare the raw binary payload when byte-exact verification is possible.

## Embedded definitions

`orzip_defs.py` embeds the token and grammar definitions used for `s1b` <-> `s1t` conversion:

- 283 core token names from `coreids.tok`, with numeric lookup.
- 1,240 expanded app/form/load-string token names from `appids.tok`, `forms.hdr`, and `loadstr.hdr`.
- 100 shape grammar rules from `newshape.bnf`.

Known verified core token IDs include:

```text
shape = 71
shape_header = 70
points = 7
point = 2
named_shader = 129
```

## Examples

```bash
python orzip.py info --verify model.s
python orzip.py check model.s model_text.s
python orzip.py test model.s model_text.s
python orzip.py check -r -s Shapes
python orzip.py convert -r -s Shapes -o ConvertedShapes
python orzip.py convert model.s
python orzip.py raw model.s -o model.s1b
python orzip.py wrap model.s1b -o model_wrapped.s
python orzip.py repack model.s -o model_repacked.s
python orzip.py defs
python orzip.py defs --token shape
python orzip.py defs --grammar points
python orzip.py blocks model.s --max-depth 2 --limit 20 --show-gaps
python orzip.py values model.s --max-depth 4 --item-limit 3
python orzip.py text model.s -o model_text.s
python orzip.py binary model_text.s -o model_binary.s
python test_orzip.py
```

Without `-o`, `convert`, `text`, and `binary` operate in place. ORZIP writes and synchronizes a same-directory temporary file, publishes a versioned backup (`model.s.bak`, then `.bak.1`, `.bak.2`, and so on), and atomically replaces the source. A failed write or replacement leaves the original intact. The explicit `--no-backup` option skips backup creation but still uses the temporary file and atomic replacement; after a successful replacement, the previous contents are not recoverable through ORZIP.

For `convert`, `text`, `binary`, and their technical aliases, one explicit input file makes `-o` an output file. With multiple files or directory input, `-o` is an output directory; ORZIP appends `.s1t.s`, `.compressed.s`, or `.s1b` as appropriate and preserves relative directories. Planned outputs are checked before writing so `--force` cannot overwrite another input or collapse colliding outputs.

## Validation and safety

For compressed files, `check` verifies the SIMISA header, complete zlib stream consumption, absence of trailing data, declared payload length, binary header, root block, and grammar decode. Text input is parsed and grammar-encoded without writing output. Malformed values, unterminated strings, excessive nesting, and expected filesystem failures are reported as concise ORZIP errors rather than Python tracebacks.

## Regression tests

Run:

```bash
python test_orzip.py
```

The source-only suite generates a minimal valid shape in the operating-system temporary directory. It covers container integrity, text/binary conversion, atomic backups, output planning and collision protection, mirrored directories, CLI behavior, and malformed-input errors without storing sample shapes in Git.

Four optional integration tests run when these ignored local files exist:

- `samples/dash8.s`
- `samples/dash8u.s`
- `samples/275004_KN.s`
- `samples/275004_LN.s`

The optional tests are the external compatibility oracle for larger real-world payloads. When those files are absent, the four tests are reported as skipped; the source-only suite still runs. The repository intentionally tracks no sample `.s` files.

## Building Windows release artifacts

From Command Prompt, install the pinned build dependencies and run the complete release build:

```text
python -m pip install -r requirements-build.txt
build_release.bat
```

This builds `DIST\orzip.exe` with PyInstaller, renders `USER_GUIDE.md` as `DIST\DOCS\ORZIP_EXE_User_Guide.pdf` with ReportLab, copies the current source documentation, and rewrites `DIST\SHA256SUMS.txt`. The checksum writer requires exactly the six documented release files and rejects missing or unexpected artifacts.

The individual build entry points are:

```text
build_orzip_exe.bat
build_user_guide_pdf.bat
```

Both builders generate through temporary artifacts before replacing the final output. If a final EXE or PDF is open or locked, the script reports the fresh temporary artifact instead of discarding it. The PDF uses deterministic metadata and built-in fonts; the EXE build sets a fixed source epoch and Python hash seed. With the pinned dependencies, consecutive clean builds in the same supported environment produce stable hashes.

## Folder processing

Most commands accept directories as inputs. Use `-r` to recurse and `-s/--only-s` to ignore non-shape files:

```bash
python orzip.py check -r -s Shapes
python orzip.py test -r -s Shapes
python orzip.py info -r -s --verify Shapes
```

Recursive conversion without `-o` converts each `.s` file in place using atomic replacement and a versioned backup. Pass an output directory with `-o` when you want a separate converted tree; ORZIP preserves the relative folder layout:

```bash
python orzip.py convert -r -s Shapes -o ConvertedShapes
```

Example:

```text
Shapes/model.S
Shapes/Nested/building.s

ConvertedShapes/model.S.s1t.s
ConvertedShapes/Nested/building.s.s1t.s
```

Without `-s/--only-s`, recursive commands inspect every file in the folder tree. If the output directory is nested under a recursive input directory, ORZIP excludes that output subtree from input discovery. The output directory cannot be identical to an input directory.

## Round-trip checks

Use `test` to verify that ORZIP can convert a file through the opposite representation without writing output:

```bash
python orzip.py test model.s model_text.s
```

For compressed/raw binary shape files it performs:

```text
binary -> text -> binary
```

and reports whether the raw binary payload is byte-exact after the round-trip, including SHA-256 when it matches.

For UTF-16/UTF-8 text shape files it performs:

```text
text -> binary -> text
```

and reports that the regenerated text is parseable. Text formatting may differ from the input because ORZIP emits its own normalized S-expression style.

## Validation

Use `check` to check files without producing converted output:

```bash
python orzip.py check model.s model_text.s
```

For compressed/raw binary shape files it checks:

- complete zlib stream, no trailing data, and declared payload size when compressed
- `JINX0s1b` binary payload header
- root binary block parses as `shape`
- grammar-guided binary decode succeeds

For UTF-16/UTF-8 text shape files it checks:

- text parses as SIMISA/S-expression shape text
- root block parses as `shape`
- grammar-guided binary encode succeeds

## One-command conversion

For normal use, prefer `convert`. Without `-o`, conversion is in-place:

```bash
python orzip.py convert model.s
```

It auto-detects the input:

- compressed binary `.s` -> UTF-16 text `s1t`, same filename
- raw binary `JINX0s1b` payload -> UTF-16 text `s1t`, same filename
- UTF-16/UTF-8 text `s1t` -> compressed binary `.s`, same filename

Pass `-o` to write a new file instead of replacing the input:

```bash
python orzip.py convert model.s -o model_converted.s
```

The explicit commands remain available when you need to force a specific layer: `text`, `binary`, `raw`, `wrap`, and `repack`. Run `python orzip.py --advanced-help` to see the compatibility and technical command names such as `s1b2s1t` and `s1t2s1b`.

## Inspection and conversion notes

`blocks` is a structural block-header inspector. It scans block boundaries and uses the embedded token table to name blocks; primitive data may appear as `<data>` gaps when `--show-gaps` is enabled.

`values` is the grammar-guided value inspector. It limits repeated lists by default so large point, UV, and normal arrays do not flood the terminal. Use `--item-limit -1` only when complete output is intentional.

`text` is the full text exporter and emits normalized S-expression formatting. `binary` is the grammar-guided compressed binary writer. Whitespace and quoting may differ from other tools, and rounded float text can produce a structurally valid binary file that is not byte-identical to an earlier binary source.

Text nesting is limited to 256 blocks so malformed input cannot exhaust Python recursion. ORZIP does not catch unexpected programming exceptions broadly; expected file, format, and value errors receive concise messages, while genuine implementation defects remain visible during development.
