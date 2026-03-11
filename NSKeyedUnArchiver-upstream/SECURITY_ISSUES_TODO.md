# Security Issues TODO

Audit of NSKeyedUnArchiver and iOSbackup (../iOSbackup) for safe use against a personal iOS backup.

---

## NSKeyedUnArchiver — `NSKeyedUnArchiver/__init__.py`

### [x] 1. Bare `except:` swallows all exceptions (line 28–30)
**Severity:** Low
**File:** `NSKeyedUnArchiver/__init__.py`
**Problem:** `except:` catches `KeyboardInterrupt`, `SystemExit`, `MemoryError`, etc., masking real failures.
**Fix:** Replace with `except Exception:` or more specifically `except (plistlib.InvalidFileException, ValueError, KeyError):`.

```python
# Current (bad)
except:
    return reassembled

# Fixed
except (plistlib.InvalidFileException, ValueError, KeyError):
    return reassembled
```

---

### [x] 2. `print()` debug statement leaks data to stdout (line 36)
**Severity:** Low
**File:** `NSKeyedUnArchiver/__init__.py`
**Problem:** `print("reassembled is a " + str(type(reassembled)) + ":" + str(reassembled))` dumps arbitrary plist values — potentially sensitive backup data — to stdout unconditionally.
**Fix:** Replace with `module_logger.debug(...)`.

---

### [x] 3. Logic bug: `finished=True` resets UID-pass flag mid-loop (line 90)
**Severity:** Low (correctness, not security)
**File:** `NSKeyedUnArchiver/__init__.py`
**Problem:** Inside the `for k in cursor` loop, if a `plistlib.UID` sets `finished=False` and a subsequent key triggers the `elif dict/list` branch, `finished=True` at line 90 resets the flag. The while-loop then exits before all UIDs in the same pass are resolved, leaving unresolved `plistlib.UID` objects in the output.
**Fix:** Remove the `finished=True` at line 90; the `True` at the top of the while-loop is sufficient.

---

## iOSbackup — `../iOSbackup/iOSbackup/__init__.py`

### [x] 4. SQL injection in `getFolderDecryptedCopy` (lines 400–451)
**Severity:** Medium (high if ever used on untrusted backups or exposed as a service)
**File:** `../iOSbackup/iOSbackup/__init__.py`
**Problem:** `relativePath`, `includeDomains`, `excludeDomains`, `includeFiles`, and `excludeFiles` are all interpolated directly into SQL strings. A tampered backup's Manifest.db or a crafted caller argument can inject arbitrary SQL.
**Fix:** Build the WHERE clause using parameterized queries with `?` placeholders and a separate params list. Use `IN (?,?,?)` patterns for list arguments.

```python
# Example of correct parameterized approach
params = [f"{relativePath}%"]
where = "relativePath LIKE ?"
cursor.execute(f"SELECT * FROM Files WHERE {where} ORDER BY domain, relativePath", params)
```

---

### [x] 5. Path traversal when writing decrypted files (line 460)
**Severity:** Medium (exploitable with a tampered backup)
**File:** `../iOSbackup/iOSbackup/__init__.py`
**Problem:** `domain` and `relativePath` from Manifest.db are joined directly into the output path with no boundary check. A crafted backup containing `domain = "../../"` or `relativePath = "../../../../etc/cron.d/evil"` could write files outside the intended target folder.
**Fix:** After constructing the target path, assert it is still rooted under `targetRootFolder` using `os.path.realpath`:

```python
physicalTarget = os.path.join(targetRootFolder, payload['domain'], payload['relativePath'])
realTarget = os.path.realpath(physicalTarget)
realRoot = os.path.realpath(targetRootFolder)
if not realTarget.startswith(realRoot + os.sep):
    raise ValueError(f"Path traversal detected: {physicalTarget!r} escapes {targetRootFolder!r}")
```

---

### [x] 6. Master decryption key printed by `__repr__` (line 233)
**Severity:** High (operational risk — key ends up in logs/terminals)
**File:** `../iOSbackup/iOSbackup/__init__.py`
**Problem:** `repr(b)` / `print(b)` on an `iOSbackup` instance emits the full master decryption key in hex. This key decrypts the entire backup; exposing it in terminal output, log files, or crash reports is a serious data leak.
**Fix:** Redact the key in `__repr__`:

```python
# Instead of:
decryptionKey=self.getDecryptionKey(),
# Use:
decryptionKey="<redacted — call getDecryptionKey() explicitly>",
```

---

### [x] 7. Plaintext `Manifest.db` temp file may persist after crash
**Severity:** Low–Medium
**File:** `../iOSbackup/iOSbackup/__init__.py`
**Problem:** `tempfile.NamedTemporaryFile(delete=False)` creates the decrypted Manifest.db on disk. Cleanup depends on `__del__` → `close()`. Python does not guarantee `__del__` runs on crash, SIGKILL, or interpreter exit, leaving plaintext backup metadata on disk.
**Fix:** Register an `atexit` handler and/or a `signal` handler for `SIGTERM` as a safety net in addition to `__del__`. Consider using a `tempfile.TemporaryDirectory` with a context manager at the call site.

```python
import atexit
# After writing the temp file:
atexit.register(self.close)
```

---

### [x] 8. `cleartextpassword` persists in memory
**Severity:** Low
**File:** `../iOSbackup/iOSbackup/__init__.py`
**Problem:** The cleartext backup password passed to `__init__` lives in Python's memory as a string (which is immutable and cannot be zeroed) and may appear in stack traces, core dumps, or process memory snapshots. The library already recommends using `derivedkey` instead.
**Fix:** Add a prominent warning in the docstring. After calling `deriveKeyFromPassword`, store only the derived key, not the original password. Document that callers should compute `derivedkey` once, save it, and use it on subsequent runs.

---

## Priority Order

| # | Issue | Repo | Severity |
|---|-------|------|----------|
| 6 | Decryption key in `__repr__` | iOSbackup | High |
| 4 | SQL injection in `getFolderDecryptedCopy` | iOSbackup | Medium |
| 5 | Path traversal on file write | iOSbackup | Medium |
| 7 | Temp file not cleaned up on crash | iOSbackup | Low–Medium |
| 1 | Bare `except:` | NSKeyedUnArchiver | Low |
| 2 | `print()` debug leak | NSKeyedUnArchiver | Low |
| 3 | `finished` flag logic bug | NSKeyedUnArchiver | Low |
| 8 | `cleartextpassword` in memory | iOSbackup | Low |
