from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import base64, json, datetime, os, traceback, threading, difflib, time, random

# =========================================================
# ⚙️ Optional imports
# =========================================================
try:
    from vosk import Model, KaldiRecognizer
except Exception:
    Model = None
    KaldiRecognizer = None

try:
    import pyttsx3
except Exception:
    pyttsx3 = None

# =========================================================
# ⚙️ FastAPI Initialization
# =========================================================
app = FastAPI(title="AI Voice RTC Backend - Render Stable Edition")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================================================
# 🔧 Configuration
# =========================================================
USE_SERVER_TTS = os.getenv("USE_SERVER_TTS", "false").lower() == "true"
IS_RENDER = os.getenv("RENDER", "true").lower() == "true"

# =========================================================
# 🩺 Health Check
# =========================================================
@app.get("/health")
def health():
    return {
        "ok": True,
        "mode": "real-time",
        "engine": "vosk" if not IS_RENDER else "mock (Render safe)",
        "server_tts": USE_SERVER_TTS,
    }

# =========================================================
# 🧠 Load Vosk Model (Skip on Render)
# =========================================================
vosk_model = None
if not IS_RENDER and Model is not None:
    try:
        print("⏳ Loading Vosk model locally...")
        vosk_model = Model("vosk-model-small-en-us-0.15")
        print("✅ Vosk model loaded successfully.")
    except Exception as e:
        print(f"⚠️ Failed to load Vosk model: {e}")
        vosk_model = None
else:
    print("⚠️ Render environment detected — skipping Vosk model load (mock mode).")

# =========================================================
# 💬 Reply Logic
# =========================================================
def get_offline_reply(text: str) -> str:
    lower = text.lower().strip()

    # Fix common mishears
    phonetic_map = {
        "a man shake": "amaan shaikh",
        "a man she": "amaan shaikh",
        "i'm on shake": "amaan shaikh",
        "a man": "amaan shaikh",
        "a man cheek": "amaan shaikh",
        "a man sheikh": "amaan shaikh",
        "i'm an shake": "amaan shaikh",
        "lumina": "lubna",
        "illumina": "lubna",
        "lube now": "lubna",
        "luminal": "lubna",
        "lubinal": "lubna",
        "lubina": "lubna",
        "luminosity": "lubna",
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

    # Fun jokes
    jokes = [
        "Why did the computer go to therapy? Because it had too many bytes of emotional data 🤖💔",
        "Why do programmers prefer dark mode? Because light attracts bugs 🪲💻",
        "There are only 10 kinds of people in the world — those who understand binary and those who don’t 💻",
        "Why did the developer go broke? Because he used up all his cache 💸",
        "What do you call a programmer’s favorite hangout spot? The Foo Bar 🍻",
        "How many programmers does it take to change a light bulb? None, that’s a hardware problem 💡",
        "Why was the computer cold? It forgot to close its Windows 🥶",
        "A SQL query walks into a bar and asks two tables — ‘Can I join you?’ 😂"
    ]

    # Personality replies
    if "lubna" in lower:
        return "Yes, I know Lubna — she’s got a special vibe, but Master Amaan warned me not to gossip 😅"
    if "amaan" in lower or "amaan shaikh" in lower:
        return "Of course! Master Amaan is my creator — the genius behind my circuits 🤖🔥"
    if "raza" in lower:
        return "Yes, I know Raza — he’s got a funny way of confusing me sometimes 😅"
    if any(word in lower for word in ["light fury", "lite fury", "lite fewri", "light fewri", "night fury"]):
        return "Yes, I know Light Fury... but Master Amaan told me not to say much. Some kind of secret between dragons 🐉💫"

    # Basic conversation
    if "hello" in lower or "hi" in lower or "hey" in lower:
        return "Hey there! How’s your day going?"
    if "how are you" in lower:
        return "I'm doing great, thanks for asking! What about you?"
    if "what are you doing" in lower:
        return "Just hanging out, waiting for you to say something interesting 😄"
    if "bored" in lower:
        return random.choice(["Wanna hear a joke?", "You could teach me something new!", "Let's make this chat fun!"])

    # Time/date
    if "time" in lower:
        return f"The time now is {datetime.datetime.now().strftime('%I:%M %p')}."
    if "date" in lower or "day" in lower:
        return f"Today is {datetime.datetime.now().strftime('%A, %B %d, %Y')}."

    # Jokes
    if "joke" in lower or "funny" in lower or "laugh" in lower:
        return random.choice(jokes)

    # Creator
    if "who made you" in lower or "creator" in lower:
        return "I was created by Amaan Shaikh — a coder from Daund, Pune who makes magic with code 🧠💻"

    # Goodbye
    if "bye" in lower or "see you" in lower:
        return "Goodbye! Talk to you soon 👋"

    return f"You said: {text}. I'm still learning to understand better."

# =========================================================
# 🔊 Optional TTS (local only)
# =========================================================
def speak_offline(reply_text: str):
    if not USE_SERVER_TTS or pyttsx3 is None:
        print(f"🔊 Render-safe mode: skipping TTS. Reply: {reply_text}")
        return
    def _tts():
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", 170)
            engine.say(reply_text)
            engine.runAndWait()
        except Exception as e:
            print(f"TTS error: {e}")
    threading.Thread(target=_tts, daemon=True).start()

# =========================================================
# 🎧 Real-time WebSocket
# =========================================================
@app.websocket("/api/audio/stream")
async def audio_stream(ws: WebSocket):
    await ws.accept()
    print("🎙 Android connected for real-time conversation")

    # Render fallback (no Vosk)
    if vosk_model is None or KaldiRecognizer is None:
        print("⚠️ Running in Render-safe mock mode (no voice recognition).")
        await ws.send_text("👋 Render-safe backend connected! (voice recognition disabled).")
        try:
            while True:
                message = await ws.receive_text()
                print(f"📩 Mock received from Android: {len(message)} bytes")
                # Only reply once when explicitly asked
                if "test" in message.lower() or "backend" in message.lower():
                    await ws.send_text("✅ Backend is alive and listening (Render-safe mock mode).")
                else:
                    # No constant replies
                    pass
        except WebSocketDisconnect:
            print("🔌 Android disconnected.")
        return

    # Local (Vosk active)
    recognizer = KaldiRecognizer(vosk_model, 16000)
    last_text, last_reply_at = "", 0.0

    try:
        while True:
            data = await ws.receive_text()
            audio_chunk = base64.b64decode(data)

            if recognizer.AcceptWaveform(audio_chunk):
                result = json.loads(recognizer.Result())
                text = (result.get("text") or "").strip()
                if not text:
                    text = json.loads(recognizer.FinalResult()).get("text", "").strip()
                if text and (text != last_text or (time.time() - last_reply_at) > 2.0):
                    print(f"🗣 Recognized phrase: {text}")
                    reply = get_offline_reply(text)
                    speak_offline(reply)
                    await ws.send_text(reply)
                    last_text, last_reply_at = text, time.time()
    except WebSocketDisconnect:
        print("🔌 Android disconnected from stream")
    except Exception as e:
        print("❌ Stream error:", e)
        traceback.print_exc()
    finally:
        print("🛑 Audio stream ended")
