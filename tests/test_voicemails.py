# Copyright (C) 2025 Keegan Leitz <kjleitz@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for extractors/voicemails.py functions."""

import os
import plistlib
import tempfile

from extractors.voicemails import _parse_transcript, _escape


class TestParseTranscript:
    def test_returns_none_for_missing_file(self):
        assert _parse_transcript('/nonexistent/file.transcript') is None

    def test_returns_none_for_non_plist(self, tmp_path):
        f = tmp_path / 'bad.transcript'
        f.write_text('not a plist')
        assert _parse_transcript(str(f)) is None


class TestEscape:
    def test_html_entities(self):
        assert _escape('a & b') == 'a &amp; b'

    def test_angle_brackets(self):
        assert _escape('<script>') == '&lt;script&gt;'

    def test_none_returns_empty(self):
        assert _escape(None) == ''
