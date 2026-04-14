def test_cors_preflight_allows_localhost_dev_origin(client):
    r = client.options(
        "/api/extract",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert r.headers.get("access-control-allow-credentials") == "true"


def test_cors_preflight_allows_loopback_dev_origin(client):
    r = client.options(
        "/api/extract",
        headers={
            "Origin": "http://127.0.0.1:4173",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "http://127.0.0.1:4173"
    assert r.headers.get("access-control-allow-credentials") == "true"
