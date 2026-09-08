# ORZIP 1.0.10

## NOTE: What you probably want is on the *releases* page 
---- look over there ---->

## What is ORZIP?

ORZIP is a standalone Python tool for MSTS/Open Rails `.s` shape files. It reads and writes the `SIMISA@F` compressed container and converts between binary/tokenized `s1b` data and editable textual `s1t` data without requiring FFEDIT or external `.tok`, `.bnf`, or `.hdr` files.

Use `check` and `test` before converting a route or trainset. ORZIP only processes `.s`, `.t`, and `.w` files; every other extension is ignored. Text conversion is for `.s` shape files; `.t` terrain and `.w` world files stay binary and can be inspected or recompressed with container-level commands.

    orzip.exe check -r "C:\MSTS\ROUTES\MyRoute\SHAPES"
    orzip.exe test -r "C:\MSTS\ROUTES\MyRoute\SHAPES"

Convert in place:

    orzip.exe convert -r "C:\MSTS\ROUTES\MyRoute\SHAPES"

In-place conversion creates versioned backups beside each source file (`model.s.bak`, `model.s.bak.1`, and so on) and replaces the source atomically. To leave the source tree untouched, use a separate output directory:

    orzip.exe convert -r "C:\MSTS\ROUTES\MyRoute\SHAPES" -o "C:\MSTS\ROUTES\MyRoute\SHAPES_ORZIP"

Advanced users can add `--no-backup` to an in-place `convert`, `text`, or `binary` command. Replacement remains atomic, but the previous file contents are not retained.

Run `orzip.exe --help` for the concise command list or `orzip.exe --advanced-help` for compatibility and technical aliases. See `USER_GUIDE.md` for normal workflows and `README-ORZIP.md` for format and developer details.

# NOTE

This update adds support for .T and .W files in addition to the already handled .S files.
