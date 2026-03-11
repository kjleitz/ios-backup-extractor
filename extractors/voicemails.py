#!/usr/bin/env python3
"""
Extract voicemails from an iOS backup.

Usage:
    python extractors/voicemails.py --udid <UDID> [--derivedkey <KEY>] [--output <DIR>]

The derivedkey can be obtained on first run by omitting it (you will be prompted
for your backup password) and then calling b.getDecryptionKey() on the resulting
object. Save that key and pass it via --derivedkey on future runs.
"""

import argparse
import os
import plistlib
import shutil
import sqlite3
import subprocess
from datetime import datetime

from iOSbackup import iOSbackup
from extractors._contacts import load_index as _load_contacts_index, contact_link as _contact_link

try:
    import NSKeyedUnArchiverLocal as _NSKUA
except ImportError:
    _NSKUA = None


def _parse_transcript(path):
    """Read an iOS voicemail .transcript file (NSKeyedArchiver plist).
    Returns the transcription string, or None on failure."""
    if not _NSKUA:
        return None
    try:
        with open(path, 'rb') as f:
            plist = plistlib.load(f)
        data = _NSKUA.unserializeNSKeyedArchiver(plist)
        return data.get('transcriptionString') or None
    except Exception:
        return None


def _convert_amr(amr_path):
    """Convert an AMR file to M4A using macOS afconvert.
    Returns the new path, or the original path if conversion fails."""
    m4a_path = os.path.splitext(amr_path)[0] + '.m4a'
    try:
        result = subprocess.run(
            ['afconvert', '-f', 'm4af', '-d', 'aac', amr_path, m4a_path],
            capture_output=True,
        )
        if result.returncode == 0:
            os.remove(amr_path)
            return m4a_path
    except FileNotFoundError:
        pass  # afconvert not available (non-macOS)
    return amr_path


def extract(backup: iOSbackup, target_folder: str, contacts_folder: str = None) -> list:
    """Extract all voicemails from a backup to target_folder.

    Pulls the voicemail database for metadata, then decrypts each .amr audio
    file and its transcript (if present), naming them by date and caller.

    Parameters
    ----------
    backup : iOSbackup
        An open, authenticated backup instance.
    target_folder : str
        Directory to write extracted files into. Created if it does not exist.
    contacts_folder : str, optional
        Path to a contacts output folder produced by extractors/contacts.py.
        When provided, sender numbers are resolved to display names and linked
        to the corresponding contact page in voicemails.html.

    Returns
    -------
    List of dicts, one per voicemail, with keys: file, sender, date, duration, trashed.
    """
    if os.path.exists(target_folder):
        shutil.rmtree(target_folder)
    os.makedirs(target_folder)

    db_info = backup.getFileDecryptedCopy(
        relativePath="Library/Voicemail/voicemail.db",
        temporary=True,
    )

    vdb = sqlite3.connect(db_info['decryptedFilePath'])
    vdb.row_factory = sqlite3.Row
    messages = vdb.execute("SELECT * FROM voicemail ORDER BY date").fetchall()
    vdb.close()

    results = []
    for m in messages:
        rowid    = m['ROWID']
        sender   = m['sender'] or 'unknown'
        date     = datetime.fromtimestamp(m['date'])
        duration = m['duration']
        trashed  = m['trashed_date'] != 0

        date_str = date.strftime('%Y-%m-%d_%H-%M-%S')
        stem     = f"{date_str}_{sender}_{duration}s"

        try:
            backup.getFileDecryptedCopy(
                relativePath=f"Library/Voicemail/{rowid}.amr",
                targetFolder=target_folder,
                targetName=f"{stem}.amr",
            )
        except FileNotFoundError:
            print(f"  ✗ missing audio for voicemail {rowid}")
            continue

        # Convert AMR to browser-playable M4A
        audio_path = os.path.join(target_folder, f"{stem}.amr")
        audio_path = _convert_amr(audio_path)

        # Pull transcript if one exists (binary plist, NSKeyedArchiver)
        transcript_text = None
        try:
            info = backup.getFileDecryptedCopy(
                relativePath=f"Library/Voicemail/{rowid}.transcript",
                targetFolder=target_folder,
                targetName=f"{stem}.transcript",
            )
            transcript_text = _parse_transcript(info['decryptedFilePath'])
            # Remove the raw binary plist now that we've extracted the text
            try:
                os.remove(info['decryptedFilePath'])
            except OSError:
                pass
        except FileNotFoundError:
            pass

        result = {
            'file':       audio_path,
            'transcript': transcript_text,
            'sender':     sender,
            'date':       date,
            'duration':   duration,
            'trashed':    trashed,
        }
        results.append(result)
        print(f"  {'🗑 ' if trashed else '✓ '}{stem}.amr")

    contacts_index = _load_contacts_index(contacts_folder)
    _render_html(results, target_folder, contacts_index,
                 os.path.abspath(contacts_folder) if contacts_folder else None)

    print(f"\n{len(results)} voicemails extracted to {target_folder}/")
    return results


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

_HTML_STYLE = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #000; color: #fff;
}
header {
    background: #1c1c1e; border-bottom: 1px solid #2c2c2e;
    padding: 20px 16px; font-size: 28px; font-weight: 700;
}
.vm {
    padding: 14px 16px; border-bottom: 1px solid #2c2c2e;
}
.vm.trashed { opacity: 0.5; }
.vm-header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; }
.caller { font-size: 17px; font-weight: 500; }
.caller .number { font-size: 13px; font-weight: 400; color: #8e8e93; margin-left: 6px; }
a.contact-link { color: inherit; text-decoration: none; }
a.contact-link:hover { color: #0b84fe; }
.when { font-size: 13px; color: #8e8e93; }
audio { width: 100%; margin-top: 6px; }
.transcript { font-size: 14px; color: #ebebf5; margin-top: 8px; line-height: 1.5; white-space: pre-wrap; }
.trashed-label { font-size: 11px; color: #ff453a; margin-top: 4px; }
"""


def _escape(text):
    if not text:
        return ''
    return (str(text)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;'))


def _render_html(results, target_folder, contacts_index, contacts_abs):
    vmdir = os.path.abspath(target_folder)
    items = []

    for vm in results:
        sender  = vm['sender']
        date    = vm['date']
        audio   = os.path.basename(vm['file'])
        trashed = vm['trashed']

        entry = contacts_index.get(sender)
        if entry:
            name     = _escape(entry['contact'].get('name') or sender)
            link     = _contact_link(contacts_abs, entry, vmdir)
            caller   = (f'<a class="contact-link" href="{link}">'
                        f'{name} <span class="number">{_escape(sender)}</span></a>')
        else:
            caller = _escape(sender)

        when = date.strftime('%b %-d, %Y at %-I:%M %p') if date else '—'
        duration_str = f"{vm['duration']}s"

        transcript_html = ''
        if vm.get('transcript'):
            transcript_html = f'<div class="transcript">{_escape(vm["transcript"])}</div>'

        items.append(f"""
<div class="vm{'  trashed' if trashed else ''}">
  <div class="vm-header">
    <span class="caller">{caller}</span>
    <span class="when">{_escape(when)} · {_escape(duration_str)}</span>
  </div>
  <audio src="{_escape(audio)}" controls></audio>
  {transcript_html}
  {'<div class="trashed-label">Deleted voicemail</div>' if trashed else ''}
</div>""")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Voicemails</title>
  <style>{_HTML_STYLE}</style>
</head>
<body>
  <header>Voicemails</header>
  {''.join(items)}
</body>
</html>"""

    with open(os.path.join(target_folder, 'voicemails.html'), 'w', encoding='utf-8') as f:
        f.write(html)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Extract voicemails from an iOS backup.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--udid',       required=True, help='Device UDID (see iOSbackup.getDeviceList())')
    parser.add_argument('--derivedkey', default=None,  help='Derived decryption key; prompts for password if omitted')
    parser.add_argument('--backuproot', default=None,  help='Backup root folder; uses platform default if omitted')
    parser.add_argument('--output',     default='voicemails', help='Output folder (default: voicemails)')
    parser.add_argument('--contacts',   default=None,  metavar='DIR',
                        help='Path to contacts output folder (from extractors/contacts.py); '
                             'enables display names and contact links')
    args = parser.parse_args()

    backup = iOSbackup(
        udid=args.udid,
        derivedkey=args.derivedkey,
        backuproot=args.backuproot,
    )

    extract(backup, args.output, contacts_folder=args.contacts)


if __name__ == '__main__':
    main()
