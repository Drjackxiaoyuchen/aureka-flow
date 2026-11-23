"""Bounded ordinary ZIP intake. Members are read in memory, never extracted."""
from contextlib import contextmanager
import io
import re
import stat
import struct
import zipfile


MAX_ARCHIVE_ENTRIES = 256
MAX_DIRECTORY_BYTES = 2 * 1024**2


def _check_directory_budget(data):
    # Classic EOCD fields, PKWARE APPNOTE 6.3.10 section 4.3.16.
    # Check limits before ZipFile allocates objects for the central directory.
    end = data.rfind(b"PK\x05\x06", max(0, len(data) - 65557))
    if end < 0 or end + 22 > len(data):
        raise ValueError("Incomplete or invalid ZIP. Finish exporting it and try again.")
    _, disk, directory_disk, disk_entries, entries, size, offset, comment = struct.unpack_from("<4s4H2IH", data, end)
    if end + 22 + comment != len(data):
        raise ValueError("Invalid ZIP end record. Re-export the archive.")
    if entries == 65535 or size == 0xffffffff or offset == 0xffffffff or data[max(0, end - 20):end - 16] == b"PK\x06\x07":
        raise ValueError("ZIP64 is not supported. Upload ordinary ZIP or individual FCS files.")
    if disk or directory_disk or disk_entries != entries:
        raise ValueError("Split ZIP archives are not supported. Upload one complete ZIP.")
    if entries > MAX_ARCHIVE_ENTRIES or size > MAX_DIRECTORY_BYTES:
        raise ValueError("ZIP directory limit: 256 entries / 2 MB. Choose a smaller archive.")
    if offset + size > end:
        raise ValueError("Incomplete ZIP directory. Finish exporting it and try again.")
    return entries


@contextmanager
def fcs_archive(data, *, file_limit, expanded_limit):
    expected_entries = _check_directory_budget(data)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) != expected_entries:
            raise ValueError("ZIP directory entry count is inconsistent. Re-export the archive.")
        samples, skipped, paths = [], [], set()
        for member in entries:
            if member.is_dir():
                continue
            path = member.orig_filename.replace("\\", "/")
            if not path.lower().endswith(".fcs") or "__MACOSX" in path.split("/") or path.split("/")[-1].startswith("._"):
                skipped.append({"member_path": path, "reason": "Not an FCS sample"})
                continue
            if ("\x00" in path or path.startswith("/") or re.match(r"^[A-Za-z]:", path)
                    or any(part in {"", ".", ".."} for part in path.split("/"))):
                raise ValueError("ZIP contains an unsafe FCS member path. Re-export relative sample paths.")
            if path in paths:
                raise ValueError("ZIP contains duplicate FCS member paths. Use unique sample paths.")
            paths.add(path)
            mode = stat.S_IFMT(member.external_attr >> 16)
            if mode not in {0, stat.S_IFREG}:
                raise ValueError("ZIP FCS members must be regular files, not links or special files.")
            if member.flag_bits & 1:
                raise ValueError("Encrypted FCS members are not supported. Upload an unencrypted export.")
            if member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise ValueError("Use stored or Deflate ZIP compression, or upload individual FCS files.")
            if member.file_size > file_limit:
                raise ValueError("An expanded FCS member exceeds the per-file upload limit.")
            samples.append(member)
        if not samples:
            raise ValueError("No FCS samples in this ZIP. Export FCS data, not a project/report archive.")
        if len(samples) > 24:
            raise ValueError("Choose at most 24 FCS samples per archive.")
        if sum(member.file_size for member in samples) > expanded_limit:
            raise ValueError("Expanded FCS data exceed the request budget. Choose a smaller batch.")
        yield archive, samples, skipped


def read_member(archive, member, file_limit):
    with archive.open(member) as handle:
        data = handle.read(min(file_limit, member.file_size) + 1)
    if len(data) != member.file_size or len(data) > file_limit:
        raise ValueError("Expanded FCS size does not match the ZIP directory or exceeds the upload limit.")
    return data
