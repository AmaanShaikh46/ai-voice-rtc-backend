from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import base64, wave, datetime, os
from openai import OpenAI

app = FastAPI(title="AI Voice RTC Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"ok": True, "service": "ai-voice-rtc", "stage": "whisper-enabled"}

# ✅ Simple model for call initiation (kept for Android compatibility)
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

# 🧠 OpenAI Whisper + GPT Integration
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@app.post("/api/ai/transcribe_and_reply")
async def transcribe_and_reply(audio_file: UploadFile = File(...)):
    """
    Takes a short audio clip, transcribes it with Whisper, 
    generates a reply using GPT-4o-mini, and returns both texts.
    """
    try:
        # 1️⃣ Transcribe using Whisper
        transcription = client.audio.transcriptions.create(
            model="gpt-4o-mini-transcribe",
            file=audio_file.file
        )
        text = transcription.text.strip()

        # 2️⃣ Generate a reply using GPT-4o-mini
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are KnightFewri, a friendly AI call assistant."},
                {"role": "user", "content": text}
            ]
        )

        ai_reply = completion.choices[0].message.content.strip()

        # 3️⃣ Send both results back
        return JSONResponse({
            "transcribed_text": text,
            "ai_reply": ai_reply
        })

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
