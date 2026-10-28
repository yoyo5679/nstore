"""ClaudeClient 가 실제 SDK로 올바른 요청을 만들고 응답을 읽는지 (네트워크 대신 가짜 서버 응답)."""

import json

import anthropic
import httpx2
import pytest
from fakes import png_bytes

from nstore.detail.claude import FALLBACK_BETA, ClaudeClient, ClaudeError, image_blocks
from nstore.detail.schema import ReviewInsights


def sse(text: str, stop_reason: str = "end_turn") -> bytes:
    events = [
        ("message_start", {"type": "message_start", "message": {
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "content": [],
            "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 0}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                           "usage": {"output_tokens": 20}}),
        ("message_stop", {"type": "message_stop"}),
    ]
    return "".join(f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n" for name, data in events).encode()


def make_client(body: bytes, seen: list):
    def handler(request):
        seen.append(request)
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    sdk = anthropic.Anthropic(api_key="test", http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)))
    return ClaudeClient("claude-opus-5-5", "high", client=sdk)


ANSWER = '{"selling_points": ["가벼워요"], "complaints": [], "questions": ["접은 크기?"]}'


def test_request_shape_and_parsed_output(tmp_path):
    photo = tmp_path / "front.jpg"
    photo.write_bytes(png_bytes(size=(4000, 3000)))
    pdf = tmp_path / "catalog.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    seen = []
    result = make_client(sse(ANSWER), seen).json("정리해줘", ReviewInsights, files=[pdf, photo], system="원칙")

    assert result == ReviewInsights(selling_points=["가벼워요"], complaints=[], questions=["접은 크기?"])
    req = seen[0]
    body = json.loads(req.content)
    assert FALLBACK_BETA in req.headers["anthropic-beta"]
    assert body["model"] == "claude-opus-5-5" and body["fallbacks"] == "default" and body["stream"] is True
    assert body["output_config"]["effort"] == "high"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["system"] == "원칙"
    content = body["messages"][0]["content"]
    assert content[0]["type"] == "document" and content[0]["title"] == "catalog.pdf"
    assert content[1] == {"type": "text", "text": "[사진: front.jpg]"}
    assert content[2]["type"] == "image" and content[2]["source"]["media_type"] == "image/jpeg"
    assert content[-1] == {"type": "text", "text": "정리해줘"}
    assert "thinking" not in body and "temperature" not in body


def test_refusal_raises(tmp_path):
    with pytest.raises(ClaudeError, match="거절"):
        make_client(sse("", "refusal"), []).json("x", ReviewInsights)


def test_truncated_raises():
    with pytest.raises(ClaudeError, match="잘렸습니다"):
        make_client(sse('{"selling', "max_tokens"), []).json("x", ReviewInsights)


def test_auth_error_message():
    def handler(request):
        return httpx2.Response(401, json={"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}})

    sdk = anthropic.Anthropic(api_key="bad", max_retries=0,
                              http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)))
    with pytest.raises(ClaudeError, match="ANTHROPIC_API_KEY"):
        ClaudeClient("claude-opus-5-5", "high", client=sdk).json("x", ReviewInsights)


def test_long_capture_is_sliced(tmp_path):
    page = tmp_path / "reference.png"
    page.write_bytes(png_bytes(size=(860, 9000)))
    assert len(image_blocks(page)) == 5          # 위에서부터 최대 5조각
    photo = tmp_path / "front.jpg"
    photo.write_bytes(png_bytes(size=(1200, 1600)))
    assert len(image_blocks(photo)) == 1


def test_text_material_becomes_text_block(tmp_path):
    txt = tmp_path / "link-01.txt"
    txt.write_text("출처: https://example.com\n무게 6.8kg", encoding="utf-8")
    client = ClaudeClient("claude-opus-5-5", "high", client=object())
    assert client._blocks(txt) == [{"type": "text", "text": "[자료: link-01.txt]\n출처: https://example.com\n무게 6.8kg"}]
