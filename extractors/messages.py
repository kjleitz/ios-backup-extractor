#!/usr/bin/env python3
"""
Extract iMessages and SMS from an iOS backup.

Output structure:
    <output>/
        index.html                  — conversation list
        <identifier>/
            conversation.json       — raw data (text, metadata, attachment paths)
            conversation.html       — self-contained viewer
            attachments/
                <filename>          — decrypted media files

Usage:
    python extractors/messages.py --udid <UDID> [--derivedkey <KEY>] [--output <DIR>]
"""

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime

from iOSbackup import iOSbackup
from extractors._contacts import load_index as _load_contacts_index, contact_link as _contact_link

# Seconds between Unix epoch (1970-01-01) and Apple epoch (2001-01-01)
_APPLE_EPOCH_OFFSET = 978307200

# Tapback reaction types
_TAPBACKS = {
    2000: '❤️', 2001: '👍', 2002: '👎',
    2003: '😂', 2004: '‼️', 2005: '❓',
}


def _apple_ts(ts):
    """Convert an Apple timestamp (seconds or nanoseconds since 2001-01-01) to datetime."""
    if ts is None or ts == 0:
        return None
    if ts > 1_000_000_000_000:   # nanoseconds (iOS 13+)
        ts = ts / 1_000_000_000
    return datetime.fromtimestamp(ts + _APPLE_EPOCH_OFFSET)


def _sanitize_folder(name):
    return re.sub(r'[^\w\-+@.]', '_', name)


_HEIC_EXTENSIONS = {'.heic', '.heif'}


def _convert_heic(path):
    """Convert a HEIC/HEIF file to JPEG using macOS sips. Returns the new path.
    Falls back to the original path if conversion fails or sips is unavailable.
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
        pass  # sips not available (non-macOS)
    return path


def _attachment_relative_path(filename):
    """~/Library/SMS/Attachments/... → Library/SMS/Attachments/..."""
    if not filename:
        return None
    return filename.replace('~/', '', 1)


def _load_conversations(mdb):
    """Return a list of conversation dicts from an open sms.db connection.

    Multiple chat rows with the same identifier (e.g. one SMS thread and one
    iMessage thread for the same contact) are merged into a single conversation
    with messages sorted by date.
    """

    chats = mdb.execute("""
        SELECT ROWID, guid, chat_identifier, display_name, service_name
        FROM chat
        ORDER BY ROWID
    """).fetchall()

    # Accumulate per-identifier: messages, participants, display_name
    merged = {}  # identifier → dict

    for chat in chats:
        chat_id    = chat['ROWID']
        identifier = chat['chat_identifier']

        participants = [row['id'] for row in mdb.execute("""
            SELECT h.id
            FROM handle h
            JOIN chat_handle_join chj ON chj.handle_id = h.ROWID
            WHERE chj.chat_id = ?
        """, (chat_id,)).fetchall()]

        raw_messages = mdb.execute("""
            SELECT
                m.ROWID, m.guid, m.text, m.date,
                m.is_from_me, m.service, m.handle_id,
                h.id AS sender_id,
                m.associated_message_guid,
                m.associated_message_type,
                m.reply_to_guid
            FROM message m
            JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
            LEFT JOIN handle h ON h.ROWID = m.handle_id
            WHERE cmj.chat_id = ?
            ORDER BY m.date
        """, (chat_id,)).fetchall()

        messages = []
        for m in raw_messages:
            attachments = [dict(a) for a in mdb.execute("""
                SELECT a.ROWID, a.guid, a.filename, a.mime_type,
                       a.total_bytes, a.transfer_name
                FROM attachment a
                JOIN message_attachment_join maj ON maj.attachment_id = a.ROWID
                WHERE maj.message_id = ?
            """, (m['ROWID'],)).fetchall()]

            dt = _apple_ts(m['date'])
            assoc_type = m['associated_message_type'] or 0

            messages.append({
                'id':              m['ROWID'],
                'guid':            m['guid'],
                'text':            m['text'],
                'date':            dt.isoformat() if dt else None,
                'is_from_me':      bool(m['is_from_me']),
                'sender':          'me' if m['is_from_me'] else (m['sender_id'] or 'unknown'),
                'service':         m['service'],
                'reply_to_guid':   m['reply_to_guid'],
                'tapback':         _TAPBACKS.get(assoc_type) if assoc_type in _TAPBACKS else None,
                'tapback_removed': assoc_type >= 3000,
                'associated_guid': m['associated_message_guid'],
                'attachments':     attachments,
            })

        if identifier not in merged:
            merged[identifier] = {
                'identifier':   identifier,
                'display_name': chat['display_name'] or None,
                'service':      chat['service_name'],
                'participants': [],
                'messages':     [],
            }

        entry = merged[identifier]

        # Prefer a display name if any chat row has one
        if not entry['display_name'] and chat['display_name']:
            entry['display_name'] = chat['display_name']

        # Merge participants, preserving order, deduplicating
        seen = set(entry['participants'])
        for p in participants:
            if p not in seen:
                entry['participants'].append(p)
                seen.add(p)

        entry['messages'].extend(messages)

    # Sort each merged conversation's messages by date
    for entry in merged.values():
        entry['messages'].sort(key=lambda m: m['date'] or '')

    return list(merged.values())


def extract(backup: iOSbackup, target_folder: str, convert_heic: bool = False,
            contacts_folder: str = None) -> list:
    """Extract all conversations from backup to target_folder.

    Parameters
    ----------
    backup : iOSbackup
        An open, authenticated backup instance.
    target_folder : str
        Root directory for output. Created if it does not exist.
    convert_heic : bool
        Whether to convert HEIC/HEIF attachments to JPEG (default: False).
        Requires macOS ``sips`` to be available.
    contacts_folder : str, optional
        Path to a contacts output folder produced by extractors/contacts.py.
        When provided, conversation identifiers are resolved to display names
        and linked to the corresponding contact page.

    Returns
    -------
    List of conversation dicts as written to conversation.json files.
    """
    if os.path.exists(target_folder):
        shutil.rmtree(target_folder)
    os.makedirs(target_folder)

    db_info = backup.getFileDecryptedCopy(
        relativePath="Library/SMS/sms.db",
        temporary=True,
    )

    mdb = sqlite3.connect(db_info['decryptedFilePath'])
    mdb.row_factory = sqlite3.Row
    conversations = _load_conversations(mdb)
    mdb.close()

    contacts_index = _load_contacts_index(contacts_folder)
    contacts_abs = os.path.abspath(contacts_folder) if contacts_folder else None

    for conv in conversations:
        label      = conv['display_name'] or conv['identifier']
        folder     = os.path.join(target_folder, _sanitize_folder(conv['identifier']))
        att_folder = os.path.join(folder, 'attachments')
        os.makedirs(att_folder, exist_ok=True)

        # Decrypt attachments and record their relative paths
        for msg in conv['messages']:
            for att in msg['attachments']:
                rel = _attachment_relative_path(att.get('filename'))
                if not rel:
                    att['extracted_path'] = None
                    continue
                name = os.path.basename(rel)
                try:
                    backup.getFileDecryptedCopy(
                        relativePath=rel,
                        targetFolder=att_folder,
                        targetName=name,
                    )
                    full_path = os.path.join(att_folder, name)
                    if convert_heic and os.path.splitext(name)[1].lower() in _HEIC_EXTENSIONS:
                        full_path = _convert_heic(full_path)
                        name = os.path.basename(full_path)
                        att['mime_type'] = 'image/jpeg'
                    att['extracted_path'] = os.path.join('attachments', name)
                except FileNotFoundError:
                    att['extracted_path'] = None

        # Write JSON
        json_path = os.path.join(folder, 'conversation.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(conv, f, indent=2, default=str)

        # Resolve contact link for this conversation's header
        entry = contacts_index.get(conv['identifier'])
        contact_url = None
        if entry and contacts_abs:
            contact_url = _contact_link(contacts_abs, entry, os.path.abspath(folder))
            if not conv['display_name']:
                conv['display_name'] = entry['contact'].get('name') or ''

        # Write HTML viewer
        _render_html(conv, os.path.join(folder, 'conversation.html'), contact_url)

        print(f"  ✓ {label} ({len(conv['messages'])} messages)")

    _render_index(conversations, target_folder, contacts_index, contacts_abs)
    print(f"\n{len(conversations)} conversations extracted to {target_folder}/")
    return conversations


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

_HTML_STYLE = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #000;
    color: #fff;
    display: flex;
    flex-direction: column;
    height: 100vh;
}
header {
    background: #1c1c1e;
    border-bottom: 1px solid #2c2c2e;
    padding: 16px;
    text-align: center;
    flex-shrink: 0;
}
header .title { font-weight: 600; font-size: 17px; }
a.title-link { color: inherit; text-decoration: none; }
a.title-link:hover { color: #0b84fe; }
header .subtitle { font-size: 12px; color: #8e8e93; margin-top: 2px; }
.messages {
    flex: 1;
    overflow-y: auto;
    padding: 12px 16px;
    display: flex;
    flex-direction: column;
    gap: 2px;
}
.date-header {
    text-align: center;
    font-size: 12px;
    color: #8e8e93;
    margin: 16px 0 8px;
}
.message-row { display: flex; }
.message-row.sent  { justify-content: flex-end; }
.message-row.received { justify-content: flex-start; }
.bubble {
    max-width: 70%;
    padding: 8px 12px;
    border-radius: 18px;
    font-size: 16px;
    line-height: 1.4;
}
.sent .bubble {
    background: #0b84fe;
    border-bottom-right-radius: 4px;
}
.received .bubble {
    background: #2c2c2e;
    border-bottom-left-radius: 4px;
}
.sender-label { font-size: 11px; color: #8e8e93; margin-bottom: 3px; }
.msg-text { white-space: pre-wrap; word-break: break-word; }
.time { font-size: 11px; color: rgba(255,255,255,0.45); margin-top: 4px; text-align: right; }
.tapback { font-size: 13px; margin-top: 2px; }
img.att   { max-width: 100%; border-radius: 12px; display: block; margin-bottom: 4px; }
video.att { max-width: 100%; border-radius: 8px; display: block; margin-bottom: 4px; }
audio.att { width: 100%; margin-bottom: 4px; }
.att-file { font-size: 14px; }
.att-file a { color: #0b84fe; text-decoration: none; }
.att-missing { color: #8e8e93; font-style: italic; font-size: 13px; }
"""


def _escape(text):
    return (text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;'))


def _format_date(iso):
    dt = datetime.fromisoformat(iso)
    return dt.strftime('%A, %B %d, %Y').replace(' 0', ' ')


def _format_time(iso):
    dt = datetime.fromisoformat(iso)
    t = dt.strftime('%I:%M %p').lstrip('0')
    return t


def _attachment_html(att):
    path = att.get('extracted_path')
    mime = att.get('mime_type') or ''
    name = att.get('transfer_name') or os.path.basename(att.get('filename') or 'file')

    if not path:
        return f'<div class="att-missing">[attachment unavailable: {_escape(name)}]</div>'
    if mime.startswith('image/'):
        return f'<img class="att" src="{path}" alt="{_escape(name)}">'
    if mime.startswith('video/'):
        return f'<video class="att" src="{path}" controls></video>'
    if mime.startswith('audio/'):
        return f'<audio class="att" src="{path}" controls></audio>'
    return f'<div class="att-file"><a href="{path}">{_escape(name)}</a></div>'


def _render_html(conv, output_path, contact_url=None):
    title    = conv['display_name'] or conv['identifier']
    subtitle = ', '.join(conv['participants'])

    # Header: link the title to the contact page if available
    if contact_url:
        title_html = f'<a href="{contact_url}" class="title-link">{_escape(title)}</a>'
    else:
        title_html = _escape(title)

    rows = []
    last_date = None

    for msg in conv['messages']:
        if not msg['date']:
            continue

        # Skip tapbacks — they appear as reactions on the target message,
        # but sms.db doesn't easily let us attach them back, so just omit.
        if msg['tapback'] and msg['associated_guid']:
            continue

        date_label = _format_date(msg['date'])
        if date_label != last_date:
            rows.append(f'<div class="date-header">{date_label}</div>')
            last_date = date_label

        side   = 'sent' if msg['is_from_me'] else 'received'
        sender = '' if msg['is_from_me'] else f'<div class="sender-label">{_escape(msg["sender"])}</div>'

        parts = []
        for att in msg['attachments']:
            parts.append(_attachment_html(att))
        if msg['text']:
            parts.append(f'<div class="msg-text">{_escape(msg["text"])}</div>')
        if not parts:
            continue

        content = '\n'.join(parts)
        rows.append(f"""
<div class="message-row {side}">
  <div class="bubble">
    {sender}
    {content}
    <div class="time">{_format_time(msg["date"])} · {msg["service"]}</div>
  </div>
</div>""")

    body = '\n'.join(rows)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(title)}</title>
  <style>{_HTML_STYLE}</style>
</head>
<body>
  <header>
    <div class="title">{title_html}</div>
    <div class="subtitle">{_escape(subtitle)}</div>
  </header>
  <div class="messages">
    {body}
  </div>
</body>
</html>"""

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)


def _render_index(conversations, target_folder, contacts_index=None, contacts_abs=None):
    index_dir = os.path.abspath(target_folder)

    # Sort by most recent message, newest first
    def _last_date(conv):
        dates = [m['date'] for m in conv['messages'] if m['date']]
        return max(dates) if dates else ''
    sorted_convs = sorted(conversations, key=_last_date, reverse=True)

    items = []
    for conv in sorted_convs:
        identifier = conv['identifier']
        folder     = _sanitize_folder(identifier)
        count      = len(conv['messages'])
        dates      = [m['date'] for m in conv['messages'] if m['date']]
        last       = _format_date(max(dates)) if dates else '—'

        # Resolve display name from contacts
        entry        = (contacts_index or {}).get(identifier)
        display_name = conv['display_name']
        if not display_name and entry:
            display_name = entry['contact'].get('name') or ''

        if display_name and display_name != identifier:
            name_html = f'{_escape(display_name)} <span class="ident">{_escape(identifier)}</span>'
        else:
            name_html = _escape(identifier)

        # Contact link as a separate button, not nested inside the conversation link
        contact_btn = ''
        if entry and contacts_abs:
            link = _contact_link(contacts_abs, entry, index_dir)
            contact_btn = f'<a href="{link}" class="contact-btn" title="View contact">i</a>'

        items.append(f"""
<div class="conv-row">
  <a href="{folder}/conversation.html" class="conv">
    <div class="name">{name_html}</div>
    <div class="meta">{count} messages &middot; last {last}</div>
  </a>{contact_btn}
</div>""")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Messages</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: #000; color: #fff; }}
    header {{ background: #1c1c1e; border-bottom: 1px solid #2c2c2e;
              padding: 20px 16px; font-size: 28px; font-weight: 700; }}
    .conv-row {{ display: flex; align-items: center; border-bottom: 1px solid #2c2c2e; }}
    .conv {{ flex: 1; display: block; padding: 14px 16px;
             text-decoration: none; color: inherit; cursor: pointer; }}
    .conv:hover {{ background: #1c1c1e; }}
    .name {{ font-size: 17px; font-weight: 500; }}
    .name .ident {{ font-size: 13px; font-weight: 400; color: #8e8e93; margin-left: 6px; }}
    .meta {{ font-size: 13px; color: #8e8e93; margin-top: 3px; }}
    .contact-btn {{ display: flex; align-items: center; justify-content: center;
                    width: 24px; height: 24px; margin-right: 16px; border-radius: 50%;
                    background: #2c2c2e; color: #8e8e93; font-size: 13px;
                    font-style: italic; font-family: serif; text-decoration: none;
                    flex-shrink: 0; }}
    .contact-btn:hover {{ background: #0b84fe; color: #fff; }}
  </style>
</head>
<body>
  <header>Messages</header>
  {''.join(items)}
</body>
</html>"""

    with open(os.path.join(target_folder, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(html)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Extract iMessages and SMS from an iOS backup.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--udid',       required=True, help='Device UDID')
    parser.add_argument('--derivedkey', default=None,  help='Derived decryption key; prompts for password if omitted')
    parser.add_argument('--backuproot', default=None,  help='Backup root folder; uses platform default if omitted')
    parser.add_argument('--output',          default='messages', help='Output folder (default: messages)')
    parser.add_argument('--convert-heic', action='store_true',
                        help='Convert HEIC/HEIF attachments to JPEG (requires macOS sips)')
    parser.add_argument('--contacts', default=None, metavar='DIR',
                        help='Path to contacts output folder (from extractors/contacts.py); '
                             'enables display names and contact links in the index')
    args = parser.parse_args()

    backup = iOSbackup(
        udid=args.udid,
        derivedkey=args.derivedkey,
        backuproot=args.backuproot,
    )
    extract(backup, args.output, convert_heic=args.convert_heic,
            contacts_folder=args.contacts)


if __name__ == '__main__':
    main()
