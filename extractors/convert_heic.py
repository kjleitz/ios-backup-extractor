# Copyright (C) 2025 Keegan Leitz <kjleitz@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

#!/usr/bin/env python3
"""
Convert HEIC/HEIF files to JPEG in an already-extracted messages folder.

Walks the output directory, converts any .heic/.heif files using macOS sips,
and updates references in conversation.html and conversation.json files.

Usage:
    python extractors/convert_heic.py <messages_folder>
    python extractors/convert_heic.py backup_export/messages
"""

import argparse
import os
import re
import subprocess
import sys

_HEIC_EXTENSIONS = {'.heic', '.heif'}


def _convert_heic(path: str) -> str | None:
    """Convert a HEIC/HEIF file to JPEG using macOS sips.

    Returns the new path on success, or None if conversion failed.
    """
    jpeg_path = os.path.splitext(path)[0] + '.jpg'
    try:
        result = subprocess.run(
            ['sips', '-s', 'format', 'jpeg', path, '--out', jpeg_path],
            capture_output=True,
        )
        if result.returncode == 0:
            return jpeg_path
    except FileNotFoundError:
        print("Error: sips not found. This requires macOS.", file=sys.stderr)
        sys.exit(1)
    return None


def _update_references(folder: str, old_name: str, new_name: str) -> None:
    """Replace old_name with new_name in conversation.html and conversation.json."""
    for filename in ('conversation.html', 'conversation.json'):
        filepath = os.path.join(folder, filename)
        if not os.path.exists(filepath):
            continue
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        updated = content.replace(old_name, new_name)
        if updated != content:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(updated)


def convert_folder(messages_folder: str) -> int:
    """Convert all HEIC/HEIF files under messages_folder to JPEG.

    Returns the number of files converted.
    """
    converted = 0

    for dirpath, _dirnames, filenames in os.walk(messages_folder):
        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in _HEIC_EXTENSIONS:
                continue

            full_path = os.path.join(dirpath, filename)
            new_path = _convert_heic(full_path)
            if new_path is None:
                print(f"  FAILED: {full_path}")
                continue

            new_name = os.path.basename(new_path)
            # Update references in the conversation folder (parent of attachments/)
            conv_folder = os.path.dirname(dirpath)
            if os.path.basename(dirpath) == 'attachments':
                _update_references(conv_folder, filename, new_name)
            else:
                _update_references(dirpath, filename, new_name)

            converted += 1
            print(f"  {filename} -> {new_name}")

    return converted


def main():
    parser = argparse.ArgumentParser(
        description="Convert HEIC/HEIF files to JPEG in an extracted messages folder.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('folder', help='Path to the extracted messages folder')
    args = parser.parse_args()

    if not os.path.isdir(args.folder):
        print(f"Error: {args.folder} is not a directory", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning {args.folder} for HEIC/HEIF files...")
    count = convert_folder(args.folder)
    if count:
        print(f"\nConverted {count} file(s).")
    else:
        print("No HEIC/HEIF files found.")


if __name__ == '__main__':
    main()
