# Copyright (C) 2025 Keegan Leitz <kjleitz@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for extractors/contacts.py pure functions."""

from extractors.contacts import _normalize_phone, _sanitize_folder, _escape


class TestNormalizePhone:
    def test_ten_digit_assumes_us(self):
        assert _normalize_phone('(617) 869-1134') == '+16178691134'

    def test_eleven_digit_with_country_code(self):
        assert _normalize_phone('+1 617 869 1134') == '+16178691134'

    def test_already_clean(self):
        assert _normalize_phone('16178691134') == '+16178691134'

    def test_dashes_and_dots(self):
        assert _normalize_phone('617-869-1134') == '+16178691134'

    def test_international(self):
        assert _normalize_phone('+44 20 7946 0958') == '+442079460958'


class TestSanitizeFolder:
    def test_phone_number(self):
        assert _sanitize_folder('+16178691134') == '+16178691134'

    def test_email(self):
        assert _sanitize_folder('user@example.com') == 'user@example.com'

    def test_special_chars(self):
        assert _sanitize_folder('hello world/foo') == 'hello_world_foo'

    def test_already_clean(self):
        assert _sanitize_folder('abc-123') == 'abc-123'


class TestEscape:
    def test_ampersand(self):
        assert _escape('a & b') == 'a &amp; b'

    def test_angle_brackets(self):
        assert _escape('<script>') == '&lt;script&gt;'

    def test_none_returns_empty(self):
        assert _escape(None) == ''

    def test_empty_returns_empty(self):
        assert _escape('') == ''
