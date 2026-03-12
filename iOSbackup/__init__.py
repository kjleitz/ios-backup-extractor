# Copyright (C) 2020 Avi Alkalay <avibrazil@gmail.com>
# Copyright (C) 2025 Keegan Leitz <kjleitz@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This file is part of ios-backup-extractor, a fork of iOSbackup.
# Modified 2025 by Keegan Leitz — see git log for details.

import atexit
import struct
import os
import sys
import textwrap
from importlib import import_module
import pprint
import tempfile
import sqlite3
import time
import mmap
import logging

from datetime import datetime, timezone
from pathlib import Path

import plistlib
import NSKeyedUnArchiverLocal

try:
    from Cryptodome.Cipher import AES
except ImportError:
    from Crypto.Cipher import AES  # https://www.dlitz.net/software/pycrypto/

from iOSbackup._crypto import (
    unpack64bit as _unpack64bit,
    pack64bit as _pack64bit,
    AESUnwrap as _AESUnwrap,
    removePadding as _removePadding,
    AESdecryptCBC as _AESdecryptCBC,
    loopTLVBlocks as _loopTLVBlocks,
)
from iOSbackup._util import (
    convertTime as _convertTime,
    isOlderThaniOS10dot2 as _isOlderThaniOS10dot2,
    getFileInfo as _getFileInfo,
    getHintedBackupRoot as _getHintedBackupRoot,
    getDeviceBasicInfo as _getDeviceBasicInfo,
    getDeviceList as _getDeviceList,
    platformFoldersHint as _platformFoldersHint,
    catalog as _catalog,
)


__version__ = '0.9.925'

module_logger = logging.getLogger(__name__)


class iOSbackup(object):
    """
    Class that reads and extracts files from a password-encrypted iOS backup created by
    iTunes on Mac and Windows. Compatible with iOS 13.

    You will need your backup password to decrypt the backup files, this is the password
    iTunes asks when it is configured to do encrypted backups. You should always prefer
    encrypted backups because they are more secure and include more files from your
    device. Non-encrypted backups do not backup files as Health app database
    and other preciosities.

    Common Usage
    ------------
    iOSbackup.getDeviceList()

    b=iOSbackup(udid="07349330-000327638962802E", derivedkey="dd61467e94c5dbdff780ddd9abdefb1b0e33b6426875a3e397cb47f351524")

    files=b.getBackupFilesList()

    b.getFileDecryptedCopy(relativePath="Library/Databases/CellularUsage.db")


    Attributes
    ----------
    backupRoot : str
        Full path of folder that contains device backups. On macOS this is ~/Library/Application Support/MobileSync/Backup
    udid : str
        The UDID of current device backup being handled.
    manifest : dict
        Device backup information as retrieved from Manifest.plist file
    manifestDB : str
        Full path of the usable decrypted copy of backup's Manifest.db file.
    platformFoldersHint : dict
        List of folders per platform used by iTunes to store device backups.
    decryptionKey : bytes
        The master backup decryption key derived directly from user's backup password.


    User Methods
    ------------
    iOSbackup()
        Constructor that delivers an initialized and usable instance of the class
    getHintedBackupRoot()
        Get full path of best-match folder name containing iOS backups, based on your platform.
    setBackupRoot()
        Set it explicitly if folder is different from what is known by platformFoldersHint
    getDeviceList()
        Returns list of devices found under backupRoot. Can be used as a static method.
    getDeviceBasicInfo()
        Static method that returns a dict of basic info about a device and its backup
    setDevice()
        Set the device by its UDID
    getBackupFilesList()
        Returns a dict with all device backup files catalogued in its Manifest.db
    getFileDecryptedCopy()
        Returns a dict with filename of a decrypted copy of certain file along with some file information
    getManifestDB()
        Returns full path name of a decrypted copy of Manifest.db
    getDecryptionKey()
        Returns decryptionKey as hex bytes


    Internal Methods
    ----------------
    deriveKeyFromPassword()
        Calculates, stores and return decryptionKey from user's clear text backup password
    loadKeys()
        Loads various encrypted decryption keys from Manifest.plist
    unlockKeys()
        Use decryptionKey to decrypt keys loaded by loadKeys()




    The process of accessing an encrypted iOS backup (encapsulated and made
    easier by this class) goes like this:

    1. Load encrypted keys (loadKeys()) from Manifest.plist file found on device's backup folder.
    2. Use Manifest.plist's parameters to derive a master decryption key (deriveKeyFromPassword()) from user's backup password (lengthy process), or use the provided derivedkey.
    3. Decrypt Manifest.plist's keys with derivedkey (unlockKeys())
    4. Use Manifest.plist decrypted keys to decrypt Manifest.db and save it unencrypted as a temporary file (getManifestDB()).
    5. Use decrypted version of Manifest.db SQLite database as a catalog to find and decrypt all other files of the backup.
    """

    # Most crypto code here from https://stackoverflow.com/a/13793043/367824

    platformFoldersHint = _platformFoldersHint
    catalog = _catalog

    WRAP_PASSCODE = 2

    CLASSKEY_TAGS = [b"CLAS", b"WRAP", b"WPKY", b"KTYP", b"PBKY"]  #UUID

    def __del__(self):
        self.close()



    def close(self):
        try:
            if self.manifestDB is not None and self.decryptionKey:
                os.remove(self.manifestDB)
        except FileNotFoundError:
            # Its OK if manifest temporary file is not there anymore
            pass



    def __init__(self, udid, cleartextpassword=None, derivedkey=None, backuproot=None):
        """Constructor that delivers an initialized and usable instance of the class.

        Parameters
        ----------
        backuproot : str, optional
            Full path of folder that contains device backups. Uses platformFoldersHint if omitted.
        udid : str
            The UDID (and folder name) of device that you want to access its backup.
        cleartextpassword : str, optional
            User's backup password. Avoid passing this directly — it will appear in shell
            history and REPL transcripts. Omit it and you will be prompted securely instead.
        derivedkey : str, optional
            The master backup decryption key derived directly from user's backup password.
            Preferred over cleartextpassword: compute it once, save it securely, and reuse
            it to avoid entering the raw password again.
        """
        self.setBackupRoot(backuproot)
        self.udid = udid
        self.date = None  # modification time of Manifest.plist is backup time, set by loadKeys()
        self.decryptionKey = None
        self.attrs = {}
        self.uuid = None
        self.wrap = None
        self.classKeys = {}
        self.manifest = None
        self.manifestDB = None


        self.loadManifest()
        self.loadKeys()

        if derivedkey:
            if type(derivedkey) == str:
                self.decryptionKey = bytes.fromhex(derivedkey)
            else:
                self.decryptionKey = derivedkey
        elif self.manifest.get('IsEncrypted'):
            if cleartextpassword:
                pw = bytearray(cleartextpassword.encode('utf-8'))
            else:
                import getpass
                pw = bytearray(getpass.getpass('Backup password: ').encode('utf-8'))
            try:
                self.deriveKeyFromPassword(pw)
            finally:
                for i in range(len(pw)):
                    pw[i] = 0

        # Now that we have backup password set as primary decryption key...

        # 1. Get decryption keys for everything else
        self.unlockKeys()

        # 2. Get master catalog of backup files (a SQLite database)
        self.getManifestDB()




    def __repr__(self):
        """Prints a lot of information about an opened backup"""

        template = textwrap.dedent("""\
            backup root folder: {backupRoot}
            device ID: {udid}
            date: {date}
            uuid: {uuid}
            device name: {name}
            device type: {type}
            iOS version: {ios}
            serial: {serial}
            manifest[IsEncrypted]: {IsEncrypted}
            manifest[WasPasscodeSet]: {PasscodeSet}
            decrypted manifest DB: {manifestDB}
            decryptionKey: {decryptionKey}
            manifest[ManifestKey]: {ManifestKey}
            attr: {attrs}
            classKeys: {classKeys}
            wrap: {wrap}
            manifest[Applications]: {Applications}""")

        return template.format(
            backupRoot=self.backupRoot,
            udid=self.udid,
            date=self.date,
            decryptionKey="<redacted — call getDecryptionKey() explicitly>",
            uuid=self.uuid.hex(),
            attrs=pprint.pformat(self.attrs, indent=4),
            wrap=self.wrap,
            classKeys=pprint.pformat(self.classKeys, indent=4),
            IsEncrypted=self.manifest['IsEncrypted'],
            PasscodeSet=self.manifest['WasPasscodeSet'],
            ManifestKey='Not applicable' if iOSbackup.isOlderThaniOS10dot2(self.manifest['Lockdown']['ProductVersion']) else self.manifest['ManifestKey'].hex(),
            Applications=pprint.pformat(self.manifest['Applications'], indent=4),
            manifestDB=self.manifestDB,
            name=self.manifest['Lockdown']['DeviceName'],
            ios=self.manifest['Lockdown']['ProductVersion'],
            serial=self.manifest['Lockdown']['SerialNumber'],
            type=self.manifest['Lockdown']['ProductType']
        )




    def getDecryptionKey(self) -> str:
        """Decryption key is tha master blob to decrypt everything in the iOS backup.
        It is calculated by deriveKeyFromPassword() from the clear text iOS backup password.
        """

        return self.decryptionKey.hex()




    # -------------------------------------------------------------------------
    # Public static-like API — thin wrappers delegating to module functions
    # so that iOSbackup.convertTime(...) etc. continue to work unchanged.
    # -------------------------------------------------------------------------

    def convertTime(timeToConvert, since2001=True):
        return _convertTime(timeToConvert, since2001)

    def isOlderThaniOS10dot2(version):
        return _isOlderThaniOS10dot2(version)

    def getFileInfo(manifestData):
        return _getFileInfo(manifestData)

    def getHintedBackupRoot():
        return _getHintedBackupRoot()

    def getDeviceBasicInfo(udid=None, backuproot=None):
        return _getDeviceBasicInfo(udid, backuproot)

    def getDeviceList(backuproot=None):
        return _getDeviceList(backuproot)

    def unpack64bit(s):
        return _unpack64bit(s)

    def pack64bit(s):
        return _pack64bit(s)

    def AESUnwrap(kek=None, wrapped=None):
        return _AESUnwrap(kek, wrapped)

    def removePadding(blocksize, s):
        return _removePadding(blocksize, s)

    def AESdecryptCBC(data, key, iv=b'\x00'*16, padding=False):
        return _AESdecryptCBC(data, key, iv, padding)

    def loopTLVBlocks(blob):
        return _loopTLVBlocks(blob)

    # -------------------------------------------------------------------------
    # Instance methods
    # -------------------------------------------------------------------------

    def setBackupRoot(self, path=None):
        """Set it explicitly if folder is different from what is known by platformFoldersHint

        Parameters
        ----------
        path : str, optional
            Full path of folder that contains device backups. Uses platformFoldersHint if omitted.
        """

        if path is not None:
            self.backupRoot = os.path.expanduser(os.path.expandvars(path))
        else:
            self.backupRoot = iOSbackup.getHintedBackupRoot()




    def setDevice(self, udid=None):
        """Set the device by its UDID"""

        self.udid = udid




    def getBackupFilesList(self):
        """Returns a dict with all device backup files catalogued in its Manifest.db"""

        if not self.manifestDB:
            raise Exception("Object not yet innitialized or can't find decrypted files catalog ({})".format(iOSbackup.catalog['manifestDB']))

        catalog = sqlite3.connect(self.manifestDB)
        catalog.row_factory = sqlite3.Row

        backupFiles = catalog.cursor().execute(f"SELECT * FROM Files ORDER BY domain,relativePath").fetchall()

        result = []
        for f in backupFiles:
            info = {
                "name": f['relativePath'],
                "backupFile": f['fileID'],
                "domain": f['domain'],
                **f
            }
            result.append(info)

        return result




    def getFolderDecryptedCopy(self, relativePath=None, targetFolder=None, temporary=False, includeDomains=None, excludeDomains=None, includeFiles=None, excludeFiles=None):
        """Recreates under targetFolder an entire folder (relativePath) found into an iOS backup.

        Parameters
        ----------
        relativePath : str
            Semi full path name of a backup file. Something like 'Media/PhotoData/Metadata'
        targetFolder : str, optional
            Folder where to store decrypted files, creates the folder tree under current folder if omitted.
        temporary : str, optional
            Creates a temporary file (using tempfile module) in a temporary folder. Use targetFolder if omitted.
        includeDomains : str, list, optional
            Retrieve files only from this single or list of iOS backup domains.
        excludeDomains : str, list, optional
            Retrieve files from all but this single or list of iOS backup domains.
        includeFiles : str, list, optional
            SQL friendly file name matches. For example "%JPG" will retrieve only files ending with JPG. Pass a list of filters to be more effective.
        excludeFiles : str, list, optional
            SQL friendly file name matches to exclude. For example "%MOV" will retrieve all but files ending with MOV. Pass a list of filters to be more effective.

        Returns
        -------
        List of dicts with info about all files retrieved.
        """

        if not self.manifestDB:
            raise Exception("Object not yet innitialized or can't find decrypted files catalog ({})".format(iOSbackup.catalog['manifestDB']))

        if not relativePath:
            relativePath = ''
            if not includeDomains:
                raise Exception("relativePath and includeDomains cannot be empty at the same time")

        if temporary:
            targetRootFolder = tempfile.TemporaryDirectory(suffix=f"---{fileName}", dir=targetFolder)
            targetRootFolder = targetRootFolder.name
        else:
            if targetFolder:
                targetRootFolder = targetFolder
            else:
                targetRootFolder = '.'

        whereClauses = ["relativePath LIKE ?"]
        params = [f"{relativePath}%"]

        if includeDomains:
            if isinstance(includeDomains, list):
                whereClauses.append(f"domain IN ({','.join('?' * len(includeDomains))})")
                params.extend(includeDomains)
            else:
                whereClauses.append("domain = ?")
                params.append(includeDomains)

        if excludeDomains:
            if isinstance(excludeDomains, list):
                whereClauses.append(f"domain NOT IN ({','.join('?' * len(excludeDomains))})")
                params.extend(excludeDomains)
            else:
                whereClauses.append("domain != ?")
                params.append(excludeDomains)

        if includeFiles:
            if isinstance(includeFiles, list):
                whereClauses.append("(" + " OR ".join(["relativePath LIKE ?"] * len(includeFiles)) + ")")
                params.extend(includeFiles)
            else:
                whereClauses.append("relativePath LIKE ?")
                params.append(includeFiles)

        if excludeFiles:
            if isinstance(excludeFiles, list):
                whereClauses.append("(" + " AND ".join(["relativePath NOT LIKE ?"] * len(excludeFiles)) + ")")
                params.extend(excludeFiles)
            else:
                whereClauses.append("relativePath NOT LIKE ?")
                params.append(excludeFiles)

        db = sqlite3.connect(self.manifestDB)
        db.row_factory = sqlite3.Row

        query = "SELECT * FROM Files WHERE {} ORDER BY domain, relativePath".format(" AND ".join(whereClauses))

        backupFiles = db.cursor().execute(query, params).fetchall()

        fileList = []
        for payload in backupFiles:
            payload = dict(payload)
            payload['manifest'] = NSKeyedUnArchiverLocal.unserializeNSKeyedArchiver(payload['file'])
            del payload['file']

            # Compute target file with path
            physicalTarget = os.path.join(targetRootFolder, payload['domain'], payload['relativePath'])

            # Guard against path traversal via crafted domain/relativePath in the backup
            realTarget = os.path.realpath(physicalTarget)
            realRoot = os.path.realpath(targetRootFolder)
            if not realTarget.startswith(realRoot + os.sep):
                raise ValueError(f"Path traversal detected: {physicalTarget!r} escapes target root {targetRootFolder!r}")

            # Create parent folder to contain it
            Path(os.path.dirname(physicalTarget)).mkdir(parents=True, exist_ok=True)

            info = self.getFileDecryptedCopy(
                manifestEntry=payload,
                targetFolder=os.path.dirname(physicalTarget),
                targetName=os.path.basename(physicalTarget)
            )

            fileList.append(info)

        db.close()
        return fileList




    def getDomains(self):
        """Returns a list of all backup domains found in this backup.
        """
        if not self.manifestDB:
            raise Exception("Object not yet innitialized or can't find decrypted files catalog ({})".format(iOSbackup.catalog['manifestDB']))

        db = sqlite3.connect(self.manifestDB)
        db.row_factory = sqlite3.Row

        domains = db.cursor().execute(f"SELECT DISTINCT domain FROM Files").fetchall()

        db.close()

        return [i['domain'] for i in domains]




    def getFileManifestDBEntry(self, fileNameHash=None, relativePath=None):
        """Get the Manifest DB entry for a file either from its file name hash or relative file name.
        File name hash is more precise because its unique, while the relative file name may appear under multiple backup domains.

        Parameters
        ----------
        relativePath : str
            Semi full path name of a backup file. Something like 'Media/PhotoData/Metadata'
        fileNameHash : str
            Hashed filename as can be seen under iOS backup folder.

        Returns
        -------
        A dict with catalog entry about the file along with its manifest.

        """
        if fileNameHash is None and relativePath is None:
            raise Exception(f"Either fileNameHash or relativePath must be provided")

        if not self.manifestDB:
            raise Exception("Object not yet innitialized or can't find decrypted files catalog ({})".format(iOSbackup.catalog['manifestDB']))

        db = sqlite3.connect(self.manifestDB)
        db.row_factory = sqlite3.Row

        if relativePath:
            backupFile = db.cursor().execute("SELECT * FROM Files WHERE relativePath=? ORDER BY domain LIMIT 1", (relativePath,)).fetchone()
        else:
            backupFile = db.cursor().execute("SELECT * FROM Files WHERE fileID=? ORDER BY domain LIMIT 1", (fileNameHash,)).fetchone()

        db.close()

        if backupFile:
            payload = dict(backupFile)
            payload['manifest'] = NSKeyedUnArchiverLocal.unserializeNSKeyedArchiver(payload['file'])
            del payload['file']
        else:
            if relativePath:
                raise(FileNotFoundError(f"Can't find backup entry for relative path «{relativePath}» on catalog"))
            else:
                raise(FileNotFoundError(f"Can't find backup entry for «{fileNameHash}» on catalog"))

        return payload




    def getFileDecryptedData(self, fileNameHash, manifestData):
        """Given a backup file hash along with its manifest data (as returned by getFileManifestDBEntry()), returns a
        dict of file metadata and the decrypted content of the file. This is the memory-only version of getFileDecryptedCopy().

        Do not use this method with large files as 4K videos.
        Those can easily reach 2GB or 3GB in size and burn your entire RAM.
        """

        info = iOSbackup.getFileInfo(manifestData)

        fileData = info['completeManifest']

        dataDecrypted = None
        if 'EncryptionKey' in fileData:
            encryptionKey = info['completeManifest']['EncryptionKey'][4:]

            # {BACKUP_ROOT}/{UDID}/ae/ae2c3d4e5f6...
            with open(os.path.join(self.backupRoot, self.udid, fileNameHash[:2], fileNameHash), 'rb') as infile:
                dataEncrypted = infile.read()

            key = self.unwrapKeyForClass(fileData['ProtectionClass'], encryptionKey)

            # See https://github.com/avibrazil/iOSbackup/issues/1
            dataDecrypted = iOSbackup.AESdecryptCBC(dataEncrypted, key, padding=True)

        return (info, dataDecrypted)




    def getRelativePathDecryptedData(self, relativePath):
        """Given a domain-relative file path as `Media/PhotoData/AlbumsMetadata/abc123.jpg`,
        find its manifest info in backup metadata and return file contents along with metadata.

        Do not use this method with large files as 4K videos.
        Those can easily reach 2GB or 3GB in size and burn your entire RAM.
        """
        if not relativePath:
            return None

        backupFile = self.getFileManifestDBEntry(relativePath=relativePath)

        (info, dataDecrypted) = self.getFileDecryptedData(fileNameHash=backupFile['fileID'], manifestData=backupFile['manifest'])

        # Add more information to the returned info dict
        info['originalFilePath'] = relativePath
        info['domain'] = backupFile['domain']
        info['backupFile'] = backupFile['fileID']

        return (info, dataDecrypted)




    def getFileDecryptedCopy(self, relativePath=None, manifestEntry=None, targetName=None, targetFolder=None, temporary=False):
        """Returns a dict with filename of a decrypted copy of certain file along with some file information
        Either relativePath or manifestEntry must be provided.

        Parameters
        ----------
        relativePath : str
            Semi full path name of a backup file. Something like 'Library/CallHistoryDB/CallHistory.storedata'.
        manifestEntry : dict
            A dict containing 'file' as the file manifest data, 'fileID' as backup file name and 'domain'.
        targetName : str, optional
            File name on targetFolder where to save decrypted data. Uses something like 'HomeDomain~Library--CallHistoryDB--CallHistory.storedata' if omitted.
        targetFolder : str, optional
            Folder where to store decrypted file, saves on current folder if omitted.
        temporary : str, optional
            Creates a temporary file (using tempfile module) in a temporary folder. Use targetFolder if omitted.

        Returns
        -------
        A dict of metadata about the file.
        """

        if relativePath:
            manifestEntry = self.getFileManifestDBEntry(relativePath=relativePath)

        if manifestEntry:
            info = iOSbackup.getFileInfo(manifestEntry['manifest'])
            fileNameHash = manifestEntry['fileID']
            domain = manifestEntry['domain']
            relativePath = manifestEntry['relativePath']
        else:
            return None

        fileData = info['completeManifest']

        if targetName:
            fileName = targetName
        else:
            fileName = '{domain}~{modifiedPath}'.format(domain=domain, modifiedPath=relativePath.replace('/', '--'))

        if temporary:
            targetFileName = tempfile.NamedTemporaryFile(suffix=f"---{fileName}", dir=targetFolder, delete=True)
            targetFileName = targetFileName.name
        else:
            if targetFolder:
                targetFileName = os.path.join(targetFolder, fileName)
            else:
                targetFileName = fileName


        if 'EncryptionKey' in fileData:
            # Encrypted file
            encryptionKey = fileData['EncryptionKey'][4:]
            key = self.unwrapKeyForClass(fileData['ProtectionClass'], encryptionKey)

            chunkSize = 16*1000000  # 16MB chunk size

            decryptor = AES.new(key, AES.MODE_CBC, b'\x00'*16)

            # {BACKUP_ROOT}/{UDID}/ae/ae2c3d4e5f6...
            with open(os.path.join(self.backupRoot, self.udid, fileNameHash[:2], fileNameHash), 'rb') as inFile:
                if os.name == 'nt':
                    mappedInFile = mmap.mmap(inFile.fileno(), length=0, access=mmap.ACCESS_READ)
                else:
                    mappedInFile = mmap.mmap(inFile.fileno(), length=0, prot=mmap.PROT_READ)

                with open(targetFileName, 'wb') as outFile:

                    chunkIndex = 0
                    while True:
                        chunk = mappedInFile[chunkIndex*chunkSize:(chunkIndex+1)*chunkSize]

                        if len(chunk) == 0:
                            break

                        outFile.write(decryptor.decrypt(chunk))
                        chunkIndex += 1

                    outFile.truncate(info['size'])
        elif info['isFolder']:
            # Plain folder
            Path(targetFileName).mkdir(parents=True, exist_ok=True)
        else:
            # Case for decrypted file: simply copy and rename
            import shutil

            shutil.copyfile(
                # {BACKUP_ROOT}/{UDID}/ae/ae2c3d4e5f6...
                src=os.path.join(self.backupRoot, self.udid, fileNameHash[:2], fileNameHash),
                dst=targetFileName,
                follow_symlinks=True
            )


        # Set file modification date and localtime time as per device's
        mtime = time.mktime(info['lastModified'].astimezone(tz=None).timetuple())
        os.utime(targetFileName, (mtime, mtime))

        # Add more information to the returned info dict
        info['decryptedFilePath'] = targetFileName

        return info




    def getManifestDB(self):
        """Returns full path name of a decrypted copy of Manifest.db. Used internally."""
        if not self.decryptionKey:
            self.manifestDB = os.path.join(self.backupRoot, self.udid, iOSbackup.catalog['manifestDB'])
            return

        with open(os.path.join(self.backupRoot, self.udid, iOSbackup.catalog['manifestDB']), 'rb') as db:
            encrypted_db = db.read()

        # Before iOS 10.2 the manifest database was not encrypted in the backups. So, there is no need for decryption.
        # Also, the ManifestKey is not presented in the Plist, so all references to 'ManifestKey' would result in KeyError
        if iOSbackup.isOlderThaniOS10dot2(self.manifest['Lockdown']['ProductVersion']):
            decrypted_data = encrypted_db
        else:
            manifest_class = struct.unpack('<l', self.manifest['ManifestKey'][:4])[0]
            manifest_key   = self.manifest['ManifestKey'][4:]

            key = self.unwrapKeyForClass(manifest_class, manifest_key)

            decrypted_data = iOSbackup.AESdecryptCBC(encrypted_db, key)

        file = tempfile.NamedTemporaryFile(suffix="--"+iOSbackup.catalog['manifestDB'], delete=False)
        self.manifestDB = file.name
        file.write(decrypted_data)
        file.close()
        atexit.register(self.close)




    def loadManifest(self):
        """Load the very initial metadata files of an iOS backup"""
        manifestFile = os.path.join(self.backupRoot, self.udid, iOSbackup.catalog['manifest'])

        self.date = iOSbackup.convertTime(os.path.getmtime(manifestFile), since2001=False)

        with open(manifestFile, 'rb') as infile:
            self.manifest = plistlib.load(infile)

        infoFile = os.path.join(self.backupRoot, self.udid, iOSbackup.catalog['info'])
        with open(infoFile, 'rb') as infile:
            self.info = plistlib.load(infile)

        statusFile = os.path.join(self.backupRoot, self.udid, iOSbackup.catalog['status'])
        with open(statusFile, 'rb') as infile:
            self.status = plistlib.load(infile)




    def loadKeys(self):
        backupKeyBag = self.manifest['BackupKeyBag']
        currentClassKey = None

        for tag, data in iOSbackup.loopTLVBlocks(backupKeyBag):
            if len(data) == 4:
                data = struct.unpack(">L", data)[0]
            if tag == b"TYPE":
                self.type = data
                if self.type > 3:
                    print("FAIL: keybag type > 3 : %d" % self.type)
            elif tag == b"UUID" and self.uuid is None:
                self.uuid = data
            elif tag == b"WRAP" and self.wrap is None:
                self.wrap = data
            elif tag == b"UUID":
                if currentClassKey:
                    self.classKeys[currentClassKey[b"CLAS"]] = currentClassKey
                currentClassKey = {b"UUID": data}
            elif tag in self.CLASSKEY_TAGS:
                currentClassKey[tag] = data
            else:
                self.attrs[tag] = data
        if currentClassKey:
            self.classKeys[currentClassKey[b"CLAS"]] = currentClassKey




    def deriveKeyFromPassword(self, cleanpassword=None):
        # Try to use fastpbkdf2.pbkdf2_hmac().
        # Fallback to Pythons default hashlib.pbkdf2_hmac() if not found.

        try:
            hlib = import_module('fastpbkdf2')
        except:
            hlib = import_module('hashlib')

        # if the ios is older that 10.2, the stage with the DPSL and DPIC are not used in the key derivation
        if iOSbackup.isOlderThaniOS10dot2(self.manifest['Lockdown']['ProductVersion']):
            temp = cleanpassword
            temp_is_intermediate = False
        else:
            temp = bytearray(hlib.pbkdf2_hmac('sha256', cleanpassword,
                self.attrs[b"DPSL"],
                self.attrs[b"DPIC"], 32))
            temp_is_intermediate = True

        try:
            self.decryptionKey = hlib.pbkdf2_hmac('sha1', temp,
                self.attrs[b"SALT"],
                self.attrs[b"ITER"], 32)
        finally:
            if temp_is_intermediate:
                for i in range(len(temp)):
                    temp[i] = 0

        return self.decryptionKey




    def unlockKeys(self):
        if not self.decryptionKey:
            return True
        for classkey in self.classKeys.values():
            if b"WPKY" not in classkey:
                continue

            if classkey[b"WRAP"] & self.WRAP_PASSCODE:
                k = iOSbackup.AESUnwrap(self.decryptionKey, classkey[b"WPKY"])

                if not k:
                    raise Exception('Failed decrypting backup. Try to start over with a clear text decrypting password on parameter "cleartextpassword".')

                classkey[b"KEY"] = k

        return True




    def unwrapKeyForClass(self, protection_class, persistent_key):
        if len(persistent_key) != 0x28:
            raise Exception("Invalid key length")

        ck = self.classKeys[protection_class][b"KEY"]

        return iOSbackup.AESUnwrap(ck, persistent_key)
