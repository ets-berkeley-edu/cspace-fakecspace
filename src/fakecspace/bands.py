"""Files of about a real file's size, for the simulator's records that have a size band (D283).

`./serena aws replay` replays the legacy imageserver's access logs against an environment with the simulator. With
the simulator's 8x8 samples a cache miss would cost Serena almost nothing, so a record added with a band gets JPEGs
of about the logged size instead: its original and OriginalJpeg about the band's size, its other derivatives about a
real one's (Thumbnail about 5 KB, the rest about 100 KB; from the access logs of September 2026).

Each band's file is made once per simulator start, in the background, from blurred noise: about 0.45 bytes a pixel at
quality 90, so it has about a photograph's pixel count for its size, and Serena's decode check costs about what a real
one would. Every record of a band shares its bytes; `marked_head` makes each record's file different (a JPEG comment
naming the record), so Serena, which stores files by content hash, stores each one."""
from __future__ import annotations

import math
import threading
from collections.abc import Iterator

# The original's size for each band a record may have, in bytes (decimal, as the access logs count).
ORIGINALS = {"100KB": 100_000, "1MB": 1_000_000, "5MB": 5_000_000, "20MB": 20_000_000, "100MB": 100_000_000}
# The other derivatives' bands, whatever the record's band.
DERIVATIVES = {"Thumbnail": "5KB", "Small": "100KB", "Medium": "100KB", "FullHD": "100KB"}
SIZES = {**ORIGINALS, "5KB": 5_000}
CHUNK = 1024 * 1024  # bytes per piece of a streamed file
WAIT_SECONDS = 600.0  # the longest a request waits for a band's file to be made (100 MB takes about a minute)

_lock = threading.Lock()
_made: dict[str, bytes] = {}
_making: dict[str, threading.Event] = {}


def band_of(name: str, record_band: str) -> str:
    """The band of a record's file: "content" or a derivative's name."""
    return DERIVATIVES.get(name, record_band)


def noise_jpeg(target: int) -> bytes:
    """A JPEG of about `target` bytes: blurred noise in three channels, at quality 90."""
    import pyvips  # only here: the simulator's other files don't need it

    def jpeg(side: int) -> bytes:
        def channel() -> object:
            return pyvips.Image.gaussnoise(side, side, mean=128, sigma=60).gaussblur(1.5).cast("uchar")
        image = channel().bandjoin([channel(), channel()])  # type: ignore[attr-defined]
        return bytes(image.jpegsave_buffer(Q=90, strip=True))

    sample = 256
    per_pixel = len(jpeg(sample)) / sample ** 2  # about 0.45; measured, as it depends on libvips's version
    return jpeg(max(16, round(math.sqrt(target / per_pixel))))


def prepare(band: str) -> None:
    """Starts making the files a record of this band needs, unless already made or being made."""
    for size in {band, *DERIVATIVES.values()}:
        _start(size)


def _start(size: str) -> threading.Event:
    with _lock:
        event = _making.get(size)
        if event is None:
            event = _making[size] = threading.Event()
            threading.Thread(target=_make, args=(size, event), daemon=True).start()
        return event


def _make(size: str, event: threading.Event) -> None:
    try:
        made = noise_jpeg(SIZES[size])
        with _lock:
            _made[size] = made
    finally:
        event.set()


def band_file(size: str) -> bytes:
    """The band's file, made now if it wasn't started, waiting for it if it's being made."""
    if not _start(size).wait(WAIT_SECONDS) or size not in _made:
        raise RuntimeError(f"the {size} file couldn't be made")
    return _made[size]


def marked_head(csid: str) -> bytes:
    """The start of a record's file: the JPEG start marker, then a comment naming the record (a COM segment)."""
    comment = f"fakecspace {csid}".encode()
    return b"\xff\xd8\xff\xfe" + (len(comment) + 2).to_bytes(2, "big") + comment


def stream(head: bytes, shared: bytes) -> Iterator[bytes]:
    """The record's file: its head, then the shared file after its own start marker, in pieces, without a copy."""
    yield head
    view = memoryview(shared)
    for start in range(2, len(shared), CHUNK):
        yield bytes(view[start:start + CHUNK])


def reset() -> None:
    """Forgets the files made (for the tests)."""
    with _lock:
        _made.clear()
        _making.clear()
