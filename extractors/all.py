# Copyright (C) 2025 Keegan Leitz <kjleitz@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

#!/usr/bin/env python3
"""
Extract all resources (contacts, messages, voicemails) from an iOS backup.

Creates a single backup instance and runs each extractor in sequence.
Contacts are extracted first so that messages and voicemails can resolve
display names and generate cross-links.

Output structure:
    <output>/
        contacts/       — contacts (JSON + HTML)
        messages/       — conversations with attachments
        voicemails/     — voicemails with transcriptions

Usage:
    python extractors/all.py --udid <UDID> [--derivedkey <KEY>] [--output <DIR>]
"""

import argparse
import os

from iOSbackup import iOSbackup

from extractors import contacts, messages, voicemails


def extract(backup: iOSbackup, target_folder: str,
            convert_heic: bool = True) -> dict:
    """Extract contacts, messages, and voicemails from a backup.

    Parameters
    ----------
    backup : iOSbackup
        An open, authenticated backup instance.
    target_folder : str
        Root directory for output. Each resource type gets its own subfolder.
    convert_heic : bool
        Convert HEIC/HEIF attachments to JPEG (default True).

    Returns
    -------
    dict
        Mapping of resource type to its list of extracted records.
    """
    contacts_folder = os.path.join(target_folder, 'contacts')
    messages_folder = os.path.join(target_folder, 'messages')
    voicemails_folder = os.path.join(target_folder, 'voicemails')

    results = {}

    print("=== Extracting contacts ===")
    results['contacts'] = contacts.extract(backup, contacts_folder)
    print(f"    {len(results['contacts'])} contacts extracted\n")

    print("=== Extracting messages ===")
    results['messages'] = messages.extract(
        backup, messages_folder,
        convert_heic=convert_heic,
        contacts_folder=contacts_folder,
    )
    print(f"    {len(results['messages'])} conversations extracted\n")

    print("=== Extracting voicemails ===")
    results['voicemails'] = voicemails.extract(
        backup, voicemails_folder,
        contacts_folder=contacts_folder,
    )
    print(f"    {len(results['voicemails'])} voicemails extracted\n")

    print(f"Done. Output written to {target_folder}/")
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Extract all resources from an iOS backup.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--udid',       required=True,
                        help='Device UDID (see iOSbackup.getDeviceList())')
    parser.add_argument('--derivedkey', default=None,
                        help='Derived decryption key; prompts for password if omitted')
    parser.add_argument('--backuproot', default=None,
                        help='Backup root folder; uses platform default if omitted')
    parser.add_argument('--output',     default='backup_export',
                        help='Output root folder (default: backup_export)')
    parser.add_argument('--no-convert-heic', action='store_true',
                        help='Skip HEIC-to-JPEG conversion for message attachments')
    args = parser.parse_args()

    backup = iOSbackup(
        udid=args.udid,
        derivedkey=args.derivedkey,
        backuproot=args.backuproot,
    )

    extract(backup, args.output, convert_heic=not args.no_convert_heic)


if __name__ == '__main__':
    main()
