"""Stage 2: CRUD, filtering, sorting, pagination, counts, soft delete."""

from __future__ import annotations

import sqlite3

from backend.config import Paths
from backend.database import open_connection


def _create(client, company="示例科技", job="前端工程师", **extra) -> dict:
    body = {
        "company_name": company,
        "job_title": job,
        "event_date": "2026-08-01",
    }
    body.update(extra)
    resp = client.post("/api/applications", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_and_get_roundtrip(client):
    created = _create(client, location="上海", source="官网", application_type="实习")
    assert created["current_status"] == "pending_review"
    assert created["archived_at"] is None

    got = client.get(f"/api/applications/{created['id']}")
    assert got.status_code == 200
    body = got.json()
    assert body["application"]["id"] == created["id"]
    # Creating a record seeds a pending_review event.
    assert len(body["events"]) == 1
    assert body["events"][0]["stage"] == "pending_review"


def test_create_requires_company_and_job(client):
    resp = client.post(
        "/api/applications", json={"job_title": "前端工程师", "event_date": "2026-08-01"}
    )
    assert resp.status_code == 422
    resp = client.post(
        "/api/applications", json={"company_name": "示例科技", "event_date": "2026-08-01"}
    )
    assert resp.status_code == 422


def test_patch_updates_metadata_but_not_status(client):
    created = _create(client)
    resp = client.patch(
        f"/api/applications/{created['id']}",
        json={"location": "北京", "notes": "备注", "next_action_date": "2026-08-10"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["location"] == "北京"
    assert body["current_status"] == "pending_review"
    # status field is not accepted on patch
    resp2 = client.patch(f"/api/applications/{created['id']}", json={"current_status": "offer"})
    assert resp2.status_code == 422


def test_soft_delete_hides_record(client):
    created = _create(client)
    resp = client.delete(f"/api/applications/{created['id']}")
    assert resp.status_code == 204

    listing = client.get("/api/applications").json()
    assert listing["total"] == 0
    # Events are preserved, not physically deleted.
    connection = open_connection(client.app.state.paths)
    event_count = connection.execute(
        "SELECT count(*) AS c FROM application_events"
    ).fetchone()["c"]
    assert event_count >= 1
    connection.close()


def test_search_filters_counts_and_options(client):
    _create(client, company="示例科技", job="前端工程师", location="上海", source="官网", application_type="实习")
    _create(client, company="示例科技", job="后端工程师", location="北京", source="内推", application_type="校招")
    _create(client, company="另一公司", job="算法工程师", location="上海", source="官网", application_type="实习")

    # q search
    r = client.get("/api/applications", params={"q": "前端"}).json()
    assert r["total"] == 1
    assert r["items"][0]["job_title"] == "前端工程师"

    # type filter
    r = client.get("/api/applications", params={"type": "实习"}).json()
    assert r["total"] == 2

    # city filter
    r = client.get("/api/applications", params={"city": "北京"}).json()
    assert r["total"] == 1

    # source filter
    r = client.get("/api/applications", params={"source": "内推"}).json()
    assert r["total"] == 1

    # counts respect non-status filters (q/type/city/source) but not status
    r = client.get("/api/applications", params={"type": "实习"}).json()
    assert r["counts"]["pending_review"] == 2
    assert set(r["options"]["types"]) == {"实习", "校招"}
    assert "北京" in r["options"]["cities"]
    assert "上海" in r["options"]["cities"]


def test_stage_group_filter(client):
    _create(client, company="A", job="x", location="上海")
    first_id = client.get("/api/applications").json()["items"][0]["id"]
    client.post(
        f"/api/applications/{first_id}/events",
        json={"stage": "interview_1", "event_date": "2026-08-15", "scheduled_date": "2026-08-20"},
    )
    r = client.get("/api/applications", params={"stage_group": "interview"}).json()
    assert r["total"] == 1


def test_listing_keeps_each_record_bound_to_its_latest_event(client):
    first = _create(client, company="甲公司", job="前端工程师")
    second = _create(client, company="乙公司", job="后端工程师")

    first_event = client.post(
        f"/api/applications/{first['id']}/events",
        json={
            "stage": "interview_1",
            "event_date": "2026-08-12",
            "scheduled_date": "2026-08-15",
        },
    )
    second_event = client.post(
        f"/api/applications/{second['id']}/events",
        json={"stage": "offer", "event_date": "2026-08-13"},
    )
    assert first_event.status_code == 201
    assert second_event.status_code == 201

    items = client.get("/api/applications", params={"sort": "company_name"}).json()["items"]
    latest_by_id = {item["id"]: item["latest_event"]["stage"] for item in items}
    assert latest_by_id == {
        first["id"]: "interview_1",
        second["id"]: "offer",
    }


def test_sort_and_pagination(client):
    for i in range(25):
        _create(client, company=f"公司{i:02d}", job=f"岗位{i}")
    # default sort updated_at desc, page size 20
    r = client.get("/api/applications").json()
    assert r["total"] == 25
    assert r["page_size"] == 20
    assert len(r["items"]) == 20
    r2 = client.get("/api/applications", params={"page": 2}).json()
    assert len(r2["items"]) == 5
    ids1 = {item["id"] for item in r["items"]}
    ids2 = {item["id"] for item in r2["items"]}
    assert ids1.isdisjoint(ids2)
    # company_name sort ascending
    rasc = client.get("/api/applications", params={"sort": "company_name"}).json()
    names = [item["company_name"] for item in rasc["items"]]
    assert names[0] == "公司00"
    rdesc = client.get("/api/applications", params={"sort": "-company_name"}).json()
    desc_names = [item["company_name"] for item in rdesc["items"]]
    assert desc_names[0] == "公司24"

    newest_id = rdesc["items"][0]["id"]
    client.patch(f"/api/applications/{newest_id}", json={"notes": "触发更新时间"})
    latest = client.get("/api/applications", params={"sort": "updated_at"}).json()
    earliest = client.get("/api/applications", params={"sort": "-updated_at"}).json()
    assert latest["items"][0]["id"] == newest_id
    assert earliest["items"][0]["id"] != newest_id


def test_ended_group_filter(client):
    created = _create(client)
    response = client.post(
        f"/api/applications/{created['id']}/events",
        json={"stage": "offer", "event_date": "2026-08-20"},
    )
    assert response.status_code == 201
    listing = client.get("/api/applications", params={"stage_group": "ended"})
    assert listing.status_code == 200
    assert listing.json()["total"] == 1


def test_application_type_is_fixed_enum_on_create_and_patch(client):
    invalid_create = client.post(
        "/api/applications",
        json={
            "company_name": "示例科技",
            "job_title": "前端工程师",
            "application_type": "未知类型",
            "event_date": "2026-08-01",
        },
    )
    assert invalid_create.status_code == 422
    assert invalid_create.json()["code"] == "validation_error"

    created = _create(client)
    invalid_patch = client.patch(
        f"/api/applications/{created['id']}", json={"application_type": "未知类型"}
    )
    assert invalid_patch.status_code == 422
    assert invalid_patch.json()["code"] == "validation_error"


def test_unknown_sort_field_rejected(client):
    resp = client.get("/api/applications", params={"sort": "bogus"})
    assert resp.status_code == 422


def test_unknown_status_rejected(client):
    resp = client.get("/api/applications", params={"status": "nonsense"})
    assert resp.status_code == 422


def test_concurrent_writes_do_not_corrupt(private_root, db_path, app):
    from concurrent.futures import ThreadPoolExecutor
    from fastapi.testclient import TestClient

    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        def make(i):
            response = c.post(
                "/api/applications",
                json={"company_name": f"并发{i}", "job_title": "岗位", "event_date": "2026-08-01"},
            )
            return response.status_code, response.text[:200]

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(make, range(40)))
        codes = [code for code, _ in results]
        assert all(code == 201 for code in codes), codes[:10]
    connection = open_connection(app.state.paths)
    count = connection.execute("SELECT count(*) AS c FROM applications").fetchone()["c"]
    connection.close()
    assert count == 40
