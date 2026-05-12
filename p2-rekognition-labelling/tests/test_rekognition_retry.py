"""
Unit tests for detect_labels_with_retry (task 2.3).

Verifies:
- Successful call on first attempt returns labels without sleeping.
- Transient errors trigger retries with the correct delays (100ms, 200ms, 400ms).
- After 3 failed attempts the exception is re-raised (4th attempt also fails).
- Permanent errors (e.g. InvalidS3ObjectException) are raised immediately without retrying.
- A transient failure followed by a success returns the labels.

Requirements: 2.6
"""

from unittest.mock import MagicMock, call, patch

import pytest
from botocore.exceptions import ClientError

from tagging_handler.rekognition import (
    _RETRY_DELAYS,
    _TRANSIENT_ERROR_CODES,
    detect_labels_with_retry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client_error(code: str) -> ClientError:
    """Build a ClientError with the given error code."""
    return ClientError(
        error_response={"Error": {"Code": code, "Message": "test"}},
        operation_name="DetectLabels",
    )


SAMPLE_LABELS = [{"Name": "Bridge", "Confidence": 95.0}]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDetectLabelsWithRetry:
    def test_success_on_first_attempt_returns_labels(self):
        """No retries needed — labels returned immediately."""
        sleep_mock = MagicMock()
        with patch(
            "tagging_handler.rekognition.detect_labels", return_value=SAMPLE_LABELS
        ) as mock_detect:
            result = detect_labels_with_retry("my-bucket", "my-key", _sleep=sleep_mock)

        assert result == SAMPLE_LABELS
        mock_detect.assert_called_once_with("my-bucket", "my-key")
        sleep_mock.assert_not_called()

    def test_transient_error_retries_with_correct_delays(self):
        """Three transient failures then success — delays match 100ms, 200ms, 400ms."""
        sleep_mock = MagicMock()
        transient_error = _client_error("ThrottlingException")

        with patch(
            "tagging_handler.rekognition.detect_labels",
            side_effect=[transient_error, transient_error, transient_error, SAMPLE_LABELS],
        ) as mock_detect:
            result = detect_labels_with_retry("b", "k", _sleep=sleep_mock)

        assert result == SAMPLE_LABELS
        assert mock_detect.call_count == 4
        # Delays: 0.1, 0.2, 0.4 (one sleep per failed attempt before the next try)
        assert sleep_mock.call_args_list == [call(0.1), call(0.2), call(0.4)]

    def test_all_attempts_fail_raises_exception(self):
        """All 4 attempts fail — ClientError is re-raised to trigger dead-lettering."""
        sleep_mock = MagicMock()
        transient_error = _client_error("ServiceUnavailableException")

        with patch(
            "tagging_handler.rekognition.detect_labels",
            side_effect=[transient_error] * 4,
        ) as mock_detect:
            with pytest.raises(ClientError) as exc_info:
                detect_labels_with_retry("b", "k", _sleep=sleep_mock)

        assert mock_detect.call_count == 4
        assert exc_info.value.response["Error"]["Code"] == "ServiceUnavailableException"
        # Three sleeps between the first three failures; no sleep after the final attempt
        assert sleep_mock.call_count == 3

    def test_permanent_error_raises_immediately_without_retry(self):
        """InvalidS3ObjectException is permanent — raised on first attempt, no retries."""
        sleep_mock = MagicMock()
        permanent_error = _client_error("InvalidS3ObjectException")

        with patch(
            "tagging_handler.rekognition.detect_labels",
            side_effect=permanent_error,
        ) as mock_detect:
            with pytest.raises(ClientError) as exc_info:
                detect_labels_with_retry("b", "k", _sleep=sleep_mock)

        mock_detect.assert_called_once()
        sleep_mock.assert_not_called()
        assert exc_info.value.response["Error"]["Code"] == "InvalidS3ObjectException"

    def test_invalid_image_format_raises_immediately(self):
        """InvalidImageFormatException is permanent — no retries."""
        sleep_mock = MagicMock()
        permanent_error = _client_error("InvalidImageFormatException")

        with patch(
            "tagging_handler.rekognition.detect_labels",
            side_effect=permanent_error,
        ) as mock_detect:
            with pytest.raises(ClientError):
                detect_labels_with_retry("b", "k", _sleep=sleep_mock)

        mock_detect.assert_called_once()
        sleep_mock.assert_not_called()

    def test_transient_then_success_returns_labels(self):
        """One transient failure then success — returns labels after one retry."""
        sleep_mock = MagicMock()
        transient_error = _client_error("LimitExceededException")

        with patch(
            "tagging_handler.rekognition.detect_labels",
            side_effect=[transient_error, SAMPLE_LABELS],
        ) as mock_detect:
            result = detect_labels_with_retry("b", "k", _sleep=sleep_mock)

        assert result == SAMPLE_LABELS
        assert mock_detect.call_count == 2
        sleep_mock.assert_called_once_with(0.1)

    def test_retry_delays_match_spec(self):
        """The configured delays are exactly 100ms, 200ms, 400ms."""
        assert _RETRY_DELAYS == (0.1, 0.2, 0.4)

    def test_all_transient_codes_are_retried(self):
        """Every code in _TRANSIENT_ERROR_CODES triggers a retry (not an immediate raise)."""
        for code in _TRANSIENT_ERROR_CODES:
            sleep_mock = MagicMock()
            error = _client_error(code)

            with patch(
                "tagging_handler.rekognition.detect_labels",
                side_effect=[error, SAMPLE_LABELS],
            ):
                result = detect_labels_with_retry("b", "k", _sleep=sleep_mock)

            assert result == SAMPLE_LABELS, f"Expected retry for code {code}"
            sleep_mock.assert_called_once_with(0.1)
