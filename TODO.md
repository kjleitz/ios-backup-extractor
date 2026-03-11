# TODO

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
