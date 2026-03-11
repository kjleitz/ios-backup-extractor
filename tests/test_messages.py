"""Tests for extractors/messages.py pure functions and conversation loading."""

import sqlite3
from datetime import datetime

from extractors.messages import (
    _apple_ts,
    _sanitize_folder,
    _attachment_relative_path,
    _escape,
    _format_date,
    _format_time,
    _load_conversations,
)

_APPLE_EPOCH_OFFSET = 978307200


class TestAppleTs:
    def test_none_returns_none(self):
        assert _apple_ts(None) is None

    def test_zero_returns_none(self):
        assert _apple_ts(0) is None

    def test_seconds_since_2001(self):
        # Apple timestamp 0 = 2001-01-01 00:00:00 UTC = Unix 978307200
        # Use a known offset: Apple ts=0 → datetime(2001, 1, 1) in UTC
        # Just check it produces a reasonable datetime
        ts = 699321600
        dt = _apple_ts(ts)
        assert dt.year == 2023
        assert isinstance(dt, datetime)

    def test_nanoseconds_since_2001(self):
        ts_sec = 699321600
        ts_ns = ts_sec * 1_000_000_000
        dt_sec = _apple_ts(ts_sec)
        dt_ns = _apple_ts(ts_ns)
        # Both should produce the same datetime
        assert dt_sec == dt_ns


class TestSanitizeFolder:
    def test_phone(self):
        assert _sanitize_folder('+16178691134') == '+16178691134'

    def test_spaces(self):
        assert _sanitize_folder('hello world') == 'hello_world'


class TestAttachmentRelativePath:
    def test_tilde_prefix(self):
        assert _attachment_relative_path('~/Library/SMS/Attachments/foo.jpg') == \
            'Library/SMS/Attachments/foo.jpg'

    def test_none(self):
        assert _attachment_relative_path(None) is None

    def test_no_tilde(self):
        assert _attachment_relative_path('Library/foo.jpg') == 'Library/foo.jpg'


class TestEscape:
    def test_html_entities(self):
        assert _escape('a < b & c > d') == 'a &lt; b &amp; c &gt; d'


class TestFormatDate:
    def test_basic(self):
        result = _format_date('2023-03-01T14:30:00')
        assert '2023' in result
        assert 'March' in result

    def test_no_leading_zero(self):
        result = _format_date('2023-03-01T00:00:00')
        # Should not have " 01" — should have " 1"
        assert ' 01' not in result or ' 1,' in result


class TestFormatTime:
    def test_pm(self):
        result = _format_time('2023-03-01T14:30:00')
        assert '2:30 PM' in result

    def test_am_no_leading_zero(self):
        result = _format_time('2023-03-01T09:05:00')
        assert '9:05 AM' in result


class TestLoadConversations:
    """Test _load_conversations with an in-memory sms.db."""

    @staticmethod
    def _make_db():
        db = sqlite3.connect(':memory:')
        db.row_factory = sqlite3.Row
        db.executescript("""
            CREATE TABLE chat (
                ROWID INTEGER PRIMARY KEY,
                guid TEXT,
                chat_identifier TEXT,
                display_name TEXT,
                service_name TEXT
            );
            CREATE TABLE handle (
                ROWID INTEGER PRIMARY KEY,
                id TEXT
            );
            CREATE TABLE chat_handle_join (
                chat_id INTEGER,
                handle_id INTEGER
            );
            CREATE TABLE message (
                ROWID INTEGER PRIMARY KEY,
                guid TEXT,
                text TEXT,
                date INTEGER,
                is_from_me INTEGER,
                service TEXT,
                handle_id INTEGER,
                associated_message_guid TEXT,
                associated_message_type INTEGER,
                reply_to_guid TEXT
            );
            CREATE TABLE chat_message_join (
                chat_id INTEGER,
                message_id INTEGER
            );
            CREATE TABLE attachment (
                ROWID INTEGER PRIMARY KEY,
                guid TEXT,
                filename TEXT,
                mime_type TEXT,
                total_bytes INTEGER,
                transfer_name TEXT
            );
            CREATE TABLE message_attachment_join (
                message_id INTEGER,
                attachment_id INTEGER
            );
        """)
        return db

    def test_single_chat(self):
        db = self._make_db()
        db.execute("INSERT INTO handle VALUES (1, '+16175551234')")
        db.execute("INSERT INTO chat VALUES (1, 'g1', '+16175551234', NULL, 'iMessage')")
        db.execute("INSERT INTO chat_handle_join VALUES (1, 1)")
        db.execute("INSERT INTO message VALUES (1, 'msg1', 'hello', 100, 0, 'iMessage', 1, NULL, 0, NULL)")
        db.execute("INSERT INTO chat_message_join VALUES (1, 1)")

        convs = _load_conversations(db)
        assert len(convs) == 1
        assert convs[0]['identifier'] == '+16175551234'
        assert len(convs[0]['messages']) == 1
        assert convs[0]['messages'][0]['text'] == 'hello'

    def test_merge_duplicate_chats(self):
        """Two chat rows with the same identifier should merge into one conversation."""
        db = self._make_db()
        db.execute("INSERT INTO handle VALUES (1, '+16175551234')")
        db.execute("INSERT INTO chat VALUES (1, 'g1', '+16175551234', NULL, 'SMS')")
        db.execute("INSERT INTO chat VALUES (2, 'g2', '+16175551234', NULL, 'iMessage')")
        db.execute("INSERT INTO chat_handle_join VALUES (1, 1)")
        db.execute("INSERT INTO chat_handle_join VALUES (2, 1)")
        db.execute("INSERT INTO message VALUES (1, 'msg1', 'sms msg', 50, 0, 'SMS', 1, NULL, 0, NULL)")
        db.execute("INSERT INTO message VALUES (2, 'msg2', 'imsg', 100, 0, 'iMessage', 1, NULL, 0, NULL)")
        db.execute("INSERT INTO chat_message_join VALUES (1, 1)")
        db.execute("INSERT INTO chat_message_join VALUES (2, 2)")

        convs = _load_conversations(db)
        assert len(convs) == 1
        assert len(convs[0]['messages']) == 2
        # Should be sorted by date
        assert convs[0]['messages'][0]['text'] == 'sms msg'
        assert convs[0]['messages'][1]['text'] == 'imsg'

    def test_display_name_preserved(self):
        db = self._make_db()
        db.execute("INSERT INTO handle VALUES (1, '+16175551234')")
        db.execute("INSERT INTO chat VALUES (1, 'g1', '+16175551234', 'Dad', 'iMessage')")
        db.execute("INSERT INTO chat_handle_join VALUES (1, 1)")
        db.execute("INSERT INTO message VALUES (1, 'msg1', 'hi', 100, 1, 'iMessage', 1, NULL, 0, NULL)")
        db.execute("INSERT INTO chat_message_join VALUES (1, 1)")

        convs = _load_conversations(db)
        assert convs[0]['display_name'] == 'Dad'

    def test_is_from_me(self):
        db = self._make_db()
        db.execute("INSERT INTO handle VALUES (1, '+16175551234')")
        db.execute("INSERT INTO chat VALUES (1, 'g1', '+16175551234', NULL, 'iMessage')")
        db.execute("INSERT INTO chat_handle_join VALUES (1, 1)")
        db.execute("INSERT INTO message VALUES (1, 'msg1', 'sent', 100, 1, 'iMessage', 1, NULL, 0, NULL)")
        db.execute("INSERT INTO chat_message_join VALUES (1, 1)")

        convs = _load_conversations(db)
        msg = convs[0]['messages'][0]
        assert msg['is_from_me'] is True
        assert msg['sender'] == 'me'

    def test_empty_db(self):
        db = self._make_db()
        convs = _load_conversations(db)
        assert convs == []
