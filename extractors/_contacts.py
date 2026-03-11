"""Shared contacts index used by other extractors."""

import json
import os
import re

_SANITIZE_RE = re.compile(r'[^\w\-+@.]')


def _sanitize_folder(name):
    return _SANITIZE_RE.sub('_', name)


def load_index(contacts_folder):
    """Build a lookup dict from a contacts output folder.

    Returns a dict mapping each normalized identifier (phone number or
    lowercase email) to a dict::

        {
            'contact': <contact dict from contacts.json>,
            'key':     <sanitized folder name>,   # e.g. '+16178691134'
        }

    The keys match the chat_identifier values written by sms.db and the
    sender strings written by voicemail.db.

    Returns an empty dict if contacts_folder is None or contacts.json is
    missing.
    """
    if not contacts_folder:
        return {}
    json_path = os.path.join(contacts_folder, 'contacts.json')
    if not os.path.exists(json_path):
        return {}
    with open(json_path, encoding='utf-8') as f:
        contacts = json.load(f)

    index = {}
    for c in contacts:
        key = (c['phones'][0]['normalized'] if c['phones']
               else c['emails'][0]['email'] if c['emails']
               else str(c['id']))
        entry = {'contact': c, 'key': _sanitize_folder(key)}
        for ident in c.get('message_identifiers', []):
            if ident not in index:
                index[ident] = entry

    return index


def contact_link(contacts_folder, entry, from_dir):
    """Return a relative URL from from_dir to the contact's contact.html page.

    Parameters
    ----------
    contacts_folder : str
        Absolute path to the contacts output folder.
    entry : dict
        An entry from load_index(), containing at least 'key'.
    from_dir : str
        Absolute path of the directory that will contain the HTML file
        doing the linking.
    """
    target = os.path.join(os.path.abspath(contacts_folder),
                          entry['key'], 'contact.html')
    return os.path.relpath(target, from_dir)
