"""GeminiClient 가 SDK를 맞게 쓰는지 (네트워크 없이 응답을 흉내냄)."""

import pytest
from google.genai import errors, types

from nstore.detail.gemini import GeminiClient, GeminiError
from nstore.detail.schema import ReviewInsights


@pytest.fixture
def client(monkeypatch):
    c = GeminiClient("test-key", "text-model", "image-model")
    calls = []

    def fake_generate(model, contents, config):
        calls.append((model, contents, config))
        return c._next

    monkeypatch.setattr(c._client.models, "generate_content", fake_generate)
    c.calls = calls
    return c


def test_json_uses_schema_and_parses(client, tmp_path):
    pdf = tmp_path / "catalog.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    client._next = types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(parts=[
        types.Part(text='{"selling_points": ["가벼움"], "complaints": [], "questions": []}')]))])
    result = client.json("정리해줘", ReviewInsights, files=[pdf], system="원칙")
    assert result.selling_points == ["가벼움"]
    model, contents, config = client.calls[0]
    assert model == "text-model"
    assert contents[0].inline_data.mime_type == "application/pdf" and contents[-1] == "정리해줘"
    assert config.response_mime_type == "application/json" and config.response_schema is ReviewInsights


def test_image_returns_bytes_and_sets_ratio(client, tmp_path):
    photo = tmp_path / "front.jpg"
    photo.write_bytes(b"jpg")
    client._next = types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(parts=[
        types.Part(inline_data=types.Blob(data=b"PNGDATA", mime_type="image/png"))]))])
    assert client.image("make scene", [photo], "4:5") == b"PNGDATA"
    model, contents, config = client.calls[0]
    assert model == "image-model" and config.response_modalities == ["IMAGE"]
    assert config.image_config.aspect_ratio == "4:5"
    assert contents[0].inline_data.mime_type == "image/jpeg"


def test_image_without_picture_explains(client):
    client._next = types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(parts=[types.Part(text="거절")]))])
    with pytest.raises(GeminiError, match="이미지가 만들어지지 않았습니다"):
        client.image("x")


def test_unknown_model_message(client, monkeypatch):
    def not_found(**_):
        raise errors.ClientError(404, {"error": {"code": 404, "message": "models/x is not found", "status": "NOT_FOUND"}})

    monkeypatch.setattr(client._client.models, "generate_content", not_found)
    with pytest.raises(GeminiError, match="모델 'image-model'"):
        client.image("x")
