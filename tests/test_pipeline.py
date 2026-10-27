"""Shared URL resolution through newsletter and auto-apply entry points."""

from argparse import Namespace
from types import SimpleNamespace

import pytest
import requests

from src import config, main
from src.apply import cli
from src.dedup import load_state, save_state, update_state
from src.models import Job


SHORT = "https://go.vansh.nyc/BX"
DIRECT = "https://jobs.ashbyhq.com/acme/1"


def _job(url):
    return Job(company="Acme", title="Software Engineer", url=url,
               locations=["New York, NY"], ats="github-list")


@pytest.fixture
def pipeline(monkeypatch, tmp_path):
    redirects = {SHORT: DIRECT}
    monkeypatch.setattr(main, "collect_jobs", lambda limit=None: [_job(SHORT)])
    monkeypatch.setattr(config, "github_lists", lambda: {"short_link_hosts": ["go.vansh.nyc"]})
    monkeypatch.setattr(config, "settings", lambda: {"email": {"enabled": True}})
    monkeypatch.setattr(config, "secrets", lambda: {})
    monkeypatch.setattr(config, "state_path", lambda: tmp_path / "seen.json")

    def head(self, url, **kwargs):
        target = redirects.get(url)
        return SimpleNamespace(status_code=302 if target else 503,
                               headers={"Location": target} if target else {})

    monkeypatch.setattr(requests.Session, "head", head)
    return redirects


def _run():
    return main.run(dry_run=False, do_email=True, do_sms=False, do_discord=False, limit=None)


def test_auto_apply_resolves_before_selecting_ats(pipeline):
    args = Namespace(retry_failed=False, category=None, company=None)
    jobs = cli._candidate_jobs(args, {}, {"ashby"})
    assert len(jobs) == 1
    assert jobs[0].url == DIRECT
    assert jobs[0].short_url == SHORT


def test_both_entry_points_exclude_resolved_destination(pipeline, monkeypatch):
    filters = {**config.filters(), "excluded_url_hosts": ["jobs.ashbyhq.com"]}
    monkeypatch.setattr(config, "filters", lambda: filters)
    assert main.collect_matching_jobs() == []
    args = Namespace(retry_failed=False, category=None, company=None)
    assert cli._candidate_jobs(args, {}, {"ashby"}) == []
    monkeypatch.setattr(main.email_notify, "send_email", lambda *args: pytest.fail("Excluded job notified"))
    assert _run() == 0
    assert load_state(config.state_path()) == {}


def test_newsletter_persists_duplicate_aliases_for_later_outage(pipeline, monkeypatch):
    other = "https://go.vansh.nyc/other"
    pipeline[other] = DIRECT
    monkeypatch.setattr(main, "collect_jobs", lambda limit=None: [_job(SHORT), _job(other)])
    sent = []
    monkeypatch.setattr(main.email_notify, "send_email", lambda jobs, *args: sent.extend(jobs))
    assert _run() == 0
    assert [j.url for j in sent] == [DIRECT]
    state = load_state(config.state_path())
    for url in (SHORT, other, DIRECT):
        assert _job(url).dedup_id in state
    pipeline.clear()
    assert _run() == 0
    assert len(sent) == 1


def test_newsletter_saves_migration_even_when_nothing_is_new(pipeline, monkeypatch):
    state = update_state({}, [_job(SHORT)])
    save_state(config.state_path(), state)
    monkeypatch.setattr(main, "collect_jobs", lambda limit=None: [_job(DIRECT), _job(SHORT)])
    monkeypatch.setattr(main.email_notify, "send_email", lambda *args: pytest.fail("Seen job notified"))
    assert _run() == 0
    saved = load_state(config.state_path())
    assert saved[_job(DIRECT).dedup_id] == state[_job(SHORT).dedup_id]
