import json
import logging

import pytest

from crycon.observability import emit_event, event_json


def test_event_json_is_machine_readable_and_omits_none():
    record = json.loads(event_json(
        "job_finished",
        worker_id="worker-a",
        job_id=7,
        error_type=None,
    ))

    assert record["event"] == "job_finished"
    assert record["worker_id"] == "worker-a"
    assert record["job_id"] == 7
    assert "error_type" not in record
    assert record["timestamp"].endswith("+00:00")


@pytest.mark.parametrize("field", ["api_key", "token", "query", "error_message"])
def test_structured_logs_reject_sensitive_field_names(field):
    with pytest.raises(ValueError, match="unsafe structured log field"):
        event_json("unsafe", **{field: "do-not-log"})


def test_emit_event_writes_one_json_log_line(caplog):
    logger = logging.getLogger("crycon.test.observability")

    with caplog.at_level(logging.INFO, logger=logger.name):
        emit_event(logger, "worker_idle", worker_id="worker-a")

    assert json.loads(caplog.messages[-1])["event"] == "worker_idle"
