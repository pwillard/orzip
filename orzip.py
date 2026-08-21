#!/usr/bin/env python
"""
ORZIP - modern MSTS/Open Rails SIMISA zlib container tool.

This replaces the compression-container part of FFEDITC with a standalone
Python implementation.  It can unpack and repack compressed binary SIMISA files
without FFEDITC or the old token/reference files.

Important MSTS distinction:
  * compressed .s files normally contain zlib-compressed binary/tokenized s1b
    data: SIMISA@F + length + @@@@ + zlib(payload)
  * FFEDITC also performs a separate binary-token <-> text-token conversion
    (s1b <-> s1t).  That grammar conversion is not needed to replace the zlib
    compression wrapper, and is deliberately not hidden here.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import struct
import sys
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path

COMPRESSED_MAGIC = b"SIMISA@F"
UNCOMPRESSED_ASCII_MAGIC = b"SIMISA@@"
UTF16LE_BOM = b"\xff\xfe"
UTF16LE_SIMISA = UTF16LE_BOM + "SIMISA".encode("utf-16le")
ZLIB_MAGIC_PREFIXES = {b"\x78\x01", b"\x78\x5e", b"\x78\x9c", b"\x78\xda"}
MAX_S1T_NESTING = 256


class ORZIPError(Exception):
    pass


@dataclass(frozen=True)
class Detection:
    kind: str
    detail: str
    payload_offset: int | None = None
    declared_length: int | None = None
    actual_payload_length: int | None = None


@dataclass(frozen=True)
class BinaryBlock:
    offset: int
    token_id: int
    token_name: str
    flags: int
    record_size: int
    label: str
    content_start: int
    end: int


@dataclass
class SExprNode:
    name: str
    label: str | None
    items: list[object]


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ORZIPError(f"cannot read {path}: {exc}") from exc


def _write(path: Path, data: bytes, force: bool) -> None:
    if path.exists() and not force:
        raise ORZIPError(f"refusing to overwrite existing file: {path} (use --force)")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ORZIPError(f"cannot create output directory {path.parent}: {exc}") from exc
    try:
        path.write_bytes(data)
    except OSError as exc:
        raise ORZIPError(f"cannot write {path}: {exc}") from exc


def _best_effort_unlink(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _create_versioned_backup(path: Path) -> Path:
    temp_path: Path | None = None
    try:
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.backup.", suffix=".tmp", dir=path.parent)
        temp_path = Path(temp_name)
        with os.fdopen(fd, "wb") as destination:
            with path.open("rb") as source:
                shutil.copyfileobj(source, destination)
                destination.flush()
                os.fsync(destination.fileno())
        shutil.copystat(path, temp_path)

        index = 0
        while True:
            suffix = ".bak" if index == 0 else f".bak.{index}"
            backup = path.with_name(path.name + suffix)
            if backup.exists():
                index += 1
                continue
            os.replace(temp_path, backup)
            return backup
    except OSError:
        _best_effort_unlink(temp_path)
        raise


def atomic_write_in_place(path: Path, data: bytes, create_backup: bool = True) -> None:
    if not path.is_file():
        raise ORZIPError(f"cannot replace missing input file: {path}")

    temp_path: Path | None = None
    backup_path: Path | None = None
    try:
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temp_path = Path(temp_name)
        with os.fdopen(fd, "wb") as destination:
            destination.write(data)
            destination.flush()
            os.fsync(destination.fileno())
    except OSError as exc:
        _best_effort_unlink(temp_path)
        raise ORZIPError(f"cannot prepare replacement for {path}: {exc}") from exc

    try:
        shutil.copymode(path, temp_path)
    except OSError as exc:
        _best_effort_unlink(temp_path)
        raise ORZIPError(f"cannot preserve mode for {path}: {exc}") from exc

    if create_backup:
        try:
            backup_path = _create_versioned_backup(path)
        except OSError as exc:
            _best_effort_unlink(temp_path)
            raise ORZIPError(f"cannot back up {path}: {exc}") from exc

    try:
        os.replace(temp_path, path)
    except OSError as exc:
        _best_effort_unlink(temp_path)
        _best_effort_unlink(backup_path)
        raise ORZIPError(f"cannot replace {path}: {exc}") from exc


def detect_bytes(data: bytes) -> Detection:
    if data.startswith(COMPRESSED_MAGIC) and len(data) >= 18:
        declared = int.from_bytes(data[8:12], "little")
        if data[12:16] != b"@@@@":
            return Detection("invalid", "SIMISA@F header found but @@@@ marker is missing", declared_length=declared)
        zhead = data[16:18]
        if zhead not in ZLIB_MAGIC_PREFIXES:
            return Detection("invalid", f"SIMISA@F header found but zlib header at offset 16 looks wrong: {zhead.hex(' ')}", declared_length=declared)
        return Detection("compressed", "compressed SIMISA binary container", 16, declared)

    if data.startswith(UTF16LE_SIMISA):
        try:
            text_prefix = data[:80].decode("utf-16le", errors="replace")
        except UnicodeError:
            text_prefix = ""
        if "JINX0" in text_prefix:
            return Detection("unicode-text", "uncompressed UTF-16LE SIMISA text file")
        return Detection("unicode", "UTF-16LE file beginning with SIMISA")

    if data.startswith(UNCOMPRESSED_ASCII_MAGIC):
        return Detection("ascii-text-or-binary", "uncompressed ASCII SIMISA file")

    if data.startswith(b"JINX0"):
        return Detection("raw-binary", "raw unwrapped SIMISA subfile/payload", actual_payload_length=len(data))

    return Detection("unknown", "not a recognized SIMISA/ORZIP file")


def zlib_decompress_container(data: bytes, *, strict_trailing: bool = False) -> bytes:
    det = detect_bytes(data)
    if det.kind != "compressed" or det.payload_offset is None:
        raise ORZIPError(det.detail)
    decompressor = zlib.decompressobj()
    try:
        payload = decompressor.decompress(data[det.payload_offset:])
        payload += decompressor.flush()
    except zlib.error as exc:
        raise ORZIPError(f"zlib decompression failed: {exc}") from exc
    if not decompressor.eof:
        raise ORZIPError("zlib stream is incomplete or truncated")
    if decompressor.unconsumed_tail:
        raise ORZIPError(f"zlib stream has {len(decompressor.unconsumed_tail)} bytes of unconsumed data")
    if strict_trailing and decompressor.unused_data:
        raise ORZIPError(f"trailing data after zlib stream: {len(decompressor.unused_data)} bytes")
    if det.declared_length is not None and len(payload) != det.declared_length:
        raise ORZIPError(f"length mismatch: header declares {det.declared_length} bytes, decompressed {len(payload)} bytes")
    return payload


def zlib_trailing_data_length(data: bytes) -> int:
    det = detect_bytes(data)
    if det.kind != "compressed" or det.payload_offset is None:
        return 0
    decompressor = zlib.decompressobj()
    try:
        decompressor.decompress(data[det.payload_offset:])
        decompressor.flush()
    except zlib.error:
        return 0
    if not decompressor.eof:
        return 0
    return len(decompressor.unused_data)


def zlib_compress_container(payload: bytes, level: int = 9) -> bytes:
    if not payload.startswith(b"JINX0"):
        raise ORZIPError("raw payload does not start with JINX0; refusing to create a SIMISA compressed binary container")
    return COMPRESSED_MAGIC + len(payload).to_bytes(4, "little") + b"@@@@" + zlib.compress(payload, level)


def extract_binary_payload(data: bytes, *, strict_trailing: bool = False) -> bytes:
    det = detect_bytes(data)
    if det.kind == "compressed":
        payload = zlib_decompress_container(data, strict_trailing=strict_trailing)
    elif det.kind == "raw-binary":
        payload = data
    else:
        raise ORZIPError(f"dump-blocks needs compressed SIMISA@F or raw JINX0 binary data; got {det.kind}")
    if not payload.startswith(b"JINX0"):
        raise ORZIPError("binary payload does not start with JINX0")
    if len(payload) < 16:
        raise ORZIPError("binary payload is too short for a JINX0 subheader")
    if payload[7:8] != b"b":
        raise ORZIPError(f"JINX0 payload is not binary/tokenized: {payload[:14]!r}")
    return payload


def reject_text_input_for_uncompress(path: Path, det: Detection) -> None:
    if det.kind in {"unicode-text", "unicode", "ascii-text-or-binary"}:
        raise ORZIPError(f"cannot uncompress {path}: file is already uncompressed text; use compress for text -> compressed binary")


def reject_binary_input_for_compress(path: Path, det: Detection) -> None:
    if det.kind == "compressed":
        raise ORZIPError(f"cannot compress {path}: file is already compressed; use uncompress for compressed binary -> text")
    if det.kind == "raw-binary":
        raise ORZIPError(f"cannot compress {path}: file is already binary s1b data; use pack to wrap raw binary payloads")


def parse_binary_block(payload: bytes, offset: int, token_lookup) -> BinaryBlock | None:
    if offset + 9 > len(payload):
        return None
    token_id = int.from_bytes(payload[offset : offset + 2], "little")
    token_name = token_lookup(token_id)
    if token_name is None:
        return None
    flags = int.from_bytes(payload[offset + 2 : offset + 4], "little")
    record_size = int.from_bytes(payload[offset + 4 : offset + 8], "little")
    end = offset + 8 + record_size
    if record_size < 1 or end > len(payload):
        return None
    label_chars = payload[offset + 8]
    label_bytes = label_chars * 2
    content_start = offset + 9 + label_bytes
    if content_start > end:
        return None
    try:
        label = payload[offset + 9 : offset + 9 + label_bytes].decode("utf-16le") if label_chars else ""
    except UnicodeDecodeError:
        return None
    return BinaryBlock(offset, token_id, token_name, flags, record_size, label, content_start, end)


def grammar_can_contain_blocks(token_name: str, defs_module) -> bool:
    rule = defs_module.shape_grammar_rule(token_name)
    if rule is None:
        return True
    primitive_types = {"uint", "sint", "dword", "float", "string", "token"}
    tokens = rule.tokens
    for i, token in enumerate(tokens[:-1]):
        if token == ":" and tokens[i + 1] not in primitive_types:
            return True
    return False


PRIMITIVE_TYPES = {"uint", "sint", "dword", "float", "string", "token"}


def parse_grammar_items(tokens: tuple[str, ...]) -> list[tuple]:
    def parse_until(index: int, stop: str | None = None) -> tuple[list[tuple], int]:
        items: list[tuple] = []
        while index < len(tokens):
            token = tokens[index]
            if stop is not None and token == stop:
                return items, index + 1
            if token == "[":
                subitems, index = parse_until(index + 1, "]")
                items.append(("optional", subitems))
                continue
            if token == "{":
                subitems, index = parse_until(index + 1, "}")
                items.append(("repeat", subitems))
                continue
            if token == "|":
                items.append(("choice",))
                index += 1
                continue
            if token == ":" and index + 1 < len(tokens):
                field_type = tokens[index + 1]
                field_name = field_type
                index += 2
                if index < len(tokens) and tokens[index] == "," and index + 1 < len(tokens):
                    field_name = tokens[index + 1]
                    index += 2
                items.append(("field", field_type, field_name))
                continue
            # Choice separators and FILE_TYPE literals are not decoded in block rules.
            index += 1
        if stop is not None:
            raise ORZIPError(f"unterminated grammar group, expected {stop}")
        return items, index

    items, _ = parse_until(0)
    return items


def grammar_alternative_items(items: list[tuple]) -> list[list[tuple]]:
    """Expand a flat grammar group containing | choices into alternatives.

    Locomotive animation files can use a repeated group like
    `{ :tcb_key | :slerp_rot }`.  Splitting the already-tokenized group at
    choice markers lets the decoder/encoder select whichever keyed block is
    actually present without changing rules that do not use alternatives.
    """
    alternatives: list[list[tuple]] = [[]]
    for item in items:
        if item[0] == "choice":
            alternatives.append([])
            continue
        alternatives[-1].append(item)
    return alternatives


def items_start_with_matching_node(items: list[tuple], node: SExprNode, defs_module) -> bool:
    if not items:
        return False
    first = items[0]
    while first[0] in {"optional", "repeat"} and first[1]:
        if first[0] == "repeat":
            return any(items_start_with_matching_node(alt, node, defs_module) for alt in grammar_alternative_items(first[1]))
        first = first[1][0]
    return first[0] == "field" and first[1] not in PRIMITIVE_TYPES and block_matches_expected(node.name, first[1], defs_module)


def items_start_with_matching_block(payload: bytes, pos: int, end: int, items: list[tuple], defs_module) -> bool:
    if pos >= end or not items:
        return False
    first = items[0]
    while first[0] in {"optional", "repeat"} and first[1]:
        if first[0] == "repeat":
            return any(items_start_with_matching_block(payload, pos, end, alt, defs_module) for alt in grammar_alternative_items(first[1]))
        first = first[1][0]
    if first[0] != "field" or first[1] in PRIMITIVE_TYPES:
        return False
    child = parse_binary_block(payload, pos, defs_module.core_token_name)
    return child is not None and child.end <= end and block_matches_expected(child.token_name, first[1], defs_module)


def items_start_with_primitive(items: list[tuple]) -> bool:
    if not items:
        return False
    first = items[0]
    while first[0] in {"optional", "repeat"} and first[1]:
        if first[0] == "repeat":
            return any(items_start_with_primitive(alt) for alt in grammar_alternative_items(first[1]))
        first = first[1][0]
    return first[0] == "field" and first[1] in PRIMITIVE_TYPES


def choice_names(rule_name: str, defs_module) -> set[str]:
    rule = defs_module.shape_grammar_rule(rule_name)
    if rule is None or rule.kind != "choice_or_value":
        return set()
    names: set[str] = set()
    tokens = rule.tokens
    for i, token in enumerate(tokens[:-1]):
        if token == ":":
            names.add(tokens[i + 1].lower())
    return names


def block_matches_expected(block_name: str, expected_type: str, defs_module) -> bool:
    if block_name.lower() == expected_type.lower():
        return True
    choices = choice_names(expected_type, defs_module)
    return block_name.lower() in choices


def optional_group_present(payload: bytes, pos: int, end: int, subitems: list[tuple], defs_module) -> bool:
    if pos >= end or not subitems:
        return False
    first = subitems[0]
    while first[0] in {"optional", "repeat"} and first[1]:
        if first[0] == "repeat":
            alternatives = grammar_alternative_items(first[1])
            if any(items_start_with_primitive(alt) for alt in alternatives):
                return pos < end
            return any(items_start_with_matching_block(payload, pos, end, alt, defs_module) for alt in alternatives)
        first = first[1][0]
    if first[0] != "field":
        return False
    field_type = first[1]
    if field_type in PRIMITIVE_TYPES:
        return pos < end
    child = parse_binary_block(payload, pos, defs_module.core_token_name)
    return child is not None and child.end <= end and block_matches_expected(child.token_name, field_type, defs_module)


def read_primitive(payload: bytes, pos: int, end: int, field_type: str) -> tuple[object, int]:
    if field_type in {"uint", "dword", "token"}:
        if pos + 4 > end:
            raise ORZIPError(f"not enough data for {field_type} at 0x{pos:08x}")
        return int.from_bytes(payload[pos : pos + 4], "little", signed=False), pos + 4
    if field_type == "sint":
        if pos + 4 > end:
            raise ORZIPError(f"not enough data for sint at 0x{pos:08x}")
        return int.from_bytes(payload[pos : pos + 4], "little", signed=True), pos + 4
    if field_type == "float":
        if pos + 4 > end:
            raise ORZIPError(f"not enough data for float at 0x{pos:08x}")
        return struct.unpack_from("<f", payload, pos)[0], pos + 4
    if field_type == "string":
        if pos + 2 > end:
            raise ORZIPError(f"not enough data for string length at 0x{pos:08x}")
        chars = int.from_bytes(payload[pos : pos + 2], "little")
        pos += 2
        byte_count = chars * 2
        if pos + byte_count > end:
            raise ORZIPError(f"not enough data for string body at 0x{pos:08x}")
        value = payload[pos : pos + byte_count].decode("utf-16le", errors="replace")
        return value, pos + byte_count
    raise ORZIPError(f"unknown primitive type {field_type}")


def format_value(value: object, field_type: str, defs_module) -> str:
    if field_type == "float":
        return f"{value:.9g}"
    if field_type == "dword":
        return f"0x{value:08x}"
    if field_type == "token":
        name = defs_module.core_token_name(value) if isinstance(value, int) else None
        return f"{value} ({name})" if name else str(value)
    return repr(value) if isinstance(value, str) else str(value)


def format_s1t_value(value: object, field_type: str, defs_module) -> str:
    if field_type == "float":
        return f"{value:.9g}"
    if field_type == "dword":
        return f"{value:08x}"
    if field_type == "token":
        name = defs_module.core_token_name(value) if isinstance(value, int) else None
        return name if name else str(value)
    if isinstance(value, str):
        if value == "" or any(ch.isspace() or ch in '()"' for ch in value):
            return '"' + value.replace('"', '\\"') + '"'
        return value
    return str(value)


def render_s1t_from_payload(payload: bytes, defs_module) -> str:
    roots: list[BinaryBlock] = []
    offset = 16
    while offset < len(payload):
        root = parse_binary_block(payload, offset, defs_module.core_token_name)
        if root is None:
            raise ORZIPError(f"could not parse top-level binary block at 0x{offset:08x}")
        roots.append(root)
        offset = root.end
    if not roots:
        raise ORZIPError("could not parse root binary block")

    def decode_entries(items: list[tuple], pos: int, end: int, counts: dict[str, int]) -> tuple[list[tuple], int]:
        entries: list[tuple] = []
        for item in items:
            kind = item[0]
            if kind == "field":
                _, field_type, field_name = item
                if field_type in PRIMITIVE_TYPES:
                    value, pos = read_primitive(payload, pos, end, field_type)
                    if isinstance(value, int):
                        counts[field_name.lower()] = value
                    entries.append(("scalar", format_s1t_value(value, field_type, defs_module)))
                else:
                    child = parse_binary_block(payload, pos, defs_module.core_token_name)
                    if child is None or child.end > end or not block_matches_expected(child.token_name, field_type, defs_module):
                        raise ORZIPError(
                            f"expected block {field_type} at 0x{pos:08x}; "
                            f"got {child.token_name if child else '<none>'}"
                        )
                    entries.append(("block", render_block(child)))
                    pos = child.end
            elif kind == "optional":
                if pos >= end:
                    continue
                if not optional_group_present(payload, pos, end, item[1], defs_module):
                    continue
                subentries, new_pos = decode_entries(item[1], pos, end, counts.copy())
                entries.extend(subentries)
                pos = new_pos
            elif kind == "repeat":
                total = next(reversed(counts.values())) if counts else None
                repeated = 0
                while pos < end and (total is None or repeated < total):
                    before = pos
                    alternatives = grammar_alternative_items(item[1])
                    chosen = next(
                        (alt for alt in alternatives if items_start_with_matching_block(payload, pos, end, alt, defs_module)),
                        alternatives[0],
                    )
                    subentries, pos = decode_entries(chosen, pos, end, counts.copy())
                    entries.extend(subentries)
                    if pos == before:
                        break
                    repeated += 1
            else:
                raise ORZIPError(f"unknown grammar item {kind}")
        return entries, pos

    def render_block(block: BinaryBlock) -> tuple[str, str | None, list[tuple]]:
        rule = defs_module.shape_grammar_rule(block.token_name)
        if rule is None or rule.kind != "block":
            raise ORZIPError(f"no block grammar for {block.token_name}")
        entries, final_pos = decode_entries(parse_grammar_items(rule.tokens), block.content_start, block.end, {})
        if final_pos != block.end:
            if (block.end - final_pos) % 4 != 0:
                raise ORZIPError(f"undecoded bytes in {block.token_name} at 0x{final_pos:08x}: {block.end - final_pos}")
            fallback_type = "dword" if block.token_name == "flags" else "uint"
            while final_pos < block.end:
                value, final_pos = read_primitive(payload, final_pos, block.end, fallback_type)
                entries.append(("scalar", format_s1t_value(value, fallback_type, defs_module)))
        return block.token_name, block.label or None, entries

    def emit_block(rendered: tuple[str, str | None, list[tuple]], depth: int, out: list[str]) -> None:
        name, label, entries = rendered
        prefix = "\t" * depth + name + (f" {label}" if label else "")
        if all(kind == "scalar" for kind, _ in entries):
            values = " ".join(value for _, value in entries)
            out.append(f"{prefix} ( {values} )" if values else f"{prefix} ( )")
            return
        out.append(f"{prefix} (")
        scalar_run: list[str] = []
        for kind, value in entries:
            if kind == "scalar":
                scalar_run.append(value)
            else:
                if scalar_run:
                    out.append("\t" * (depth + 1) + " ".join(scalar_run))
                    scalar_run = []
                emit_block(value, depth + 1, out)
        if scalar_run:
            out.append("\t" * (depth + 1) + " ".join(scalar_run))
        out.append("\t" * depth + ")")

    lines = ["SIMISA@@@@@@@@@@JINX0s1t______", ""]
    for root in roots:
        emit_block(render_block(root), 0, lines)
        lines.append("")
    return (chr(13) + chr(10)).join(lines)


def decode_text_auto(data: bytes) -> str:
    if data.startswith(UTF16LE_BOM):
        return data[2:].decode("utf-16le", errors="replace")
    if data.startswith(b"\xfe\xff"):
        return data[2:].decode("utf-16be", errors="replace")
    return data.decode("utf-8", errors="replace")


def tokenize_s1t(text: str) -> list[str]:
    tokens: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "#":
            while i < len(text) and text[i] not in "\r\n":
                i += 1
            continue
        if ch in "()":
            tokens.append(ch)
            i += 1
            continue
        if ch == '"':
            quote_start = i
            i += 1
            value = []
            closed = False
            while i < len(text):
                if text[i] == "\\" and i + 1 < len(text):
                    value.append(text[i + 1])
                    i += 2
                    continue
                if text[i] == '"':
                    i += 1
                    closed = True
                    break
                value.append(text[i])
                i += 1
            if not closed:
                raise ORZIPError(f"unterminated quoted string at character {quote_start}")
            tokens.append("".join(value))
            continue
        start = i
        while i < len(text) and not text[i].isspace() and text[i] not in "()":
            i += 1
        tokens.append(text[start:i])
    return tokens


def parse_s1t_roots(text: str) -> list[SExprNode]:
    tokens = tokenize_s1t(text.lstrip("\ufeff"))
    if not tokens:
        raise ORZIPError("empty text file")
    if tokens[0].startswith("SIMISA"):
        tokens = tokens[1:]

    def can_start_node(token: str) -> bool:
        try:
            float(token)
            return False
        except ValueError:
            pass
        if token and len(token) >= 4 and all(c in "0123456789abcdefABCDEF" for c in token):
            return False
        return not any(c in token.lower() for c in ".\\/")

    def parse_node(index: int, depth: int = 0) -> tuple[SExprNode, int]:
        if depth >= MAX_S1T_NESTING:
            raise ORZIPError(f"S1T nesting exceeds {MAX_S1T_NESTING} blocks")
        if index >= len(tokens):
            raise ORZIPError("unexpected end of tokens")
        name = tokens[index]
        index += 1
        label = None
        if index < len(tokens) and tokens[index] != "(":
            label = tokens[index]
            index += 1
        if index >= len(tokens) or tokens[index] != "(":
            raise ORZIPError(f"expected '(' after {name}")
        index += 1
        items: list[object] = []
        while index < len(tokens) and tokens[index] != ")":
            if can_start_node(tokens[index]) and index + 1 < len(tokens) and tokens[index + 1] == "(":
                child, index = parse_node(index, depth + 1)
                items.append(child)
            elif can_start_node(tokens[index]) and index + 2 < len(tokens) and tokens[index + 2] == "(":
                child, index = parse_node(index, depth + 1)
                items.append(child)
            else:
                items.append(tokens[index])
                index += 1
        if index >= len(tokens) or tokens[index] != ")":
            raise ORZIPError(f"missing ')' for {name}")
        return SExprNode(name, label, items), index + 1

    roots: list[SExprNode] = []
    index = 0
    while index < len(tokens):
        root, index = parse_node(index)
        roots.append(root)
    return roots


def parse_s1t_text(text: str) -> SExprNode:
    roots = parse_s1t_roots(text)
    if len(roots) != 1:
        raise ORZIPError(f"expected one root block, got {len(roots)}")
    return roots[0]


def parse_scalar_token(token: object, field_type: str, defs_module) -> object:
    if isinstance(token, SExprNode):
        raise ORZIPError(f"expected scalar {field_type}, got block {token.name}")
    text = str(token)
    try:
        if field_type == "dword":
            return int(text[2:], 16) if text.lower().startswith("0x") else int(text, 16)
        if field_type == "uint":
            if text.lower().startswith("0x") or any(c in text.lower() for c in "abcdef"):
                return int(text, 16)
            return int(text, 10)
        if field_type == "sint":
            return int(text, 0)
        if field_type == "float":
            return float(text)
        if field_type == "string":
            return text
        if field_type == "token":
            token_id = defs_module.core_token_id(text)
            return token_id if token_id is not None else int(text, 0)
        raise ORZIPError(f"unknown scalar type {field_type}")
    except (ValueError, OverflowError) as exc:
        raise ORZIPError(f"invalid {field_type} value {text!r}") from exc


def write_primitive(value: object, field_type: str) -> bytes:
    try:
        if field_type in {"uint", "dword", "token"}:
            return int(value).to_bytes(4, "little", signed=False)
        if field_type == "sint":
            return int(value).to_bytes(4, "little", signed=True)
        if field_type == "float":
            return struct.pack("<f", float(value))
        if field_type == "string":
            encoded = str(value).encode("utf-16le")
            return (len(str(value))).to_bytes(2, "little") + encoded
        raise ORZIPError(f"unknown primitive type {field_type}")
    except UnicodeError as exc:
        raise ORZIPError(f"cannot encode {field_type} value {value!r}") from exc
    except (OverflowError, ValueError, struct.error) as exc:
        raise ORZIPError(f"{field_type} value out of range: {value!r}") from exc


def encode_s1t_node(root: SExprNode, defs_module) -> bytes:
    def node_matches_expected(node: SExprNode, expected_type: str) -> bool:
        return block_matches_expected(node.name, expected_type, defs_module)

    def encode_items(node: SExprNode, items: list[tuple], index: int, counts: dict[str, int]) -> tuple[bytes, int]:
        out = bytearray()
        for item in items:
            kind = item[0]
            if kind == "field":
                _, field_type, field_name = item
                if field_type in PRIMITIVE_TYPES:
                    if index >= len(node.items):
                        raise ORZIPError(f"missing scalar {field_name} in {node.name}")
                    value = parse_scalar_token(node.items[index], field_type, defs_module)
                    index += 1
                    if isinstance(value, int):
                        counts[field_name.lower()] = value
                    out.extend(write_primitive(value, field_type))
                else:
                    if index >= len(node.items) or not isinstance(node.items[index], SExprNode):
                        raise ORZIPError(f"missing child block {field_type} in {node.name}")
                    child = node.items[index]
                    if not node_matches_expected(child, field_type):
                        raise ORZIPError(f"expected child {field_type} in {node.name}, got {child.name}")
                    out.extend(encode_node(child))
                    index += 1
            elif kind == "optional":
                if index >= len(node.items):
                    continue
                subitems = item[1]
                first = subitems[0] if subitems else None
                present = True
                if first and first[0] == "field" and first[1] not in PRIMITIVE_TYPES:
                    present = isinstance(node.items[index], SExprNode) and node_matches_expected(node.items[index], first[1])
                elif first and first[0] == "repeat":
                    alternatives = grammar_alternative_items(first[1])
                    if any(items_start_with_primitive(alt) for alt in alternatives):
                        present = not isinstance(node.items[index], SExprNode)
                    else:
                        present = isinstance(node.items[index], SExprNode) and any(
                            items_start_with_matching_node(alt, node.items[index], defs_module)
                            for alt in alternatives
                        )
                if present:
                    subbytes, index = encode_items(node, subitems, index, counts.copy())
                    out.extend(subbytes)
            elif kind == "repeat":
                subitems = item[1]
                total = next(reversed(counts.values())) if counts else None
                repeated = 0
                while index < len(node.items) and (total is None or repeated < total):
                    alternatives = grammar_alternative_items(subitems)
                    current = node.items[index]
                    chosen = next(
                        (
                            alt
                            for alt in alternatives
                            if isinstance(current, SExprNode) and items_start_with_matching_node(alt, current, defs_module)
                        ),
                        alternatives[0],
                    )
                    subbytes, new_index = encode_items(node, chosen, index, counts.copy())
                    if new_index == index:
                        break
                    out.extend(subbytes)
                    index = new_index
                    repeated += 1
            else:
                raise ORZIPError(f"unknown grammar item {kind}")
        return bytes(out), index

    def encode_node(node: SExprNode) -> bytes:
        token_id = defs_module.core_token_id(node.name)
        if token_id is None:
            raise ORZIPError(f"unknown token name {node.name}")
        rule = defs_module.shape_grammar_rule(node.name)
        if rule is None or rule.kind != "block":
            raise ORZIPError(f"no grammar for block {node.name}")
        content, index = encode_items(node, parse_grammar_items(rule.tokens), 0, {})
        # Some FFEDIT grammar rules under-specify flat numeric tails, e.g. normal_idxs.
        fallback_type = "dword" if node.name == "flags" else "uint"
        while index < len(node.items):
            if isinstance(node.items[index], SExprNode):
                raise ORZIPError(f"unencoded child {node.items[index].name} in {node.name}")
            content += write_primitive(parse_scalar_token(node.items[index], fallback_type, defs_module), fallback_type)
            index += 1
        label = node.label or ""
        label_bytes = label.encode("utf-16le")
        if len(label) > 255:
            raise ORZIPError(f"label too long in {node.name}: {label}")
        record = bytes([len(label)]) + label_bytes + content
        return int(token_id).to_bytes(2, "little") + (0).to_bytes(2, "little") + len(record).to_bytes(4, "little") + record

    return b"JINX0s1b______" + bytes([13, 10]) + encode_node(root)


def encode_s1t_nodes(roots: list[SExprNode], defs_module) -> bytes:
    encodable_roots = [root for root in roots if root.name.lower() != "max_data"]
    if not encodable_roots:
        raise ORZIPError("empty text file")
    return b"JINX0s1b______" + bytes([13, 10]) + b"".join(encode_s1t_node(root, defs_module)[16:] for root in encodable_roots)


def default_output(path: Path, command: str) -> Path:
    if command == "unpack":
        return path.with_suffix(path.suffix + ".slb")
    if command == "pack":
        suffix = path.suffix
        if suffix.lower() in {".slb", ".s1b", ".bin"}:
            return path.with_suffix(".s")
        return path.with_suffix(path.suffix + ".s")
    if command == "normalize":
        return path.with_suffix(path.suffix + ".repacked")
    raise AssertionError(command)


def iter_inputs(paths: list[Path], recursive: bool, only_s: bool = False) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if p.is_dir():
            pattern = "**/*" if recursive else "*"
            out.extend(x for x in p.glob(pattern) if x.is_file())
        else:
            out.append(p)
    if only_s:
        out = [p for p in out if p.suffix.lower() == ".s"]
    # stable order; de-duplicate without losing order
    seen: set[Path] = set()
    unique: list[Path] = []
    for p in out:
        rp = p.resolve()
        if rp not in seen:
            unique.append(p)
            seen.add(rp)
    return unique


def iter_arg_inputs(args: argparse.Namespace) -> list[Path]:
    return iter_inputs(args.inputs, args.recursive, getattr(args, "only_s", False))


def iter_conversion_inputs(args: argparse.Namespace) -> list[Path]:
    inputs = iter_arg_inputs(args)
    if args.output is None:
        return inputs

    output_root = args.output.resolve()
    directory_roots = [input_path.resolve() for input_path in args.inputs if input_path.is_dir()]
    if output_root in directory_roots:
        raise ORZIPError(f"output directory must not be the same as an input directory: {args.output}")
    if any(output_root.is_relative_to(root) for root in directory_roots):
        inputs = [input_path for input_path in inputs if not input_path.resolve().is_relative_to(output_root)]
    return inputs


def relative_to_input_roots(path: Path, inputs: list[Path]) -> Path:
    resolved = path.resolve()
    directory_roots = sorted((p.resolve() for p in inputs if p.is_dir()), key=lambda p: len(str(p)), reverse=True)
    for root in directory_roots:
        try:
            return resolved.relative_to(root)
        except ValueError:
            continue
    return Path(path.name)


def convert_output_path(path: Path, args: argparse.Namespace, suffix: str) -> Path:
    if args.output and len(args.inputs) == 1 and not args.inputs[0].is_dir():
        return args.output
    if args.output:
        rel = relative_to_input_roots(path, args.inputs)
        return args.output / rel.with_suffix(rel.suffix + suffix)
    return path


def reject_planned_output_collisions(inputs: list[Path], outputs: list[Path]) -> None:
    input_paths = {os.path.normcase(str(input_path.resolve())) for input_path in inputs}
    seen: set[str] = set()
    existing_outputs: list[Path] = []
    for input_path, output in zip(inputs, outputs):
        normalized = os.path.normcase(str(output.resolve()))
        same_single_input = len(inputs) == 1 and normalized == os.path.normcase(str(input_path.resolve()))
        if normalized in input_paths and not same_single_input:
            raise ORZIPError(f"output would overwrite an input file: {output}")
        if output.exists() and not same_single_input:
            for other_input in inputs:
                try:
                    if output.samefile(other_input):
                        raise ORZIPError(f"output is the same file as an input: {output}")
                except OSError:
                    continue
        if normalized in seen:
            raise ORZIPError(f"multiple inputs would write the same output file: {output}")
        if output.exists():
            for prior_output in existing_outputs:
                try:
                    if output.samefile(prior_output):
                        raise ORZIPError(f"multiple outputs refer to the same file: {output}")
                except OSError:
                    continue
            existing_outputs.append(output)
        seen.add(normalized)


def reject_output_collisions(args: argparse.Namespace, inputs: list[Path], suffix: str) -> None:
    if args.output is None:
        return
    outputs = [convert_output_path(input_path, args, suffix) for input_path in inputs]
    reject_planned_output_collisions(inputs, outputs)


def cmd_detect(args: argparse.Namespace) -> int:
    rc = 0
    for p in iter_arg_inputs(args):
        data = _read(p)
        det = detect_bytes(data)
        if args.verify and det.kind == "compressed":
            try:
                payload = zlib_decompress_container(data, strict_trailing=getattr(args, "strict_zlib", False))
                print(f"{p}: {det.kind}; declared={det.declared_length}; decompressed={len(payload)}")
                trailing = zlib_trailing_data_length(data)
                if trailing:
                    print(f"  warning: trailing data after zlib stream: {trailing} bytes")
            except ORZIPError as exc:
                rc = 1
                print(f"{p}: invalid; {exc}")
        else:
            extra = ""
            if det.declared_length is not None:
                extra = f"; declared={det.declared_length}"
            print(f"{p}: {det.kind}; {det.detail}{extra}")
    return rc


def cmd_unpack(args: argparse.Namespace) -> int:
    for p in iter_arg_inputs(args):
        data = _read(p)
        payload = zlib_decompress_container(data)
        out = args.output if len(args.inputs) == 1 and not p.is_dir() and args.output else default_output(p, "unpack")
        _write(out, payload, args.force)
        print(f"[unpack] {p} -> {out} ({len(payload)} bytes)")
    return 0


def cmd_pack(args: argparse.Namespace) -> int:
    for p in iter_arg_inputs(args):
        payload = _read(p)
        data = zlib_compress_container(payload, args.level)
        out = args.output if len(args.inputs) == 1 and not p.is_dir() and args.output else default_output(p, "pack")
        _write(out, data, args.force)
        print(f"[pack] {p} -> {out} ({len(payload)} raw bytes, {len(data)} packed bytes)")
    return 0


def cmd_normalize(args: argparse.Namespace) -> int:
    for p in iter_arg_inputs(args):
        payload = zlib_decompress_container(_read(p))
        data = zlib_compress_container(payload, args.level)
        out = args.output if len(args.inputs) == 1 and not p.is_dir() and args.output else default_output(p, "normalize")
        _write(out, data, args.force)
        print(f"[normalize] {p} -> {out} ({len(data)} bytes)")
    return 0


def cmd_s1b2s1t(args: argparse.Namespace) -> int:
    try:
        import orzip_defs
    except ImportError as exc:
        raise ORZIPError(f"cannot import embedded definitions module orzip_defs.py: {exc}") from exc

    inputs = iter_conversion_inputs(args)
    reject_output_collisions(args, inputs, ".s1t.s")
    for p in inputs:
        data = _read(p)
        reject_text_input_for_uncompress(p, detect_bytes(data))
        payload = extract_binary_payload(data)
        text = render_s1t_from_payload(payload, orzip_defs)
        output_bytes = UTF16LE_BOM + text.encode("utf-16le")
        if args.output:
            out = convert_output_path(p, args, ".s1t.s")
        elif getattr(args, "in_place", False):
            out = p
        else:
            out = p.with_suffix(p.suffix + ".s1t.s")
        if out.resolve() == p.resolve():
            atomic_write_in_place(out, output_bytes, create_backup=not getattr(args, "no_backup", False))
        else:
            _write(out, output_bytes, args.force)
        print(f"[s1b2s1t] {p} -> {out} ({len(output_bytes)} bytes)")
    return 0


def cmd_s1t2s1b(args: argparse.Namespace) -> int:
    try:
        import orzip_defs
    except ImportError as exc:
        raise ORZIPError(f"cannot import embedded definitions module orzip_defs.py: {exc}") from exc

    suffix = ".compressed.s" if args.compress else ".s1b"
    inputs = iter_conversion_inputs(args)
    reject_output_collisions(args, inputs, suffix)
    for p in inputs:
        data = _read(p)
        reject_binary_input_for_compress(p, detect_bytes(data))
        roots = parse_s1t_roots(decode_text_auto(data))
        payload = encode_s1t_nodes(roots, orzip_defs)
        data = zlib_compress_container(payload, args.level) if args.compress else payload
        if args.output:
            out = convert_output_path(p, args, suffix)
        elif getattr(args, "in_place", False):
            out = p
        elif args.compress:
            out = p.with_suffix(p.suffix + ".compressed.s")
        else:
            out = p.with_suffix(p.suffix + ".s1b")
        if out.resolve() == p.resolve():
            atomic_write_in_place(out, data, create_backup=not getattr(args, "no_backup", False))
        else:
            _write(out, data, args.force)
        mode = "compressed" if args.compress else "raw"
        print(f"[s1t2s1b] {p} -> {out} ({mode}, {len(data)} bytes)")
    return 0


def cmd_convert(args: argparse.Namespace) -> int:
    try:
        import orzip_defs
    except ImportError as exc:
        raise ORZIPError(f"cannot import embedded definitions module orzip_defs.py: {exc}") from exc

    inputs = iter_conversion_inputs(args)
    plans: list[tuple[Path, bytes, Detection, Path]] = []
    for p in inputs:
        data = _read(p)
        det = detect_bytes(data)
        if det.kind in {"compressed", "raw-binary"}:
            suffix = ".s1t.s"
        elif det.kind in {"unicode-text", "ascii-text-or-binary"}:
            suffix = ".compressed.s"
        else:
            raise ORZIPError(f"convert cannot auto-convert {p}: {det.detail}")
        plans.append((p, data, det, convert_output_path(p, args, suffix)))

    if args.output:
        reject_planned_output_collisions(inputs, [out for _, _, _, out in plans])

    for p, data, det, out in plans:
        if det.kind in {"compressed", "raw-binary"}:
            payload = extract_binary_payload(data)
            text = render_s1t_from_payload(payload, orzip_defs)
            output_data = UTF16LE_BOM + text.encode("utf-16le")
            if out.resolve() == p.resolve():
                atomic_write_in_place(out, output_data, create_backup=not getattr(args, "no_backup", False))
            else:
                _write(out, output_data, args.force)
            print(f"[convert] {p} -> {out} (binary -> text, {len(output_data)} bytes)")
        elif det.kind in {"unicode-text", "ascii-text-or-binary"}:
            roots = parse_s1t_roots(decode_text_auto(data))
            payload = encode_s1t_nodes(roots, orzip_defs)
            output_data = zlib_compress_container(payload, args.level)
            if out.resolve() == p.resolve():
                atomic_write_in_place(out, output_data, create_backup=not getattr(args, "no_backup", False))
            else:
                _write(out, output_data, args.force)
            print(f"[convert] {p} -> {out} (text -> compressed binary, {len(output_data)} bytes)")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        import orzip_defs
    except ImportError as exc:
        raise ORZIPError(f"cannot import embedded definitions module orzip_defs.py: {exc}") from exc

    rc = 0
    for p in iter_arg_inputs(args):
        try:
            data = _read(p)
            det = detect_bytes(data)
            if det.kind in {"compressed", "raw-binary"}:
                payload = extract_binary_payload(data, strict_trailing=getattr(args, "strict_zlib", False))
                root = parse_binary_block(payload, 16, orzip_defs.core_token_name)
                if root is None:
                    raise ORZIPError("could not parse root binary block")
                if root.token_name.lower() != "shape":
                    raise ORZIPError(f"root block must be shape, got {root.token_name}")
                render_s1t_from_payload(payload, orzip_defs)
                print(f"{p.name}: OK")
                print(f"  kind: {det.kind}")
                if det.declared_length is not None:
                    print(f"  declared payload: {det.declared_length}")
                print(f"  actual payload: {len(payload)}")
                trailing = zlib_trailing_data_length(data) if det.kind == "compressed" else 0
                if trailing:
                    print(f"  warning: trailing data after zlib stream: {trailing} bytes")
                print(f"  payload header: {payload[:16].decode('ascii', errors='replace').rstrip()}")
                print(f"  root block: {root.token_name}")
                print("  grammar decode: OK")
            elif det.kind in {"unicode-text", "ascii-text-or-binary"}:
                text = decode_text_auto(data)
                roots = parse_s1t_roots(text)
                if roots[0].name.lower() != "shape":
                    raise ORZIPError(f"root block must be shape, got {roots[0].name}")
                payload = encode_s1t_nodes(roots, orzip_defs)
                print(f"{p.name}: OK")
                print(f"  kind: {det.kind}")
                header = text.lstrip("\ufeff").split()[0] if text.strip() else "<empty>"
                print(f"  text header: {header}")
                print(f"  root block: {roots[0].name}")
                print("  grammar encode: OK")
                print(f"  binary payload size: {len(payload)}")
            else:
                rc = 1
                print(f"{p.name}: unsupported")
                print(f"  reason: {det.detail}")
        except ORZIPError as exc:
            rc = 1
            print(f"{p.name}: invalid")
            print(f"  reason: {exc}")
    return rc


def cmd_roundtrip(args: argparse.Namespace) -> int:
    try:
        import orzip_defs
    except ImportError as exc:
        raise ORZIPError(f"cannot import embedded definitions module orzip_defs.py: {exc}") from exc

    rc = 0
    for p in iter_arg_inputs(args):
        try:
            data = _read(p)
            det = detect_bytes(data)
            if det.kind in {"compressed", "raw-binary"}:
                original_payload = extract_binary_payload(data)
                rendered = render_s1t_from_payload(original_payload, orzip_defs)
                roots = parse_s1t_roots(rendered)
                roundtrip_payload = encode_s1t_nodes(roots, orzip_defs)
                digest = hashlib.sha256(original_payload).hexdigest()
                print(f"{p.name}: OK" if original_payload == roundtrip_payload else f"{p.name}: differs")
                print("  path: binary -> text -> binary")
                print(f"  original payload: {len(original_payload)} bytes")
                print(f"  roundtrip payload: {len(roundtrip_payload)} bytes")
                if original_payload == roundtrip_payload:
                    print("  payload match: byte-exact")
                    print(f"  sha256: {digest}")
                else:
                    rc = 1
                    print("  payload match: differs")
                    print(f"  original sha256: {digest}")
                    print(f"  roundtrip sha256: {hashlib.sha256(roundtrip_payload).hexdigest()}")
            elif det.kind in {"unicode-text", "ascii-text-or-binary"}:
                text = decode_text_auto(data)
                roots = parse_s1t_roots(text)
                payload = encode_s1t_nodes(roots, orzip_defs)
                regenerated = render_s1t_from_payload(payload, orzip_defs)
                parse_s1t_roots(regenerated)
                print(f"{p.name}: OK")
                print("  path: text -> binary -> text")
                print(f"  binary payload: {len(payload)} bytes")
                print("  regenerated text: parseable")
                print("  note: text formatting may differ from input")
            else:
                rc = 1
                print(f"{p.name}: unsupported")
                print(f"  reason: {det.detail}")
        except ORZIPError as exc:
            rc = 1
            print(f"{p.name}: invalid")
            print(f"  reason: {exc}")
    return rc


def cmd_defs(args: argparse.Namespace) -> int:
    try:
        import orzip_defs
    except ImportError as exc:
        raise ORZIPError(f"cannot import embedded definitions module orzip_defs.py: {exc}") from exc

    if args.token is not None:
        token_text = args.token.strip()
        if token_text.lower().startswith("0x"):
            token_id = int(token_text, 16)
            print(f"core token {token_text}: {orzip_defs.core_token_name(token_id) or '<unknown>'}")
        elif token_text.isdigit():
            token_id = int(token_text, 10)
            print(f"core token {token_id}: {orzip_defs.core_token_name(token_id) or '<unknown>'}")
        else:
            token_id = orzip_defs.core_token_id(token_text)
            print(f"core token {token_text}: {token_id if token_id is not None else '<unknown>'}")

    if args.grammar is not None:
        rule = orzip_defs.shape_grammar_rule(args.grammar)
        if rule is None:
            print(f"shape grammar {args.grammar}: <unknown>")
        else:
            print(f"shape grammar {rule.name}: {rule.kind}")
            print(f"  {rule.body}")
            print(f"  tokens: {' '.join(rule.tokens)}")

    if args.token is None and args.grammar is None:
        print("embedded definitions:")
        print(f"  core tokens: {len(orzip_defs.CORE_TOKEN_NAMES)}")
        print(f"  app token sequence names: {len(orzip_defs.APP_TOKEN_SEQUENCE)}")
        print(f"  form token names: {len(orzip_defs.FORM_TOKEN_NAMES)}")
        print(f"  load-string token names: {len(orzip_defs.LOADSTRING_TOKEN_NAMES)}")
        print(f"  shape grammar rules: {len(orzip_defs.SHAPE_GRAMMAR_RULES)}")
        for name in ("shape", "shape_header", "points", "point", "named_shader"):
            print(f"  core token {name}: {orzip_defs.core_token_id(name)}")
    return 0


def cmd_dump_blocks(args: argparse.Namespace) -> int:
    try:
        import orzip_defs
    except ImportError as exc:
        raise ORZIPError(f"cannot import embedded definitions module orzip_defs.py: {exc}") from exc

    for path_index, p in enumerate(iter_arg_inputs(args)):
        payload = extract_binary_payload(_read(p))
        subheader = payload[:16].decode("ascii", errors="replace").rstrip()
        if path_index:
            print()
        print(f"{p}: payload={subheader!r} bytes={len(payload)}")

        printed = 0

        def emit(block: BinaryBlock, depth: int) -> bool:
            nonlocal printed
            if printed >= args.limit:
                return False
            indent = "  " * depth
            label = f" label={block.label!r}" if block.label else ""
            print(
                f"{indent}{block.offset:08x}  {block.token_name} "
                f"id={block.token_id} flags=0x{block.flags:04x} "
                f"size={block.record_size} content={block.content_start:08x}..{block.end:08x}{label}"
            )
            printed += 1
            return printed < args.limit

        def walk(start: int, end: int, depth: int) -> None:
            nonlocal printed
            pos = start
            gap_start: int | None = None
            while pos + 9 <= end and printed < args.limit:
                block = parse_binary_block(payload, pos, orzip_defs.core_token_name)
                if block is not None and block.end <= end:
                    if gap_start is not None and args.show_gaps:
                        indent = "  " * depth
                        print(f"{indent}{gap_start:08x}  <data> size={pos - gap_start}")
                    gap_start = None
                    keep_going = emit(block, depth)
                    if keep_going and depth < args.max_depth and grammar_can_contain_blocks(block.token_name, orzip_defs):
                        walk(block.content_start, block.end, depth + 1)
                    pos = block.end
                else:
                    if gap_start is None:
                        gap_start = pos
                    pos += 1
            if gap_start is not None and args.show_gaps and gap_start < end:
                indent = "  " * depth
                print(f"{indent}{gap_start:08x}  <data> size={end - gap_start}")

        root = parse_binary_block(payload, 16, orzip_defs.core_token_name)
        if root is None:
            raise ORZIPError(f"could not parse root binary block in {p}")
        emit(root, 0)
        if args.max_depth > 0 and grammar_can_contain_blocks(root.token_name, orzip_defs):
            walk(root.content_start, root.end, 1)
        if printed >= args.limit:
            print(f"... stopped after --limit {args.limit} blocks")
    return 0


def cmd_dump_values(args: argparse.Namespace) -> int:
    try:
        import orzip_defs
    except ImportError as exc:
        raise ORZIPError(f"cannot import embedded definitions module orzip_defs.py: {exc}") from exc

    for path_index, p in enumerate(iter_arg_inputs(args)):
        payload = extract_binary_payload(_read(p))
        subheader = payload[:16].decode("ascii", errors="replace").rstrip()
        if path_index:
            print()
        print(f"{p}: payload={subheader!r} bytes={len(payload)}")

        printed_blocks = 0

        def print_block_header(block: BinaryBlock, indent: str) -> None:
            label = f" {block.label}" if block.label else ""
            print(f"{indent}{block.token_name}{label} (  # id={block.token_id} off=0x{block.offset:08x} size={block.record_size}")

        def decode_items(items: list[tuple], pos: int, end: int, depth: int, counts: dict[str, int]) -> int:
            indent = "  " * depth
            for item in items:
                kind = item[0]
                if kind == "field":
                    _, field_type, field_name = item
                    if field_type in PRIMITIVE_TYPES:
                        value, pos = read_primitive(payload, pos, end, field_type)
                        if isinstance(value, int):
                            counts[field_name.lower()] = value
                        print(f"{indent}{field_name} = {format_value(value, field_type, orzip_defs)}")
                    else:
                        child = parse_binary_block(payload, pos, orzip_defs.core_token_name)
                        if child is None or child.end > end or not block_matches_expected(child.token_name, field_type, orzip_defs):
                            raise ORZIPError(
                                f"expected block {field_type} at 0x{pos:08x}; "
                                f"got {child.token_name if child else '<none>'}"
                            )
                        decode_block(child, depth, field_name)
                        pos = child.end
                elif kind == "optional":
                    subitems = item[1]
                    if optional_group_present(payload, pos, end, subitems, orzip_defs):
                        pos = decode_items(subitems, pos, end, depth, counts.copy())
                elif kind == "repeat":
                    subitems = item[1]
                    total = None
                    if counts:
                        total = next(reversed(counts.values()))
                    shown = 0
                    repeated = 0
                    while pos < end and (total is None or repeated < total):
                        if args.item_limit >= 0 and shown >= args.item_limit:
                            remaining = (total - repeated) if total is not None else "unknown"
                            print(f"{indent}... skipped repeated items ({remaining} remaining shown by --item-limit)")
                            if total is not None and len(subitems) == 1 and subitems[0][0] == "field" and subitems[0][1] not in PRIMITIVE_TYPES:
                                expected = subitems[0][1]
                                while pos < end and repeated < total:
                                    child = parse_binary_block(payload, pos, orzip_defs.core_token_name)
                                    if child is None or child.end > end or not block_matches_expected(child.token_name, expected, orzip_defs):
                                        break
                                    pos = child.end
                                    repeated += 1
                                break
                            break
                        before = pos
                        pos = decode_items(subitems, pos, end, depth, counts.copy())
                        if pos == before:
                            break
                        repeated += 1
                        shown += 1
                else:
                    raise ORZIPError(f"unknown grammar item {kind}")
            return pos

        def decode_block(block: BinaryBlock, depth: int, field_name: str | None = None) -> None:
            nonlocal printed_blocks
            if printed_blocks >= args.block_limit:
                return
            indent = "  " * depth
            print_block_header(block, indent)
            printed_blocks += 1
            rule = orzip_defs.shape_grammar_rule(block.token_name)
            if rule is None or rule.kind != "block":
                print(f"{indent}  <raw> size={block.end - block.content_start}")
            elif depth < args.max_depth:
                items = parse_grammar_items(rule.tokens)
                try:
                    final_pos = decode_items(items, block.content_start, block.end, depth + 1, {})
                    if final_pos < block.end:
                        print(f"{indent}  <undecoded> off=0x{final_pos:08x} size={block.end - final_pos}")
                except ORZIPError as exc:
                    print(f"{indent}  <decode-error> {exc}")
                    if args.strict:
                        raise
            else:
                print(f"{indent}  ... max depth reached")
            print(f"{indent})")

        root = parse_binary_block(payload, 16, orzip_defs.core_token_name)
        if root is None:
            raise ORZIPError(f"could not parse root binary block in {p}")
        decode_block(root, 0)
        if printed_blocks >= args.block_limit:
            print(f"... stopped after --block-limit {args.block_limit} blocks")
    return 0


PRIMARY_COMMANDS = "info,check,test,convert,text,binary,raw,wrap,repack,defs,blocks,values"
ADVANCED_COMMANDS = (
    "info,detect,check,validate,test,roundtrip,convert,text,uncompress,s1b2s1t,"
    "binary,compress,s1t2s1b,raw,unpack,wrap,pack,repack,normalize,defs,blocks,"
    "dump-blocks,values,dump-values"
)


def build_parser(advanced_help: bool = False) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orzip.py",
        description="Standalone MSTS/Open Rails SIMISA zlib compressor/decompressor for compressed binary .s containers.",
    )
    parser.add_argument("--version", action="version", version="ORZIP 1.0.4")
    parser.add_argument("--advanced-help", action="store_true", help="show all compatibility and technical commands")
    sub = parser.add_subparsers(dest="command", metavar=ADVANCED_COMMANDS if advanced_help else PRIMARY_COMMANDS)

    def add_common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("inputs", nargs="+", type=Path)
        sp.add_argument("-r", "--recursive", action="store_true", help="recurse into directory inputs")
        sp.add_argument("-s", "--only-s", action="store_true", help="when processing directories, include only .s/.S files")

    def add_no_backup(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--no-backup",
            action="store_true",
            help="skip backup for in-place conversion; atomic replacement is still used",
        )

    def add_strict_zlib(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--strict-zlib",
            action="store_true",
            help="fail if a compressed SIMISA@F file has bytes after the valid zlib stream",
        )

    p = sub.add_parser("info", help="identify file type")
    add_common(p)
    p.add_argument("-v", "--verify", action="store_true", help="also inflate compressed files and check declared size")
    add_strict_zlib(p)
    p.set_defaults(func=cmd_detect)

    p = sub.add_parser("detect", help="identify file type" if advanced_help else argparse.SUPPRESS)
    add_common(p)
    p.add_argument("-v", "--verify", action="store_true", help="also inflate compressed files and check declared size")
    add_strict_zlib(p)
    p.set_defaults(func=cmd_detect)

    p = sub.add_parser("raw", help="extract raw JINX0... binary payload")
    add_common(p)
    p.add_argument("-o", "--output", type=Path, help="output path for a single input")
    p.add_argument("-f", "--force", action="store_true", help="overwrite output files")
    p.set_defaults(func=cmd_unpack)

    p = sub.add_parser("unpack", help="SIMISA@F compressed file -> raw JINX0... binary payload" if advanced_help else argparse.SUPPRESS)
    add_common(p)
    p.add_argument("-o", "--output", type=Path, help="output path for a single input")
    p.add_argument("-f", "--force", action="store_true", help="overwrite output files")
    p.set_defaults(func=cmd_unpack)

    p = sub.add_parser("wrap", help="wrap raw JINX0... binary payload as compressed SIMISA@F")
    add_common(p)
    p.add_argument("-o", "--output", type=Path, help="output path for a single input")
    p.add_argument("-f", "--force", action="store_true", help="overwrite output files")
    p.add_argument("-l", "--level", type=int, default=9, choices=range(0, 10), metavar="0-9", help="zlib compression level (default: 9)")
    p.set_defaults(func=cmd_pack)

    p = sub.add_parser("pack", help="raw JINX0... binary payload -> SIMISA@F compressed file" if advanced_help else argparse.SUPPRESS)
    add_common(p)
    p.add_argument("-o", "--output", type=Path, help="output path for a single input")
    p.add_argument("-f", "--force", action="store_true", help="overwrite output files")
    p.add_argument("-l", "--level", type=int, default=9, choices=range(0, 10), metavar="0-9", help="zlib compression level (default: 9)")
    p.set_defaults(func=cmd_pack)

    p = sub.add_parser("repack", help="inflate and recompress a compressed SIMISA@F file")
    add_common(p)
    p.add_argument("-o", "--output", type=Path, help="output path for a single input")
    p.add_argument("-f", "--force", action="store_true", help="overwrite output files")
    p.add_argument("-l", "--level", type=int, default=9, choices=range(0, 10), metavar="0-9", help="zlib compression level (default: 9)")
    p.set_defaults(func=cmd_normalize)

    p = sub.add_parser("normalize", help="inflate and repack a compressed SIMISA@F file with modern zlib" if advanced_help else argparse.SUPPRESS)
    add_common(p)
    p.add_argument("-o", "--output", type=Path, help="output path for a single input")
    p.add_argument("-f", "--force", action="store_true", help="overwrite output files")
    p.add_argument("-l", "--level", type=int, default=9, choices=range(0, 10), metavar="0-9", help="zlib compression level (default: 9)")
    p.set_defaults(func=cmd_normalize)

    p = sub.add_parser("text", help="make a binary/compressed shape file editable text")
    add_common(p)
    p.add_argument("-o", "--output", type=Path, help="output path for a single input")
    p.add_argument("-f", "--force", action="store_true", help="overwrite output files")
    add_no_backup(p)
    p.set_defaults(func=cmd_s1b2s1t, in_place=True)

    p = sub.add_parser("uncompress", help="convert compressed/raw binary s1b shape data to UTF-16 text s1t" if advanced_help else argparse.SUPPRESS)
    add_common(p)
    p.add_argument("-o", "--output", type=Path, help="output path for a single input")
    p.add_argument("-f", "--force", action="store_true", help="overwrite output files")
    add_no_backup(p)
    p.set_defaults(func=cmd_s1b2s1t, in_place=True)

    p = sub.add_parser("s1b2s1t", help="convert compressed/raw binary s1b shape data to UTF-16 text s1t" if advanced_help else argparse.SUPPRESS)
    add_common(p)
    p.add_argument("-o", "--output", type=Path, help="output path for a single input")
    p.add_argument("-f", "--force", action="store_true", help="overwrite output files")
    add_no_backup(p)
    p.set_defaults(func=cmd_s1b2s1t, in_place=False)

    p = sub.add_parser("binary", help="make an editable text shape file compressed binary")
    add_common(p)
    p.add_argument("-o", "--output", type=Path, help="output path for a single input")
    p.add_argument("-f", "--force", action="store_true", help="overwrite output files")
    p.add_argument("-l", "--level", type=int, default=9, choices=range(0, 10), metavar="0-9", help="zlib compression level (default: 9)")
    add_no_backup(p)
    p.set_defaults(func=cmd_s1t2s1b, compress=True, in_place=True)

    p = sub.add_parser("compress", help="convert text s1t shape data to compressed SIMISA@F .s" if advanced_help else argparse.SUPPRESS)
    add_common(p)
    p.add_argument("-o", "--output", type=Path, help="output path for a single input")
    p.add_argument("-f", "--force", action="store_true", help="overwrite output files")
    p.add_argument("-l", "--level", type=int, default=9, choices=range(0, 10), metavar="0-9", help="zlib compression level (default: 9)")
    add_no_backup(p)
    p.set_defaults(func=cmd_s1t2s1b, compress=True, in_place=True)

    p = sub.add_parser("s1t2s1b", help="convert UTF-16/UTF-8 text s1t shape data to binary s1b" if advanced_help else argparse.SUPPRESS)
    add_common(p)
    p.add_argument("-o", "--output", type=Path, help="output path for a single input")
    p.add_argument("-f", "--force", action="store_true", help="overwrite output files")
    p.add_argument("--compress", action="store_true", help="wrap output as compressed SIMISA@F .s instead of raw s1b")
    p.add_argument("-l", "--level", type=int, default=9, choices=range(0, 10), metavar="0-9", help="zlib compression level when --compress is used (default: 9)")
    add_no_backup(p)
    p.set_defaults(func=cmd_s1t2s1b, in_place=False)

    p = sub.add_parser("convert", help="auto-convert binary .s/raw s1b to text, or text s1t to compressed binary")
    add_common(p)
    p.add_argument("-o", "--output", type=Path, help="output path for a single input")
    p.add_argument("-f", "--force", action="store_true", help="overwrite output files")
    p.add_argument("-l", "--level", type=int, default=9, choices=range(0, 10), metavar="0-9", help="zlib compression level for text -> compressed output (default: 9)")
    add_no_backup(p)
    p.set_defaults(func=cmd_convert)

    p = sub.add_parser("check", help="validate shape files without writing output")
    add_common(p)
    add_strict_zlib(p)
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("validate", help="validate compressed/raw/text shape files without writing output" if advanced_help else argparse.SUPPRESS)
    add_common(p)
    add_strict_zlib(p)
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("test", help="test binary/text conversion round-trips without writing output")
    add_common(p)
    p.set_defaults(func=cmd_roundtrip)

    p = sub.add_parser("roundtrip", help="test binary/text conversion round-trips without writing output" if advanced_help else argparse.SUPPRESS)
    add_common(p)
    p.set_defaults(func=cmd_roundtrip)

    p = sub.add_parser("defs", help="inspect embedded token and shape grammar definitions")
    p.add_argument("--token", help="core token name or numeric id to look up")
    p.add_argument("--grammar", help="shape grammar rule name to display")
    p.set_defaults(func=cmd_defs)

    p = sub.add_parser("blocks", help="dump binary block headers from compressed or raw files")
    add_common(p)
    p.add_argument("-d", "--max-depth", type=int, default=3, help="maximum child-block depth to scan (default: 3)")
    p.add_argument("-n", "--limit", type=int, default=200, help="maximum blocks to print per file (default: 200)")
    p.add_argument("--show-gaps", action="store_true", help="also show non-block data gaps between child blocks")
    p.set_defaults(func=cmd_dump_blocks)

    p = sub.add_parser("dump-blocks", help="dump binary s1b block headers from compressed or raw files" if advanced_help else argparse.SUPPRESS)
    add_common(p)
    p.add_argument("-d", "--max-depth", type=int, default=3, help="maximum child-block depth to scan (default: 3)")
    p.add_argument("-n", "--limit", type=int, default=200, help="maximum blocks to print per file (default: 200)")
    p.add_argument("--show-gaps", action="store_true", help="also show non-block data gaps between child blocks")
    p.set_defaults(func=cmd_dump_blocks)

    p = sub.add_parser("values", help="decode binary blocks into named values")
    add_common(p)
    p.add_argument("-d", "--max-depth", type=int, default=3, help="maximum block depth to decode (default: 3)")
    p.add_argument("-i", "--item-limit", type=int, default=8, help="maximum repeated items to print per list; -1 means no limit (default: 8)")
    p.add_argument("-b", "--block-limit", type=int, default=500, help="maximum decoded blocks to print per file (default: 500)")
    p.add_argument("--strict", action="store_true", help="stop on the first grammar decode error")
    p.set_defaults(func=cmd_dump_values)

    p = sub.add_parser("dump-values", help="grammar-decode binary s1b blocks into named fields" if advanced_help else argparse.SUPPRESS)
    add_common(p)
    p.add_argument("-d", "--max-depth", type=int, default=3, help="maximum block depth to decode (default: 3)")
    p.add_argument("-i", "--item-limit", type=int, default=8, help="maximum repeated items to print per list; -1 means no limit (default: 8)")
    p.add_argument("-b", "--block-limit", type=int, default=500, help="maximum decoded blocks to print per file (default: 500)")
    p.add_argument("--strict", action="store_true", help="stop on the first grammar decode error")
    p.set_defaults(func=cmd_dump_values)

    if not advanced_help:
        primary_order = PRIMARY_COMMANDS.split(",")
        sub._choices_actions = [
            action
            for command in primary_order
            for action in sub._choices_actions
            if action.dest == command and action.help != argparse.SUPPRESS
        ]

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.advanced_help:
        build_parser(advanced_help=True).print_help()
        return 0
    if args.command is None:
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except ORZIPError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
