from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.leads.pipeline import (
    DUE,
    NEVER_CONTACTED,
    NO_NEXT_ACTION,
    OVERDUE,
    STALE,
    UNANSWERED,
    UNOWNED,
    Counted,
    Stage,
    StageRefused,
    Watched,
    attention,
    check_move,
    check_pipeline,
    next_action_default,
    since_days,
    summarise,
)

D = Decimal
TODAY = date(2026, 9, 4)

NEW = Stage("new", "New enquiry", 10, is_default=True)
QUALIFIED = Stage("qualified", "Qualified", 20)
QUOTED = Stage("quoted", "Quoted", 30)
WON = Stage("won", "Won", 50, is_won=True)
LOST = Stage("lost", "Lost", 60, is_lost=True)
PIPELINE = [NEW, QUALIFIED, QUOTED, WON, LOST]


def test_a_sensible_pipeline_has_nothing_wrong_with_it():
    assert check_pipeline(PIPELINE) == []


def test_a_pipeline_with_no_entry_stage_is_reported():
    problems = check_pipeline([QUALIFIED, QUOTED, WON, LOST])
    assert any("nowhere to start" in one for one in problems)


def test_two_entry_stages_are_reported_by_name():
    problems = check_pipeline(
        [NEW, Stage("triage", "Triage", 15, is_default=True), WON, LOST]
    )
    assert any(
        "New enquiry" in one and "Triage" in one for one in problems
    ), problems


def test_a_pipeline_that_cannot_express_won_or_lost_is_reported():
    problems = check_pipeline([NEW, QUALIFIED, LOST])
    assert any("nothing can ever be counted as converted" in one for one in problems)
    problems = check_pipeline([NEW, QUALIFIED, WON])
    assert any("sit in the pipeline forever" in one for one in problems)


def test_a_stage_cannot_mean_both_won_and_lost():
    problems = check_pipeline(
        [NEW, Stage("closed", "Closed", 50, is_won=True, is_lost=True)]
    )
    assert any("cannot mean both" in one for one in problems)


def test_problems_are_reported_rather_than_raised():
    assert isinstance(check_pipeline([]), list)
    assert check_pipeline([])


def test_a_lead_moves_forward():
    check_move(NEW, QUALIFIED)


def test_a_lead_may_move_backwards():
    check_move(QUOTED, QUALIFIED)


def test_a_closed_lead_may_be_reopened():
    check_move(LOST, QUALIFIED, lost_reason="was lost on price")
    check_move(WON, QUOTED)


def test_moving_to_the_stage_it_is_already_at_is_refused():
    with pytest.raises(StageRefused, match="already at Quoted"):
        check_move(QUOTED, QUOTED)


def test_losing_a_lead_requires_a_reason():
    with pytest.raises(StageRefused, match="Say why the lead was lost") as raised:
        check_move(QUOTED, LOST)
    assert "nobody can act on" in str(raised.value)
    check_move(QUOTED, LOST, lost_reason="Went with a competitor.")


def test_a_blank_reason_is_not_a_reason():
    with pytest.raises(StageRefused):
        check_move(QUOTED, LOST, lost_reason="   ")


def _watched(**over):
    fields = {
        "name": "Acme Ltd",
        "stage": QUOTED,
        "stage_since": TODAY,
        "next_action_on": TODAY,
        "owner": "agent-1",
        "last_contact_on": TODAY,
        "last_answered_on": TODAY,
    }
    fields.update(over)
    return Watched(**fields)


def test_a_lead_with_no_next_action_is_the_first_thing_reported():
    found = attention(_watched(next_action_on=None), today=TODAY)
    assert found[0].code == NO_NEXT_ACTION
    assert "nothing will bring it back" in found[0].message


def test_an_overdue_action_says_how_late_it_is():
    found = attention(
        _watched(next_action_on=date(2026, 8, 30)), today=TODAY
    )
    late = next(one for one in found if one.code == OVERDUE)
    assert late.days == 5
    assert "5 day(s) ago" in late.message


def test_an_action_due_today_is_reported_without_alarm():
    found = attention(_watched(next_action_on=TODAY), today=TODAY)
    assert [one.code for one in found] == [DUE]
    assert next(one for one in found if one.code == DUE).days == 0


def test_an_action_due_later_is_not_on_the_list():
    assert attention(_watched(next_action_on=date(2026, 9, 20)), today=TODAY) == []


def test_an_unowned_lead_is_nobodys_to_lose():
    found = attention(_watched(owner=None), today=TODAY)
    assert any(one.code == UNOWNED for one in found)


def test_a_lead_nobody_has_touched_is_reported_but_not_judged():
    found = attention(
        _watched(last_contact_on=date(2026, 8, 1)),
        today=TODAY,
        stale_after_days=14,
    )
    stale = next(one for one in found if one.code == STALE)
    assert stale.days == 34
    assert "has not been contacted for" in stale.message
    assert "Not necessarily cold" in stale.message
    assert "worth a decision" in stale.message


def test_staleness_falls_back_to_the_stage_where_there_is_no_log():
    found = attention(
        _watched(last_contact_on=None, stage_since=date(2026, 8, 1)),
        today=TODAY,
        stale_after_days=14,
    )
    stale = next(one for one in found if one.code == STALE)
    assert stale.days == 34
    assert "has been at Quoted for" in stale.message


def test_the_stale_threshold_is_the_callers():
    lead = _watched(
        last_contact_on=date(2026, 8, 25), next_action_on=date(2026, 9, 20)
    )
    assert [
        one.code for one in attention(lead, today=TODAY, stale_after_days=7)
    ] == [STALE]
    assert attention(lead, today=TODAY, stale_after_days=30) == []


def test_an_enquiry_nobody_has_answered_outranks_everything():
    found = attention(
        _watched(
            last_contact_on=None,
            last_answered_on=None,
            stage_since=date(2026, 9, 1),
            next_action_on=None,
        ),
        today=TODAY,
    )
    assert found[0].code == NEVER_CONTACTED
    assert found[0].days == 3
    assert "3 day(s) after the enquiry arrived" in found[0].message
    assert NO_NEXT_ACTION in {one.code for one in found}


def test_internal_notes_are_not_contact():
    found = attention(
        _watched(last_contact_on=None, last_answered_on=None, logged=3, stage_since=TODAY),
        today=TODAY,
    )
    never = next(one for one in found if one.code == NEVER_CONTACTED)
    assert "though there are notes on it" in never.message


def test_a_lead_chased_into_silence_is_reported_not_concluded():
    found = attention(
        _watched(chases=4, last_inbound_on=None), today=TODAY, chase_threshold=3
    )
    quiet = next(one for one in found if one.code == UNANSWERED)
    assert quiet.days == 4
    assert "chased 4 time(s) and has never replied" in quiet.message
    assert "not something a report can make" in quiet.message


def test_the_chase_threshold_is_the_callers_too():
    lead = _watched(chases=2)
    assert UNANSWERED in {
        one.code for one in attention(lead, today=TODAY, chase_threshold=2)
    }
    assert UNANSWERED not in {
        one.code for one in attention(lead, today=TODAY, chase_threshold=3)
    }


def test_silence_since_a_reply_reads_differently_from_never_replying():
    found = attention(
        _watched(chases=3, last_inbound_on=date(2026, 8, 20)),
        today=TODAY,
        chase_threshold=3,
    )
    quiet = next(one for one in found if one.code == UNANSWERED)
    assert "since they last replied" in quiet.message


def test_a_closed_lead_needs_nothing():
    for stage in (WON, LOST):
        assert attention(
            _watched(stage=stage, next_action_on=None, owner=None), today=TODAY
        ) == []


def test_a_new_lead_gets_a_next_action_a_few_days_out():
    assert next_action_default(today=TODAY) == date(2026, 9, 7)
    assert next_action_default(today=TODAY, days=0) == TODAY


def test_since_days_takes_a_date_or_a_timestamp():
    from datetime import UTC, datetime

    assert since_days(date(2026, 9, 1), today=TODAY) == 3
    assert since_days(datetime(2026, 9, 1, 23, 30, tzinfo=UTC), today=TODAY) == 3
    assert since_days(None, today=TODAY) is None


def _counted(stage, **over):
    fields = {"stage": stage, "source": "website", "stage_since": TODAY}
    fields.update(over)
    return Counted(**fields)


def test_every_configured_stage_appears_even_when_empty():
    report = summarise([_counted(QUOTED)], PIPELINE, today=TODAY)
    assert [one.stage for one in report.stages] == [
        "new",
        "qualified",
        "quoted",
        "won",
        "lost",
    ]
    assert next(one for one in report.stages if one.stage == "new").leads == 0


def test_stages_are_reported_in_the_configured_order():
    shuffled = [LOST, NEW, WON, QUOTED, QUALIFIED]
    report = summarise([], shuffled, today=TODAY)
    assert [one.stage for one in report.stages] == [
        "new",
        "qualified",
        "quoted",
        "won",
        "lost",
    ]


def test_dwell_time_is_a_median_over_the_leads_in_that_stage():
    report = summarise(
        [
            _counted(QUOTED, stage_since=date(2026, 9, 3)),
            _counted(QUOTED, stage_since=date(2026, 8, 30)),
            _counted(QUOTED, stage_since=date(2026, 6, 1)),
        ],
        PIPELINE,
        today=TODAY,
    )
    quoted = next(one for one in report.stages if one.stage == "quoted")
    assert quoted.leads == 3
    assert quoted.median_days == 5


def test_open_won_and_lost_are_counted_apart():
    report = summarise(
        [
            _counted(NEW),
            _counted(QUOTED),
            _counted(WON),
            _counted(WON),
            _counted(LOST),
        ],
        PIPELINE,
        today=TODAY,
    )
    assert report.open_leads == 2
    assert report.won_leads == 2
    assert report.lost_leads == 1
    assert report.win_rate == D("0.6667")


def test_stated_budgets_are_summed_per_currency_and_only_while_open():
    report = summarise(
        [
            _counted(NEW, budget_amount=D("400000"), budget_currency="KES"),
            _counted(QUOTED, budget_amount=D("3000"), budget_currency="USD"),
            _counted(WON, budget_amount=D("999999"), budget_currency="KES"),
        ],
        PIPELINE,
        today=TODAY,
    )
    assert report.open_budget == {"KES": D("400000"), "USD": D("3000")}


def test_a_source_is_answerable_for_bookings_not_enquiries():
    report = summarise(
        [
            *[_counted(NEW, source="social") for _ in range(8)],
            _counted(WON, source="social", quotes=1, accepted=True),
            _counted(QUOTED, source="referral", quotes=1),
            _counted(WON, source="referral", quotes=2, accepted=True),
        ],
        PIPELINE,
        today=TODAY,
    )
    social = next(one for one in report.sources if one.source == "social")
    referral = next(one for one in report.sources if one.source == "referral")
    assert social.leads == 9 and social.won == 1
    assert social.win_rate == D("0.1111")
    assert referral.leads == 2 and referral.quoted == 2 and referral.won == 1
    assert referral.win_rate == D("0.5000")
    assert report.sources[0].source == "social"


def test_nothing_decided_reports_no_win_rate():
    report = summarise([_counted(NEW)], PIPELINE, today=TODAY)
    assert report.win_rate is None
    assert next(one for one in report.sources).win_rate == D("0.0000")


def test_the_summary_accepts_a_generator_once():
    leads = (_counted(QUOTED) for _ in range(3))
    report = summarise(leads, PIPELINE, today=TODAY)
    assert next(one for one in report.stages if one.stage == "quoted").leads == 3
