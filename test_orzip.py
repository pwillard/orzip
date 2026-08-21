#!/usr/bin/env python
"""ORZIP regression tests with generated fixtures and optional local samples."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

import orzip
import orzip_defs

ROOT = Path(__file__).resolve().parent
LOCAL_SAMPLES_DIR = ROOT / "samples"
DASH8_COMPRESSED = LOCAL_SAMPLES_DIR / "dash8.s"
DASH8_TEXT = LOCAL_SAMPLES_DIR / "dash8u.s"
SHAPE_275004_KN = LOCAL_SAMPLES_DIR / "275004_KN.s"
SHAPE_275004_LN = LOCAL_SAMPLES_DIR / "275004_LN.s"
KIHA31_WIPER_TEXT = LOCAL_SAMPLES_DIR / "kiha31wiper.s"
KIHA31_WIPER_REFERENCE_COMPRESSED = Path("C:/tmp/kiha31wiper.s") if os.name == "nt" else Path("/mnt/c/tmp/kiha31wiper.s")

SYNTHETIC_TEXT_CONTENT = """SIMISA@@@@@@@@@@JINX0s1t______
shape (
 shape_header ( 00000000 )
 volumes ( 0 )
 shader_names ( 0 )
 texture_filter_names ( 0 )
 points ( 1 point ( 1 2 3 ) )
 uv_points ( 0 )
 normals ( 0 )
 sort_vectors ( 0 )
 colours ( 0 )
 matrices ( 0 )
 images ( 0 )
 textures ( 0 )
 light_materials ( 0 )
 light_model_cfgs ( 0 )
 vtx_states ( 0 )
 prim_states ( 0 )
 lod_controls ( 0 )
)
"""
SYNTHETIC_PAYLOAD = orzip.encode_s1t_node(orzip.parse_s1t_text(SYNTHETIC_TEXT_CONTENT), orzip_defs)
SYNTHETIC_TEMP_DIR = tempfile.TemporaryDirectory(prefix="orzip-synthetic-fixtures-")
SYNTHETIC_ROOT = Path(SYNTHETIC_TEMP_DIR.name)
SYNTHETIC_TEXT = SYNTHETIC_ROOT / "synthetic-text.s"
SYNTHETIC_COMPRESSED = SYNTHETIC_ROOT / "synthetic-compressed.s"
SYNTHETIC_TEXT.write_bytes(orzip.UTF16LE_BOM + SYNTHETIC_TEXT_CONTENT.encode("utf-16le"))
SYNTHETIC_COMPRESSED.write_bytes(orzip.zlib_compress_container(SYNTHETIC_PAYLOAD))


def requires_local_samples(*paths: Path):
    names = ", ".join(path.name for path in paths)
    return unittest.skipUnless(all(path.is_file() for path in paths), f"optional local samples unavailable: {names}")


class ORZIPRegressionTests(unittest.TestCase):
    def test_default_fixtures_are_generated_outside_repository(self) -> None:
        self.assertFalse(SYNTHETIC_COMPRESSED.is_relative_to(ROOT))
        self.assertFalse(SYNTHETIC_TEXT.is_relative_to(ROOT))

    def test_parse_scalar_reports_invalid_float(self) -> None:
        with self.assertRaisesRegex(orzip.ORZIPError, "invalid float value 'nope'"):
            orzip.parse_scalar_token("nope", "float", None)

    def test_write_primitive_reports_unsigned_integer_overflow(self) -> None:
        with self.assertRaisesRegex(orzip.ORZIPError, "uint value out of range"):
            orzip.write_primitive(2**32, "uint")

    def test_tokenizer_rejects_unterminated_quoted_string(self) -> None:
        with self.assertRaisesRegex(orzip.ORZIPError, "unterminated quoted string"):
            orzip.tokenize_s1t('shape ( image ( "missing end ) )')

    def test_cli_binary_reports_invalid_float_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-invalid-value-test-") as td:
            temp = Path(td)
            malformed = temp / "malformed.s"
            output = temp / "output.s"
            text = orzip.decode_text_auto(SYNTHETIC_TEXT.read_bytes())
            self.assertIn("point ( 1 2 3 )", text)
            malformed.write_bytes(orzip.UTF16LE_BOM + text.replace("point ( 1", "point ( nope", 1).encode("utf-16le"))

            result = subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "binary", str(malformed), "-o", str(output)],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("invalid float value 'nope'", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(output.exists())

    def test_cli_binary_rejects_excessive_nesting_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-nesting-test-") as td:
            temp = Path(td)
            malformed = temp / "nested.s"
            output = temp / "output.s"
            depth = 1_200
            text = "SIMISA@@@@@@@@@@JINX0s1t______\n" + ("shape ( " * depth) + (") " * depth)
            malformed.write_text(text, encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "binary", str(malformed), "-o", str(output)],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("nesting exceeds", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(output.exists())

    def test_cli_output_parent_error_has_no_traceback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-write-error-test-") as td:
            temp = Path(td)
            blocker = temp / "blocked"
            blocker.write_text("not a directory", encoding="utf-8")
            output = blocker / "output.s"

            result = subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "text", str(SYNTHETIC_COMPRESSED), "-o", str(output)],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("cannot create output directory", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_atomic_in_place_write_creates_backup(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-atomic-write-test-") as td:
            target = Path(td) / "shape.s"
            target.write_bytes(b"original")

            orzip.atomic_write_in_place(target, b"replacement")

            self.assertEqual(target.read_bytes(), b"replacement")
            self.assertEqual((Path(td) / "shape.s.bak").read_bytes(), b"original")
            self.assertEqual(list(Path(td).glob(".shape.s.*.tmp")), [])

    def test_atomic_in_place_write_can_skip_backup(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-atomic-write-test-") as td:
            target = Path(td) / "shape.s"
            target.write_bytes(b"original")

            orzip.atomic_write_in_place(target, b"replacement", create_backup=False)

            self.assertEqual(target.read_bytes(), b"replacement")
            self.assertFalse(target.with_name(target.name + ".bak").exists())
            self.assertEqual(list(Path(td).glob(".shape.s.*.tmp")), [])

    def test_atomic_in_place_write_versions_existing_backup(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-atomic-write-test-") as td:
            target = Path(td) / "shape.s"
            target.write_bytes(b"first")

            orzip.atomic_write_in_place(target, b"second")
            orzip.atomic_write_in_place(target, b"third")

            self.assertEqual(target.read_bytes(), b"third")
            self.assertEqual((Path(td) / "shape.s.bak").read_bytes(), b"first")
            self.assertEqual((Path(td) / "shape.s.bak.1").read_bytes(), b"second")

    def test_atomic_in_place_write_publishes_backup_with_atomic_replace(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-atomic-write-test-") as td:
            target = Path(td) / "shape.s"
            backup = Path(td) / "shape.s.bak"
            target.write_bytes(b"original")

            with mock.patch("orzip.os.replace", wraps=os.replace) as replace:
                orzip.atomic_write_in_place(target, b"replacement")

            destinations = [Path(call.args[1]) for call in replace.call_args_list]
            self.assertIn(backup, destinations)
            self.assertIn(target, destinations)

    def test_atomic_in_place_write_failure_preserves_original(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-atomic-write-test-") as td:
            target = Path(td) / "shape.s"
            target.write_bytes(b"original")
            real_replace = os.replace

            def fail_target_replace(source: str | Path, destination: str | Path) -> None:
                if Path(destination) == target:
                    raise OSError("simulated replace failure")
                real_replace(source, destination)

            with mock.patch("orzip.os.replace", side_effect=fail_target_replace):
                with self.assertRaisesRegex(orzip.ORZIPError, "cannot replace"):
                    orzip.atomic_write_in_place(target, b"replacement")

            self.assertEqual(target.read_bytes(), b"original")
            self.assertEqual(list(Path(td).glob(".shape.s.*.tmp")), [])

    def test_atomic_in_place_write_cleanup_failure_does_not_mask_replace_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-atomic-write-test-") as td:
            target = Path(td) / "shape.s"
            target.write_bytes(b"original")
            real_replace = os.replace

            def fail_target_replace(source: str | Path, destination: str | Path) -> None:
                if Path(destination) == target:
                    raise OSError("simulated replace failure")
                real_replace(source, destination)

            with mock.patch("orzip.os.replace", side_effect=fail_target_replace):
                with mock.patch.object(Path, "unlink", side_effect=OSError("simulated cleanup failure")):
                    with self.assertRaisesRegex(orzip.ORZIPError, "cannot replace"):
                        orzip.atomic_write_in_place(target, b"replacement")

            self.assertEqual(target.read_bytes(), b"original")

    def test_atomic_in_place_write_backup_read_failure_closes_temp_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-atomic-write-test-") as td:
            target = Path(td) / "shape.s"
            target.write_bytes(b"original")
            real_open = Path.open

            def fail_backup_read(path: Path, mode: str = "r", *args, **kwargs):
                if path == target and mode == "rb":
                    raise OSError("simulated backup read failure")
                return real_open(path, mode, *args, **kwargs)

            with mock.patch.object(Path, "open", autospec=True, side_effect=fail_backup_read):
                with self.assertRaisesRegex(orzip.ORZIPError, "cannot back up"):
                    orzip.atomic_write_in_place(target, b"replacement")

            self.assertEqual(target.read_bytes(), b"original")
            self.assertEqual(list(Path(td).glob(".shape.s.*.tmp")), [])

    def test_cli_standard_help_shows_concise_commands_only(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "orzip.py"), "--help"],
            check=True,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        self.assertIn("info,check,test,convert,text,binary,raw,wrap,repack,defs,blocks,values", result.stdout)
        self.assertIn("check", result.stdout)
        self.assertIn("binary", result.stdout)
        self.assertNotIn("s1b2s1t", result.stdout)
        self.assertNotIn("roundtrip", result.stdout)
        self.assertNotIn("==SUPPRESS==", result.stdout)

    def test_cli_advanced_help_shows_compatibility_commands(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "orzip.py"), "--advanced-help"],
            check=True,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        self.assertIn("s1b2s1t", result.stdout)
        self.assertIn("s1t2s1b", result.stdout)
        self.assertIn("roundtrip", result.stdout)
        self.assertIn("dump-values", result.stdout)

    def test_detect_and_verify_synthetic_compressed_file(self) -> None:
        data = SYNTHETIC_COMPRESSED.read_bytes()
        detection = orzip.detect_bytes(data)
        self.assertEqual(detection.kind, "compressed")
        payload = orzip.zlib_decompress_container(data)
        self.assertEqual(payload, SYNTHETIC_PAYLOAD)
        self.assertTrue(payload.startswith(b"JINX0s1b______" + bytes([13, 10])))

    def test_decompress_tolerates_bytes_after_zlib_stream_by_default(self) -> None:
        payload = b"JINX0s1b______" + bytes([13, 10])
        container = orzip.zlib_compress_container(payload)

        self.assertEqual(orzip.zlib_decompress_container(container + b"GARBAGE"), payload)

    def test_decompress_strict_mode_rejects_bytes_after_zlib_stream(self) -> None:
        container = orzip.zlib_compress_container(b"JINX0s1b______" + bytes([13, 10]))

        with self.assertRaisesRegex(orzip.ORZIPError, "trailing data"):
            orzip.zlib_decompress_container(container + b"GARBAGE", strict_trailing=True)

    def test_decompress_rejects_truncated_zlib_stream(self) -> None:
        container = orzip.zlib_compress_container(b"JINX0s1b______" + bytes([13, 10]))

        with self.assertRaisesRegex(orzip.ORZIPError, "incomplete or truncated"):
            orzip.zlib_decompress_container(container[:-1])

    def test_decompress_rejects_declared_length_mismatch(self) -> None:
        container = bytearray(orzip.zlib_compress_container(b"JINX0s1b______" + bytes([13, 10])))
        declared = int.from_bytes(container[8:12], "little")
        container[8:12] = (declared + 1).to_bytes(4, "little")

        with self.assertRaisesRegex(orzip.ORZIPError, "length mismatch"):
            orzip.zlib_decompress_container(bytes(container))

    def test_cli_check_warns_but_accepts_bytes_after_zlib_stream_by_default(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-stream-test-") as td:
            damaged = Path(td) / "trailing.s"
            damaged.write_bytes(SYNTHETIC_COMPRESSED.read_bytes() + b"GARBAGE")

            result = subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "check", str(damaged)],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertEqual(result.returncode, 0)
            self.assertIn("trailing data after zlib stream: 7 bytes", result.stdout)
            self.assertIn("warning", result.stdout.lower())

    def test_cli_check_strict_zlib_rejects_bytes_after_zlib_stream(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-stream-test-") as td:
            damaged = Path(td) / "trailing.s"
            damaged.write_bytes(SYNTHETIC_COMPRESSED.read_bytes() + b"GARBAGE")

            result = subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "check", "--strict-zlib", str(damaged)],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("trailing data after zlib stream: 7 bytes", result.stdout)

    def test_synthetic_text_encodes_to_byte_exact_binary_payload(self) -> None:
        expected_payload = orzip.zlib_decompress_container(SYNTHETIC_COMPRESSED.read_bytes())
        root = orzip.parse_s1t_text(orzip.decode_text_auto(SYNTHETIC_TEXT.read_bytes()))
        actual_payload = orzip.encode_s1t_node(root, orzip_defs)

        self.assertEqual(actual_payload, expected_payload)

    @requires_local_samples(KIHA31_WIPER_TEXT, KIHA31_WIPER_REFERENCE_COMPRESSED)
    def test_text_with_top_level_max_data_matches_reference_compressed_payload(self) -> None:
        text = orzip.decode_text_auto(KIHA31_WIPER_TEXT.read_bytes())
        roots = orzip.parse_s1t_roots(text)
        actual_payload = orzip.encode_s1t_nodes(roots, orzip_defs)
        expected_payload = orzip.zlib_decompress_container(KIHA31_WIPER_REFERENCE_COMPRESSED.read_bytes())

        self.assertEqual([root.name for root in roots], ["shape", "max_data"])
        self.assertEqual(actual_payload, expected_payload)

    def test_single_root_parser_rejects_multiple_roots_with_clear_count(self) -> None:
        base_text = orzip.decode_text_auto(SYNTHETIC_TEXT.read_bytes())
        multi_root_text = base_text + (chr(13) + chr(10)) + "max_data ( )" + (chr(13) + chr(10))

        with self.assertRaisesRegex(orzip.ORZIPError, "expected one root block, got 2"):
            orzip.parse_s1t_text(multi_root_text)

    def test_synthetic_binary_renders_known_shape_values(self) -> None:
        payload = orzip.zlib_decompress_container(SYNTHETIC_COMPRESSED.read_bytes())
        rendered = orzip.render_s1t_from_payload(payload, orzip_defs)

        self.assertIn("SIMISA@@@@@@@@@@JINX0s1t______", rendered)
        self.assertIn("point ( 1 2 3 )", rendered)
        self.assertIn("lod_controls (", rendered)

    @requires_local_samples(DASH8_TEXT)
    def test_dash8_text_compresses_to_valid_binary_container(self) -> None:
        root = orzip.parse_s1t_text(orzip.decode_text_auto(DASH8_TEXT.read_bytes()))
        payload = orzip.encode_s1t_node(root, orzip_defs)
        compressed = orzip.zlib_compress_container(payload)

        detection = orzip.detect_bytes(compressed)
        self.assertEqual(detection.kind, "compressed")
        self.assertEqual(detection.declared_length, 3_440_900)
        self.assertEqual(len(orzip.zlib_decompress_container(compressed)), 3_440_900)

    @requires_local_samples(SHAPE_275004_KN)
    def test_275004_kn_shape_binary_text_binary_is_byte_exact(self) -> None:
        original_payload = orzip.zlib_decompress_container(SHAPE_275004_KN.read_bytes())
        rendered = orzip.render_s1t_from_payload(original_payload, orzip_defs)
        root = orzip.parse_s1t_text(rendered)
        roundtrip_payload = orzip.encode_s1t_node(root, orzip_defs)

        self.assertEqual(len(original_payload), 12_074_302)
        self.assertIn("shape (", rendered)
        self.assertIn("points (", rendered)
        self.assertIn("lod_controls (", rendered)
        self.assertEqual(roundtrip_payload, original_payload)

    @requires_local_samples(DASH8_COMPRESSED)
    def test_dash8_shape_binary_text_binary_is_byte_exact(self) -> None:
        original_payload = orzip.zlib_decompress_container(DASH8_COMPRESSED.read_bytes())
        rendered = orzip.render_s1t_from_payload(original_payload, orzip_defs)
        root = orzip.parse_s1t_text(rendered)
        roundtrip_payload = orzip.encode_s1t_node(root, orzip_defs)

        self.assertEqual(len(original_payload), 3_440_900)
        self.assertIn("shape (", rendered)
        self.assertIn("points (", rendered)
        self.assertIn("images (", rendered)
        self.assertIn("textures (", rendered)
        self.assertIn("lod_controls (", rendered)
        self.assertEqual(roundtrip_payload, original_payload)

    @requires_local_samples(SHAPE_275004_LN)
    def test_275004_ln_shape_binary_text_binary_is_byte_exact(self) -> None:
        original_payload = orzip.zlib_decompress_container(SHAPE_275004_LN.read_bytes())
        rendered = orzip.render_s1t_from_payload(original_payload, orzip_defs)
        root = orzip.parse_s1t_text(rendered)
        roundtrip_payload = orzip.encode_s1t_node(root, orzip_defs)

        self.assertEqual(len(original_payload), 12_074_302)
        self.assertIn("shape (", rendered)
        self.assertIn("points (", rendered)
        self.assertIn("matrices (", rendered)
        self.assertIn("images (", rendered)
        self.assertIn("textures (", rendered)
        self.assertIn("lod_controls (", rendered)
        self.assertEqual(roundtrip_payload, original_payload)

    def test_cli_compress_then_uncompress_smoke(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-test-") as td:
            temp = Path(td)
            compressed = temp / "csx_from_text.s"
            text_roundtrip = temp / "csx_roundtrip.s"

            subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "compress", str(SYNTHETIC_TEXT), "-o", str(compressed)],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "uncompress", str(compressed), "-o", str(text_roundtrip)],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            roundtrip_text = orzip.decode_text_auto(text_roundtrip.read_bytes())
            self.assertIn("point (", roundtrip_text)
            self.assertIn("point ( 1 2 3 )", roundtrip_text)

    def test_cli_compress_rejects_already_compressed_input(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-wrong-kind-test-") as td:
            temp = Path(td)
            already_compressed = temp / "already_compressed.s"
            already_compressed.write_bytes(orzip.zlib_compress_container(b"JINX0s1b______" + bytes([13, 10])))

            result = subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "compress", str(already_compressed)],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("file is already compressed", result.stderr)

    def test_cli_uncompress_rejects_already_uncompressed_text_input(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-wrong-kind-test-") as td:
            temp = Path(td)
            already_text = temp / "already_text.s"
            text = "SIMISA@@@@@@@@@@JINX0s1t______" + chr(13) + chr(10) + "shape ( )" + chr(13) + chr(10)
            already_text.write_bytes(orzip.UTF16LE_BOM + text.encode("utf-16le"))

            result = subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "uncompress", str(already_text)],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("file is already uncompressed text", result.stderr)

    def test_cli_compress_and_uncompress_aliases(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-test-") as td:
            temp = Path(td)
            compressed = temp / "synthetic-from-text.s"
            text_roundtrip = temp / "synthetic-roundtrip.s"

            subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "compress", str(SYNTHETIC_TEXT), "-o", str(compressed)],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            detection = orzip.detect_bytes(compressed.read_bytes())
            self.assertEqual(detection.kind, "compressed")
            self.assertEqual(detection.declared_length, len(SYNTHETIC_PAYLOAD))

            subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "uncompress", str(compressed), "-o", str(text_roundtrip)],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            roundtrip_text = orzip.decode_text_auto(text_roundtrip.read_bytes())
            self.assertIn("SIMISA@@@@@@@@@@JINX0s1t______", roundtrip_text)
            self.assertIn("point ( 1 2 3 )", roundtrip_text)

    def test_cli_text_and_binary_concise_commands(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-test-") as td:
            temp = Path(td)
            text_shape = temp / "synthetic-text.s"
            compressed = temp / "synthetic-binary.s"

            subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "text", str(SYNTHETIC_COMPRESSED), "-o", str(text_shape)],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertIn("SIMISA@@@@@@@@@@JINX0s1t______", orzip.decode_text_auto(text_shape.read_bytes()))

            subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "binary", str(text_shape), "-o", str(compressed)],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            detection = orzip.detect_bytes(compressed.read_bytes())
            self.assertEqual(detection.kind, "compressed")
            self.assertEqual(detection.declared_length, len(SYNTHETIC_PAYLOAD))

    def test_cli_binary_multiple_files_writes_to_output_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-multi-output-test-") as td:
            temp = Path(td)
            first = temp / "first.s"
            second = temp / "second.s"
            output = temp / "Converted"
            shutil.copy2(SYNTHETIC_TEXT, first)
            shutil.copy2(SYNTHETIC_TEXT, second)
            original = SYNTHETIC_TEXT.read_bytes()

            subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "binary", str(first), str(second), "-o", str(output)],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertEqual(first.read_bytes(), original)
            self.assertEqual(second.read_bytes(), original)
            self.assertEqual(orzip.detect_bytes((output / "first.s.compressed.s").read_bytes()).kind, "compressed")
            self.assertEqual(orzip.detect_bytes((output / "second.s.compressed.s").read_bytes()).kind, "compressed")

    def test_cli_text_multiple_files_writes_to_output_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-multi-output-test-") as td:
            temp = Path(td)
            first = temp / "first.s"
            second = temp / "second.s"
            output = temp / "Converted"
            shutil.copy2(SYNTHETIC_COMPRESSED, first)
            shutil.copy2(SYNTHETIC_COMPRESSED, second)
            original = SYNTHETIC_COMPRESSED.read_bytes()

            subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "text", str(first), str(second), "-o", str(output)],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertEqual(first.read_bytes(), original)
            self.assertEqual(second.read_bytes(), original)
            self.assertIn("SIMISA@@@@@@@@@@JINX0s1t______", orzip.decode_text_auto((output / "first.s.s1t.s").read_bytes()))
            self.assertIn("SIMISA@@@@@@@@@@JINX0s1t______", orzip.decode_text_auto((output / "second.s.s1t.s").read_bytes()))

    def test_cli_multiple_files_rejects_output_name_collision_before_writing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-multi-output-test-") as td:
            temp = Path(td)
            first = temp / "First" / "shape.s"
            second = temp / "Second" / "shape.s"
            output = temp / "Converted"
            first.parent.mkdir()
            second.parent.mkdir()
            shutil.copy2(SYNTHETIC_COMPRESSED, first)
            shutil.copy2(SYNTHETIC_COMPRESSED, second)

            result = subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "text", str(first), str(second), "-o", str(output)],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("same output file", result.stderr)
            self.assertFalse(output.exists())

    def test_cli_multiple_files_rejects_output_that_matches_an_input(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-multi-output-test-") as td:
            temp = Path(td)
            source = temp / "Source" / "shape.s"
            output = temp / "Converted"
            later_input = output / "shape.s.s1t.s"
            source.parent.mkdir()
            output.mkdir()
            shutil.copy2(SYNTHETIC_COMPRESSED, source)
            shutil.copy2(SYNTHETIC_COMPRESSED, later_input)
            original = SYNTHETIC_COMPRESSED.read_bytes()

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "orzip.py"),
                    "text",
                    str(source),
                    str(later_input),
                    "-o",
                    str(output),
                    "--force",
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("overwrite an input file", result.stderr)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(later_input.read_bytes(), original)
            self.assertFalse((output / "shape.s.s1t.s.s1t.s").exists())

    def test_cli_convert_rejects_output_that_matches_a_later_input(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-convert-output-test-") as td:
            temp = Path(td)
            source = temp / "Source" / "shape.s"
            output = temp / "Converted"
            later_input = output / "shape.s.compressed.s"
            source.parent.mkdir()
            output.mkdir()
            shutil.copy2(SYNTHETIC_TEXT, source)
            shutil.copy2(SYNTHETIC_COMPRESSED, later_input)
            original_source = source.read_bytes()
            original_later = later_input.read_bytes()

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "orzip.py"),
                    "convert",
                    str(source),
                    str(later_input),
                    "-o",
                    str(output),
                    "--force",
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("overwrite an input file", result.stderr)
            self.assertEqual(source.read_bytes(), original_source)
            self.assertEqual(later_input.read_bytes(), original_later)
            self.assertFalse((output / "shape.s.compressed.s.s1t.s").exists())

    def test_cli_multiple_files_rejects_hard_link_output_alias(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-hardlink-output-test-") as td:
            temp = Path(td)
            source = temp / "Source" / "shape.s"
            later_input = temp / "Inputs" / "other.s"
            output = temp / "Converted"
            source.parent.mkdir()
            later_input.parent.mkdir()
            output.mkdir()
            shutil.copy2(SYNTHETIC_COMPRESSED, source)
            shutil.copy2(SYNTHETIC_COMPRESSED, later_input)
            planned_output = output / "shape.s.s1t.s"
            try:
                os.link(later_input, planned_output)
            except OSError as exc:
                self.skipTest(f"hard links unavailable: {exc}")
            original = SYNTHETIC_COMPRESSED.read_bytes()

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "orzip.py"),
                    "text",
                    str(source),
                    str(later_input),
                    "-o",
                    str(output),
                    "--force",
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("same file as an input", result.stderr)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(later_input.read_bytes(), original)
            self.assertEqual(planned_output.read_bytes(), original)

    def test_cli_compress_uncompress_default_to_in_place(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-inplace-test-") as td:
            temp = Path(td)
            target = temp / "synthetic.s"
            shutil.copy2(SYNTHETIC_TEXT, target)
            original_text = target.read_bytes()

            subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "compress", str(target)],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            compressed_detection = orzip.detect_bytes(target.read_bytes())
            self.assertEqual(compressed_detection.kind, "compressed")
            self.assertEqual(compressed_detection.declared_length, len(SYNTHETIC_PAYLOAD))
            self.assertEqual(target.with_name(target.name + ".bak").read_bytes(), original_text)
            compressed_data = target.read_bytes()

            subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "uncompress", str(target)],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            roundtrip_text = orzip.decode_text_auto(target.read_bytes())
            self.assertIn("SIMISA@@@@@@@@@@JINX0s1t______", roundtrip_text)
            self.assertIn("point ( 1 2 3 )", roundtrip_text)
            self.assertEqual(target.with_name(target.name + ".bak.1").read_bytes(), compressed_data)

    def test_cli_convert_defaults_to_in_place(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-inplace-test-") as td:
            temp = Path(td)
            target = temp / "synthetic.s"
            shutil.copy2(SYNTHETIC_COMPRESSED, target)
            original_binary = target.read_bytes()

            subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "convert", str(target)],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            text = orzip.decode_text_auto(target.read_bytes())
            self.assertIn("SIMISA@@@@@@@@@@JINX0s1t______", text)
            self.assertIn("shape (", text)
            self.assertEqual(target.with_name(target.name + ".bak").read_bytes(), original_binary)
            converted_text = target.read_bytes()

            subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "convert", str(target)],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            detection = orzip.detect_bytes(target.read_bytes())
            self.assertEqual(detection.kind, "compressed")
            self.assertEqual(detection.declared_length, len(SYNTHETIC_PAYLOAD))
            self.assertEqual(target.with_name(target.name + ".bak.1").read_bytes(), converted_text)

    def test_cli_convert_no_backup_replaces_in_place_without_backup(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-no-backup-test-") as td:
            target = Path(td) / "synthetic.s"
            shutil.copy2(SYNTHETIC_COMPRESSED, target)

            subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "convert", str(target), "--no-backup"],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertIn("SIMISA@@@@@@@@@@JINX0s1t______", orzip.decode_text_auto(target.read_bytes()))
            self.assertFalse(target.with_name(target.name + ".bak").exists())

    def test_cli_convert_help_documents_no_backup(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "orzip.py"), "convert", "--help"],
            check=True,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        self.assertIn("--no-backup", result.stdout)
        self.assertIn("in-place", result.stdout)

    def test_cli_convert_auto_detects_binary_and_text_inputs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-convert-test-") as td:
            temp = Path(td)
            converted_text = temp / "synthetic-text.s"
            converted_binary = temp / "synthetic-binary.s"

            subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "convert", str(SYNTHETIC_COMPRESSED), "-o", str(converted_text)],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            text = orzip.decode_text_auto(converted_text.read_bytes())
            self.assertIn("SIMISA@@@@@@@@@@JINX0s1t______", text)
            self.assertIn("point ( 1 2 3 )", text)

            subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "convert", str(SYNTHETIC_TEXT), "-o", str(converted_binary)],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            detection = orzip.detect_bytes(converted_binary.read_bytes())
            self.assertEqual(detection.kind, "compressed")
            self.assertEqual(detection.declared_length, len(SYNTHETIC_PAYLOAD))

    def test_cli_validate_accepts_compressed_and_text_shape_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-validate-test-") as td:
            temp = Path(td)
            text_shape = temp / "synthetic-text.s"
            subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "convert", str(SYNTHETIC_COMPRESSED), "-o", str(text_shape)],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            compressed_result = subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "validate", str(SYNTHETIC_COMPRESSED)],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertIn("synthetic-compressed.s: OK", compressed_result.stdout)
            self.assertIn("kind: compressed", compressed_result.stdout)
            self.assertIn(f"declared payload: {len(SYNTHETIC_PAYLOAD)}", compressed_result.stdout)
            self.assertIn("root block: shape", compressed_result.stdout)
            self.assertIn("grammar decode: OK", compressed_result.stdout)

            text_result = subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "validate", str(text_shape)],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertIn("synthetic-text.s: OK", text_result.stdout)
            self.assertIn("kind: unicode-text", text_result.stdout)
            self.assertIn("root block: shape", text_result.stdout)
            self.assertIn("grammar encode: OK", text_result.stdout)

    def test_cli_validate_rejects_unsupported_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-validate-test-") as td:
            bad = Path(td) / "not_shape.txt"
            bad.write_text("not a SIMISA shape file", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "validate", str(bad)],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unsupported", result.stdout)

    def test_cli_validate_rejects_non_shape_root(self) -> None:
        point_text = "SIMISA@@@@@@@@@@JINX0s1t______\npoint ( 1 2 3 )\n"
        point_node = orzip.parse_s1t_text(point_text)
        point_payload = orzip.encode_s1t_node(point_node, orzip_defs)
        cases = {
            "point-text.s": orzip.UTF16LE_BOM + point_text.encode("utf-16le"),
            "point-binary.s": orzip.zlib_compress_container(point_payload),
        }

        with tempfile.TemporaryDirectory(prefix="orzip-root-test-") as td:
            for name, data in cases.items():
                with self.subTest(name=name):
                    path = Path(td) / name
                    path.write_bytes(data)
                    result = subprocess.run(
                        [sys.executable, str(ROOT / "orzip.py"), "check", str(path)],
                        cwd=ROOT,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )

                    self.assertEqual(result.returncode, 1)
                    self.assertIn("root block must be shape", result.stdout)

    def test_cli_roundtrip_reports_byte_exact_binary_payload(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "orzip.py"), "roundtrip", str(SYNTHETIC_COMPRESSED)],
            check=True,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        self.assertIn("synthetic-compressed.s: OK", result.stdout)
        self.assertIn("path: binary -> text -> binary", result.stdout)
        self.assertIn(f"original payload: {len(SYNTHETIC_PAYLOAD)} bytes", result.stdout)
        self.assertIn(f"roundtrip payload: {len(SYNTHETIC_PAYLOAD)} bytes", result.stdout)
        self.assertIn("payload match: byte-exact", result.stdout)
        self.assertIn("sha256:", result.stdout)

    def test_cli_roundtrip_reports_text_parseable(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "orzip.py"), "roundtrip", str(SYNTHETIC_TEXT)],
            check=True,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        self.assertIn("synthetic-text.s: OK", result.stdout)
        self.assertIn("path: text -> binary -> text", result.stdout)
        self.assertIn(f"binary payload: {len(SYNTHETIC_PAYLOAD)} bytes", result.stdout)
        self.assertIn("regenerated text: parseable", result.stdout)
        self.assertIn("note: text formatting may differ from input", result.stdout)

    def test_cli_validate_recursive_only_s_ignores_non_shape_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-folder-test-") as td:
            temp = Path(td)
            shapes = temp / "Shapes"
            nested = shapes / "Nested"
            nested.mkdir(parents=True)
            shutil.copy2(SYNTHETIC_COMPRESSED, shapes / "first.S")
            shutil.copy2(SYNTHETIC_COMPRESSED, nested / "second.s")
            (nested / "notes.txt").write_text("not a shape", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "validate", "-r", "--only-s", str(shapes)],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertIn("first.S: OK", result.stdout)
            self.assertIn("second.s: OK", result.stdout)
            self.assertNotIn("notes.txt", result.stdout)

    def test_cli_convert_recursive_only_s_mirrors_output_folder(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-folder-test-") as td:
            temp = Path(td)
            shapes = temp / "Shapes"
            nested = shapes / "Nested"
            out = temp / "Converted"
            nested.mkdir(parents=True)
            shutil.copy2(SYNTHETIC_COMPRESSED, shapes / "first.S")
            shutil.copy2(SYNTHETIC_COMPRESSED, nested / "second.s")
            (nested / "notes.txt").write_text("not a shape", encoding="utf-8")

            subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "convert", "-r", "--only-s", str(shapes), "-o", str(out)],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            first_text = out / "first.S.s1t.s"
            second_text = out / "Nested" / "second.s.s1t.s"
            self.assertTrue(first_text.exists())
            self.assertTrue(second_text.exists())
            self.assertFalse((out / "Nested" / "notes.txt.s1t.s").exists())
            self.assertIn("SIMISA@@@@@@@@@@JINX0s1t______", orzip.decode_text_auto(first_text.read_bytes()))
            self.assertIn("SIMISA@@@@@@@@@@JINX0s1t______", orzip.decode_text_auto(second_text.read_bytes()))

    def test_cli_text_directory_mirrors_output_folder(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-folder-output-test-") as td:
            temp = Path(td)
            shapes = temp / "Shapes"
            nested = shapes / "Nested"
            output = temp / "Text"
            nested.mkdir(parents=True)
            first = shapes / "first.s"
            second = nested / "second.S"
            shutil.copy2(SYNTHETIC_COMPRESSED, first)
            shutil.copy2(SYNTHETIC_COMPRESSED, second)
            (nested / "notes.txt").write_text("not a shape", encoding="utf-8")
            original = SYNTHETIC_COMPRESSED.read_bytes()

            subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "text", "-r", "-s", str(shapes), "-o", str(output)],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertEqual(first.read_bytes(), original)
            self.assertEqual(second.read_bytes(), original)
            self.assertIn("SIMISA@@@@@@@@@@JINX0s1t______", orzip.decode_text_auto((output / "first.s.s1t.s").read_bytes()))
            self.assertIn("SIMISA@@@@@@@@@@JINX0s1t______", orzip.decode_text_auto((output / "Nested" / "second.S.s1t.s").read_bytes()))
            self.assertFalse((output / "Nested" / "notes.txt.s1t.s").exists())

    def test_cli_binary_directory_mirrors_output_folder(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-folder-output-test-") as td:
            temp = Path(td)
            shapes = temp / "Shapes"
            nested = shapes / "Nested"
            output = temp / "Binary"
            nested.mkdir(parents=True)
            first = shapes / "first.s"
            second = nested / "second.S"
            shutil.copy2(SYNTHETIC_TEXT, first)
            shutil.copy2(SYNTHETIC_TEXT, second)
            (nested / "notes.txt").write_text("not a shape", encoding="utf-8")
            original = SYNTHETIC_TEXT.read_bytes()

            subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "binary", "-r", "-s", str(shapes), "-o", str(output)],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertEqual(first.read_bytes(), original)
            self.assertEqual(second.read_bytes(), original)
            self.assertEqual(orzip.detect_bytes((output / "first.s.compressed.s").read_bytes()).kind, "compressed")
            self.assertEqual(orzip.detect_bytes((output / "Nested" / "second.S.compressed.s").read_bytes()).kind, "compressed")
            self.assertFalse((output / "Nested" / "notes.txt.compressed.s").exists())

    def test_cli_directory_roots_reject_same_relative_output_before_writing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-folder-output-test-") as td:
            temp = Path(td)
            first_root = temp / "First"
            second_root = temp / "Second"
            output = temp / "Text"
            first_root.mkdir()
            second_root.mkdir()
            first = first_root / "shape.s"
            second = second_root / "shape.s"
            shutil.copy2(SYNTHETIC_COMPRESSED, first)
            shutil.copy2(SYNTHETIC_COMPRESSED, second)
            original = SYNTHETIC_COMPRESSED.read_bytes()

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "orzip.py"),
                    "text",
                    "-r",
                    "-s",
                    str(first_root),
                    str(second_root),
                    "-o",
                    str(output),
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("same output file", result.stderr)
            self.assertEqual(first.read_bytes(), original)
            self.assertEqual(second.read_bytes(), original)
            self.assertFalse(output.exists())

    def test_cli_directory_scan_excludes_nested_output_tree(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-folder-output-test-") as td:
            shapes = Path(td) / "Shapes"
            output = shapes / "Converted"
            output.mkdir(parents=True)
            source = shapes / "shape.s"
            prior_output = output / "prior.s"
            shutil.copy2(SYNTHETIC_COMPRESSED, source)
            shutil.copy2(SYNTHETIC_COMPRESSED, prior_output)
            original = SYNTHETIC_COMPRESSED.read_bytes()

            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "orzip.py"),
                    "text",
                    "-r",
                    "-s",
                    str(shapes),
                    "-o",
                    str(output),
                    "--force",
                ],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(prior_output.read_bytes(), original)
            self.assertIn("SIMISA@@@@@@@@@@JINX0s1t______", orzip.decode_text_auto((output / "shape.s.s1t.s").read_bytes()))
            self.assertFalse((output / "Converted" / "prior.s.s1t.s").exists())


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        SYNTHETIC_TEMP_DIR.cleanup()
        shutil.rmtree(ROOT / "__pycache__", ignore_errors=True)
