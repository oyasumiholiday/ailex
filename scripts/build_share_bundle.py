#!/usr/bin/env python3
"""Build the fixed, offline IntentIR notation-lab share bundle."""

from __future__ import annotations

import argparse
from email.parser import BytesParser
from email.policy import compat32
import hashlib
import io
from pathlib import Path, PurePosixPath
import stat
import sys
import zipfile


EXPECTED_WHEEL = "intentir-0.15.0a1-py3-none-any.whl"
EXPECTED_NAME = "intentir"
EXPECTED_VERSION = "0.15.0a1"
ROOT = Path(__file__).resolve().parents[1]
FIXED_FILES = (
    (ROOT / "docs" / "TRY_IT_JA.md", PurePosixPath("README_JA.md")),
    (
        ROOT / "examples" / "notation_lab" / "price.expr",
        PurePosixPath("examples/notation_lab/price.expr"),
    ),
    (
        ROOT / "examples" / "notation_lab" / "price.graph.json",
        PurePosixPath("examples/notation_lab/price.graph.json"),
    ),
    (
        ROOT / "examples" / "notation_lab" / "price.rows.json",
        PurePosixPath("examples/notation_lab/price.rows.json"),
    ),
    (ROOT / "LICENSE-APACHE", PurePosixPath("LICENSE-APACHE")),
)


class BundleError(ValueError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the IntentIR 0.15.0a1 offline notation-lab ZIP."
    )
    parser.add_argument("--wheel", required=True, type=Path, help="path to the release wheel")
    parser.add_argument("--output", required=True, type=Path, help="new ZIP path")
    return parser.parse_args()


def read_regular_file(path: Path, label: str) -> bytes:
    try:
        mode = path.stat().st_mode
    except OSError as error:
        raise BundleError(f"cannot read {label}: {path}: {error}") from error
    if not stat.S_ISREG(mode):
        raise BundleError(f"{label} must be a regular file: {path}")
    try:
        return path.read_bytes()
    except OSError as error:
        raise BundleError(f"cannot read {label}: {path}: {error}") from error


def validate_wheel(path: Path, wheel_bytes: bytes) -> None:
    if path.name != EXPECTED_WHEEL:
        raise BundleError(f"wheel filename must be exactly {EXPECTED_WHEEL}")
    try:
        with zipfile.ZipFile(io.BytesIO(wheel_bytes)) as wheel_zip:
            metadata_names = [
                name
                for name in wheel_zip.namelist()
                if name == "intentir-0.15.0a1.dist-info/METADATA"
            ]
            if metadata_names != ["intentir-0.15.0a1.dist-info/METADATA"]:
                raise BundleError("wheel must contain the expected 0.15.0a1 METADATA file")
            metadata = BytesParser(policy=compat32).parsebytes(
                wheel_zip.read(metadata_names[0])
            )
    except BundleError:
        raise
    except (OSError, KeyError, zipfile.BadZipFile) as error:
        raise BundleError(f"invalid wheel archive: {error}") from error
    if metadata.get("Name") != EXPECTED_NAME:
        raise BundleError(f"wheel metadata Name must be {EXPECTED_NAME}")
    if metadata.get("Version") != EXPECTED_VERSION:
        raise BundleError(f"wheel metadata Version must be {EXPECTED_VERSION}")
    if not wheel_bytes:
        raise BundleError("wheel must not be empty")


def zip_info(name: PurePosixPath) -> zipfile.ZipInfo:
    if name.is_absolute() or ".." in name.parts or "\\" in name.as_posix():
        raise BundleError(f"unsafe archive entry: {name}")
    info = zipfile.ZipInfo(name.as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def checksum_manifest(files: list[tuple[PurePosixPath, bytes]]) -> bytes:
    lines = [f"{hashlib.sha256(data).hexdigest()}  {name.as_posix()}" for name, data in files]
    return ("\n".join(lines) + "\n").encode("utf-8")


def build_bundle(wheel: Path, output: Path) -> None:
    if output.suffix.lower() != ".zip":
        raise BundleError("output path must end in .zip")
    if output.exists():
        raise BundleError(f"refusing to overwrite existing output: {output}")
    if not output.parent.is_dir():
        raise BundleError(f"output directory does not exist: {output.parent}")

    wheel_bytes = read_regular_file(wheel, "wheel")
    validate_wheel(wheel, wheel_bytes)
    payload: list[tuple[PurePosixPath, bytes]] = [
        (PurePosixPath(EXPECTED_WHEEL), wheel_bytes)
    ]
    payload.extend((archive_name, read_regular_file(path, "bundle input")) for path, archive_name in FIXED_FILES)
    names = [name.as_posix() for name, _ in payload]
    if len(names) != len(set(names)):
        raise BundleError("duplicate archive entry")
    manifest = checksum_manifest(payload)

    created = False
    try:
        with output.open("x+b") as handle:
            created = True
            with zipfile.ZipFile(handle, mode="w") as bundle:
                for name, data in payload:
                    bundle.writestr(zip_info(name), data)
                bundle.writestr(zip_info(PurePosixPath("SHA256SUMS")), manifest)
    except FileExistsError as error:
        raise BundleError(f"refusing to overwrite existing output: {output}") from error
    except Exception:
        if created:
            output.unlink(missing_ok=True)
        raise


def main() -> int:
    args = parse_args()
    try:
        build_bundle(args.wheel, args.output)
    except BundleError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
