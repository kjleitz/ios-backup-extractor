# Copyright (C) 2025 Keegan Leitz <kjleitz@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for extractors/_contacts.py shared index module."""

import json
import os
import tempfile

from extractors._contacts import load_index, contact_link


class TestLoadIndex:
    def test_returns_empty_for_none(self):
        assert load_index(None) == {}

    def test_returns_empty_for_missing_folder(self):
        assert load_index('/nonexistent/path') == {}

    def test_indexes_by_phone(self, tmp_path):
        contacts = [{
            'id': 1,
            'name': 'John Doe',
            'phones': [{'normalized': '+16175551234', 'number': '(617) 555-1234', 'label': ''}],
            'emails': [],
            'message_identifiers': ['+16175551234'],
        }]
        with open(tmp_path / 'contacts.json', 'w') as f:
            json.dump(contacts, f)

        index = load_index(str(tmp_path))
        assert '+16175551234' in index
        assert index['+16175551234']['contact']['name'] == 'John Doe'

    def test_indexes_by_email(self, tmp_path):
        contacts = [{
            'id': 2,
            'name': 'Jane',
            'phones': [],
            'emails': [{'email': 'jane@example.com', 'label': ''}],
            'message_identifiers': ['jane@example.com'],
        }]
        with open(tmp_path / 'contacts.json', 'w') as f:
            json.dump(contacts, f)

        index = load_index(str(tmp_path))
        assert 'jane@example.com' in index

    def test_first_match_wins(self, tmp_path):
        contacts = [
            {
                'id': 1, 'name': 'Alice',
                'phones': [{'normalized': '+15555555555', 'number': '', 'label': ''}],
                'emails': [],
                'message_identifiers': ['+15555555555'],
            },
            {
                'id': 2, 'name': 'Bob',
                'phones': [{'normalized': '+15555555555', 'number': '', 'label': ''}],
                'emails': [],
                'message_identifiers': ['+15555555555'],
            },
        ]
        with open(tmp_path / 'contacts.json', 'w') as f:
            json.dump(contacts, f)

        index = load_index(str(tmp_path))
        assert index['+15555555555']['contact']['name'] == 'Alice'


class TestContactLink:
    def test_relative_path(self, tmp_path):
        contacts_dir = tmp_path / 'contacts'
        messages_dir = tmp_path / 'messages'
        contacts_dir.mkdir()
        messages_dir.mkdir()

        entry = {'key': '+16175551234'}
        link = contact_link(str(contacts_dir), entry, str(messages_dir))
        assert link == os.path.join('..', 'contacts', '+16175551234', 'contact.html')

    def test_same_parent(self, tmp_path):
        entry = {'key': 'foo'}
        link = contact_link(str(tmp_path / 'contacts'), entry, str(tmp_path / 'messages'))
        assert '../contacts/foo/contact.html' == link
