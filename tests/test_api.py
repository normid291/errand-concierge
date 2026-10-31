"""HTTP API and storage behaviour."""

from __future__ import annotations

from datetime import date, timedelta


def create(client, **payload):
    response = client.post("/api/errands", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_health_and_config(client):
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["assistant"] == "demo"

    config = client.get("/api/config").json()
    assert config["mode"] == "demo"
    assert config["calendar_timezone"] == "Africa/Lagos"


def test_crud_and_status_flow(client):
    errand = create(client, title="Pay rent", due="Friday", notes="Bank transfer")
    assert errand["status"] == "pending"
    assert errand["due_text"] == "Friday"
    assert errand["due_at"] is not None

    listed = client.get("/api/errands?status=pending").json()["errands"]
    assert [item["id"] for item in listed] == [errand["id"]]

    updated = client.patch(f"/api/errands/{errand['id']}", json={"title": "Pay rent early"}).json()
    assert updated["title"] == "Pay rent early"

    done = client.post(f"/api/errands/{errand['id']}/complete").json()
    assert done["status"] == "done"
    assert done["completed_at"]

    reopened = client.post(f"/api/errands/{errand['id']}/reopen").json()
    assert reopened["status"] == "pending"
    assert reopened["completed_at"] is None

    cancelled = client.post(f"/api/errands/{errand['id']}/cancel").json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancelled_at"]

    assert client.get("/api/errands?status=pending").json()["errands"] == []
    assert len(client.get("/api/errands?status=cancelled").json()["errands"]) == 1


def test_validation_rejects_empty_title(client):
    response = client.post("/api/errands", json={"title": "   "})
    assert response.status_code == 422


def test_delete_moves_to_trash_and_restore(client):
    errand = create(client, title="Renew passport", due="next week")
    response = client.delete(f"/api/errands/{errand['id']}")
    assert response.status_code == 200

    assert client.get(f"/api/errands/{errand['id']}").status_code == 404
    trash = client.get("/api/errands/trash").json()["errands"]
    assert trash[0]["id"] == errand["id"]
    assert trash[0]["deleted_at"]

    restored = client.post(f"/api/errands/trash/{errand['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["id"] == errand["id"]
    assert client.get("/api/errands/trash").json()["errands"] == []


def test_permanent_trash_delete_and_clear(client):
    first = create(client, title="First")
    second = create(client, title="Second")
    client.delete(f"/api/errands/{first['id']}")
    client.delete(f"/api/errands/{second['id']}")

    assert client.delete(f"/api/errands/trash/{first['id']}").status_code == 200
    assert len(client.get("/api/errands/trash").json()["errands"]) == 1

    cleared = client.post("/api/errands/trash/clear")
    assert cleared.status_code == 200
    assert client.get("/api/errands/trash").json()["errands"] == []


def test_search_filters_title_and_notes(client):
    create(client, title="Dentist appointment", notes="Ask about whitening")
    create(client, title="Pay electricity", notes="November bill")

    by_title = client.get("/api/errands?q=dentist").json()["errands"]
    assert [item["title"] for item in by_title] == ["Dentist appointment"]

    by_notes = client.get("/api/errands?q=november").json()["errands"]
    assert [item["title"] for item in by_notes] == ["Pay electricity"]

    assert client.get("/api/errands?q=%25").json()["errands"] == []


def test_stats_counts_overdue_and_today(client):
    past = (date.today() - timedelta(days=2)).isoformat()
    create(client, title="Overdue thing", due=past)
    create(client, title="Today thing", due=date.today().isoformat())
    create(client, title="No date")

    stats = client.get("/api/stats").json()
    assert stats["pending"] == 3
    assert stats["overdue"] == 1
    assert stats["due_today"] == 1


def test_chat_demo_adds_and_updates_errands(client):
    response = client.post(
        "/api/chat",
        json={"message": "pay electricity bill by Friday, call mum tomorrow", "session_id": "test-session-123"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "demo"
    assert body["session_id"] == "test-session-123"

    titles = [item["title"] for item in client.get("/api/errands").json()["errands"]]
    assert "Pay electricity bill" in titles
    assert "Call mum" in titles

    reschedule = client.post(
        "/api/chat",
        json={"message": "push the electricity bill to next week", "session_id": "test-session-123"},
    )
    assert reschedule.status_code == 200
    assert "next week" in reschedule.json()["reply"].lower()

    complete = client.post(
        "/api/chat",
        json={"message": "mark electricity bill done", "session_id": "test-session-123"},
    )
    assert "done" in complete.json()["reply"].lower()

    pending = client.get("/api/errands?status=pending").json()["errands"]
    assert [item["title"] for item in pending] == ["Call mum"]


def test_chat_rejects_blank_message(client):
    assert client.post("/api/chat", json={"message": "  "}).status_code == 422


def test_reset_chat_is_idempotent(client):
    assert client.delete("/api/chat/unknown-session").status_code == 200


def test_frontend_is_served(settings):
    from fastapi.testclient import TestClient

    from app.config import BASE_DIR
    from app.factory import create_app

    # The fixture settings point base_dir at tmp_path, so build one whose
    # base_dir is the repository root to exercise static serving.
    root_settings = settings.__class__(
        base_dir=BASE_DIR,
        database_path=settings.database_path,
        demo_mode=True,
        app_secret="test-secret",
    )
    with TestClient(create_app(root_settings)) as client:
        index = client.get("/")
        assert index.status_code == 200
        assert "Errand Concierge" in index.text
        assert client.get("/styles.css").status_code == 200
        assert client.get("/app.js").status_code == 200
