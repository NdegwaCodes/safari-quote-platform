from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.modules.comms.rules import (
    CALL,
    EMAIL,
    INBOUND,
    INTERNAL,
    MEETING,
    NOTE,
    OUTBOUND,
    Contact,
    Logged,
    LogRefused,
    check_logged,
    first_response_hours,
    history,
    median_hours,
    normalise_channel,
    normalise_direction,
    silence,
)

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
D = Decimal


def _entry(**over):
    fields = {
        "channel": CALL,
        "direction": OUTBOUND,
        "occurred_at": NOW - timedelta(hours=1),
        "body": "Talked through the coast options.",
    }
    fields.update(over)
    return Logged(**fields)


def _contact(hours_ago: float, **over):
    fields = {
        "channel": EMAIL,
        "direction": OUTBOUND,
        "occurred_at": NOW - timedelta(hours=hours_ago),
    }
    fields.update(over)
    return Contact(**fields)


def test_a_channel_is_grouped_the_way_a_report_should_group_it():
    assert normalise_channel("WhatsApp") == "whatsapp"
    assert normalise_channel(" WHATSAPP ") == "whatsapp"
    assert normalise_channel("Video call") == normalise_channel("video-call")
    assert normalise_channel("") == NOTE


def test_a_channel_is_not_validated_against_a_list():
    assert normalise_channel("Instagram DM") == "instagram_dm"


def test_a_direction_is_refused_rather_than_defaulted():
    assert normalise_direction("Inbound") == INBOUND
    with pytest.raises(LogRefused) as raised:
        normalise_direction("received")
    assert "not a direction" in str(raised.value)
    assert "internal" in str(raised.value)


def test_a_conversation_cannot_be_logged_before_it_happens():
    with pytest.raises(LogRefused) as raised:
        check_logged(_entry(occurred_at=NOW + timedelta(hours=2)), now=NOW)
    assert "has not happened yet" in str(raised.value)
    assert "next action" in str(raised.value)


def test_an_entry_with_no_words_is_refused():
    with pytest.raises(LogRefused) as raised:
        check_logged(_entry(body="   "), now=NOW)
    assert "Say what was said" in str(raised.value)


def test_an_internal_note_reached_nobody():
    with pytest.raises(LogRefused):
        check_logged(_entry(direction=INTERNAL, reached=True), now=NOW)
    check_logged(_entry(direction=INTERNAL, reached=None), now=NOW)


def test_an_email_does_not_last_nineteen_minutes():
    with pytest.raises(LogRefused) as raised:
        check_logged(_entry(channel=EMAIL, duration_minutes=19), now=NOW)
    assert "call or a meeting" in str(raised.value)
    check_logged(_entry(channel=MEETING, duration_minutes=45), now=NOW)


def test_an_unanswered_call_has_no_length():
    with pytest.raises(LogRefused) as raised:
        check_logged(_entry(reached=False, duration_minutes=19), now=NOW)
    assert "not answered has no length" in str(raised.value)
    check_logged(_entry(reached=False), now=NOW)


def test_a_call_of_no_length_is_refused():
    with pytest.raises(LogRefused):
        check_logged(_entry(duration_minutes=0), now=NOW)


def test_the_history_is_sorted_here_rather_than_trusted():
    log = history(
        [_contact(1), _contact(48, direction=INBOUND), _contact(24)]
    )
    assert log.last_contact_at == NOW - timedelta(hours=1)
    assert log.last_inbound_at == NOW - timedelta(hours=48)
    assert log.last_outbound_at == NOW - timedelta(hours=1)


def test_internal_notes_count_as_entries_and_not_as_contact():
    log = history([_contact(1, direction=INTERNAL), _contact(2, direction=INTERNAL)])
    assert log.entries == 2
    assert log.contacts == 0
    assert log.ever_contacted is False
    assert log.by_direction[INTERNAL] == 2


def test_a_voided_entry_stays_visible_and_counts_towards_nothing():
    log = history([_contact(1, voided=True), _contact(30, direction=INBOUND)])
    assert log.entries == 2
    assert log.contacts == 1
    assert log.last_contact_at == NOW - timedelta(hours=30)
    assert log.chases == 0


def test_chases_are_counted_since_the_client_last_replied():
    log = history(
        [
            _contact(200),
            _contact(150),
            _contact(100, direction=INBOUND),
            _contact(50),
            _contact(20),
            _contact(2),
        ]
    )
    assert log.chases == 3
    assert log.has_replied is True


def test_unanswered_calls_are_kept_apart_from_a_conversation_that_went_quiet():
    log = history(
        [
            _contact(30, channel=CALL, reached=False),
            _contact(20, channel=CALL, reached=False),
            _contact(10, channel=EMAIL),
        ]
    )
    assert log.unreached_calls == 2
    assert log.chases == 3
    assert log.by_channel == {CALL: 2, EMAIL: 1}


def test_the_first_response_is_measured_to_the_first_word_back():
    arrived = NOW - timedelta(hours=10)
    assert first_response_hours(
        arrived, [_contact(4), _contact(1)]
    ) == D("6.00")


def test_a_client_chasing_us_is_not_us_answering():
    arrived = NOW - timedelta(hours=10)
    entries = [_contact(8, direction=INBOUND), _contact(3)]
    assert first_response_hours(arrived, entries) == D("7.00")


def test_an_unanswered_enquiry_is_none_and_never_zero():
    arrived = NOW - timedelta(hours=10)
    assert first_response_hours(arrived, []) is None
    assert (
        first_response_hours(arrived, [_contact(2, direction=INBOUND)]) is None
    )
    assert first_response_hours(arrived, [_contact(2, voided=True)]) is None


def test_answering_the_phone_before_typing_the_lead_gives_zero_not_a_negative():
    arrived = NOW - timedelta(hours=2)
    assert first_response_hours(arrived, [_contact(5)]) == D("0.00")


def test_the_median_response_ignores_the_fortnight_somebody_was_on_leave():
    assert median_hours([D("1"), D("2"), D("300")]) == D("2")
    assert median_hours([D("1"), D("2"), D("3"), D("300")]) == D("2.50")
    assert median_hours([]) is None


def test_silence_needs_both_thresholds_and_both_are_the_callers():
    log = history([_contact(hours) for hours in (72, 48)])
    assert silence(log, now=NOW, after_chases=2, after_days=1) is not None
    assert silence(log, now=NOW, after_chases=2, after_days=7) is None
    assert silence(log, now=NOW, after_chases=5, after_days=1) is None


def test_silence_refuses_to_conclude():
    log = history([_contact(hours) for hours in (400, 300, 200)])
    quiet = silence(log, now=NOW, after_chases=2, after_days=5)
    assert quiet is not None
    assert quiet.chases == 3
    assert quiet.ever_replied is False
    assert "never replied" in quiet.message
    assert "not something a report can make" in quiet.message


def test_a_conversation_with_no_outbound_word_is_not_silence():
    log = history([_contact(100, direction=INBOUND)])
    assert silence(log, now=NOW, after_chases=1, after_days=1) is None
