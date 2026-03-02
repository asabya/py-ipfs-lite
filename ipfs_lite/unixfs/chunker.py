import io
from typing import Iterator


class Chunker:
    """Splits input into fixed-size chunks."""

    def __init__(self, chunk_size: int = 262144):
        self.chunk_size = chunk_size

    def chunk(self, data: io.BytesIO) -> Iterator[bytes]:
        while True:
            chunk = data.read(self.chunk_size)
            if not chunk:
                break
            yield chunk
