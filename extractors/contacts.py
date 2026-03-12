# Copyright (C) 2025 Keegan Leitz <kjleitz@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

#!/usr/bin/env python3
"""
Extract contacts from an iOS backup.

Output structure:
    <output>/
        contacts.json       — all contacts with phones, emails, addresses, etc.
        contacts.html       — searchable contact list
        <identifier>/       — per-contact folder (keyed by normalized phone/email)
            contact.json    — single contact record

Usage:
    python extractors/contacts.py --udid <UDID> [--derivedkey <KEY>] [--output <DIR>]
"""

import argparse
import json
import os
import re
import shutil
import sqlite3

from iOSbackup import iOSbackup

# ABMultiValue.property constants (iOS AddressBook)
_PROP_PHONE   = 3
_PROP_EMAIL   = 4
_PROP_ADDRESS = 12
_PROP_URL     = 22


def _normalize_phone(raw):
    """Strip all non-digit characters, return E.164-ish string prefixed with +."""
    digits = re.sub(r'\D', '', raw)
    if len(digits) == 10:
        digits = '1' + digits   # assume US
    return '+' + digits


def _sanitize_folder(name):
    return re.sub(r'[^\w\-+@.]', '_', name)


def _load_contacts(adb):
    """Return a list of contact dicts from an open AddressBook.sqlitedb connection."""

    people = adb.execute("""
        SELECT ROWID, First, Last, Middle, Organization, Department, Note, Birthday
        FROM ABPerson
        ORDER BY Last, First
    """).fetchall()

    contacts = []
    for p in people:
        rowid = p['ROWID']

        multivals = adb.execute("""
            SELECT ROWID AS mvid, property, value, label
            FROM ABMultiValue
            WHERE record_id = ?
        """, (rowid,)).fetchall()

        phones    = []
        emails    = []
        urls      = []
        addresses = []

        for mv in multivals:
            mvid  = mv['mvid']
            prop  = mv['property']
            value = mv['value']
            label = mv['label'] or ''
            if not value:
                continue

            if prop == _PROP_PHONE:
                phones.append({'label': label, 'number': value, 'normalized': _normalize_phone(value)})
            elif prop == _PROP_EMAIL:
                emails.append({'label': label, 'email': value})
            elif prop == _PROP_URL:
                urls.append({'label': label, 'url': value})
            elif prop == _PROP_ADDRESS:
                # Structured addresses live in ABMultiValueEntry
                parts = {row['key']: row['value'] for row in adb.execute("""
                    SELECT key, value
                    FROM ABMultiValueEntry
                    WHERE parent_id = ?
                """, (mvid,)).fetchall()}
                addresses.append({'label': label, **parts})

        # Build display name
        parts = [p['First'], p['Middle'], p['Last']]
        name  = ' '.join(x for x in parts if x).strip() or p['Organization'] or ''

        contacts.append({
            'id':           rowid,
            'name':         name,
            'first':        p['First'],
            'last':         p['Last'],
            'middle':       p['Middle'],
            'organization': p['Organization'],
            'department':   p['Department'],
            'note':         p['Note'],
            'birthday':     p['Birthday'],
            'phones':       phones,
            'emails':       emails,
            'urls':         urls,
            'addresses':    addresses,
            # Identifiers that match chat_identifier values in sms.db:
            'message_identifiers': (
                [ph['normalized'] for ph in phones] +
                [em['email'].lower() for em in emails]
            ),
        })

    return contacts


def extract(backup: iOSbackup, target_folder: str) -> list:
    """Extract all contacts from backup to target_folder.

    Parameters
    ----------
    backup : iOSbackup
        An open, authenticated backup instance.
    target_folder : str
        Root directory for output. Created if it does not exist.

    Returns
    -------
    List of contact dicts as written to contacts.json.
    """
    if os.path.exists(target_folder):
        shutil.rmtree(target_folder)
    os.makedirs(target_folder)

    db_info = backup.getFileDecryptedCopy(
        relativePath='Library/AddressBook/AddressBook.sqlitedb',
        temporary=True,
    )

    adb = sqlite3.connect(db_info['decryptedFilePath'])
    adb.row_factory = sqlite3.Row
    contacts = _load_contacts(adb)
    adb.close()

    # Write top-level contacts.json
    all_json = os.path.join(target_folder, 'contacts.json')
    with open(all_json, 'w', encoding='utf-8') as f:
        json.dump(contacts, f, indent=2, default=str)

    # Write per-contact folders
    for contact in contacts:
        label  = contact['name'] or f"contact_{contact['id']}"
        # Use first phone or email as folder key; fall back to rowid
        key = (contact['phones'][0]['normalized'] if contact['phones']
               else contact['emails'][0]['email'] if contact['emails']
               else str(contact['id']))
        folder = os.path.join(target_folder, _sanitize_folder(key))
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, 'contact.json'), 'w', encoding='utf-8') as f:
            json.dump(contact, f, indent=2, default=str)
        _render_contact_html(contact, folder)
        print(f"  ✓ {label}")

    _render_html(contacts, target_folder)
    print(f"\n{len(contacts)} contacts extracted to {target_folder}/")
    return contacts


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

_BASE_STYLE = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #000; color: #fff;
}
a { color: #0b84fe; text-decoration: none; }
a:hover { text-decoration: underline; }
"""

_HTML_STYLE = _BASE_STYLE + """
header {
    background: #1c1c1e; border-bottom: 1px solid #2c2c2e;
    padding: 20px 16px; font-size: 28px; font-weight: 700; position: sticky; top: 0;
}
#search-wrap { padding: 8px 16px; background: #1c1c1e; position: sticky; top: 64px; }
#search {
    width: 100%; padding: 8px 12px; border-radius: 10px;
    background: #2c2c2e; border: none; color: #fff; font-size: 16px;
}
#search::placeholder { color: #636366; }
.contact {
    display: block; padding: 14px 16px; border-bottom: 1px solid #2c2c2e;
    text-decoration: none; color: inherit;
}
.contact:hover { background: #1c1c1e; }
.name { font-size: 17px; font-weight: 500; }
.meta { font-size: 13px; color: #8e8e93; margin-top: 3px; }
.contact.hidden { display: none; }
"""

_DETAIL_STYLE = _BASE_STYLE + """
header {
    background: #1c1c1e; border-bottom: 1px solid #2c2c2e; padding: 16px;
}
header .back { font-size: 14px; color: #0b84fe; display: block; margin-bottom: 8px; }
header .title { font-size: 22px; font-weight: 700; }
header .org   { font-size: 14px; color: #8e8e93; margin-top: 4px; }
section { padding: 16px; border-bottom: 1px solid #1c1c1e; }
section h2 { font-size: 12px; color: #8e8e93; text-transform: uppercase;
             letter-spacing: 0.05em; margin-bottom: 10px; }
.row { display: flex; justify-content: space-between; align-items: baseline;
       padding: 6px 0; border-bottom: 1px solid #1c1c1e; }
.row:last-child { border-bottom: none; }
.row .label { font-size: 13px; color: #8e8e93; }
.row .value { font-size: 16px; }
.note { font-size: 15px; line-height: 1.5; color: #ebebf5; white-space: pre-wrap; }
"""

_SEARCH_JS = """
const input = document.getElementById('search');
input.addEventListener('input', () => {
    const q = input.value.toLowerCase();
    document.querySelectorAll('.contact').forEach(el => {
        el.classList.toggle('hidden', !el.dataset.search.includes(q));
    });
});
"""


def _escape(text):
    if not text:
        return ''
    return (str(text)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;'))


def _render_contact_html(contact, folder):
    name  = _escape(contact['name'] or '(no name)')
    org   = _escape(contact.get('organization') or '')
    dept  = _escape(contact.get('department') or '')
    org_line = ' · '.join(x for x in [org, dept] if x)

    sections = []

    if contact['phones']:
        rows = ''.join(
            f'<div class="row"><span class="label">{_escape(ph["label"] or "phone")}</span>'
            f'<span class="value"><a href="tel:{_escape(ph["normalized"])}">{_escape(ph["number"])}</a></span></div>'
            for ph in contact['phones']
        )
        sections.append(f'<section><h2>Phone</h2>{rows}</section>')

    if contact['emails']:
        rows = ''.join(
            f'<div class="row"><span class="label">{_escape(em["label"] or "email")}</span>'
            f'<span class="value"><a href="mailto:{_escape(em["email"])}">{_escape(em["email"])}</a></span></div>'
            for em in contact['emails']
        )
        sections.append(f'<section><h2>Email</h2>{rows}</section>')

    if contact['addresses']:
        rows = []
        for addr in contact['addresses']:
            label = addr.get('label') or 'address'
            parts = [addr.get(k, '') for k in ('Street', 'City', 'State', 'ZIP', 'Country') if addr.get(k)]
            rows.append(
                f'<div class="row"><span class="label">{_escape(label)}</span>'
                f'<span class="value">{_escape(", ".join(parts))}</span></div>'
            )
        sections.append(f'<section><h2>Address</h2>{"".join(rows)}</section>')

    if contact['urls']:
        rows = ''.join(
            f'<div class="row"><span class="label">{_escape(u["label"] or "url")}</span>'
            f'<span class="value"><a href="{_escape(u["url"])}">{_escape(u["url"])}</a></span></div>'
            for u in contact['urls']
        )
        sections.append(f'<section><h2>URL</h2>{rows}</section>')

    if contact.get('birthday'):
        sections.append(
            f'<section><h2>Birthday</h2>'
            f'<div class="row"><span class="label">date</span>'
            f'<span class="value">{_escape(str(contact["birthday"]))}</span></div></section>'
        )

    if contact.get('note'):
        sections.append(
            f'<section><h2>Note</h2><p class="note">{_escape(contact["note"])}</p></section>'
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{name}</title>
  <style>{_DETAIL_STYLE}</style>
</head>
<body>
  <header>
    <a class="back" href="../contacts.html">← Contacts</a>
    <div class="title">{name}</div>
    {'<div class="org">' + org_line + '</div>' if org_line else ''}
  </header>
  {''.join(sections)}
</body>
</html>"""

    with open(os.path.join(folder, 'contact.html'), 'w', encoding='utf-8') as f:
        f.write(html)


def _render_html(contacts, target_folder):
    items = []
    for c in contacts:
        name    = _escape(c['name'] or '(no name)')
        phones  = ', '.join(ph['number'] for ph in c['phones'])
        emails  = ', '.join(em['email'] for em in c['emails'])
        meta    = ' · '.join(x for x in [phones, emails] if x) or ''
        search  = ' '.join([
            c['name'] or '', phones, emails,
            c.get('organization') or '',
        ]).lower()
        key     = (c['phones'][0]['normalized'] if c['phones']
                   else c['emails'][0]['email'] if c['emails']
                   else str(c['id']))
        folder  = _sanitize_folder(key)
        items.append(
            f'<a class="contact" href="{folder}/contact.html" '
            f'data-search="{_escape(search)}">'
            f'<div class="name">{name}</div>'
            f'<div class="meta">{_escape(meta)}</div>'
            f'</a>'
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Contacts</title>
  <style>{_HTML_STYLE}</style>
</head>
<body>
  <header>Contacts</header>
  <div id="search-wrap"><input id="search" type="search" placeholder="Search contacts…"></div>
  {''.join(items)}
  <script>{_SEARCH_JS}</script>
</body>
</html>"""

    with open(os.path.join(target_folder, 'contacts.html'), 'w', encoding='utf-8') as f:
        f.write(html)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Extract contacts from an iOS backup.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--udid',       required=True, help='Device UDID (see iOSbackup.getDeviceList())')
    parser.add_argument('--derivedkey', default=None,  help='Derived decryption key; prompts for password if omitted')
    parser.add_argument('--backuproot', default=None,  help='Backup root folder; uses platform default if omitted')
    parser.add_argument('--output',     default='contacts', help='Output folder (default: contacts)')
    args = parser.parse_args()

    backup = iOSbackup(
        udid=args.udid,
        derivedkey=args.derivedkey,
        backuproot=args.backuproot,
    )
    extract(backup, args.output)


if __name__ == '__main__':
    main()
