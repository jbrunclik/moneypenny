"""Unit tests for validation utilities."""

import pytest
from pydantic import BaseModel, ValidationError, field_validator

from src.api.validation import pydantic_to_error_response


class SampleSchema(BaseModel):
    """Test schema for validation tests."""

    name: str
    age: int

    @field_validator("age")
    @classmethod
    def validate_age(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Age must be positive")
        return v


class NestedSchema(BaseModel):
    """Test schema with nested items."""

    items: list[SampleSchema]


class TestPydanticToErrorResponse:
    """Tests for pydantic_to_error_response function."""

    def test_missing_field_error(self) -> None:
        """Should convert missing field error."""
        with pytest.raises(ValidationError) as exc_info:
            SampleSchema(age=25)  # type: ignore[call-arg]

        response, status = pydantic_to_error_response(exc_info.value)

        assert status == 400
        assert response["error"]["code"] == "VALIDATION_ERROR"
        assert response["error"]["retryable"] is False
        assert response["error"]["details"]["field"] == "name"
        assert (
            "name" in response["error"]["message"].lower()
            or "required" in response["error"]["message"].lower()
        )

    def test_type_error(self) -> None:
        """Should convert type error."""
        with pytest.raises(ValidationError) as exc_info:
            SampleSchema(name="Test", age="not a number")  # type: ignore[arg-type]

        response, status = pydantic_to_error_response(exc_info.value)

        assert status == 400
        assert response["error"]["code"] == "VALIDATION_ERROR"
        assert response["error"]["details"]["field"] == "age"

    def test_custom_validator_error(self) -> None:
        """Should clean 'Value error, ' prefix from message."""
        with pytest.raises(ValidationError) as exc_info:
            SampleSchema(name="Test", age=-1)

        response, status = pydantic_to_error_response(exc_info.value)

        assert status == 400
        assert "Age must be positive" in response["error"]["message"]
        # Should NOT contain the "Value error, " prefix
        assert "Value error" not in response["error"]["message"]

    def test_nested_field_location(self) -> None:
        """Should handle nested field locations with dot notation."""
        with pytest.raises(ValidationError) as exc_info:
            NestedSchema(items=[{"name": "Test", "age": -1}])

        response, status = pydantic_to_error_response(exc_info.value)

        assert status == 400
        # Should have dot-separated field path
        field = response["error"]["details"]["field"]
        assert "items" in field
        assert "0" in field
        assert "age" in field

    def test_multiple_errors_returns_first(self) -> None:
        """Should return first error when multiple validation errors occur."""
        with pytest.raises(ValidationError) as exc_info:
            SampleSchema()  # type: ignore[call-arg]

        response, status = pydantic_to_error_response(exc_info.value)

        # Should return 400 with first error
        assert status == 400
        assert response["error"]["code"] == "VALIDATION_ERROR"
        # Should have a field in details
        assert "field" in response["error"]["details"]

    def test_empty_location(self) -> None:
        """Should handle empty location tuple."""

        class RootValidatorSchema(BaseModel):
            value: int

            @field_validator("value")
            @classmethod
            def validate_value(cls, v: int) -> int:
                if v == 0:
                    raise ValueError("Value cannot be zero")
                return v

        with pytest.raises(ValidationError) as exc_info:
            RootValidatorSchema(value=0)

        response, status = pydantic_to_error_response(exc_info.value)

        assert status == 400
        assert response["error"]["code"] == "VALIDATION_ERROR"
        # Field should be "value"
        assert response["error"]["details"]["field"] == "value"

    def test_error_message_preserved(self) -> None:
        """Should preserve the error message from validator."""

        class CustomMessageSchema(BaseModel):
            email: str

            @field_validator("email")
            @classmethod
            def validate_email(cls, v: str) -> str:
                if "@" not in v:
                    raise ValueError("Invalid email format - must contain @")
                return v

        with pytest.raises(ValidationError) as exc_info:
            CustomMessageSchema(email="notanemail")

        response, status = pydantic_to_error_response(exc_info.value)

        assert "Invalid email format - must contain @" in response["error"]["message"]


class TestMemoryBounds:
    """A2: memory writes are size-bounded (injected into every request)."""

    def test_oversized_add_rejected(self):
        from src.api.utils import validate_memory_operations
        from src.config import Config

        ops = [{"action": "add", "content": "x" * (Config.MEMORY_MAX_ENTRY_CHARS + 1)}]
        assert validate_memory_operations(ops) == []

    def test_normal_add_accepted(self):
        from src.api.utils import validate_memory_operations

        ops = [{"action": "add", "content": "User lives in Prague"}]
        assert len(validate_memory_operations(ops)) == 1

    def test_oversized_update_rejected(self):
        from src.api.utils import validate_memory_operations
        from src.config import Config

        ops = [
            {"action": "update", "id": "m1", "content": "x" * (Config.MEMORY_MAX_ENTRY_CHARS + 1)}
        ]
        assert validate_memory_operations(ops) == []
