
import os

# Use a test-only token before importing the application.
os.environ["REMOTE_TOKEN"] = "test-token-for-unit-tests"
os.environ.pop("GEMINI_API_KEY", None)

from fastapi.testclient import TestClient
from server import app

client = TestClient(app)

TEST_HEADERS = {
    "Authorization": "Bearer test-token-for-unit-tests"
}


def test_home_returns_server_status():
    response = client.get("/")

    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Remote Control AI server is running"
    assert "laptops_online" in data
    assert data["ai_enabled"] is False


def test_laptops_rejects_missing_token():
    response = client.get("/laptops")

    assert response.status_code == 401


def test_laptops_accepts_test_token():
    response = client.get("/laptops", headers=TEST_HEADERS)

    assert response.status_code == 200
    assert isinstance(response.json(), dict)


def test_command_rejects_missing_token():
    response = client.post(
        "/command/my-laptop",
        json={"command": "open_chrome"},
    )

    assert response.status_code == 401


def test_command_rejects_unknown_command():
    response = client.post(
        "/command/my-laptop",
        headers=TEST_HEADERS,
        json={"command": "run_arbitrary_shell_command"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Command is not allowed"


def test_laptops_rejects_invalid_token():
    response = client.get(
        "/laptops",
        headers={"Authorization": "Bearer wrong-token"},
    )

    assert response.status_code == 401


def test_command_rejects_invalid_token():
    response = client.post(
        "/command/my-laptop",
        headers={"Authorization": "Bearer wrong-token"},
        json={"command": "open_chrome"},
    )

    assert response.status_code == 401


def test_restart_requires_confirmation_token():
    response = client.post(
        "/command/my-laptop",
        headers=TEST_HEADERS,
        json={"command": "restart"},
    )

    assert response.status_code == 428
    assert response.json()["detail"] == (
        "A valid, unexpired confirmation token is required"
    )


def test_shutdown_rejects_invalid_confirmation_token():
    response = client.post(
        "/command/my-laptop",
        headers=TEST_HEADERS,
        json={
            "command": "shutdown",
            "confirmation_token": "invalid-confirmation-token",
        },
    )

    assert response.status_code == 428
    assert response.json()["detail"] == (
        "A valid, unexpired confirmation token is required"
    )


def test_confirmation_token_cannot_be_reused_for_another_laptop():
    from server import create_confirmation

    token = create_confirmation("laptop-A", "restart")

    response = client.post(
        "/command/laptop-B",
        headers=TEST_HEADERS,
        json={
            "command": "restart",
            "confirmation_token": token,
        },
    )

    assert response.status_code == 428


def test_confirmation_token_cannot_be_used_for_another_command():
    from server import create_confirmation

    token = create_confirmation("my-laptop", "restart")

    response = client.post(
        "/command/my-laptop",
        headers=TEST_HEADERS,
        json={
            "command": "shutdown",
            "confirmation_token": token,
        },
    )

    assert response.status_code == 428


def test_confirmation_token_cannot_be_reused():
    from server import consume_confirmation, create_confirmation

    token = create_confirmation("my-laptop", "restart")

    first_use = consume_confirmation(
        token, "my-laptop", "restart"
    )
    second_use = consume_confirmation(
        token, "my-laptop", "restart"
    )

    assert first_use is True
    assert second_use is False
