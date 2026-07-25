"""Live meeting-minutes (Faz 1): create -> start -> transcribe -> tag -> end.

ASR is mocked (``app.asr.transcribe``/``asr_available``) so these tests need
no real faster-whisper model weights or audio decoding — they only exercise
the API contract (edit-token access control, status transitions, manual
speaker tagging).
"""


def _mock_asr(monkeypatch, text="Merhaba, bugün gündemi konuşalım."):
    # Import fresh, *after* the `client` fixture has reimported `app.*` for
    # this test's isolated DB (see conftest.py) — importing at module load
    # time would bind to a stale module object from before that reimport.
    import app.asr as asr_module

    monkeypatch.setattr(asr_module, "asr_available", lambda: True)
    monkeypatch.setattr(asr_module, "transcribe", lambda audio_bytes: text)


def _create_and_start(client):
    r = client.post(
        "/api/meetings",
        json={
            "title": "Şubat Ayı Değerlendirme",
            "agenda_items": ["Üretim hedefleri", "Kalite kontrol"],
            "participants": ["Onur Aydın", "Melis Kaya"],
        },
    )
    assert r.status_code == 201, r.text
    meeting = r.json()
    headers = {"X-Edit-Token": meeting["edit_token"]}
    r = client.post(f"/api/meetings/{meeting['id']}/start", headers=headers)
    assert r.status_code == 200, r.text
    return r.json(), headers


def test_create_meeting_returns_edit_token_and_setup_status(client):
    r = client.post(
        "/api/meetings",
        json={"title": "Kısa Toplantı", "agenda_items": [], "participants": ["Ali"]},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "setup"
    assert body["started_at"] is None
    assert isinstance(body["edit_token"], str) and len(body["edit_token"]) > 10
    assert len(body["participants"]) == 1
    assert body["participants"][0]["display_name"] == "Ali"


def test_get_requires_token__missing_and_wrong_403__unknown_id_404(client):
    r = client.post("/api/meetings", json={"title": "T", "agenda_items": [], "participants": []})
    meeting_id = r.json()["id"]
    token = r.json()["edit_token"]

    assert client.get(f"/api/meetings/{meeting_id}").status_code == 403
    assert (
        client.get(f"/api/meetings/{meeting_id}", headers={"X-Edit-Token": "wrong"}).status_code
        == 403
    )
    assert client.get("/api/meetings/999999", headers={"X-Edit-Token": token}).status_code == 404
    assert (
        client.get(f"/api/meetings/{meeting_id}", headers={"X-Edit-Token": token}).status_code
        == 200
    )


def test_audio_chunk_requires_live_status(client, monkeypatch):
    _mock_asr(monkeypatch)
    r = client.post(
        "/api/meetings",
        json={"title": "Henüz Başlamadı", "agenda_items": [], "participants": []},
    )
    meeting_id = r.json()["id"]
    headers = {"X-Edit-Token": r.json()["edit_token"]}
    r = client.post(
        f"/api/meetings/{meeting_id}/audio-chunk",
        headers=headers,
        files={"audio": ("chunk.webm", b"fake-audio-bytes", "audio/webm")},
    )
    assert r.status_code == 409, r.text


def test_full_transcript_flow_with_manual_tagging(client, monkeypatch):
    _mock_asr(monkeypatch)
    meeting, headers = _create_and_start(client)
    meeting_id = meeting["id"]
    onur = next(p for p in meeting["participants"] if p["display_name"] == "Onur Aydın")
    melis = next(p for p in meeting["participants"] if p["display_name"] == "Melis Kaya")

    # Tagged chunk (speaker chip selected client-side).
    r = client.post(
        f"/api/meetings/{meeting_id}/audio-chunk",
        headers=headers,
        data={"participant_id": str(onur["id"])},
        files={"audio": ("chunk1.webm", b"fake-audio-1", "audio/webm")},
    )
    assert r.status_code == 200, r.text
    seg1 = r.json()
    assert seg1["participant_id"] == onur["id"]
    assert seg1["participant_name"] == "Onur Aydın"
    assert seg1["text"] == "Merhaba, bugün gündemi konuşalım."

    # Untagged chunk — nobody selected as speaking, tagged later manually.
    r = client.post(
        f"/api/meetings/{meeting_id}/audio-chunk",
        headers=headers,
        files={"audio": ("chunk2.webm", b"fake-audio-2", "audio/webm")},
    )
    assert r.status_code == 200, r.text
    seg2 = r.json()
    assert seg2["participant_id"] is None

    # Silence: an empty transcription creates no segment.
    _mock_asr(monkeypatch, text="")
    r = client.post(
        f"/api/meetings/{meeting_id}/audio-chunk",
        headers=headers,
        files={"audio": ("silence.webm", b"fake-silence", "audio/webm")},
    )
    assert r.status_code == 204, r.text

    # Poll for new segments.
    r = client.get(f"/api/meetings/{meeting_id}/segments", headers=headers, params={"after_id": 0})
    assert r.status_code == 200, r.text
    ids = [s["id"] for s in r.json()]
    assert ids == [seg1["id"], seg2["id"]]

    r = client.get(
        f"/api/meetings/{meeting_id}/segments", headers=headers, params={"after_id": seg1["id"]}
    )
    assert [s["id"] for s in r.json()] == [seg2["id"]]

    # Manually tag the untagged line, and fix a typo on the first line.
    r = client.patch(
        f"/api/meetings/{meeting_id}/segments/{seg2['id']}",
        headers=headers,
        json={"participant_id": melis["id"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["participant_name"] == "Melis Kaya"

    r = client.patch(
        f"/api/meetings/{meeting_id}/segments/{seg1['id']}",
        headers=headers,
        json={"text": "Merhaba, gündemi konuşalım."},
    )
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "Merhaba, gündemi konuşalım."

    # End the meeting: final GET reflects everything.
    r = client.post(f"/api/meetings/{meeting_id}/end", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ended"
    assert r.json()["ended_at"] is not None

    r = client.get(f"/api/meetings/{meeting_id}", headers=headers)
    final = r.json()
    assert final["status"] == "ended"
    assert len(final["segments"]) == 2
    assert {s["participant_name"] for s in final["segments"]} == {"Onur Aydın", "Melis Kaya"}


def test_segment_patch_requires_a_field(client, monkeypatch):
    _mock_asr(monkeypatch)
    meeting, headers = _create_and_start(client)
    r = client.post(
        f"/api/meetings/{meeting['id']}/audio-chunk",
        headers=headers,
        files={"audio": ("chunk.webm", b"fake-audio", "audio/webm")},
    )
    seg = r.json()
    r = client.patch(
        f"/api/meetings/{meeting['id']}/segments/{seg['id']}", headers=headers, json={}
    )
    assert r.status_code == 422, r.text


def test_audio_chunk_503_when_asr_unavailable(client, monkeypatch):
    import app.asr as asr_module

    monkeypatch.setattr(asr_module, "asr_available", lambda: False)
    meeting, headers = _create_and_start(client)
    r = client.post(
        f"/api/meetings/{meeting['id']}/audio-chunk",
        headers=headers,
        files={"audio": ("chunk.webm", b"fake-audio", "audio/webm")},
    )
    assert r.status_code == 503, r.text


def test_token_from_one_meeting_rejected_on_another_meeting(client):
    r1 = client.post("/api/meetings", json={"title": "Toplantı 1", "agenda_items": [], "participants": []})
    r2 = client.post("/api/meetings", json={"title": "Toplantı 2", "agenda_items": [], "participants": []})
    meeting2_id = r2.json()["id"]
    token1 = r1.json()["edit_token"]

    r = client.post(f"/api/meetings/{meeting2_id}/start", headers={"X-Edit-Token": token1})
    assert r.status_code == 403, r.text
