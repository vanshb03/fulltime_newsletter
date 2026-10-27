"""Persisted state: which jobs have already been notified.

State file shape (data/seen_jobs.json):
    { "<dedup_id>": {...}, "<legacy_job_id>": {...}, ... }
Canonical newsletter entries use `dedup_id`; legacy `job_id` entries are
still honored when reading, and new writes mirror both for compatibility.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from .models import Job

log = logging.getLogger(__name__)


def load_state(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("could not read state %s: %s — starting fresh", path, exc)
        return {}


def save_state(path: Path, state: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")


def _short_link_ids(job: Job) -> tuple[str, str]:
    """The ids the job had before its short link was resolved."""
    alias = job.model_copy(update={"url": job.short_url})
    return alias.job_id, alias.dedup_id


def _job_ids(job: Job) -> set[str]:
    ids = {job.job_id, job.dedup_id}
    if job.short_url:
        ids.update(_short_link_ids(job))
    return ids


def reconcile_short_links(jobs: list[Job], state: dict[str, dict]) -> None:
    """Remember aliases of already-seen postings without resetting their age."""
    groups: dict[str, set[str]] = {}
    for job in jobs:
        groups.setdefault(job.dedup_id, set()).update(_job_ids(job))
    for ids in groups.values():
        known = next((state[i] for i in sorted(ids) if i in state), None)
        if known is not None:
            for jid in ids:
                state.setdefault(jid, known)


def new_jobs(jobs: list[Job], state: dict[str, dict]) -> list[Job]:
    """Return unseen jobs, backfilling state with aliases of seen postings."""
    # Reconcile the whole batch first: a direct listing may precede the short
    # link that connects it to an old state entry.
    reconcile_short_links(jobs, state)
    seen_now: set[str] = set()
    out: list[Job] = []
    for job in jobs:
        legacy_id = job.job_id
        dedup_id = job.dedup_id
        if (
            legacy_id in state
            or dedup_id in state
            or legacy_id in seen_now
            or dedup_id in seen_now
        ):
            continue
        seen_now.update({legacy_id, dedup_id})
        out.append(job)
    return out


def update_state(
    state: dict[str, dict], jobs: list[Job], today: date | None = None
) -> dict[str, dict]:
    today = today or datetime.now().date()
    iso = today.isoformat()
    for job in jobs:
        meta = {
            "first_seen": iso,
            "company": job.company,
            "title": job.title,
            "url": job.url,
        }
        for jid in _job_ids(job):
            state[jid] = meta
    return state


def prune(
    state: dict[str, dict], max_age_days: int, today: date | None = None
) -> dict[str, dict]:
    if not max_age_days or max_age_days <= 0:
        return state
    today = today or datetime.now().date()
    cutoff = today - timedelta(days=max_age_days)
    kept: dict[str, dict] = {}
    for jid, meta in state.items():
        fs = meta.get("first_seen")
        try:
            seen_date = date.fromisoformat(fs) if fs else today
        except ValueError:
            seen_date = today
        if seen_date >= cutoff:
            kept[jid] = meta
    removed = len(state) - len(kept)
    if removed:
        log.info("pruned %d stale state entries (> %d days)", removed, max_age_days)
    return kept
