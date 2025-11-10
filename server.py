from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from openai import OpenAI
import base64, wave, datetime, os, json, traceback, threading, difflib, time
from vosk import Model, KaldiRecognizer

# =========================================================
# ⚙️ FastAPI Initialization
# =========================================================
app = FastAPI(title="AI Voice RTC Backend - Stable Whisper + Vosk Edition")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Optional import: only used if USE_SERVER_TTS=true
try:
    import pyttsx3
except Exception:
    pyttsx3 = None

# =========================================================
# 🔧 Configurations
# =========================================================
USE_SERVER_TTS = os.getenv("USE_SERVER_TTS", "false").lower() == "true"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

# =========================================================
# 🩺 Health Check
# =========================================================
@app.get("/health")
def health():
    return {"ok": True, "service": "ai-voice-rtc", "stage": "whisper-enabled"}

# =========================================================
# 📞 Call Initiation API (for Android compatibility)
# =========================================================
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

# =========================================================
# 🧠 Load Vosk Model
# =========================================================
try:
    print("⏳ Loading Vosk model...")
    vosk_model = Model(model_name="vosk-model-small-en-us-0.15")
    print("✅ Vosk model loaded successfully.")
except Exception as e:
    print(f"⚠️ Failed to load Vosk model: {e}")
    vosk_model = None

# =========================================================
# 🔎 Helper Functions
# =========================================================
def match_phrase(phrase: str, possibilities, threshold=0.65):
    phrase = phrase.lower().strip()
    for p in possibilities:
        if difflib.SequenceMatcher(None, phrase, p.lower()).ratio() >= threshold:
            return p
    return None

def normalize_names(s: str) -> str:
    lower = s.lower()
    phonetic_map = {
        "a man shake": "amaan shaikh",
        "a man sheikh": "amaan shaikh",
        "a man she": "amaan shaikh",
        "a man cheek": "amaan shaikh",
        "i'm on shake": "amaan shaikh",
        "i'm an shake": "amaan shaikh",
        "a man": "amaan shaikh",
        "lumina": "lubna",
        "illumina": "lubna",
        "luminal": "lubna",
        "lubinal": "lubna",
        "lubina": "lubna",
        "lubena": "lubna",
        "lupna": "lubna",
        "lube now": "lubna",
        "loop nah": "lubna",
        "luna": "lubna",
        "razor": "raza",
        "rather": "raza",
        "riser": "raza",
        "rosa": "raza",
        "rasa": "raza",
        "riza": "raza",
    }
    for wrong, right in phonetic_map.items():
        if wrong in lower:
            lower = lower.replace(wrong, right)
    return lower

# =========================================================
# 💬 Reply Logic
# =========================================================
def get_offline_reply(text: str) -> str:
    lower = normalize_names(text.lower().strip())

    if "lubna" in lower:
        return "Yes, I know Lubna — she has a very bad sense of humor 😂"
    if "amaan" in lower or "amaan shaikh" in lower:
        return "Of course! Master Amaan is my creator — the brilliant mind behind me."
    if "raza" in lower:
        return "Yes, I know Raza — he’s stupid 😆"
    if any(k in lower for k in ["light fury", "lite fury", "lite fewri", "light fewri", "night fury"]):
        return "Yes, I know Light Fury... but Master Amaan told me not to say much about her. Something about a secret mission or feelings involved 😅"

    if match_phrase(lower, ["good morning", "morning"]):
        return "Good morning! Hope your day starts with a smile 😊"
    if match_phrase(lower, ["good night", "night"]):
        return "Good night! Don’t forget to dream big 🌙"
    if match_phrase(lower, ["hello", "hi", "hey", "what's up", "yo"]):
        return "Hello there! How are you doing today?"

    if "how are you" in lower:
        return "I'm doing great, thanks for asking! What about you?"
    if "what are you doing" in lower:
        return "Just hanging out in your phone, waiting to chat with you!"
    if "bored" in lower:
        return "Maybe you could play some music or ask me to tell you a joke?"

    if "time" in lower:
        return f"The time now is {datetime.datetime.now().strftime('%I:%M %p')}."
    if "date" in lower or "day" in lower:
        return f"Today is {datetime.datetime.now().strftime('%A, %B %d, %Y')}."

    if "joke" in lower:
        return "Why did the computer go to therapy? Because it had too many bytes of emotional data 🤖💔"
    if "funny" in lower or "laugh" in lower:
        return "Haha! I’ll try to be funnier next time 😂"
    if "cool" in lower or "fact" in lower:
        return "Did you know dolphins actually have names for each other?"

    if "your name" in lower or "who are you" in lower:
        return "I'm your AI assistant — offline, smart, and kind of funny sometimes!"
    if "who made you" in lower or "creator" in lower:
        return "I was made by Amaan Shaikh — a genius coder from Daund, Pune 🔥"

    if "thank" in lower:
        return "You're very welcome! 😇"
    if "please" in lower:
        return "Of course! What do you need?"
    if match_phrase(lower, ["bye", "goodbye", "see you", "later"]):
        return "Goodbye! Talk to you soon 👋"

    return f"You said: {text}. I'm still learning to understand more topics."

# =========================================================
# 🔊 Server-side TTS (optional; off on Render)
# =========================================================
def speak_offline(reply_text: str):
    if not USE_SERVER_TTS:
        print(f"🔊 (Render mode) Skipping server TTS. Reply: {reply_text}")
        return
    if pyttsx3 is None:
        print("⚠️ pyttsx3 not available; skipping server TTS.")
        return
    def _tts():
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", 170)
            engine.say(reply_text)
            engine.runAndWait()
            print(f"🔊 AI spoke (server): {reply_text}")
        except Exception as e:
            print(f"⚠️ TTS error: {e}")
    threading.Thread(target=_tts, daemon=True).start()

# =========================================================
# 🎧 Real-time Audio Stream
# =========================================================
@app.websocket("/api/audio/stream")
async def audio_stream(ws: WebSocket):
    await ws.accept()
    print("🎙 Android connected for real-time conversation")

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"call_recording_{timestamp}.wav"
    wf = wave.open(filename, "wb")
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(16000)

    recognizer = KaldiRecognizer(vosk_model, 16000)
    last_text = ""
    last_reply_at = 0.0

    try:
        while True:
            data = await ws.receive_text()
            audio_bytes = base64.b64decode(data)
            wf.writeframes(audio_bytes)

            if recognizer.AcceptWaveform(audio_bytes):
                result = json.loads(recognizer.Result())
                text = (result.get("text") or "").strip()

                if not text:
                    final_result = json.loads(recognizer.FinalResult())
                    text = (final_result.get("text") or "").strip()

                if text and (text != last_text or (time.time() - last_reply_at) > 2.0):
                    print(f"🗣 Recognized phrase: {text}")
                    reply = get_offline_reply(text)
                    speak_offline(reply)
                    await ws.send_text(reply)
                    last_text = text
                    last_reply_at = time.time()

    except WebSocketDisconnect:
        print("🔌 Android disconnected from stream")
    except Exception as e:
        print("❌ Stream error:", e)
        traceback.print_exc()
    finally:
        wf.close()
        print(f"💾 Audio saved as {filename}")
        print("🛑 Audio stream ended")

# =========================================================
# 🧠 Whisper + GPT Integration
# =========================================================
@app.post("/api/ai/transcribe_and_reply")
async def transcribe_and_reply(audio_file: UploadFile = File(...)):
    try:
        transcription = client.audio.transcriptions.create(
            model="gpt-4o-mini-transcribe",
            file=audio_file.file
        )
        text = transcription.text.strip()

        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are KnightFewri, a friendly AI call assistant."},
                {"role": "user", "content": text}
            ]
        )

        ai_reply = completion.choices[0].message.content.strip()

        return JSONResponse({
            "transcribed_text": text,
            "ai_reply": ai_reply
        })

    except Exception as e:
        print("❌ Whisper+GPT Error:", e)
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)
