def test_missing_api_key_returns_401(client):
    resp = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hello"}]},
    )
    assert resp.status_code == 401


def test_default_dev_key_works(client):
    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer gw_dev_default_key"},
        json={"messages": [{"role": "user", "content": "hello"}]},
    )
    assert resp.status_code == 200
    assert resp.headers.get("X-Cache") == "MISS"
