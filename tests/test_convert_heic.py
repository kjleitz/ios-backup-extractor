# Copyright (C) 2025 Keegan Leitz <kjleitz@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for extractors.convert_heic — standalone HEIC-to-JPEG conversion."""

import os
from unittest.mock import patch, MagicMock

from extractors.convert_heic import convert_folder, _update_references


def test_update_references_replaces_in_html_and_json(tmp_path):
    conv_folder = tmp_path / "conv1"
    conv_folder.mkdir()
    html = conv_folder / "conversation.html"
    json_ = conv_folder / "conversation.json"
    html.write_text('<img src="attachments/photo.heic">')
    json_.write_text('{"extracted_path": "attachments/photo.heic"}')

    _update_references(str(conv_folder), "photo.heic", "photo.jpg")

    assert "photo.jpg" in html.read_text()
    assert "photo.heic" not in html.read_text()
    assert "photo.jpg" in json_.read_text()
    assert "photo.heic" not in json_.read_text()


def test_update_references_no_file_is_fine(tmp_path):
    """Should not crash if conversation files don't exist."""
    _update_references(str(tmp_path), "photo.heic", "photo.jpg")


def test_convert_folder_finds_and_converts(tmp_path):
    """convert_folder should find .heic files and convert them."""
    # Set up a fake messages directory structure
    conv = tmp_path / "conv1"
    att = conv / "attachments"
    att.mkdir(parents=True)

    heic_file = att / "IMG_001.HEIC"
    heic_file.write_bytes(b"fake heic data")

    html = conv / "conversation.html"
    html.write_text('<img src="attachments/IMG_001.HEIC">')

    json_ = conv / "conversation.json"
    json_.write_text('{"extracted_path": "attachments/IMG_001.HEIC"}')

    def fake_sips(args, capture_output):
        # Simulate sips: create the jpg output
        # args = ['sips', '-s', 'format', 'jpeg', input, '--out', output]
        out_path = args[6]
        with open(out_path, 'wb') as f:
            f.write(b"fake jpeg data")
        return MagicMock(returncode=0)

    with patch('extractors.convert_heic.subprocess.run', side_effect=fake_sips):
        count = convert_folder(str(tmp_path))

    assert count == 1
    assert heic_file.exists()
    assert (att / "IMG_001.jpg").exists()
    assert "IMG_001.jpg" in html.read_text()
    assert "IMG_001.jpg" in json_.read_text()


def test_convert_folder_skips_non_heic(tmp_path):
    """Non-HEIC files should be left alone."""
    att = tmp_path / "conv1" / "attachments"
    att.mkdir(parents=True)
    (att / "photo.jpg").write_bytes(b"already jpeg")
    (att / "video.mp4").write_bytes(b"video data")

    with patch('extractors.convert_heic.subprocess.run') as mock_run:
        count = convert_folder(str(tmp_path))

    assert count == 0
    mock_run.assert_not_called()
