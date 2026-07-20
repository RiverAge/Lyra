"""Match orchestration — multi-source async candidate resolution.

resolve_candidates fans out across providers (each owns async search+detail),
scores all candidates uniformly, and returns a single ranked list.
match_query wraps a single query (the route-facing entry point).
batch_result_for_file wraps a single audio file (kept for batch use; the CLI
run_batch/_print_batch_line batch driver is dropped per §3.5 — Lyra's route
layer only needs match_query).

Stage 1 (zero-regression) contract: with a single NetEaseProvider the
behavior — decision thresholds, lyric fetch/summary, candidate ranking — is
identical to the pre-split netease_match_lyrics.py (transport is now async
httpx; encryption + scoring + decision are unchanged).

Stage 2 (QQ): resolve_candidates merges provider pools — the QQ provider just
appears in the list and QQ candidates carry source="qq". _provider_for_candidate
routes a hit to its owning provider (qq candidate → QqProvider, everything else
→ first non-qq provider, i.e. NetEase). batch_result_for_file sets the sidecar
suffix from the winning candidate: netease hits keep "netease" (zero-regression);
qq hits use "qq" → <song>-qq.ttml.

All orchestration is async (provider methods are async; pure scoring/decision
stay sync — they read only Candidate fields).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.lyrics.lyric_match.lyrics_io import (
    compare_embedded,
    lyric_payload_has_text,
    planned_lyrics_paths,
    read_audio_query,
    save_raw_payload,
    save_ttml,
)
from backend.lyrics.lyric_match.providers import LyricProvider, fetch_lyrics_cached
from backend.lyrics.lyric_match.scoring import decision, score_candidate
from backend.lyrics.lyric_match.types import (
    REVIEW_SCORE,
    Candidate,
    TrackQuery,
    candidate_to_dict,
    query_to_dict,
)


async def resolve_candidates(
    providers: list[LyricProvider], q: TrackQuery, limit: int,
) -> list[Candidate]:
    """Search+detail every provider, score the merged pool, return ranked.

    Each provider owns its own search strategy (NetEase: /search/match +
    multi-/cloudsearch; QQ: single client_search_cp) and dedup. Cross-provider
    dedup is not done (different id spaces). A provider that throws is skipped
    so one broken source never aborts the whole match. Scoring (sync, pure) is
    applied uniformly across all providers' candidates.

    search+detail 走 candidate_cache（per provider × 查询指纹）：同一首歌第二
    次点「在线匹配」命中缓存，跳过全部 search/detail 网络往返（payload_cache
    只盖了最后的拉词，省不掉大头）。命中后照常 score_candidate 打分（纯 CPU）。
    缓存 miss/损坏/过期 → 回源 search+detail 再 set。异常路径不缓存（允许重试）。
    """
    from backend.lyrics.lyric_match.candidate_cache import get_candidate_cache

    cache = get_candidate_cache()
    scored: list[Candidate] = []
    for provider in providers:
        try:
            cached = await cache.get(provider.source, q, limit)
            if cached is not None:
                cands = cached
            else:
                cands = await provider.search(q, limit)
                if cands:
                    cands = await provider.detail(cands)
                # 空列表也缓存（「搜不到」是稳定结果，省重复探测）。异常路径
                #（上面的 try/except 跳过）不走到这里，不会把异常结果缓存。
                await cache.set(provider.source, q, limit, cands)
        except Exception:
            continue
        for c in cands:
            if c.id:
                scored.append(score_candidate(q, c))
    scored.sort(key=lambda c: c.score, reverse=True)
    return scored


async def match_query(
    providers: list[LyricProvider],
    q: TrackQuery,
    limit: int,
    top_n: int,
    include_lyrics: bool,
) -> dict[str, Any]:
    """Single-query entry point (route-facing). Returns a result dict.

    Runs resolve_candidates → decision → (if include_lyrics & accept/review)
    _fetch_best_with_qq_fallback. The result shape mirrors the original CLI
    output (query/decision/reason/best/lyrics/candidates/lyric_source) so the
    route layer and any future batch driver share one contract.
    """
    candidates = await resolve_candidates(providers, q, limit)
    status, why = decision(candidates)
    lyric_info: dict[str, Any] | None = None
    fallback_marker: str | None = None
    if include_lyrics and candidates and status in {"accept", "review"}:
        _, _, lyric_info, fallback_marker, _ = await _fetch_best_with_qq_fallback(
            providers, candidates, status,
        )
    result: dict[str, Any] = {
        "query": query_to_dict(q),
        "decision": status,
        "reason": why,
        "best": candidate_to_dict(candidates[0]) if candidates else None,
        "lyrics": lyric_info,
        "candidates": [candidate_to_dict(c) for c in candidates[:top_n]],
    }
    if fallback_marker:
        result["lyric_source"] = fallback_marker
    return result


async def match_query_with_payload(
    providers: list[LyricProvider],
    q: TrackQuery,
    limit: int,
    top_n: int,
) -> tuple[dict[str, Any], dict[str, Any] | None, str | None]:
    """Like match_query but also returns the raw best lyric payload + the
    provider source slug for the lyric actually used (so the route layer can
    convert it to TTML without re-fetching).

    Returns (result_dict, best_payload, lyric_source_slug):
      - result_dict: same shape as match_query (query/decision/reason/best/
        lyrics/candidates/lyric_source).
      - best_payload: the raw lyric payload of the chosen candidate (NetEase
        /lyric/new dict, or QQ {"_qrc_xml": ...}). None when status is not
        accept/review or no candidate carries real lyrics.
      - lyric_source_slug: "qq" when a QQ QRC was chosen (incl. qq_preferred
        fallback), else "netease". Used to pick payload_to_ttml vs
        qrc_xml_to_ttml. None when no payload was fetched.

    Same single-fetch guarantee as match_query — _fetch_best_with_qq_fallback
    runs once; this wrapper just surfaces the payload it already produced
    rather than discarding it (match_query keeps the summary only, for
    JSONL/CLI shape compat). include_lyrics is implicitly True here — the
    route only calls this when it wants lyrics.
    """
    candidates = await resolve_candidates(providers, q, limit)
    status, why = decision(candidates)
    lyric_info: dict[str, Any] | None = None
    fallback_marker: str | None = None
    best_payload: dict[str, Any] | None = None
    lyric_source_slug: str | None = None
    if candidates and status in {"accept", "review"}:
        best, payload, lyric_info, fallback_marker, _ = await _fetch_best_with_qq_fallback(
            providers, candidates, status,
        )
        best_payload = payload
        # Suffix follows the WINNING lyric source (mirrors batch_result_for_file):
        #   - qq_preferred (best NetEase, lyric from QQ) → "qq"
        #   - best.source == "qq" and no netease_line fallback → "qq"
        #   - netease_line fallback (best QQ, lyric fell back to NetEase) → "netease"
        #   - otherwise → "netease"
        if fallback_marker == "netease_line":
            lyric_source_slug = "netease"
        elif best.source == "qq" or fallback_marker == "qq_preferred":
            lyric_source_slug = "qq"
        else:
            lyric_source_slug = "netease"
    result: dict[str, Any] = {
        "query": query_to_dict(q),
        "decision": status,
        "reason": why,
        "best": candidate_to_dict(candidates[0]) if candidates else None,
        "lyrics": lyric_info,
        "candidates": [candidate_to_dict(c) for c in candidates[:top_n]],
    }
    if fallback_marker:
        result["lyric_source"] = fallback_marker
    return result, best_payload, lyric_source_slug


def _provider_for_candidate(
    providers: list[LyricProvider], candidate: Candidate,
) -> LyricProvider | None:
    """Pick the provider that owns a candidate.

    Candidate.source is NOT rewritten by any provider (NetEase keeps its
    search-origin tag "search/match"/"cloudsearch:…" for output compat), so we
    cannot key off it for NetEase. The one exception is QQ, whose
    candidate_from_qq_song sets source="qq" (QQ has no search-origin sub-tag),
    so a "qq" candidate routes to the QQ provider. Everything else routes to
    the first non-qq provider — which in the supported "NetEase primary, QQ
    fallback" ordering is NetEase.
    """
    if not providers:
        return None
    if candidate.source == "qq":
        for p in providers:
            if p.source == "qq":
                return p
        # No QQ provider in the list (shouldn't happen for a qq candidate) —
        # fall through to the first non-qq provider.
    for p in providers:
        if p.source != "qq":
            return p
    return providers[0]


async def _fetch_best_with_qq_fallback(
    providers: list[LyricProvider],
    candidates: list[Candidate],
    status: str | None = None,
) -> tuple[
    Candidate,
    dict[str, Any] | None,
    dict[str, Any] | None,
    str | None,
    dict[str, Any] | None,
]:
    """Fetch the best candidate's lyrics, preferring QQ word-synced QRC when a
    same-song QQ candidate exists.

    Returns (best, lyric_payload, lyric_info, fallback_marker, netease_payload):
      - best: candidates[0] (highest score) — unchanged regardless of fallback.
      - lyric_payload / lyric_info: lyrics actually used (NetEase best's, or a
        QQ candidate's QRC if a fallback fired) — the "primary" lyric.
      - fallback_marker: None normally; "qq_preferred" when the lyric came
        from a same-song QQ QRC.
      - netease_payload: the NetEase best's lyric payload, ONLY when
        qq_preferred fired (so the runner can ALSO write -netease.ttml).

    Single-source (no QQ provider) short-circuits at the gate — zero extra
    requests, zero behavior change vs. the single-source path (zero-regression).

    Multi-source + best is NetEase: prefer a SAME-SONG QQ candidate (strict
    title+artist, or artist-only when NetEase has no yrc) with a real QRC.
    Multi-source + best is QQ but QQ has no real lyric: fall back to the
    highest-scoring NetEase candidate (≥ REVIEW_SCORE) that has real lyric text.
    """
    best = candidates[0]
    provider = _provider_for_candidate(providers, best)
    lyric_payload = await fetch_lyrics_cached(provider, best) if provider else None
    lyric_info = provider.lyric_summary(lyric_payload) if (provider and lyric_payload) else None

    qq_provider = next((p for p in providers if p.source == "qq"), None)
    # Zero-regression gate: single-source (no QQ provider) → identical to before.
    if qq_provider is None:
        return best, lyric_payload, lyric_info, None, None

    # Prefer QQ word-synced QRC for NetEase best when a same-song QQ candidate
    # carries real QRC. Same-song strictness is split on whether NetEase already
    # has word-synced yrc — see _same_song_qq_candidates docstring.
    if best.source != "qq" and hasattr(qq_provider, "find_qrc_candidate"):
        netease_has_yrc = bool((lyric_info or {}).get("yrc"))
        same_song_qq = _same_song_qq_candidates(best, candidates, strict=netease_has_yrc)
        if same_song_qq:
            qq_best, qq_payload = await qq_provider.find_qrc_candidate(same_song_qq)
            if qq_best is not None and qq_payload:
                # lyric_payload switches to QQ; netease_payload carries the
                # NetEase best's lyrics so the runner ALSO writes -netease.ttml.
                return (
                    best,
                    qq_payload,
                    qq_provider.lyric_summary(qq_payload),
                    "qq_preferred",
                    lyric_payload,
                )

    # Symmetric fallback: best is QQ but QQ has no real lyric — fall back to
    # the highest-scoring NetEase candidate with real lyric text.
    if best.source == "qq" and not _qq_lyric_is_real(lyric_info):
        netease_provider = next((p for p in providers if p.source != "qq"), None)
        if netease_provider is not None:
            netease_cands = [c for c in candidates if c.source != "qq"]
            for c in netease_cands:
                if c.score < REVIEW_SCORE:
                    break
                np = await fetch_lyrics_cached(netease_provider, c)
                if np and lyric_payload_has_text(np):
                    return best, np, netease_provider.lyric_summary(np), "netease_line", None

    return best, lyric_payload, lyric_info, None, None


def _same_song_qq_candidates(
    best: Candidate, candidates: list[Candidate], strict: bool = True,
) -> list[Candidate]:
    """QQ candidates that are the SAME SONG as the NetEase best.

    strict=True (used when NetEase best already has word-synced yrc): require
    exact title + artist equality after compact normalization. Switching to QQ
    here is optional icing, so never risk a wrong switch — false-keep (stay on
    NetEase only) is free.

    strict=False (used when NetEase best has NO yrc — QQ is the only word-synced
    source): match on ARTIST only, dropping the title requirement. Rescues songs
    whose QQ title is a truncated/variant of NetEase's that strict title
    equality would block. Artist matching is also loosened to SUBSTRING
    containment (best artist compact ⊂ a QQ artist compact, either direction):
    QQ often credits the full name ("Nanne Grönvall") where NetEase lists only
    the stage name ("Nanne"), and the same-song variant carrying the full逐字 QRC
    is frequently that full-name entry. Exact artist-set equality would filter
    it out before find_qrc_candidate ever sees it. find_qrc_candidate's score
    floor + real-line-count check + max_probe reject any noise the looser
    recall lets through.
    """
    from backend.lyrics.lyric_match.scoring import compact_text

    best_title = compact_text(best.title)
    best_artists = [
        compact_text(a) for a in (best.artists or []) if compact_text(a)
    ]
    same: list[Candidate] = []
    for c in candidates:
        if c.source != "qq":
            continue
        if strict and compact_text(c.title) != best_title:
            continue
        c_artists = [
            compact_text(a) for a in (c.artists or []) if compact_text(a)
        ]
        if strict:
            if sorted(c_artists) != sorted(best_artists):
                continue
        else:
            # Loosened recall: a best artist and a QQ artist share a containment
            # either way (stage name ⊂ full name, or vice versa).
            if not _artists_share_containment(best_artists, c_artists):
                continue
        same.append(c)
    return same


def _artists_share_containment(
    a_artists: list[str], b_artists: list[str],
) -> bool:
    """True if any compact-normalized artist from one side is a substring of any
    artist from the other side. Catches "Nanne" vs "Nanne Grönvall" (same person,
    QQ credits full name) which exact-set equality misses. Both directions
    checked because either side can be the longer form.
    """
    for a in a_artists:
        if not a:
            continue
        for b in b_artists:
            if not b:
                continue
            if a in b or b in a:
                return True
    return False


def _qq_lyric_is_real(lyric_info: dict[str, Any] | None) -> bool:
    """True if a QQ lyric_summary indicates a real word-synced QRC (not a
    no_content / placeholder / decrypt-error marker)."""
    if not lyric_info:
        return False
    if not lyric_info.get("qrc"):
        return False
    status = lyric_info.get("qrc_status", "ok")
    return status in ("ok", None)


async def batch_result_for_file(
    providers: list[LyricProvider],
    path: Path,
    args: Any,
) -> dict[str, Any]:
    """Single-file orchestration (kept for batch use; the CLI run_batch driver
    is dropped per §3.5, but this per-file contract is reused by any future
    batch runner and by tests).

    args is a config object with the same shape the original CLI args namespace
    had (limit/top/with_md5/compare_embedded/save_lyrics/save_ttml/
    save_decisions_effective/overwrite_lyrics/ttml_source/
    library_root_effective/lyrics_root_effective). The route layer does NOT use
    this — it calls match_query directly; batch_result_for_file is the
    file-scoped analog for offline batch drivers.
    """
    q = read_audio_query(path, getattr(args, "with_md5", False))
    candidates = await resolve_candidates(providers, q, args.limit)
    status, why = decision(candidates)
    lyric_payload: dict[str, Any] | None = None
    lyric_info: dict[str, Any] | None = None
    fallback_marker: str | None = None
    netease_payload: dict[str, Any] | None = None
    save_decisions = getattr(args, "save_decisions_effective", {"accept"})
    should_fetch_for_save = (args.save_lyrics or args.save_ttml) and status in save_decisions
    if (
        (args.lyrics or args.compare_embedded or should_fetch_for_save)
        and candidates and status in {"accept", "review"}
    ):
        _, lyric_payload, lyric_info, fallback_marker, netease_payload = (
            await _fetch_best_with_qq_fallback(providers, candidates, status)
        )

    result: dict[str, Any] = {
        "query": query_to_dict(q),
        "decision": status,
        "reason": why,
        "best": candidate_to_dict(candidates[0]) if candidates else None,
        "lyrics": lyric_info,
        "candidates": [candidate_to_dict(c) for c in candidates[: args.top]],
    }
    if fallback_marker:
        # Only added when a fallback fired (multi-source). Absent on the
        # single-source path so its key set stays byte-identical.
        result["lyric_source"] = fallback_marker
    if args.compare_embedded:
        result["lyric_compare"] = (
            compare_embedded(path, lyric_payload)
            if lyric_payload is not None
            else {"verdict": "not_compared"}
        )
    resolved = path.resolve()
    result["file"] = {
        "path": str(resolved),
        "name": path.name,
        "size": path.stat().st_size,
    }
    library_root = getattr(args, "library_root_effective", None)
    lyrics_root = getattr(args, "lyrics_root_effective", None)
    # Sidecar suffix follows the WINNING candidate's provider (not
    # args.ttml_source): netease hits → -netease.ttml; qq hits → -qq.ttml.
    default_suffix = "netease"
    if fallback_marker == "netease_line":
        suffix = default_suffix
    elif candidates and (candidates[0].source == "qq" or fallback_marker is not None):
        suffix = "qq"
    else:
        suffix = default_suffix
    planned_paths: dict[str, str] | None = None
    if library_root is not None and lyrics_root is not None:
        planned_paths = planned_lyrics_paths(
            path, library_root, lyrics_root, args.ttml_source, suffix,
        )
        result["planned_lyrics"] = planned_paths
    # When qq_preferred fired, the NetEase best's lyrics are ALSO persisted to
    # -netease.ttml alongside the QQ -qq.ttml ("download everything, consumer
    # picks").
    netease_paths: dict[str, str] | None = None
    if (
        fallback_marker == "qq_preferred"
        and library_root is not None
        and lyrics_root is not None
    ):
        netease_paths = planned_lyrics_paths(
            path, library_root, lyrics_root, args.ttml_source, "netease",
        )
    if args.save_lyrics:
        if status in save_decisions:
            result["saved_lyrics"] = save_raw_payload(
                lyric_payload, planned_paths, suffix,
                overwrite=args.overwrite_lyrics,
            )
            if netease_paths is not None and netease_payload:
                result["saved_lyrics_netease"] = save_raw_payload(
                    netease_payload, netease_paths, "netease",
                    overwrite=args.overwrite_lyrics,
                )
        else:
            result["saved_lyrics"] = {"status": "skipped", "reason": f"decision:{status}"}
    if args.save_ttml:
        if status in save_decisions:
            result["saved_ttml"] = save_ttml(
                lyric_payload, planned_paths, suffix,
                overwrite=args.overwrite_lyrics,
            )
            if netease_paths is not None and netease_payload:
                result["saved_ttml_netease"] = save_ttml(
                    netease_payload, netease_paths, "netease",
                    overwrite=args.overwrite_lyrics,
                )
        else:
            result["saved_ttml"] = {"status": "skipped", "reason": f"decision:{status}"}
    return result
