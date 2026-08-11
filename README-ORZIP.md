# ORZIP

ORZIP is a standalone modern Python tool for the MSTS/Open Rails `SIMISA@F` compressed-binary container used by `.s` shape files.

It replaces the old FFEDITC compression wrapper without using `ffeditc_unicode.exe`, `ffedit.exe`, `.tok`, `.bnf`, or `.hdr` files.

## What it supports now

- Detect SIMISA compressed, Unicode text, ASCII/unwrapped, and raw `JINX0...` payload files.
- Verify compressed files by inflating zlib and checking the header's declared payload length.
- Unpack compressed `SIMISA@F` files to raw `JINX0...` binary payloads.
- Pack raw `JINX0...` binary payloads back into MSTS-compatible `SIMISA@F` compressed files.
- Normalize/repack existing compressed files with modern zlib.
- Batch folder processing with `-r`.
- Inspect embedded MSTS/FFEDIT token and shape grammar definitions with `defs`.
- Dump binary `s1b` block headers/hierarchy from compressed or raw files with `dump-blocks`.
- Decode binary `s1b` block contents into grammar-named values with `dump-values`.
- Export compressed/raw binary `s1b` shape data to UTF-16 textual `s1t` files with `s1b2s1t` / `decompress-text`.
- Convert textual `s1t` shape files back to raw or compressed binary `s1b` with `s1t2s1b` / `compress-text`.

## Important format note

FFEDITC does two different jobs:

1. zlib container compression/decompression:
   `SIMISA@F + length + @@@@ + zlib(JINX0...s1b...)`
2. token/grammar conversion:
   binary/tokenized `s1b` <-> textual UTF-16 `s1t`

This version of ORZIP replaces job 1. It deliberately does not pretend that zlib unpacking is the same thing as FFEDITC's `s1b` <-> `s1t` token conversion.

The local verification proves that ORZIP-repacked `.s` files remain acceptable to FFEDITC for text conversion.

## Embedded definitions

`orzip_defs.py` embeds the first definition layer needed for full `s1b` <-> `s1t` conversion:

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
python orzip.py detect --verify comp_csx9550.s FFEDIT/dash8.s
python orzip.py validate comp_csx9550.s csx9550.s
python orzip.py roundtrip comp_csx9550.s csx9550.s
python orzip.py validate -r --only-s Shapes
python orzip.py convert -r --only-s Shapes -o ConvertedShapes
python orzip.py convert comp_csx9550.s
python orzip.py convert csx9550.s
python orzip.py unpack comp_csx9550.s -o csx9550.slb
python orzip.py pack csx9550.slb -o csx9550_repacked.s
python orzip.py normalize FFEDIT/dash8.s -o dash8_norm.s
python orzip.py detect -r --verify FFEDIT
python orzip.py defs
python orzip.py defs --token shape
python orzip.py defs --grammar points
python orzip.py dump-blocks FFEDIT/dash8.s --max-depth 1 --limit 30
python orzip.py dump-blocks comp_csx9550.s --max-depth 2 --limit 20 --show-gaps
python orzip.py dump-values comp_csx9550.s --max-depth 4 --item-limit 3
python orzip.py s1b2s1t comp_csx9550.s -o csx9550_orzip.s
python orzip.py uncompress FFEDIT/dash8.s -o dash8_orzip.s
python orzip.py s1t2s1b csx9550.s -o csx9550.slb
python orzip.py s1t2s1b csx9550.s --compress -o csx9550_compressed.s
python orzip.py compress FFEDIT/dash8u.s -o dash8_compressed.s
python test_orzip.py
```

Text/binary conversion commands default to in-place conversion: the filename stays the same and only the file contents change. Pass `-o/--output` when you want a separate output file or folder. Use `--force` to overwrite an explicit output path that already exists.

## Verified in this folder

- `comp_csx9550.s` inflates to a 671,102-byte raw `JINX0s1b` payload.
- Repacking and unpacking that payload gives an identical SHA-256 hash.
- `FFEDIT/dash8.s` inflates to a 3,440,900-byte raw `JINX0s1b` payload.
- `ACL66320.s` inflates to a 1,313,974-byte raw `JINX0s1b` wagon-shape payload and round-trips binary -> text -> binary byte-exactly.
- `DEPOT.S` inflates to a 54,161-byte raw `JINX0s1b` scenery-shape payload and round-trips binary -> text -> binary byte-exactly.
- `CR_GP38-2_8270.s` inflates to a 5,757,584-byte raw `JINX0s1b` complex locomotive-shape payload and round-trips binary -> text -> binary byte-exactly.
- An ORZIP-normalized `dash8.s` was accepted by `ffeditc_unicode.exe` and converted to UTF-16 text identical to `FFEDIT/dash8u.s`.
- `dump-blocks` identifies the root `shape` block and expected top-level shape children in both `FFEDIT/dash8.s` and `comp_csx9550.s`.
- `dump-values` decodes named primitive fields for core shape structures, including shape headers, volume spheres, shader/filter names, points, UV points, normals, matrices, images, textures, vertex states, primitive states, LOD controls, and animations.
- The first decoded point from `comp_csx9550.s` matches the first text point in `csx9550.s`: `-1.51228 0.435418 -7.89935`.
- `s1b2s1t` generated UTF-16 text from both `comp_csx9550.s` and `FFEDIT/dash8.s`.
- FFEDITC accepted both ORZIP-generated text files, compressed them back to binary, and decompressed those binaries back to UTF-16 text.
- `s1t2s1b csx9550.s` generated a raw 671,102-byte `JINX0s1b` payload byte-identical to the decompressed payload from `comp_csx9550.s`.
- `compress FFEDIT/dash8u.s` generated a compressed file whose declared decompressed size is 3,440,900 bytes and which ORZIP can convert back to text.
- `convert` auto-detects binary/compressed input and writes UTF-16 text in place, or auto-detects text input and writes compressed binary in place.
- `validate` checks compressed/raw/text shape files without writing output.
- `roundtrip` checks binary -> text -> binary or text -> binary -> text conversion without writing output.
- `python test_orzip.py` runs the automated regression suite for detection, zlib verification, binary->text rendering, text->binary writing, and CLI compress/decompress smoke coverage.

## Regression tests

Run:

```bash
python test_orzip.py
```

The test suite uses only Python's standard library and the sample files in this folder. It verifies:

- `comp_csx9550.s` and `FFEDIT/dash8.s` are detected as compressed and inflate to the expected raw payload sizes.
- `csx9550.s` encodes back to a raw binary payload byte-identical to the inflated payload from `comp_csx9550.s`.
- `ACL66320.s` renders to text and encodes back to the original binary payload byte-for-byte.
- `DEPOT.S` renders to text and encodes back to the original binary payload byte-for-byte.
- `CR_GP38-2_8270.s` renders to text and encodes back to the original binary payload byte-for-byte.
- binary `comp_csx9550.s` renders to text containing known shape values.
- `FFEDIT/dash8u.s` encodes to a valid compressed container with the expected declared decompressed size.
- the CLI can run `compress` followed by `uncompress` on `csx9550.s`, defaulting to in-place conversion when no `-o` is supplied.
- the CLI can run `convert` on compressed binary input and text input.
- the CLI can run `validate` on compressed binary input and text input, and rejects unsupported files clearly.
- the CLI can run `roundtrip` on compressed binary input and text input.
- recursive folder processing can be limited to `.s`/`.S` files with `--only-s`.
- recursive `convert` can mirror a folder tree under an output directory.

## Folder processing

Most commands accept directories as inputs. Use `-r` to recurse and `--only-s` to ignore non-shape files:

```bash
python orzip.py validate -r --only-s Shapes
python orzip.py roundtrip -r --only-s Shapes
python orzip.py detect -r --only-s --verify Shapes
```

Recursive conversion without `-o` rewrites each `.s` file in place. Pass an output directory with `-o` when you want a separate converted tree; ORZIP then preserves the relative folder layout:

```bash
python orzip.py convert -r --only-s Shapes -o ConvertedShapes
```

Example:

```text
Shapes/DEPOT.S
Shapes/Nested/ACL66320.s

ConvertedShapes/DEPOT.S.s1t.s
ConvertedShapes/Nested/ACL66320.s.s1t.s
```

Without `--only-s`, recursive commands inspect every file in the folder tree.

## Round-trip checks

Use `roundtrip` to verify that ORZIP can convert a file through the opposite representation without writing output:

```bash
python orzip.py roundtrip comp_csx9550.s csx9550.s
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

Use `validate` to check files without producing converted output:

```bash
python orzip.py validate comp_csx9550.s csx9550.s
```

For compressed/raw binary shape files it checks:

- zlib/container integrity and declared payload size when compressed
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

The explicit commands remain available when you need to force a specific layer: `unpack`, `pack`, `s1b2s1t`, `s1t2s1b`, `compress`, and `uncompress`. The older names `compress-text` and `decompress-text` are still accepted as compatibility aliases.

## Current `dump-blocks` limitation

`dump-blocks` is a structural block-header inspector, not a full grammar decoder yet. It scans block boundaries and uses the embedded token table to name blocks. With `--show-gaps`, primitive data such as counts and floats appears as `<data>` gaps. The next step is to replace scanning with grammar-guided field decoding so those gaps become named values like `num_points`, `pX`, `pY`, and `pZ`.

`dump-values` is the first grammar-guided decoder. It is intended for inspection and parser development, not final `.s` text export yet. It limits repeated lists by default with `--item-limit` so huge arrays such as `points`, `uv_points`, and `normals` do not flood the terminal. Use `--item-limit -1` only when you intentionally want complete output.

`s1b2s1t` is the first full text exporter. It is now good enough for FFEDITC to read the generated text for the tested files, but its formatting is ORZIP's own clean S-expression style rather than byte-for-byte FFEDITC formatting. This is expected: whitespace and some string quoting are not semantically important. ORZIP emits enough float precision for tested ORZIP-generated text to encode back to the original float32 payload bytes.

`s1t2s1b` is the first grammar-guided binary writer. It round-trips the provided `csx9550.s` exactly to the original binary payload. Some text files produced by FFEDITC may contain rounded float values, so converting those back to binary can be structurally valid without being byte-identical to the original binary source.
