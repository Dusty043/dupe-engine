from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
from PIL import Image


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def perceptual_dhash(image_path: Path, hash_size: int = 8) -> str:
    """Compute a compact 64-bit difference hash for a rendered page image.

    This keeps the project self-contained. It is not as strong as a tuned pHash,
    but it is good enough for a first local visual-near-duplicate layer and can
    later be swapped for ImageHash/OpenCV without changing the match contract.
    """

    with Image.open(image_path) as image:
        grayscale = image.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
        pixels = np.asarray(grayscale, dtype=np.int16)

    diff = pixels[:, 1:] > pixels[:, :-1]
    bits = "".join("1" if value else "0" for value in diff.flatten())
    return f"{int(bits, 2):0{hash_size * hash_size // 4}x}"


def hamming_distance(hex_a: str, hex_b: str) -> int:
    if len(hex_a) != len(hex_b):
        raise ValueError(f"Hash lengths differ: {len(hex_a)} vs {len(hex_b)}")
    return (int(hex_a, 16) ^ int(hex_b, 16)).bit_count()
