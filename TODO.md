# TODO

## Migration: Rename & Re-home as ios-backup-extractor

### Upstream Licenses

- **iOSbackup** (https://github.com/avibrazil/iOSbackup) by Avi Alkalay
  - Declared license: LGPL (in pyproject.toml classifiers)
  - No LICENSE file was committed to the repo
- **NSKeyedUnArchiver** (https://github.com/avibrazil/NSKeyedUnArchiver) by Avi Alkalay
  - License: GPL v3 (full LICENSE file present)

Since one upstream is GPL v3, the combined project must be GPL v3 (GPL is the
more restrictive of the two and LGPL is forward-compatible with GPL).

### 1. Add LICENSE file
- [x] Add a GPL v3 LICENSE file to the repo root (copy from NSKeyedUnArchiver)

### 2. Bring NSKeyedUnArchiverLocal into this repo
- [x] Copy `NSKeyedUnArchiverLocal/` package directory into this repo
- [x] Copy remaining upstream files to `NSKeyedUnArchiver-upstream/` for reference
- [x] Remove old `../NSKeyedUnArchiver-local` directory
- [x] Update `pyproject.toml` to remove the local-path dependency
- [x] Update `[tool.setuptools.packages.find]` to include `NSKeyedUnArchiverLocal*`
- [x] Verify imports still work

### 3. Rename project to ios-backup-extractor
- [x] Update `pyproject.toml`: name, urls, package find config
- [ ] Decide: rename the `iOSbackup/` directory itself or keep it for now?
      (Renaming the importable package is a bigger change — may want a separate task)

### 4. Update README.md
- [x] Add a prominent "Fork Notice" section at the top
- [x] Remove the donation section
- [x] Update installation instructions for the new project name
- [ ] Update remaining GitHub links in body to point to the new repo

### 5. Change git remote origin
- [x] `git remote set-url origin https://github.com/kjleitz/ios-backup-extractor.git`

---

## Feature Work

- [ ] Render tapbacks inline on the parent message bubble
- [ ] Button in the messages HTML UI to trigger HEIC→JPEG conversion
- [ ] Pull contact photo from `Library/AddressBook/AddressBookImages.sqlitedb` and embed in per-contact folder
- [ ] Cross-reference contacts into messages index (show display name instead of phone/email)
- [ ] Cross-reference contacts into voicemails output (show display name)
- [ ] Extractor: call history — `Library/CallHistoryDB/CallHistory.storedata` (CoreData)
- [ ] Extractor: photos — `Media/DCIM/**/*.{JPG,HEIC,MOV}` (add size/date filters)

## Reach

- [ ] Group chats: per-sender labels and color coding
- [ ] Thread / reply-to visual nesting (reply_to_guid is already in the JSON)
- [ ] Shared CLI argument parser to deduplicate `--udid`/`--derivedkey`/`--backuproot` across extractors
- [ ] `extractors/all.py` — run all extractors in sequence with one login prompt
- [ ] Calendar — `Library/Calendar/Calendar.sqlitedb`
- [ ] Notes — `Library/Notes/NoteStore.sqlite`
- [ ] Safari bookmarks / history — `Library/Safari/Bookmarks.db`, `History.db`
- [ ] Health — `Library/Health/healthdb_secure.sqlite`
