"""Filter behaviour against the real config/filters.yaml."""

import pytest

from src import config
from src.filters import is_new_grad_title, is_top_match_title, match_priority, passes
from src.models import Job


def _job(title, locations=None, **kw):
    return Job(
        company=kw.pop("company", "Acme"),
        title=title,
        url=kw.pop("url", f"https://example.com/{abs(hash(title)) % 10000}"),
        locations=locations or [],
        **kw,
    )


F = config.filters()


@pytest.mark.parametrize("url", [
    "https://go.vansh.nyc/job123",
    "http://go.vansh.nyc/job123?ref=newsletter",
    "https://GO.VANSH.NYC:443/job123",
    "https://go.vansh.nyc./job123",
])
def test_excluded_application_host_rejected(url):
    assert not passes(_job("Software Engineer", ["New York, NY"], url=url), F)


@pytest.mark.parametrize("url", [
    "https://vansh.nyc/job123",
    "https://example.com/go.vansh.nyc",
    "https://example.com/?ref=https://go.vansh.nyc/job123",
    "https://go.vansh.nyc.example.com/job123",
])
def test_other_application_hosts_kept(url):
    assert passes(_job("Software Engineer", ["New York, NY"], url=url), F)


def test_new_grad_titles_are_high_priority():
    assert is_new_grad_title("Software Engineer, New Grad")
    assert is_new_grad_title("New Graduate Software Engineer")
    assert match_priority(_job("Software Engineer New Graduate")) > match_priority(
        _job("Software Engineer")
    )


def test_entry_titles_are_top_matches():
    assert is_top_match_title("Entry-Level Software Engineer")
    assert match_priority(_job("Entry Software Engineer")) > match_priority(
        _job("Software Engineer")
    )


def test_new_grad_title_matching_uses_word_boundaries():
    assert is_new_grad_title("New Graduate Program Manager")
    assert not is_new_grad_title("New Grading Engineer")
    assert not is_top_match_title("Entryway Software Engineer")


def test_swe_fulltime_us_kept():
    j = _job("Software Engineer", ["New York, NY"])
    assert passes(j, F)
    assert j.category == "swe"
    assert j.season is None


def test_quant_fulltime_classified_as_quant():
    j = _job("Quantitative Trader", ["Chicago, IL"])
    assert passes(j, F)
    assert j.category == "quant"


def test_technology_analyst_rejected():
    j = _job("Technology Analyst", ["Boston, MA"])
    assert not passes(j, F)


def test_associate_rejected():
    j = _job("Registered Client Service Associate", ["Boston, MA"])
    assert not passes(j, F)


def test_senior_role_rejected():
    j = _job("Senior Software Engineer", ["San Francisco, CA"])
    assert not passes(j, F)


def test_sr_role_rejected():
    j = _job("Sr. Software Engineer", ["San Francisco, CA"])
    assert not passes(j, F)


def test_internship_rejected():
    j = _job("Software Engineer Intern", ["Seattle, WA"])
    assert not passes(j, F)


def test_non_us_location_rejected():
    j = _job("Software Engineer Intern", ["London, UK"])
    assert not passes(j, F)


def test_canada_rejected():
    j = _job("Software Developer Intern", ["Toronto, Canada"])
    assert not passes(j, F)


def test_unknown_location_kept():
    j = _job("Software Engineer")
    assert passes(j, F)  # keep_when_location_unknown: true


def test_multi_location_with_us_option_kept():
    j = _job("Software Engineer", ["London, UK", "New York, NY"])
    assert passes(j, F)


def test_non_category_fulltime_rejected():
    j = _job("Marketing Coordinator", ["New York, NY"])
    assert not passes(j, F)


def test_research_scientist_rejected():
    j = _job("Research Scientist", ["Austin, TX"])
    assert not passes(j, F)


def test_remote_kept():
    j = _job("Software Engineer", ["Remote"])
    assert passes(j, F)
