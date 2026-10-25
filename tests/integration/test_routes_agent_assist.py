"""AI assist routes for the agent editor: schedule parsing and prompt enhancement.

The model is faked; these cover the parsing, validation and error shapes.
"""

from unittest.mock import MagicMock, patch

from flask.testing import FlaskClient
from langchain_core.messages import AIMessage

_MODEL = "src.api.routes.agent_assist.chat_model"


def _model_saying(text: str) -> MagicMock:
    model = MagicMock()
    model.invoke.return_value = AIMessage(content=text)
    return model


def _model_raising(error: Exception) -> MagicMock:
    model = MagicMock()
    model.invoke.side_effect = error
    return model


class TestParseSchedule:
    URL = "/api/ai-assist/parse-schedule"

    def test_returns_a_valid_cron(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        reply = '```json\n{"cron": "0 9 * * 1-5", "explanation": "Weekdays at 9:00"}\n```'
        with patch(_MODEL, return_value=_model_saying(reply)):
            data = client.post(
                self.URL, json={"natural_language": "weekdays at 9"}, headers=auth_headers
            ).get_json()
        assert data == {"cron": "0 9 * * 1-5", "explanation": "Weekdays at 9:00", "error": None}

    def test_rejects_an_invalid_cron(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        with patch(_MODEL, return_value=_model_saying('{"cron": "99 99 * * *"}')):
            data = client.post(
                self.URL, json={"natural_language": "whenever"}, headers=auth_headers
            ).get_json()
        assert data["cron"] is None
        assert data["error"] == "Generated invalid cron expression"

    def test_a_model_failure_does_not_leak_its_message(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        failure = RuntimeError("upstream said: key AIza-secret quota exceeded")
        with patch(_MODEL, return_value=_model_raising(failure)):
            data = client.post(
                self.URL, json={"natural_language": "daily"}, headers=auth_headers
            ).get_json()
        assert data["cron"] is None
        assert "AIza" not in data["error"]

    def test_validates_the_body(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        response = client.post(self.URL, json={"natural_language": ""}, headers=auth_headers)
        assert response.status_code == 400

    def test_auth_comes_before_validation(self, client: FlaskClient) -> None:
        assert client.post(self.URL, json={}).status_code == 401


class TestEnhancePrompt:
    URL = "/api/ai-assist/enhance-prompt"

    def test_returns_the_enhanced_prompt(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        reply = '{"enhanced_prompt": "Summarize the news every morning.", "error": null}'
        with patch(_MODEL, return_value=_model_saying(reply)):
            data = client.post(
                self.URL, json={"prompt": "news", "agent_name": "News"}, headers=auth_headers
            ).get_json()
        assert data == {"enhanced_prompt": "Summarize the news every morning.", "error": None}

    def test_a_model_failure_does_not_leak_its_message(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        failure = RuntimeError("connection reset by 10.0.0.7")
        with patch(_MODEL, return_value=_model_raising(failure)):
            data = client.post(
                self.URL, json={"prompt": "news", "agent_name": "News"}, headers=auth_headers
            ).get_json()
        assert data["enhanced_prompt"] is None
        assert "10.0.0.7" not in data["error"]

    def test_auth_comes_before_validation(self, client: FlaskClient) -> None:
        assert client.post(self.URL, json={}).status_code == 401
