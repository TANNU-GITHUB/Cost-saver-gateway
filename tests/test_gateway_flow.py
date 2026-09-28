def test_cache_hit_on_repeated_prompt(client):
    headers = {"Authorization": "Bearer gw_dev_default_key"}
    body = {"messages": [{"role": "user", "content": "gateway cache test unique phrase alpha"}]}
    first = client.post("/v1/chat/completions", headers=headers, json=body)
    assert first.status_code == 200
    assert first.headers.get("X-Cache") == "MISS"

    second = client.post("/v1/chat/completions", headers=headers, json=body)
    assert second.status_code == 200
    assert second.headers.get("X-Cache") == "HIT"
