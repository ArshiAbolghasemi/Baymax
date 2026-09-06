"""Cross-cutting helpers: correlation ids and duration logging."""

import logging

from hiro.common.logging import bind_correlation_id, get_logger, log_duration


class TestCorrelationId:
    def test_an_inbound_id_is_honoured(self):
        with bind_correlation_id("abc-123") as request_id:
            assert request_id == "abc-123"

    def test_a_missing_id_is_generated(self):
        with bind_correlation_id(None) as request_id:
            assert request_id

    def test_ids_do_not_leak_between_requests(self):
        with bind_correlation_id(None) as first:
            pass
        with bind_correlation_id(None) as second:
            pass
        assert first != second


class TestLogDuration:
    def test_the_block_still_runs_and_is_logged(self, caplog):
        logger = get_logger("tests.duration")
        with caplog.at_level(logging.INFO), log_duration(logger, "some work", items=2):
            result = 1 + 1
        assert result == 2

    def test_a_failure_inside_the_block_propagates(self):
        logger = get_logger("tests.duration")
        try:
            with log_duration(logger, "failing work"):
                raise ValueError("boom")
        except ValueError as error:
            assert str(error) == "boom"
        else:  # pragma: no cover
            raise AssertionError("the error was swallowed")
