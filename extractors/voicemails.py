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
import shutil
import sqlite3
from datetime import datetime

from iOSbackup import iOSbackup


def extract(backup: iOSbackup, target_folder: str) -> list:
    """Extract all voicemails from a backup to target_folder.

    Pulls the voicemail database for metadata, then decrypts each .amr audio
    file and its transcript (if present), naming them by date and caller.

    Parameters
    ----------
    backup : iOSbackup
        An open, authenticated backup instance.
    target_folder : str
        Directory to write extracted files into. Created if it does not exist.

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

        # Pull transcript if one exists
        transcript_path = None
        try:
            info = backup.getFileDecryptedCopy(
                relativePath=f"Library/Voicemail/{rowid}.transcript",
                targetFolder=target_folder,
                targetName=f"{stem}.transcript",
            )
            transcript_path = info['decryptedFilePath']
        except FileNotFoundError:
            pass

        result = {
            'file':       os.path.join(target_folder, f"{stem}.amr"),
            'transcript': transcript_path,
            'sender':     sender,
            'date':       date,
            'duration':   duration,
            'trashed':    trashed,
        }
        results.append(result)
        print(f"  {'🗑 ' if trashed else '✓ '}{stem}.amr")

    print(f"\n{len(results)} voicemails extracted to {target_folder}/")
    return results


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
    args = parser.parse_args()

    backup = iOSbackup(
        udid=args.udid,
        derivedkey=args.derivedkey,
        backuproot=args.backuproot,
    )

    extract(backup, args.output)


if __name__ == '__main__':
    main()
