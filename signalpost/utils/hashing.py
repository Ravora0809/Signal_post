import hashlib


def sha256_hex(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def content_hash(text: str) -> str:
    normalized = " ".join(text.split())
    return sha256_hex(normalized)