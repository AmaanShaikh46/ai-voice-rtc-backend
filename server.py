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

# --- NEW AI Imports ---
from fastapi.responses import StreamingResponse
import pyttsx3
from vosk import Model, KaldiRecognizer
import json
import subprocess

# --- Load offline models once ---
try:
    vosk_model = Model(lang="en-us")
    print("✅ Vosk speech model loaded.")
except Exception as e:
    print(f"⚠️ Could not load Vosk model: {e}")

# --- Offline Text-to-Speech setup ---
engine = pyttsx3.init()
engine.setProperty("rate", 170)

@app.post("/api/ai/respond")
async def ai_respond(req: CallRequest):
    """
    Simulate AI reasoning and voice response fully offline
    """
    user_text = req.caller_id.lower()

    # super simple logic for now
    if "hello" in user_text:
        reply_text = "Hello! How can I help you today?"
    elif "how are you" in user_text:
        reply_text = "I'm just a bunch of Python code, but feeling awesome!"
    elif "time" in user_text:
        reply_text = f"The time is {datetime.datetime.now().strftime('%H:%M')}."
    else:
        reply_text = "Sorry, I'm still learning new things."

    # Convert to speech (save temporary .wav)
    filename = f"ai_reply_{datetime.datetime.now().strftime('%H%M%S')}.wav"
    engine.save_to_file(reply_text, filename)
    engine.runAndWait()

    # Return the WAV as stream
    def iterfile():
        with open(filename, mode="rb") as file_like:
            yield from file_like

    return StreamingResponse(iterfile(), media_type="audio/wav")

