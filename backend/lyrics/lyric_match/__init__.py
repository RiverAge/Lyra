"""lyric_match — modular lyric matching (NetEase / QQ providers, scoring, converters).

Online lyric matching package, ported from AppleMusicDecrypt's
``tools/lyric_match/`` and adapted for Lyra:

- Encryption: AES-CBC via ``cryptography`` (standard AES, byte-identical to
  the original pycryptodome output); QQ 3DES kept verbatim (non-standard).
- Transport: async ``httpx.AsyncClient`` (Lyra is a long-lived FastAPI
  service; the original blocking ``requests``/``urllib`` is async-ified).
- Scoring / decision / converters: pure functions, unchanged.
- CLI batch driver (``run_batch`` / ``_print_batch_line`` / scan_cache /
  JSONL output) is dropped per §3.5 anti-over-design — the route layer drives
  ``match_query`` directly.

Public API re-exports the route-facing entry points + data types + the two
TTML converters. Internal modules (providers, crypto, lyrics_io) are imported
by name from their submodules (e.g.
``from backend.lyrics.lyric_match.providers.netease import NeteaseProvider``).
"""

from __future__ import annotations

from backend.lyrics.lyric_match.converters import payload_to_ttml, qrc_xml_to_ttml
from backend.lyrics.lyric_match.runner import (
    batch_result_for_file,
    match_query,
    match_query_with_payload,
    resolve_candidates,
)
from backend.lyrics.lyric_match.types import Candidate, TrackQuery

__all__ = [
    "Candidate",
    "TrackQuery",
    "batch_result_for_file",
    "match_query",
    "match_query_with_payload",
    "payload_to_ttml",
    "qrc_xml_to_ttml",
    "resolve_candidates",
]
