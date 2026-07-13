"""NetEase weapi encryption + async HTTP session.

Talks directly to music.163.com via the weapi protocol (AES-CBC-128 ×2 +
RSA modular exponentiation), with no deployed reverse proxy.

The weapi protocol is public knowledge (constants below are documented across
many open implementations, e.g. HuberTRoy/MusicBox, xhongc/music-tag-web).
This module is a from-scratch implementation of that public protocol — it is
not a GPL/port of any specific project's code, so there is no license
inheritance concern (unlike crypto/tripledes_qq.py which is LDDC/GPL-3.0).

Private internal use.

AES-CBC-128 is implemented via the ``cryptography`` library (standard AES,
byte-identical ciphertext vs. the original pycryptodome implementation —
both implement standard AES-CBC with PKCS7 padding, §3.9 behavior-equivalence).
The RSA variant is plain Python ``pow(reversed_secret, e, modulus)`` and does
not depend on any crypto library, so it is unchanged.

HTTP is async via ``httpx.AsyncClient`` (Lyra is a long-lived FastAPI service;
the original ``requests.Session`` was blocking). Encryption is unchanged — only
the transport layer that calls ``weapi_encrypt`` is async.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import random
from typing import Any

import httpx
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# --- weapi constants (public protocol) ---
# First-layer AES key and CBC iv are fixed, well-known values.
_NONCE = b"0CoJUm6Qyw8W8jud"
_IV = b"0102030405060708"
# RSA: e and modulus are fixed; encryption is raw modular exponentiation of
# the reversed secret key (NOT PKCS#1) — this is NetEase's own variant.
_PUBKEY = 0x10001
_MODULUS = int(
    "00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7"
    "b725152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280"
    "104e0312ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932"
    "575cce10b424d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b"
    "3ece0462db0a22b8e7",
    16,
)
# base62 alphabet for the random per-request secret key.
_BASE62 = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

_BASE_URL = "https://music.163.com"
_DEFAULT_TIMEOUT = 15
_DEFAULT_SLEEP = 0.15
_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def _aes_cbc_b64(text: str, key: bytes) -> str:
    """AES-CBC-128 encrypt (PKCS7) → base64.

    Standard AES-CBC with a fixed 16-byte iv. ``cryptography``'s Cipher is
    byte-identical to pycryptodome's ``AES.new(key, MODE_CBC, iv).encrypt(pad(...))``
    — both implement standard AES-CBC + PKCS7 padding. PKCS7(128) matches
    pycryptodome's ``pad(data, 16)`` (block size 16 = 128 bits).
    """
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(text.encode("utf-8")) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(_IV)).encryptor()
    ct = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(ct).decode("utf-8")


def _create_secret_key(length: int = 16) -> str:
    return "".join(random.choice(_BASE62) for _ in range(length))


def _rsa_encrypt(text: str) -> str:
    """NetEase RSA variant: raw modular exp of reversed secret key → 256-hex.

    Pure Python ``pow()`` — no library dependency, unchanged from the
    pycryptodome version (RSA was never library-backed there either).
    """
    rev = text[::-1].encode("utf-8")
    rs = pow(int(binascii.hexlify(rev), 16), _PUBKEY, _MODULUS)
    return format(rs, "x").zfill(256)


def weapi_encrypt(payload: dict[str, Any]) -> tuple[str, str]:
    """Encrypt a payload dict for a /weapi/ POST. Returns (params, encSecKey).

    Pure function (no I/O, no randomness beyond the per-request secret key) —
    signature and output contract unchanged from the pycryptodome version.
    With a fixed secret key the params/encSecKey output is byte-identical,
    which the equivalence test asserts.
    """
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    secret = _create_secret_key(16)
    params = _aes_cbc_b64(_aes_cbc_b64(text, _NONCE), secret.encode("utf-8"))
    enc_seckey = _rsa_encrypt(secret)
    return params, enc_seckey


def weapi_encrypt_with_key(
    payload: dict[str, Any], secret_key: str,
) -> tuple[str, str]:
    """Encrypt with a caller-supplied secret key (deterministic, test-use).

    Same pipeline as ``weapi_encrypt`` but the random secret key is injected,
    so (params, encSecKey) is reproducible — used by the equivalence test to
    assert byte-identical output across the cryptography rewrite. Not part of
    the public transport API; kept here next to ``weapi_encrypt`` so the two
    never drift.
    """
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    params = _aes_cbc_b64(_aes_cbc_b64(text, _NONCE), secret_key.encode("utf-8"))
    enc_seckey = _rsa_encrypt(secret_key)
    return params, enc_seckey


class WeapiSession:
    """Async HTTP session that POSTs weapi-encrypted payloads to music.163.com.

    Wraps an ``httpx.AsyncClient`` (Lyra is a long-lived FastAPI service; the
    original ``requests.Session`` was blocking). Encryption is unchanged —
    only the transport that calls ``weapi_encrypt`` is async.

    cookie : optional MUSIC_U cookie string (login state). Anonymous by
             default — covers /song/detail, /cloudsearch, /song/lyric yrc for
             the majority of tracks. Pass MUSIC_U only for the few tracks whose
             lyrics require login.
    proxy  : optional HTTP(S) proxy URL. None = direct (music.163.com is a
             domestic domain; most home/business networks reach it directly,
             and a rule-based split proxy typically routes it via DIRECT, so
             pointing at one is usually a no-op).

    The underlying ``httpx.AsyncClient`` is created lazily on first use and
    must be closed (``await close()``) on shutdown to avoid connection leaks
    (§3.6 resource constraint). Also usable as an async context manager.
    """

    def __init__(
        self,
        cookie: str | None = None,
        proxy: str | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
        sleep: float = _DEFAULT_SLEEP,
    ):
        self.cookie = cookie
        self.timeout = timeout
        self.sleep = sleep
        self._proxy = proxy
        self._client: httpx.AsyncClient | None = None
        self._headers: dict[str, str] = {
            "User-Agent": _DEFAULT_UA,
            "Referer": "https://music.163.com",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        if cookie:
            self._headers["Cookie"] = cookie if "MUSIC_U" in cookie else f"MUSIC_U={cookie}"

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                proxy=self._proxy,
                timeout=self.timeout,
                headers=self._headers,
            )
        return self._client

    async def post_weapi(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST payload (weapi-encrypted) to music.163.com<path>; return JSON.

        Encryption (weapi_encrypt) is unchanged; only the transport is async.
        Raises RuntimeError on network failure or invalid JSON (mirrors the
        original's error contract so callers don't need a new exception path).
        """
        params, enc_seckey = weapi_encrypt(payload)
        url = f"{_BASE_URL}{path}"
        client = self._ensure_client()
        try:
            resp = await client.post(
                url,
                data={"params": params, "encSecKey": enc_seckey},
            )
            data = resp.json()
        except httpx.HTTPError as e:
            raise RuntimeError(f"weapi request failed for {path}: {e}") from e
        except ValueError as e:
            raise RuntimeError(f"invalid JSON from {path}: {resp.text[:300]}") from e
        if self.sleep > 0:
            await asyncio.sleep(self.sleep)
        return data

    async def close(self) -> None:
        """Close the underlying httpx.AsyncClient (idempotent)."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> WeapiSession:
        self._ensure_client()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.close()
