"""Tests for extractors.all — the unified extract-everything entry point."""

import os
from unittest.mock import MagicMock, patch

from extractors.all import extract


def test_extract_calls_all_extractors_in_order(tmp_path):
    """extract() should call contacts, messages, and voicemails extractors."""
    backup = MagicMock()
    target = str(tmp_path / 'out')

    call_order = []

    def fake_contacts(b, folder):
        call_order.append('contacts')
        assert b is backup
        assert folder == os.path.join(target, 'contacts')
        return [{'name': 'Alice'}]

    def fake_messages(b, folder, convert_heic, contacts_folder):
        call_order.append('messages')
        assert b is backup
        assert folder == os.path.join(target, 'messages')
        assert convert_heic is True
        assert contacts_folder == os.path.join(target, 'contacts')
        return [{'id': 'conv1'}]

    def fake_voicemails(b, folder, contacts_folder):
        call_order.append('voicemails')
        assert b is backup
        assert folder == os.path.join(target, 'voicemails')
        assert contacts_folder == os.path.join(target, 'contacts')
        return [{'id': 'vm1'}, {'id': 'vm2'}]

    with patch('extractors.all.contacts.extract', side_effect=fake_contacts), \
         patch('extractors.all.messages.extract', side_effect=fake_messages), \
         patch('extractors.all.voicemails.extract', side_effect=fake_voicemails):
        results = extract(backup, target)

    assert call_order == ['contacts', 'messages', 'voicemails']
    assert len(results['contacts']) == 1
    assert len(results['messages']) == 1
    assert len(results['voicemails']) == 2


def test_extract_passes_convert_heic_false(tmp_path):
    """When convert_heic=False, it should be forwarded to messages.extract."""
    backup = MagicMock()
    target = str(tmp_path / 'out')

    captured = {}

    def fake_messages(b, folder, convert_heic, contacts_folder):
        captured['convert_heic'] = convert_heic
        return []

    with patch('extractors.all.contacts.extract', return_value=[]), \
         patch('extractors.all.messages.extract', side_effect=fake_messages), \
         patch('extractors.all.voicemails.extract', return_value=[]):
        extract(backup, target, convert_heic=False)

    assert captured['convert_heic'] is False


def test_extract_default_convert_heic_is_true(tmp_path):
    """HEIC conversion should be on by default in the all-in-one extractor."""
    backup = MagicMock()
    target = str(tmp_path / 'out')

    captured = {}

    def fake_messages(b, folder, convert_heic, contacts_folder):
        captured['convert_heic'] = convert_heic
        return []

    with patch('extractors.all.contacts.extract', return_value=[]), \
         patch('extractors.all.messages.extract', side_effect=fake_messages), \
         patch('extractors.all.voicemails.extract', return_value=[]):
        extract(backup, target)

    assert captured['convert_heic'] is True
