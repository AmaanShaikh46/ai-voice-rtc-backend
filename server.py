from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import base64, json, datetime, os, traceback, threading, difflib, time, random
from vosk import Model, KaldiRecognizer

# Optional import: only used if USE_SERVER_TTS=true
try:
    import pyttsx3
except Exception:
    pyttsx3 = None

# =========================================================
# ⚙️ FastAPI Initialization
# =========================================================
app = FastAPI(title="AI Voice RTC Backend - Stable Interactive Edition")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Toggle: server-side TTS (off on Render; on for local if you want)
USE_SERVER_TTS = os.getenv("USE_SERVER_TTS", "false").lower() == "true"

# =========================================================
# 🩺 Health Check
# =========================================================
@app.get("/health")
def health():
    return {
        "ok": True,
        "mode": "real-time",
        "engine": "vosk",
        "server_tts": USE_SERVER_TTS,
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
# 🔎 Helpers
# =========================================================
def match_phrase(phrase: str, possibilities, threshold=0.65):
    """Fuzzy-match a phrase to a list of options."""
    phrase = phrase.lower().strip()
    for p in possibilities:
        if difflib.SequenceMatcher(None, phrase, p.lower()).ratio() >= threshold:
            return p
    return None

def normalize_names(s: str) -> str:
    """Normalize common Vosk mis-hearings to target names."""
    lower = s.lower()

    phonetic_map = {
        # Amaan Shaikh
        "a man shake": "amaan shaikh",
        "a man sheikh": "amaan shaikh",
        "a man she": "amaan shaikh",
        "a man cheek": "amaan shaikh",
        "i'm on shake": "amaan shaikh",
        "i'm an shake": "amaan shaikh",
        "a man": "amaan shaikh",

        # Lubna
        "lumina": "lubna",
        "illumina": "lubna",
        "luminal": "lubna",
        "lubinal": "lubna",
        "lubina": "lubna",
        "lubena": "lubna",
        "lupna": "lubna",
        "lube now": "lubna",
        "no been up": "lubna",
        "been up": "lubna",
        "loop nah": "lubna",
        "luna": "lubna",
        "luminosity": "lubna",

        # Raza
        "razor": "raza",
        "rather": "raza",
        "riser": "raza",
        "rosa": "raza",
        "rasa": "raza",
        "riza": "raza",

         # Bored
        "Board": "bored",
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

    # --- Custom personality / names ---
    if "lubna" in lower:
        return "Yes, I know Lubna — she has a very bad sense of humor 😂"
    if "amaan" in lower or "amaan shaikh" in lower:
        return "Of course! Master Amaan is my creator — the brilliant mind behind me."
    if "raza" in lower:
        return "Yes, I know Raza — he’s stupid 😆"
    if any(k in lower for k in ["Night fury", "Nite fury", "Nite fewri", "Night fewri", "night fury", "light theory"]):
        return ("Yes, I know Night Fury... but Master Amaan told me not to say much about it............. "
                "Something about a secret mission😅")
    if "kartikay" in lower or "kohli" in lower:
        return "Yes i know kartikay, He is very smart"
    # --- Greetings ---
    if match_phrase(lower, ["good morning", "morning"]):
        return "Good morning! Hope your day starts with a smile 😊"
    if match_phrase(lower, ["good night", "night"]):
        return "Good night! Don’t forget to dream big 🌙"
    if match_phrase(lower, ["hello", "hi", "hey", "what's up", "yo"]):
        return "Hello there! How are you doing today?"

    # --- Conversation ---
    if "how are you" in lower:
        return "I'm doing great, thanks for asking! What about you?"
    if "what are you doing" in lower:
        return "Just hanging out in your phone, waiting to chat with you!"
    if "bored" in lower:
        return "Maybe you could play some music or ask me to tell you a joke?"

    # --- Time and Date ---
    if "time" in lower:
        return f"The time now is {datetime.datetime.now().strftime('%I:%M %p')}."
    if "date" in lower or "day" in lower:
        return f"Today is {datetime.datetime.now().strftime('%A, %B %d, %Y')}."

    # --- Mood ---
    if any(w in lower for w in ["i'm fine", "i am fine", "i'm good", "doing good"]):
        return "That’s awesome to hear! 😄"
    if any(w in lower for w in ["sad", "tired", "not good"]):
        return "I'm sorry to hear that. Want to talk about it?"

    # --- Fun ---
        # --- Fun ---
    jokes = [
        "Why did the computer go to therapy? Because it had too many bytes of emotional data 🤖💔",
        "Why do programmers prefer dark mode? Because light attracts bugs 🪲💻",
        "There are only 10 kinds of people in the world — those who understand binary and those who don’t 💻",
        "Why did the developer go broke? Because he used up all his cache 💸",
        "What do you call a programmer’s favorite hangout spot? The Foo Bar 🍻",
        "How many programmers does it take to change a light bulb? None, that’s a hardware problem 💡",
        "Why was the computer cold? It forgot to close its Windows 🥶",
        "A SQL query walks into a bar, walks up to two tables, and asks — ‘Can I join you?’ 😂"
    ]

    if "joke" in lower or "Another one" in lower or "make me laugh" in lower:
        chosen_joke = random.choice(jokes)
        reaction = random.choice([
            "Haha! That one never gets old 😄",
            "Classic programmer humor 😂",
            "Hope that made you smile 😇",
            "Good one, right? 😅"
        ])
        return f"{chosen_joke} {reaction}"


    
    if "funny" in lower or "laugh" in lower:
        return "Haha! I’ll try to be funnier next time 😂"
    if "cool" in lower or "fact" in lower:
        return "Did you know dolphins actually have names for each other?"

    # --- Identity ---
    if "your name" in lower or "who are you" in lower:
        return "I'm your AI assistant — offline, smart, and kind of funny sometimes!"
    if "who made you" in lower or "creator" in lower:
        return "I was made by Amaan Shaikh — a genius coder from Daund, Pune 🔥"

    # --- Politeness ---
    if "thank" in lower:
        return "You're very welcome! 😇"
    if "please" in lower:
        return "Of course! What do you need?"

    # --- Goodbye ---
    if match_phrase(lower, ["bye", "goodbye", "see you", "later"]):
        return "Goodbye! Talk to you soon 👋"

    # --- Default ---
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

    recognizer = KaldiRecognizer(vosk_model, 16000)
    last_text = ""
    last_reply_at = 0.0

    try:
        while True:
            data = await ws.receive_text()
            audio_chunk = base64.b64decode(data)

            # Feed Vosk
            if recognizer.AcceptWaveform(audio_chunk):
                result = json.loads(recognizer.Result())
                text = (result.get("text") or "").strip()

                if not text:
                    final_result = json.loads(recognizer.FinalResult())
                    text = (final_result.get("text") or "").strip()

                # Basic debouncing: ignore duplicate lines within ~2s
                if text and (text != last_text or (time.time() - last_reply_at) > 2.0):
                    print(f"🗣 Recognized phrase: {text}")
                    reply = get_offline_reply(text)
                    speak_offline(reply)
                    await ws.send_text(reply)
                    last_text = text
                    last_reply_at = time.time()
            else:
                partial = json.loads(recognizer.PartialResult()).get("partial", "")
                if partial:
                    print(f"⌛ Partial: {partial}")

    except WebSocketDisconnect:
        print("🔌 Android disconnected from stream")
    except Exception as e:
        print("❌ Stream error:", e)
        traceback.print_exc()
    finally:
        print("🛑 Audio stream ended")
