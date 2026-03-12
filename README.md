# ios-backup-extractor

Reads and extracts files from a **password-encrypted iOS backup** created by iTunes/Finder on Mac and Windows.

> **Fork notice:** This project is a fork of
> [iOSbackup](https://github.com/avibrazil/iOSbackup) by Avi Alkalay, and
> incorporates [NSKeyedUnArchiver](https://github.com/avibrazil/NSKeyedUnArchiver)
> (also by Avi Alkalay). Licensed under GPL v3 — see [LICENSE](LICENSE).
> If you find this software useful, please consider
> [donating to the original author](https://github.com/avibrazil/iOSbackup#donation).

You will need your backup password to decrypt the backup files. This is the password iTunes/Finder asks for when it is configured to do encrypted backups. This password can be found on macOS’ Keychain Access app, under `login` keychain, entry `iOS Backup` (update: newer macOS apparently doesn’t store it in Keychain anymore).

You should always prefer encrypted backups because they are more secure and include more files from your device. Non-encrypted backups do not backup files such as the Health app database.

## Installation

Use a virtual environment to keep dependencies isolated:

```shell
python3 -m venv .venv
source .venv/bin/activate   # on Windows: .venv\Scripts\activate
pip install -e .
```

`ios-backup-extractor` requires `pycryptodome`, which will be installed automatically by `pip`.

## Quick Start

### 1. Find your device UDID

```shell
python3 -c "from iOSbackup import iOSbackup; print(iOSbackup.getDeviceList())"
```

### 2. Extract everything

```shell
python3 extractors/all.py --udid <UDID>
```

You'll be prompted for your backup password. This extracts contacts, messages
(with attachments), and voicemails into `backup_export/` by default:

```
backup_export/
    contacts/       — contacts (JSON + searchable HTML)
    messages/       — conversations with attachments and an HTML viewer
    voicemails/     — voicemails with transcriptions and an HTML player
```

HEIC/HEIF attachments are automatically converted to JPEG (requires macOS).
To skip that, pass `--no-convert-heic`.

#### Options

```
--udid UDID          Device UDID (required)
--derivedkey KEY     Skip password prompt by passing a saved decryption key
--backuproot DIR     Custom backup folder (uses platform default if omitted)
--output DIR         Output root folder (default: backup_export)
--no-convert-heic    Skip HEIC-to-JPEG conversion
```

### 3. Save your decryption key

Key derivation is slow by design. After the first run, save the derived key
so you can skip the password prompt on future runs:

```python
from iOSbackup import iOSbackup
b = iOSbackup(udid="<UDID>")
print(b.getDecryptionKey())  # save this hex string
```

Then pass it on subsequent runs:

```shell
python3 extractors/all.py --udid <UDID> --derivedkey <KEY>
```

### 4. Convert HEIC images after the fact

If you already extracted messages without HEIC conversion (or used one of the
individual extractors), you can convert them separately:

```shell
python3 extractors/convert_heic.py backup_export/messages
```

This finds all `.heic`/`.heif` files under the folder, converts them to JPEG,
and updates references in `conversation.html` and `conversation.json`.

### Running individual extractors

You can also run each extractor independently:

```shell
python3 extractors/contacts.py   --udid <UDID> [--output contacts]
python3 extractors/messages.py   --udid <UDID> [--output messages] [--convert-heic] [--contacts contacts]
python3 extractors/voicemails.py --udid <UDID> [--output voicemails] [--contacts contacts]
```

The `--contacts` flag tells messages/voicemails where to find the contacts
output so they can resolve display names and generate cross-links.

## Security

This fork fixes several security and correctness issues present in the original [iOSbackup](https://github.com/avibrazil/iOSbackup) and [NSKeyedUnArchiver](https://github.com/avibrazil/NSKeyedUnArchiver) libraries.

### iOSbackup fixes

**Password handling** (original: cleartext password persisted in memory)
- The constructor now prompts for your backup password via `getpass` when no `derivedkey` is supplied. The password never appears in your shell history, REPL transcript, or log output.
- Internally the password is held in a mutable `bytearray` and zeroed immediately after key derivation, including the intermediate PBKDF2 round. Python's immutable `str` type cannot be zeroed and may persist in memory or appear in stack traces — this approach avoids that.
- The `cleartextpassword` parameter still exists for scripted/non-interactive use, but should be avoided wherever possible.

**Decryption key redacted from `repr`** (original: full key printed by `__repr__`)
- The original library's `repr(b)` / `print(b)` emitted the full master decryption key in hex, which could end up in terminal output, log files, or crash reports. This key decrypts the entire backup. It is now redacted — call `b.getDecryptionKey()` explicitly when you need it.

**SQL injection prevention** (original: string interpolation in SQL queries)
- `getFolderDecryptedCopy()` previously built SQL queries by string interpolation, which would allow a crafted `relativePath`, `includeDomains`, or `includeFiles` value to inject arbitrary SQL. All filters now use parameterised queries.

**Path traversal prevention** (original: no output path validation)
- The original library joined `domain` and `relativePath` from `Manifest.db` directly into the output path with no boundary check. A crafted backup containing `domain = "../../"` or a similar `relativePath` could write files outside the intended target folder. `getFolderDecryptedCopy()` now validates each output path against the target root before writing.

**Temporary file cleanup** (original: decrypted `Manifest.db` could persist after crash)
- The original library used `tempfile.NamedTemporaryFile(delete=False)` with cleanup depending solely on `__del__`, which Python does not guarantee on crash, `SIGKILL`, or interpreter exit. An `atexit` handler is now registered at creation time to ensure the file is deleted even if the process exits abnormally. The explicit `close()` method and `__del__` remain as the primary cleanup path.

### NSKeyedUnArchiver fixes

**Bare `except:` swallowed all exceptions**
- The original code used a bare `except:` which catches `KeyboardInterrupt`, `SystemExit`, `MemoryError`, etc., masking real failures. Replaced with specific exception types (`plistlib.InvalidFileException`, `ValueError`, `KeyError`).

**Debug `print()` leaked data to stdout**
- An unconditional `print()` statement dumped arbitrary plist values — potentially sensitive backup data — to stdout. Replaced with `logging.debug()`.

**Logic bug: `finished` flag reset mid-loop**
- Inside the UID-resolution loop, a `finished=True` assignment in the `elif dict/list` branch could reset the flag set by an earlier `plistlib.UID` key in the same pass. This caused the while-loop to exit before all UIDs were resolved, leaving unresolved `plistlib.UID` objects in the output. Fixed by removing the premature reset.

## iOSbackup documentation

See [the original iOSbackup repo](https://github.com/avibrazil/iOSbackup) by Avi Alkalay.
