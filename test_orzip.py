#!/usr/bin/env python
"""Regression tests for ORZIP using the sample files in this folder."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

import orzip

ROOT = Path(__file__).resolve().parent
SAMPLE_ROOT = ROOT if (ROOT / "comp_csx9550.s").exists() else ROOT.parent.parent
COMP_CSX = SAMPLE_ROOT / "comp_csx9550.s"
TEXT_CSX = SAMPLE_ROOT / "csx9550.s"
DASH8_COMP = SAMPLE_ROOT / "FFEDIT" / "dash8.s"
DASH8_TEXT = SAMPLE_ROOT / "FFEDIT" / "dash8u.s"
ACL_WAGON_COMP = SAMPLE_ROOT / "ACL66320.s"
DEPOT_SCENERY_COMP = SAMPLE_ROOT / "DEPOT.S"
CR_GP38_COMPLEX_COMP = SAMPLE_ROOT / "CR_GP38-2_8270.s"


class ORZIPRegressionTests(unittest.TestCase):
    def test_detect_and_verify_known_compressed_files(self) -> None:
        for path, expected_size in [(COMP_CSX, 671_102), (DASH8_COMP, 3_440_900)]:
            data = path.read_bytes()
            detection = orzip.detect_bytes(data)
            self.assertEqual(detection.kind, "compressed")
            payload = orzip.zlib_decompress_container(data)
            self.assertEqual(len(payload), expected_size)
            self.assertTrue(payload.startswith(b"JINX0s1b______\r\n"))

    def test_text_csx_encodes_to_original_binary_payload_byte_for_byte(self) -> None:
        import orzip_defs

        expected_payload = orzip.zlib_decompress_container(COMP_CSX.read_bytes())
        root = orzip.parse_s1t_text(orzip.decode_text_auto(TEXT_CSX.read_bytes()))
        actual_payload = orzip.encode_s1t_node(root, orzip_defs)

        self.assertEqual(hashlib.sha256(actual_payload).hexdigest(), hashlib.sha256(expected_payload).hexdigest())
        self.assertEqual(actual_payload, expected_payload)

    def test_binary_csx_renders_text_containing_known_shape_values(self) -> None:
        import orzip_defs

        payload = orzip.zlib_decompress_container(COMP_CSX.read_bytes())
        rendered = orzip.render_s1t_from_payload(payload, orzip_defs)

        self.assertIn("SIMISA@@@@@@@@@@JINX0s1t______", rendered)
        self.assertIn("point ( -1.51227999 0.43541801 -7.89935017 )", rendered)
        self.assertIn("named_shader ( TexDiff )", rendered)
        self.assertIn("named_filter_mode ( MipLinear )", rendered)
        self.assertIn("lod_controls (", rendered)

    def test_dash8_text_compresses_to_valid_binary_container(self) -> None:
        import orzip_defs

        root = orzip.parse_s1t_text(orzip.decode_text_auto(DASH8_TEXT.read_bytes()))
        payload = orzip.encode_s1t_node(root, orzip_defs)
        compressed = orzip.zlib_compress_container(payload)

        detection = orzip.detect_bytes(compressed)
        self.assertEqual(detection.kind, "compressed")
        self.assertEqual(detection.declared_length, 3_440_900)
        self.assertEqual(len(orzip.zlib_decompress_container(compressed)), 3_440_900)

    def test_acl66320_wagon_shape_binary_text_binary_is_byte_exact(self) -> None:
        import orzip_defs

        original_payload = orzip.zlib_decompress_container(ACL_WAGON_COMP.read_bytes())
        rendered = orzip.render_s1t_from_payload(original_payload, orzip_defs)
        root = orzip.parse_s1t_text(rendered)
        roundtrip_payload = orzip.encode_s1t_node(root, orzip_defs)

        self.assertEqual(len(original_payload), 1_313_974)
        self.assertIn("shape (", rendered)
        self.assertIn("points (", rendered)
        self.assertIn("lod_controls (", rendered)
        self.assertEqual(roundtrip_payload, original_payload)

    def test_depot_scenery_shape_binary_text_binary_is_byte_exact(self) -> None:
        import orzip_defs

        original_payload = orzip.zlib_decompress_container(DEPOT_SCENERY_COMP.read_bytes())
        rendered = orzip.render_s1t_from_payload(original_payload, orzip_defs)
        root = orzip.parse_s1t_text(rendered)
        roundtrip_payload = orzip.encode_s1t_node(root, orzip_defs)

        self.assertEqual(len(original_payload), 54_161)
        self.assertIn("shape (", rendered)
        self.assertIn("points (", rendered)
        self.assertIn("images (", rendered)
        self.assertIn("textures (", rendered)
        self.assertIn("lod_controls (", rendered)
        self.assertEqual(roundtrip_payload, original_payload)

    def test_cr_gp38_complex_shape_binary_text_binary_is_byte_exact(self) -> None:
        import orzip_defs

        original_payload = orzip.zlib_decompress_container(CR_GP38_COMPLEX_COMP.read_bytes())
        rendered = orzip.render_s1t_from_payload(original_payload, orzip_defs)
        root = orzip.parse_s1t_text(rendered)
        roundtrip_payload = orzip.encode_s1t_node(root, orzip_defs)

        self.assertEqual(len(original_payload), 5_757_584)
        self.assertIn("shape (", rendered)
        self.assertIn("points (", rendered)
        self.assertIn("matrices (", rendered)
        self.assertIn("images (", rendered)
        self.assertIn("textures (", rendered)
        self.assertIn("lod_controls (", rendered)
        self.assertEqual(roundtrip_payload, original_payload)

    def test_cli_compress_text_then_decompress_text_smoke(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-test-") as td:
            temp = Path(td)
            compressed = temp / "csx_from_text.s"
            text_roundtrip = temp / "csx_roundtrip.s"

            subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "compress-text", str(TEXT_CSX), "-o", str(compressed)],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "decompress-text", str(compressed), "-o", str(text_roundtrip)],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            roundtrip_text = orzip.decode_text_auto(text_roundtrip.read_bytes())
            self.assertIn("point ( -1.51227999 0.43541801 -7.89935017 )", roundtrip_text)
            self.assertIn("named_shader ( TexDiff )", roundtrip_text)

    def test_cli_compress_and_uncompress_aliases(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-test-") as td:
            temp = Path(td)
            compressed = temp / "csx_from_text.s"
            text_roundtrip = temp / "csx_roundtrip.s"

            subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "compress", str(TEXT_CSX), "-o", str(compressed)],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            detection = orzip.detect_bytes(compressed.read_bytes())
            self.assertEqual(detection.kind, "compressed")
            self.assertEqual(detection.declared_length, 671_102)

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
            self.assertIn("named_shader ( TexDiff )", roundtrip_text)

    def test_cli_compress_uncompress_default_to_in_place(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-inplace-test-") as td:
            temp = Path(td)
            target = temp / "csx9550.s"
            shutil.copy2(TEXT_CSX, target)

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
            self.assertEqual(compressed_detection.declared_length, 671_102)

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
            self.assertIn("named_shader ( TexDiff )", roundtrip_text)

    def test_cli_convert_defaults_to_in_place(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-inplace-test-") as td:
            temp = Path(td)
            target = temp / "DEPOT.S"
            shutil.copy2(DEPOT_SCENERY_COMP, target)

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
            self.assertEqual(detection.declared_length, 54_161)

    def test_cli_convert_auto_detects_binary_and_text_inputs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-convert-test-") as td:
            temp = Path(td)
            converted_text = temp / "csx_text.s"
            converted_binary = temp / "csx_binary.s"

            subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "convert", str(COMP_CSX), "-o", str(converted_text)],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            text = orzip.decode_text_auto(converted_text.read_bytes())
            self.assertIn("SIMISA@@@@@@@@@@JINX0s1t______", text)
            self.assertIn("point ( -1.51227999 0.43541801 -7.89935017 )", text)

            subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "convert", str(TEXT_CSX), "-o", str(converted_binary)],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            detection = orzip.detect_bytes(converted_binary.read_bytes())
            self.assertEqual(detection.kind, "compressed")
            self.assertEqual(detection.declared_length, 671_102)

    def test_cli_validate_accepts_compressed_and_text_shape_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-validate-test-") as td:
            temp = Path(td)
            text_shape = temp / "csx_text.s"
            subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "convert", str(COMP_CSX), "-o", str(text_shape)],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            compressed_result = subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "validate", str(COMP_CSX)],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertIn("comp_csx9550.s: OK", compressed_result.stdout)
            self.assertIn("kind: compressed", compressed_result.stdout)
            self.assertIn("declared payload: 671102", compressed_result.stdout)
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
            self.assertIn("csx_text.s: OK", text_result.stdout)
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

    def test_cli_roundtrip_reports_byte_exact_binary_payload(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "orzip.py"), "roundtrip", str(COMP_CSX)],
            check=True,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        self.assertIn("comp_csx9550.s: OK", result.stdout)
        self.assertIn("path: binary -> text -> binary", result.stdout)
        self.assertIn("original payload: 671102 bytes", result.stdout)
        self.assertIn("roundtrip payload: 671102 bytes", result.stdout)
        self.assertIn("payload match: byte-exact", result.stdout)
        self.assertIn("sha256: 3ae9a6a96dff0d3ce0afb8c5dc03523b80afb0886970107573f2eec16768d621", result.stdout)

    def test_cli_roundtrip_reports_text_parseable(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "orzip.py"), "roundtrip", str(TEXT_CSX)],
            check=True,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        self.assertIn("csx9550.s: OK", result.stdout)
        self.assertIn("path: text -> binary -> text", result.stdout)
        self.assertIn("binary payload: 671102 bytes", result.stdout)
        self.assertIn("regenerated text: parseable", result.stdout)
        self.assertIn("note: text formatting may differ from input", result.stdout)

    def test_cli_validate_recursive_only_s_ignores_non_shape_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-folder-test-") as td:
            temp = Path(td)
            shapes = temp / "Shapes"
            nested = shapes / "Nested"
            nested.mkdir(parents=True)
            shutil.copy2(DEPOT_SCENERY_COMP, shapes / "DEPOT.S")
            shutil.copy2(ACL_WAGON_COMP, nested / "ACL66320.s")
            (nested / "notes.txt").write_text("not a shape", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "validate", "-r", "--only-s", str(shapes)],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertIn("DEPOT.S: OK", result.stdout)
            self.assertIn("ACL66320.s: OK", result.stdout)
            self.assertNotIn("notes.txt", result.stdout)

    def test_cli_convert_recursive_only_s_mirrors_output_folder(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orzip-folder-test-") as td:
            temp = Path(td)
            shapes = temp / "Shapes"
            nested = shapes / "Nested"
            out = temp / "Converted"
            nested.mkdir(parents=True)
            shutil.copy2(DEPOT_SCENERY_COMP, shapes / "DEPOT.S")
            shutil.copy2(ACL_WAGON_COMP, nested / "ACL66320.s")
            (nested / "notes.txt").write_text("not a shape", encoding="utf-8")

            subprocess.run(
                [sys.executable, str(ROOT / "orzip.py"), "convert", "-r", "--only-s", str(shapes), "-o", str(out)],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            depot_text = out / "DEPOT.S.s1t.s"
            wagon_text = out / "Nested" / "ACL66320.s.s1t.s"
            self.assertTrue(depot_text.exists())
            self.assertTrue(wagon_text.exists())
            self.assertFalse((out / "Nested" / "notes.txt.s1t.s").exists())
            self.assertIn("SIMISA@@@@@@@@@@JINX0s1t______", orzip.decode_text_auto(depot_text.read_bytes()))
            self.assertIn("SIMISA@@@@@@@@@@JINX0s1t______", orzip.decode_text_auto(wagon_text.read_bytes()))


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        shutil.rmtree(ROOT / "__pycache__", ignore_errors=True)
