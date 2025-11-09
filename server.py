from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import base64, wave, datetime

app = FastAPI(title="AI Voice RTC Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"ok": True, "service": "ai-voice-rtc", "stage": "call-init-enabled"}

# ✅ This must be in your code
class CallRequest(BaseModel):
    caller_id: str

@app.post("/api/calls/initiate")
def initiate_call(req: CallRequest):
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    session_id = f"session_{timestamp}"
    return {
        "ok": True,
        "session_id": session_id,
        "message": f"Call session started for {req.caller_id}"
    }

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
