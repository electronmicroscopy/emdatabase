"""Fetching one file out of a zip on someone else's server.

Some data worth shipping is a single member of a multi-gigabyte archive on a
record that cannot be re-published, where downloading all of it to get one file
is not reasonable. A zip's directory sits at its end and names the byte range of
every member, so with HTTP range requests the whole archive never has to move:
three requests find the directory, and the member costs its own stored bytes.

:class:`_HTTPRangeFile` is the seekable file ``zipfile`` reads that through, and
:class:`ArchiveMemberDownloader` is the pooch downloader
:meth:`~emdatabase.downloadable_dataset.DownloadableDataset._retrieve` hands to
:func:`pooch.retrieve` in place of :class:`pooch.HTTPDownloader` when an entry
names an ``archive``.
"""

from __future__ import annotations

import io
import urllib.parse
import urllib.request
import zipfile
from typing import Any

from emdatabase.downloadable_dataset import USER_AGENT, Progress

# The zip directory is read in many small seeks, so an unbuffered reader would
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


class _HTTPRangeFile(io.RawIOBase):
    """A seekable, read-only file over HTTP range requests.

    ``zipfile`` only seeks and reads, so ranges stand in for a local copy.
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
                "where a zip keeps its directory - cannot be found."
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
        buffer[: len(data)] = data
        self.pos += len(data)
        return len(data)


class ArchiveMemberDownloader:
    """A pooch downloader that pulls one member out of a remote zip.

    pooch calls a downloader as ``(url, output_file, pooch)`` from inside
    ``pooch.core.stream_download``, which streams to a temporary file, checks it
    against the entry's ``checksum`` and only then renames it into place,
    deleting the temporary file on any failure. So this only has to produce the
    member's bytes and drive ``progressbar`` the way :class:`pooch.HTTPDownloader`
    does: ``total`` once before streaming, ``update(n)`` per chunk, then
    ``reset()``, ``update(total)``, ``close()``. The widgets' cancel works by
    raising from ``update``, which aborts the stream and takes the temporary
    file with it.
    """

    def __init__(
        self,
        member: str,
        progressbar: Progress | bool = False,
        chunk_size: int = 4096,
    ) -> None:
        self.member = member
        # `True` means "build your own bar", which pooch's HTTPDownloader does
        # and this does not: _retrieve has already swapped it for a Progress.
        self.progressbar = None if isinstance(progressbar, bool) else progressbar
        self.chunk_size = chunk_size

    def __call__(self, url: str, output_file: str, _pooch: Any = None) -> None:
        bar = self.progressbar
        with io.BufferedReader(_HTTPRangeFile(url), buffer_size=_BUFFER_SIZE) as stream:  # pyright: ignore[reportArgumentType]
            with zipfile.ZipFile(stream) as archive:
                try:
                    info = archive.getinfo(self.member)
                except KeyError:
                    raise KeyError(
                        f"{url} holds no member {self.member!r}. Name the complete path "
                        "inside the archive: one file name can appear in several of its "
                        "directories."
                    ) from None
                if bar:
                    bar.total = info.file_size
                with archive.open(info) as member, open(output_file, "wb") as out:
                    while chunk := member.read(self.chunk_size):
                        out.write(chunk)
                        if bar:
                            bar.update(len(chunk))
                if bar:
                    bar.reset()
                    bar.update(info.file_size)
                    bar.close()
