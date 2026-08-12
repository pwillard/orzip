# ORZIP User Guide

This guide is for MSTS/Open Rails users who want to check or convert `.s` shape files without needing to understand the internals of the SIMISA file format.

ORZIP works with MSTS/Open Rails shape files. It can tell what kind of shape file you have, check whether it can be read, convert between compressed binary and editable text forms, and process whole folders of shape files.

## Quick safety advice

Before converting files in an installed route or trainset, make a backup.

The `convert`, `compress`, and `uncompress` commands change files in place when you do not give an output location. That means the filename stays the same, but the file contents are replaced with the converted version.

A safe first pass is:

```text
orzip.exe validate -r --only-s "C:\MSTS\ROUTES\MyRoute\SHAPES"
orzip.exe roundtrip -r --only-s "C:\MSTS\ROUTES\MyRoute\SHAPES"
```

Only convert after those checks pass and after you have a backup.

## Running ORZIP

If you have `orzip.exe`, use commands like this:

```text
orzip.exe validate model.s
```

If you are running from the Python source version, use commands like this instead:

```text
python orzip.py validate model.s
```

The examples below use `orzip.exe`. Replace `orzip.exe` with `python orzip.py` if you are using the Python source version.

## Common tasks

### Check a single shape file

Use `validate` when you want to know whether ORZIP can read a file correctly.

```text
orzip.exe validate model.s
```

This does not write any output files.

### Check every shape file in a folder

Use `-r` to include subfolders. Use `--only-s` so ORZIP only looks at `.s` and `.S` files.

```text
orzip.exe validate -r --only-s "C:\MSTS\ROUTES\MyRoute\SHAPES"
```

### Test whether conversion is safe

Use `roundtrip` to test whether ORZIP can convert a file out and back again without writing anything.

```text
orzip.exe roundtrip model.s
```

For a compressed or binary shape file, ORZIP checks:

```text
binary shape -> text shape -> binary shape
```

For a text shape file, ORZIP checks:

```text
text shape -> binary shape -> text shape
```

### Convert one file automatically

Use `convert` for normal day-to-day conversion.

```text
orzip.exe convert model.s
```

ORZIP detects the current file type and converts it to the other normal form:

- compressed or raw binary shape data becomes UTF-16 text shape data
- text shape data becomes compressed binary shape data

By default this is in-place. The same file path is rewritten.

### Convert one file to a separate output file

Use `-o` if you do not want to replace the original file.

```text
orzip.exe convert model.s -o model_converted.s
```

If the output file already exists, ORZIP refuses to overwrite it unless you add `--force`.

```text
orzip.exe convert model.s -o model_converted.s --force
```

### Convert a folder to a separate output folder

This is the safer folder-conversion method because your original folder is left alone.

```text
orzip.exe convert -r --only-s "C:\MSTS\ROUTES\MyRoute\SHAPES" -o "C:\MSTS\ROUTES\MyRoute\SHAPES_ORZIP"
```

ORZIP preserves the relative folder layout under the output folder.

When converting to a separate output folder, ORZIP adds a suffix to the output filename so you can see what happened:

- binary to text output: `.s1t.s`
- text to compressed output: `.compressed.s`

### Convert a folder in place

This rewrites the `.s` files in the original folder tree. Make a backup first.

```text
orzip.exe convert -r --only-s "C:\MSTS\ROUTES\MyRoute\SHAPES"
```

## Commands by purpose

### Recommended commands for most users

| Command | What it does | Writes files? |
| --- | --- | --- |
| `validate` | Checks whether files are readable and structurally valid. | No |
| `roundtrip` | Tests conversion out and back without saving output. | No |
| `convert` | Automatically converts binary shape files to text, or text shape files to compressed binary. | Yes |
| `detect` | Reports what kind of file ORZIP thinks each input is. | No |

### More specialized commands

| Command | What it does | Typical use |
| --- | --- | --- |
| `uncompress` | Converts compressed or raw binary shape data to UTF-16 text. Alias for `decompress-text`, which is an alias for `s1b2s1t`. | Force binary-to-text conversion. |
| `compress` | Converts text shape data to compressed binary. Alias for `compress-text`. | Force text-to-compressed conversion. |
| `s1b2s1t` | Converts binary `s1b` shape data to text `s1t`. | Technical binary-to-text conversion. |
| `s1t2s1b` | Converts text `s1t` shape data to raw binary `s1b`. Add `--compress` to make a normal compressed `.s` file. | Technical text-to-binary conversion. |
| `unpack` | Extracts the raw `JINX0...` binary payload from a compressed SIMISA file. | Low-level inspection or repair work. |
| `pack` | Wraps a raw `JINX0...` binary payload as a compressed SIMISA file. | Low-level rebuilding. |
| `normalize` | Decompresses and recompresses an existing compressed file with modern zlib. | Repacking an already-compressed file. |
| `defs` | Shows the embedded MSTS/Open Rails token and grammar definitions ORZIP knows about. | Developer/reference lookup. |
| `dump-blocks` | Prints the binary block structure inside a compressed or raw binary shape file. | Developer inspection. |
| `dump-values` | Decodes binary blocks into named values where the grammar is known. | Developer inspection. |

## Options explained

### `-r` or `--recursive`

Process files inside folders and subfolders.

Example:

```text
orzip.exe validate -r "C:\MSTS\ROUTES\MyRoute\SHAPES"
```

### `--only-s`

When processing a folder, include only `.s` and `.S` files.

This is usually what you want for MSTS/Open Rails shape folders. Without it, ORZIP will inspect every file in the folder tree.

Example:

```text
orzip.exe validate -r --only-s "C:\MSTS\ROUTES\MyRoute\SHAPES"
```

### `-o` or `--output`

Choose where output should be written.

For one input file, this is the output file:

```text
orzip.exe convert model.s -o model_converted.s
```

For folder conversion with `convert`, this is the output folder:

```text
orzip.exe convert -r --only-s Shapes -o ConvertedShapes
```

### `--force`

Allow ORZIP to overwrite an explicit output file that already exists.

You do not need `--force` for normal in-place conversion, because in-place conversion intentionally replaces the input file.

### `--level 0-9`

Choose the zlib compression level when ORZIP writes compressed binary output.

- `0` means no compression
- `9` means maximum compression
- default is `9`

Most users should leave this alone.

### `--verify`

Used with `detect`. If a file is compressed, ORZIP also tries to decompress it and checks the declared payload size.

```text
orzip.exe detect --verify model.s
```

### `--compress`

Used with `s1t2s1b`. It tells ORZIP to write a normal compressed SIMISA file instead of a raw binary payload.

```text
orzip.exe s1t2s1b model_text.s --compress -o model_binary.s
```

Most users should use `compress` or `convert` instead.

## Inspection options

These are mainly for troubleshooting or development.

### `defs`

Show the embedded definitions ORZIP uses.

```text
orzip.exe defs
orzip.exe defs --token shape
orzip.exe defs --grammar points
```

### `dump-blocks`

Show binary block headers.

```text
orzip.exe dump-blocks model.s --max-depth 2 --limit 20
```

Options:

- `--max-depth NUMBER`: how deep ORZIP should scan child blocks; default is `3`
- `--limit NUMBER`: maximum blocks to print per file; default is `200`
- `--show-gaps`: also show non-block data gaps between child blocks

### `dump-values`

Decode binary blocks into named values.

```text
orzip.exe dump-values model.s --max-depth 4 --item-limit 3
```

Options:

- `--max-depth NUMBER`: maximum block depth to decode; default is `3`
- `--item-limit NUMBER`: maximum repeated items to print per list; default is `8`; use `-1` for no limit
- `--block-limit NUMBER`: maximum decoded blocks to print per file; default is `500`
- `--strict`: stop on the first grammar decode error

## What ORZIP can recognize

ORZIP can identify these file forms:

- compressed SIMISA binary containers beginning with `SIMISA@F`
- UTF-16 text SIMISA files
- ASCII/unwrapped SIMISA files
- raw `JINX0...` binary payload files
- files that are not recognized as SIMISA/ORZIP files

Use `detect` to see what ORZIP thinks a file is:

```text
orzip.exe detect --verify model.s
```

## Suggested workflow for a route or trainset folder

1. Make a backup of the folder.
2. Validate the files:

```text
orzip.exe validate -r --only-s "C:\MSTS\ROUTES\MyRoute\SHAPES"
```

3. Test round-trip conversion:

```text
orzip.exe roundtrip -r --only-s "C:\MSTS\ROUTES\MyRoute\SHAPES"
```

4. Convert to a separate folder first:

```text
orzip.exe convert -r --only-s "C:\MSTS\ROUTES\MyRoute\SHAPES" -o "C:\MSTS\ROUTES\MyRoute\SHAPES_ORZIP"
```

5. Inspect or test the converted files before replacing originals.

## Reading ORZIP messages

A successful validation shows `OK` for each file and reports details such as file kind, payload size, root block, and grammar status.

If ORZIP reports `unsupported`, the file was not recognized as a supported SIMISA shape format.

If ORZIP reports `invalid`, the file looked like a supported format but failed a required check. The following `reason:` line explains what failed.

## Notes and limitations

ORZIP is intended for MSTS/Open Rails `.s` shape files. It is not a general-purpose ZIP tool.

The text output produced by ORZIP is a clean SIMISA/S-expression style. It may not match FFEDITC's exact whitespace or formatting. That is expected; the important question is whether the shape data can be parsed and round-tripped.

For text files originally produced by other tools, float rounding can mean a file converts back to a valid binary shape without being byte-for-byte identical to the original binary source.

The inspection commands `dump-blocks` and `dump-values` are for troubleshooting and parser development. Most route or model users will not need them.
