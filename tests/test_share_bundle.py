import hashlib
import io
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path

from scripts.build_share_bundle import (
    BundleError,
    EXPECTED_METADATA,
    EXPECTED_VERSION,
    EXPECTED_WHEEL,
    FIXED_FILES,
    build_bundle,
)


def wheel_bytes(
    *, name: str = "intentir", version: str = EXPECTED_VERSION, duplicate: bool = False
) -> bytes:
    output = io.BytesIO()
    metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n\n"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr(EXPECTED_METADATA, metadata)
            if duplicate:
                archive.writestr(EXPECTED_METADATA, metadata)
    return output.getvalue()


class ShareBundleTest(unittest.TestCase):
    def write_wheel(self, root: Path, data: bytes, name: str = EXPECTED_WHEEL) -> Path:
        wheel = root / name
        wheel.write_bytes(data)
        return wheel

    def test_rejects_filename_name_and_version_mismatches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = (
                ("wrong.whl", wheel_bytes(), "filename"),
                (EXPECTED_WHEEL, wheel_bytes(name="other"), "Name"),
                (EXPECTED_WHEEL, wheel_bytes(version="9.9"), "Version"),
            )
            for index, (filename, data, message) in enumerate(cases):
                with self.subTest(message=message):
                    wheel = self.write_wheel(root, data, filename)
                    with self.assertRaisesRegex(BundleError, message):
                        build_bundle(wheel, root / f"output-{index}.zip")
                    wheel.unlink()

    def test_rejects_corrupt_wheel_and_duplicate_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wheel = self.write_wheel(root, b"not a zip")
            with self.assertRaisesRegex(BundleError, "invalid wheel archive"):
                build_bundle(wheel, root / "corrupt.zip")
            wheel.write_bytes(wheel_bytes(duplicate=True))
            with self.assertRaisesRegex(BundleError, "exactly one"):
                build_bundle(wheel, root / "duplicate.zip")

    def test_existing_output_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wheel = self.write_wheel(root, wheel_bytes())
            output = root / "preview.zip"
            output.write_bytes(b"keep")
            with self.assertRaisesRegex(BundleError, "refusing to overwrite"):
                build_bundle(wheel, output)
            self.assertEqual(output.read_bytes(), b"keep")

    def test_fixed_entries_checksums_and_determinism(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wheel = self.write_wheel(root, wheel_bytes())
            first = root / "first.zip"
            second = root / "second.zip"
            build_bundle(wheel, first)
            build_bundle(wheel, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())

            expected_names = [EXPECTED_WHEEL]
            expected_names.extend(name.as_posix() for _, name in FIXED_FILES)
            expected_names.append("SHA256SUMS")
            with zipfile.ZipFile(first) as archive:
                self.assertEqual(archive.namelist(), expected_names)
                manifest = archive.read("SHA256SUMS").decode("utf-8")
                expected_lines = []
                for name in expected_names[:-1]:
                    digest = hashlib.sha256(archive.read(name)).hexdigest()
                    expected_lines.append(f"{digest}  {name}")
                self.assertEqual(manifest, "\n".join(expected_lines) + "\n")

    def test_guide_references_expected_wheel(self) -> None:
        guide_path = next(
            path for path, name in FIXED_FILES if name.as_posix() == "README_JA.md"
        )
        guide = guide_path.read_text(encoding="utf-8")
        self.assertIn(EXPECTED_WHEEL, guide)


if __name__ == "__main__":
    unittest.main()
