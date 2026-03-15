"""Python service with HTTP calls to other services."""

import requests


def call_lua_endpoint(data: dict):
    """Call a Lua-backed endpoint."""
    response = requests.post("http://lua-svc:8080/api/process", json=data)
    return response.json()


def fetch_user(user_id: int):
    """GET request to another service."""
    response = requests.get(f"http://lua-svc:8080/api/users/{user_id}")
    return response.json()


def notify_webhook(url: str, payload: dict):
    """POST to an external webhook."""
    requests.post("https://hooks.example.com/notify", json=payload)
