"""Fetching one file out of an archive on someone else's server.

Some data worth shipping is a single member of a multi-gigabyte archive on a
record that cannot be re-published, where downloading all of it to get one file
is not reasonable. Both formats handled here keep their directory at a known
place, so with HTTP range requests the whole archive never has to move: a few
requests find the directory, and only the member's own bytes follow.

:class:`_HTTPRangeFile` is the seekable file the readers work through, and
:class:`ArchiveMemberDownloader` is the pooch downloader
:meth:`~emdatabase.downloadable_dataset.DownloadableDataset._retrieve` hands to
:func:`pooch.retrieve` in place of :class:`pooch.HTTPDownloader` when an entry
names an ``archive``.

``.zip`` and ``.7z`` differ in what that costs. A zip compresses each member on
its own, so one member is read and streamed directly. 7z compresses files
together in solid blocks, so reaching a member means decompressing its block
from the start: cheap for a file at the front of a small block, expensive for
one at the back of a large one. Nothing here can change that - it is how the
archive was written - so the cost of a 7z entry is worth measuring before it is
added.
"""

from __future__ import annotations

import io
import os
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import IO, Any

import py7zr
from py7zr.callbacks import ExtractCallback

from emdatabase.downloadable_dataset import USER_AGENT, Progress

# A zip's directory is read in many small seeks, so an unbuffered reader would
# cost hundreds of requests before a single byte of the member moved.
_BUFFER_SIZE = 1 << 20


class ArchiveError(Exception):
    """The host will not serve the archive in a way one member can be read out of.

    Deliberately not an :class:`OSError`: ``zipfile`` turns any ``OSError``
    raised while it is reading the directory into
    ``BadZipFile("File is not a zip file")``, which would replace the real
    explanation with a wrong one.
    """


def _host(url: str) -> str:
    return urllib.parse.urlsplit(url).netloc


def _is_sevenzip(url: str) -> bool:
    """Which reader to use, taken from the link's own file name."""
    return urllib.parse.urlsplit(url).path.lower().endswith(".7z")


class _HTTPRangeFile(io.RawIOBase):
    """A seekable, read-only file over HTTP range requests.

    The archive readers only seek and read, so ranges stand in for a local copy.
    """

    def __init__(self, url: str, timeout: float = 120) -> None:
        self.url = url
        self.timeout = timeout
        self.pos = 0
        request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            declared = response.headers["Content-Length"]
        if declared is None:
            raise ArchiveError(
                f"{_host(url)} did not say how big {url} is, so the end of the archive - "
                "where its directory lives - cannot be found."
            )
        self.size = int(declared)

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            self.pos = offset
        elif whence == io.SEEK_CUR:
            self.pos += offset
        else:
            self.pos = self.size + offset
        return self.pos

    def readinto(self, buffer) -> int:  # pyright: ignore[reportMissingParameterType]
        if self.pos >= self.size:
            return 0
        end = min(self.pos + len(buffer), self.size) - 1
        request = urllib.request.Request(
            self.url,
            headers={"User-Agent": USER_AGENT, "Range": f"bytes={self.pos}-{end}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                # A host that does not do ranges answers 200 with the whole body.
                # Reading it would quietly pull the entire archive, which is the one
                # thing this exists to avoid, so it is an error rather than a
                # fallback.
                if response.status != 206:
                    raise ArchiveError(
                        f"{_host(self.url)} ignored a Range request and answered "
                        f"{response.status}, so fetching one member would mean downloading "
                        f"all {self.size} bytes of {self.url}."
                    )
                data = response.read()
        except OSError as error:
            # A host that answered the HEAD and then stopped serving - a 503
            # from one under load, a dropped connection, a range it will not
            # give - fails here as an OSError, and ``zipfile`` turns any OSError
            # raised while it reads the directory into
            # BadZipFile("File is not a zip file"). Reporting an outage as a
            # corrupt archive is the substitution ArchiveError exists to
            # prevent, so the transport failure is named rather than left to it.
            raise ArchiveError(
                f"{_host(self.url)} did not serve bytes {self.pos}-{end} of {self.url}: "
                f"{type(error).__name__}: {error}"
            ) from error
        buffer[: len(data)] = data
        self.pos += len(data)
        return len(data)


class _SevenZipProgress(ExtractCallback):
    """Drives a :class:`Progress` from py7zr's extract callbacks.

    py7zr reports once per file, after it has finished writing it, so a 7z
    member's bar stands at nothing and then jumps to full rather than filling as
    the bytes arrive. A cancel raised from ``update`` therefore cannot interrupt
    a 7z extraction the way it interrupts a zip's chunk loop; the bytes are
    already written by the time it is called. Giving 7z real streaming progress
    would mean driving ``extract``'s writer factory instead, which is worth
    doing only once an entry exists that is big enough to need it.
    """

    def __init__(self, bar: Progress) -> None:
        self._bar = bar

    def report_start_preparation(self) -> None: ...

    def report_start(self, processing_file_path: str, processing_bytes: str) -> None: ...

    def report_update(self, decompressed_bytes: str) -> None:
        self._bar.update(int(decompressed_bytes))

    def report_end(self, processing_file_path: str, wrote_bytes: str) -> None: ...

    def report_postprocess(self) -> None: ...

    def report_warning(self, message: str) -> None: ...


class ArchiveMemberDownloader:
    """A pooch downloader that pulls one member out of a remote archive.

    pooch calls a downloader as ``(url, output_file, pooch)`` from inside
    ``pooch.core.stream_download``, which streams to a temporary file, checks it
    against the entry's ``checksum`` and only then renames it into place,
    deleting the temporary file on any failure. So this only has to produce the
    member's bytes and drive ``progressbar`` the way :class:`pooch.HTTPDownloader`
    does: ``total`` once before the bytes, ``update(n)`` as they arrive, then
    ``reset()``, ``update(total)``, ``close()``.
    """

    def __init__(
        self,
        member: str,
        progressbar: Progress | None = None,
        chunk_size: int = 4096,
    ) -> None:
        self.member = member
        # pooch's `progressbar=True` - "build your own bar", which this does not
        # do - stops at _retrieve, which has already turned it into a Progress
        # or into nothing.
        self.progressbar = progressbar
        self.chunk_size = chunk_size

    def __call__(self, url: str, output_file: str, _pooch: Any = None) -> None:
        with io.BufferedReader(_HTTPRangeFile(url), buffer_size=_BUFFER_SIZE) as stream:  # pyright: ignore[reportArgumentType]
            if _is_sevenzip(url):
                self._from_7z(stream, url, output_file)
            else:
                self._from_zip(stream, url, output_file)
        bar = self.progressbar
        if bar:
            # The member's size is whatever the reader set the bar to; a second
            # copy of it threaded back through the return value could only
            # disagree with what the bar is actually showing.
            bar.reset()
            bar.update(bar.total)
            bar.close()

    def _missing(self, url: str) -> str:
        return (
            f"{url} holds no member {self.member!r}. Name the complete path inside "
            "the archive: one file name can appear in several of its directories."
        )

    def _from_zip(self, stream: IO[bytes], url: str, output_file: str) -> None:
        """Stream one zip member out; each is compressed on its own."""
        bar = self.progressbar
        with zipfile.ZipFile(stream) as archive:
            try:
                info = archive.getinfo(self.member)
            except KeyError:
                raise KeyError(self._missing(url)) from None
            if bar:
                bar.total = info.file_size
            with archive.open(info) as member, open(output_file, "wb") as out:
                while chunk := member.read(self.chunk_size):
                    out.write(chunk)
                    if bar:
                        bar.update(len(chunk))

    def _from_7z(self, stream: IO[bytes], url: str, output_file: str) -> None:
        """Extract one 7z member, which py7zr will only write to a directory."""
        bar = self.progressbar
        with py7zr.SevenZipFile(stream) as archive:
            wanted = next(
                (f for f in archive.list() if f.filename.replace("\\", "/") == self.member),
                None,
            )
            # py7zr extracts nothing, and raises nothing, for a name the archive
            # does not hold, so the failure has to be found here or the download
            # would end as a missing file with no explanation.
            if wanted is None:
                raise KeyError(self._missing(url))
            if bar:
                bar.total = wanted.uncompressed
            # Written beside pooch's temporary file, so the move is a rename
            # rather than a copy, and so a failure cleans up with the directory.
            with tempfile.TemporaryDirectory(dir=os.path.dirname(output_file)) as scratch:
                archive.extract(
                    path=scratch,
                    targets=[wanted.filename],
                    callback=_SevenZipProgress(bar) if bar else None,
                )
                os.replace(Path(scratch) / wanted.filename, output_file)
