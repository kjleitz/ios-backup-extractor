# Copyright (C) 2020 Avi Alkalay <avibrazil@gmail.com>
# Copyright (C) 2025 Keegan Leitz <kjleitz@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This file is part of ios-backup-extractor, a fork of iOSbackup.
# Refactored from iOSbackup/__init__.py, 2025 by Keegan Leitz.

import os
import sys
import logging
import plistlib

from datetime import datetime, timezone

import NSKeyedUnArchiverLocal


platformFoldersHint = {
    'darwin': '~/Library/Application Support/MobileSync/Backup',
    'win32': r'%APPDATA%\Apple Computer\MobileSync\Backup'
}

catalog = {
    'manifest': 'Manifest.plist',
    'manifestDB': 'Manifest.db',
    'info': 'Info.plist',
    'status': 'Status.plist'
}


def convertTime(timeToConvert, since2001=True):
    """Smart and static method that converts time values.
    If timeToConvert is an integer, it is considered as UTC Unix time and will be converted to a Python datetime object with timezone set on UTC.
    If timeToConvert is a Python datetime object, converts to UTC Unix time integer.
    If since2001 is True (default), integer values start at 2001-01-01 00:00:00 UTC, not 1970-01-01 00:00:00 UTC (as standard Unix time).
    """

    apple2001reference = datetime(2001, 1, 1, tzinfo=timezone.utc)

    if type(timeToConvert) == int or type(timeToConvert) == float:
        # convert from UTC timestamp to datetime.datetime python object on UTC timezone
        if since2001:
            return datetime.fromtimestamp(timeToConvert + apple2001reference.timestamp(), timezone.utc)
        else:
            return datetime.fromtimestamp(timeToConvert, timezone.utc)

    if isinstance(timeToConvert, datetime):
        # convert from timezone-aware datetime Python object to UTC UNIX timestamp
        if since2001:
            return (timeToConvert - apple2001reference).total_seconds()
        else:
            return timeToConvert.timestamp()


def isOlderThaniOS10dot2(version):
    """Return boolean whether the version is older than iOS 10.2

    Parameters
    ----------
    version : str,
        Version we want to compare. Assumes version is separated using point.
    """

    versions = version.split('.')
    if int(versions[0]) < 10:
        return True
    if int(versions[0]) > 10:
        return False
    if int(versions[0]) == 10:
        if len(versions) == 1:  # str is ios 10 only
            return True
        if int(versions[1]) < 2:
            return True
        else:
            return False


def getFileInfo(manifestData):
    """Given manifest data (as returned by getFileManifestDBEntry()), returns a
    dict of file metadata (size, time created, isFolder etc) and content of the file
    including passed manifestData itself in completeManifest key.
    """
    if type(manifestData) == dict:
        # Assuming this is biplist-processed plist file already converted into a dict
        manifest = manifestData
    elif type(manifestData) == bytes:
        # Interpret data stream and convert into a dict
        manifest = NSKeyedUnArchiverLocal.unserializeNSKeyedArchiver(manifestData)

    if "$version" in manifest:
        if manifest["$version"] == 100000:
            fileData = manifest["$objects"][1]
    else:
        fileData = manifest

    return {
        "size": fileData['Size'],
        "created": convertTime(fileData['Birth'], since2001=False),
        "lastModified": convertTime(fileData['LastModified'], since2001=False),
        "lastStatusChange": convertTime(fileData['LastStatusChange'], since2001=False),
        "mode": fileData['Mode'],
        "isFolder": True if fileData['Size'] == 0 and 'EncryptionKey' not in fileData else False,
        "userID": fileData['UserID'],
        "inode": fileData['InodeNumber'],
        "completeManifest": manifest
    }


def getHintedBackupRoot():
    """Get full path of best-match folder name containing iOS backups, based on your platform."""

    for plat in platformFoldersHint.keys():
        if sys.platform.startswith(plat):
            return os.path.expanduser(os.path.expandvars(platformFoldersHint[plat]))
    return None


def getDeviceBasicInfo(udid=None, backuproot=None):
    """Returns a dict of basic info about a device and its backup.
    Used by getDeviceList().

    Parameters
    ----------
    backuproot : str, optional
        Full path of folder that contains device backups. Uses platformFoldersHint if omitted.
    """
    info = None
    root = None

    if backuproot:
        root = os.path.expanduser(backuproot)
    else:
        root = getHintedBackupRoot()

    if udid and root:
        manifestFile = os.path.join(root, udid, catalog['manifest'])
        info = {}
        try:
            with open(manifestFile, 'rb') as infile:
                manifest = plistlib.load(infile)
        except FileNotFoundError:
            logging.warning(f"{udid} under {root} doesn't seem to have a manifest file.")
            return None
        info = {
            "udid": udid,
            "name": manifest['Lockdown']['DeviceName'],
            "ios": manifest['Lockdown']['ProductVersion'],
            "serial": manifest['Lockdown']['SerialNumber'],
            "type": manifest['Lockdown']['ProductType'],
            "encrypted": manifest['IsEncrypted'],
            "passcodeSet": manifest['WasPasscodeSet'],
            "date": convertTime(os.path.getmtime(manifestFile), since2001=False),
        }
    else:
        raise Exception("Need valid backup root folder path and a device UDID.")

    return info


def getDeviceList(backuproot=None):
    """Returns list of devices found under backuproot. Static method.

    Parameters
    ----------
    backuproot : str, optional
        Full path of folder that contains device backups. Uses platformFoldersHint if omitted.
    """

    result = []
    root = None

    if backuproot:
        root = os.path.expanduser(backuproot)
    else:
        root = getHintedBackupRoot()

    if root:
        (_, dirnames, _) = next(os.walk(root))

        for i in dirnames:
            result.append(getDeviceBasicInfo(udid=i, backuproot=root))

        return result
    else:
        raise Exception("Need valid backup root folder path passed through `backuproot`.")
