def test_health(client):
    # Verify that the health endpoint is working

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
