import asyncio
import base64
import json

from gateway.routes.asr import _relay_asr_events


class Client:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.sent = []

    async def receive(self):
        return await self.incoming.get()

    async def send_text(self, data):
        self.sent.append(json.loads(data))

    async def send_json(self, data):
        self.sent.append(data)


class Upstream:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.sent = []
        self.cancelled = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return await self.incoming.get()
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    async def send(self, data):
        self.sent.append(json.loads(data))


async def test_disconnect_cancels_idle_upstream_without_waiting_for_recognition():
    client, upstream = Client(), Upstream()
    await client.incoming.put({"type": "websocket.disconnect"})
    await asyncio.wait_for(_relay_asr_events(client, upstream, "test"), 0.5)
    assert upstream.cancelled


async def test_binary_pcm_and_final_transcript_are_delivered_before_finish():
    client, upstream = Client(), Upstream()
    await client.incoming.put({"type": "websocket.receive", "bytes": b"\x00\x01"})
    await client.incoming.put(
        {"type": "websocket.receive", "text": '{"type":"session.finish"}'}
    )
    task = asyncio.create_task(_relay_asr_events(client, upstream, "test"))
    await asyncio.sleep(0)
    await upstream.incoming.put(
        json.dumps(
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "transcript": "hello",
            }
        )
    )
    await upstream.incoming.put('{"type":"session.finished"}')
    await asyncio.wait_for(task, 0.5)
    assert base64.b64decode(upstream.sent[0]["audio"]) == b"\x00\x01"
    assert client.sent[-2]["transcript"] == "hello"
    assert client.sent[-1]["type"] == "session.finished"


async def test_upstream_finish_unblocks_client_receive_and_forwards_warmed_event():
    client, upstream = Client(), Upstream()
    await upstream.incoming.put('{"type":"session.finished"}')
    await asyncio.wait_for(
        _relay_asr_events(client, upstream, "test", '{"type":"session.created"}'), 0.5
    )
    assert [event["type"] for event in client.sent] == [
        "session.created",
        "session.finished",
    ]


async def test_dashscope_api_error_ends_setup_immediately():
    client, upstream = Client(), Upstream()
    await upstream.incoming.put(
        '{"code":"InvalidParameter","message":"Model not exist."}'
    )
    await asyncio.wait_for(_relay_asr_events(client, upstream, "test"), 0.5)
    assert client.sent == [
        {
            "type": "error",
            "error": {"code": "InvalidParameter", "message": "Model not exist."},
        }
    ]
