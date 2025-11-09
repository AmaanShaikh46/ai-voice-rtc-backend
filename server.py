from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import base64, wave, datetime, os

app = FastAPI(title="AI Voice RTC Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"ok": True, "service": "ai-voice-rtc", "stage": "stream-enabled"}

@app.websocket("/api/audio/stream")
async def audio_stream(ws: WebSocket):
    await ws.accept()
    print("🎧 Android connected to /api/audio/stream")

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"call_recording_{timestamp}.wav"
    wf = wave.open(filename, "wb")
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(16000)

    try:
        while True:
            data = await ws.receive_text()
            audio_bytes = base64.b64decode(data)
            wf.writeframes(audio_bytes)
    except WebSocketDisconnect:
        print("🔌 WebSocket disconnected")
    finally:
        wf.close()
        print(f"💾 Audio saved as {filename}")
