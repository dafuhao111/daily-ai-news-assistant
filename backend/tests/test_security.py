from fastapi.testclient import TestClient


def test_rejects_non_local_host(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"Host": "attacker.example"})
    assert response.status_code == 400
    assert response.json() == {"detail": "host_not_allowed"}


def test_mutation_requires_local_origin_and_json(
    client: TestClient, local_headers: dict[str, str]
) -> None:
    payload = {"display_name": "Lin"}
    response = client.put(
        "/api/v1/profile",
        json=payload,
        headers={"Host": "127.0.0.1", "Origin": "https://attacker.example"},
    )
    assert response.status_code == 403

    response = client.put(
        "/api/v1/profile",
        content='{"display_name":"Lin"}',
        headers={**local_headers, "Content-Type": "text/plain"},
    )
    assert response.status_code == 415


def test_missing_origin_is_rejected_for_mutations(
    client: TestClient, local_headers: dict[str, str]
) -> None:
    response = client.put(
        "/api/v1/profile",
        json={"display_name": "Lin"},
        headers={"Host": local_headers["Host"]},
    )
    assert response.status_code == 403
