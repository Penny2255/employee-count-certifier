"""Scoring decisions of 2026-10-12 (DECISIONS.md D76-D78), on the UC Davis pattern:
IPEDS latest-release allowance, one root cause one penalty, and the health-system "so what"."""

from datetime import date

from certifier import certify
from certifier.models import Entity, LinkedInEvidence
from certifier.record import build_record

from .conftest import src

TODAY = date(2026, 10, 11)
UCD = Entity(name="University of California-Davis", website="https://www.ucdavis.edu",
             legal_parent="University of California")
IPEDS_URL = "https://nces.ed.gov/ipeds/institution-profile/110644"
LINKEDIN_URL = "https://www.linkedin.com/school/uc-davis/"
HEALTH = ("UC Davis Health (a comprehensive health system) may or may not be included in the IPEDS total; "
          "it is a separately managed academic health system.")


def ipeds(as_of=date(2024, 11, 1)):
    return src(2, 15_029, as_of=as_of, url=IPEDS_URL, document_type="ipeds",
               excerpt="All staff (excludes graduate assistants): Total 15,029 (Fall 2024)")


def linkedin_description(value=21_000):
    return src(5, value, as_of=None, url=LINKEDIN_URL, qualifier="more_than",
               excerpt=f"more than {value:,} employees")


def uc_davis(sources, lookup_date=TODAY, linkedin=None, review_flags=(HEALTH,)):
    cert = certify(UCD, sources, lookup_date=lookup_date, linkedin=linkedin, review_flags=list(review_flags))
    return cert, build_record(cert, lookup_date=lookup_date)


# --- 1. IPEDS: the latest release counts as current ----------------------------------------------

def test_latest_ipeds_release_has_no_recency_penalty_and_says_when_the_next_is_due():
    cert, r = uc_davis([ipeds()], review_flags=())
    assert cert.confidence_score == 4 and not any(s.reason.startswith("recency") for s in cert.confidence_breakdown)
    selected = next(s for s in cert.sources if s.role == "selected")
    assert any(n.startswith("Latest release: as of 2024-11-01") and "December 2026" in n for n in selected.notes)
    latest = next(f for f in r.findings.items if f.title.startswith("Latest IPEDS Filing release"))
    assert (latest.group, latest.impact, latest.score_impact) == ("worth_knowing", "Counted as current (no recency penalty)", 0)
    assert "December 2026" in latest.so_what
    assert r.headline.next_expected_update == date(2026, 12, 6) and "December 2026" in r.headline.next_update_note


def test_allowance_ends_once_the_next_release_is_overdue():
    cert, _ = uc_davis([ipeds()], lookup_date=date(2027, 3, 1), review_flags=())  # due Dec 2026 + 60 days grace
    assert any(s.reason.startswith("recency") and s.points == -1 for s in cert.confidence_breakdown)


def test_form_990_is_not_covered_by_the_allowance():
    form990 = src(2, 513, as_of=date(2024, 12, 31), url="https://projects.propublica.org/nonprofits/organizations/1/2/full",
                  document_type="form_990")
    cert = certify(Entity(name="Donor Network West"), [form990], lookup_date=TODAY)
    assert any(s.reason.startswith("recency") for s in cert.confidence_breakdown) and cert.confidence_score == 3


# --- 2. One root cause, one penalty -------------------------------------------------------------

def test_linkedin_gap_explained_by_the_health_system_is_linked_not_penalized_twice():
    members = LinkedInEvidence(member_count=48_000, workforce_profile="mixed")
    cert, r = uc_davis([ipeds(), linkedin_description()], linkedin=members)
    assert cert.confidence_score == 3  # base 4, health-system scope question -1; nothing else
    assert [f for f in cert.flags] == [f"Complexity: {HEALTH}"]
    assert {f.split(":")[0] for f, _ in cert.explained_flags} == {"Conflict", "LinkedIn"}
    assert all(cause == f"Complexity: {HEALTH}" for _, cause in cert.explained_flags)

    scope = next(f for f in r.findings.items if f.category == "scope" and f.status == "red")
    explained = [f for f in r.findings.items if f.impact.startswith("No extra penalty")]
    assert len(explained) == 2 and all(f.impact == f"No extra penalty (same cause as {scope.id})" for f in explained)
    assert all(f.group == "worth_knowing" and f.score_impact == 0 for f in explained)
    assert all(f"Related: {f.id}" in scope.rationale for f in explained)
    assert r.linkedin_check.finding_id in {f.id for f in explained}
    assert [line.points for line in r.confidence.breakdown] == [4, -1]


def test_without_a_scope_question_the_linkedin_conflict_is_still_penalized():
    cert, _ = uc_davis([ipeds(), linkedin_description()], review_flags=())
    assert cert.confidence_score == 3 and any(f.startswith("Conflict:") for f in cert.flags)
    assert cert.explained_flags == []


def test_a_linkedin_figure_below_the_certified_count_is_not_explained_by_scope():
    cert, _ = uc_davis([ipeds(), linkedin_description(9_000)])
    assert any(f.startswith("Conflict:") for f in cert.flags) and cert.confidence_score == 2


# --- 3. Health-system "so what" -------------------------------------------------------------------

def test_health_system_so_what_says_the_full_organization_count_is_likely_higher():
    _, r = uc_davis([ipeds()])
    scope = next(f for f in r.findings.items if f.category == "scope" and f.status == "red")
    assert scope.so_what.startswith("The campus figure likely excludes health-system staff, so the full-organization "
                                    "count is likely higher")
    assert scope.score_impact == -1 and scope.group == "affects"


def test_no_growth_adjustment_on_a_current_latest_release():
    """Live UC Davis run: Revelio ~20,000-21,000 (likely incl. UC Davis Health) moved IPEDS to a 19,000 estimate.
    The latest IPEDS release is current, so there is no lag to correct; the gap belongs to the scope question."""
    revelio = [src(7, 20_000, as_of=date(2026, 8, 1), url="https://www.reveliolabs.com/companies/uc-davis"),
               src(8, 21_000, as_of=date(2026, 6, 1), url="https://pitchbook.com/profiles/uc-davis")]
    cert, r = uc_davis([ipeds(), *revelio])
    assert (cert.certified_count, cert.count_type, cert.confidence_score) == (15_029, "reported", 3)
    assert [line.points for line in r.confidence.breakdown] == [4, -1]
