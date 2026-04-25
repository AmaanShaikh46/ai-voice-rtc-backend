# =========================================================
#  Imports
# =========================================================
import os
import base64, json, traceback, time, random
import threading
import difflib
from datetime import datetime, timedelta, timezone
import asyncio


from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Body
from fastapi.middleware.cors import CORSMiddleware

from dotenv import load_dotenv
from supabase import create_client, Client
from vosk import Model, KaldiRecognizer
import requests


try:
    import pyttsx3
except Exception:
    pyttsx3 = None

# =========================================================
#  Load ENV FIRST (CRITICAL)
# =========================================================
load_dotenv()

# =========================================================
#  Supabase setup
# =========================================================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")                  # anon key
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

print("SUPABASE_URL =", SUPABASE_URL)
print("SUPABASE_KEY =", (SUPABASE_KEY or "")[:10] + "...")
print("SUPABASE_SERVICE_ROLE_KEY =", (SUPABASE_SERVICE_ROLE_KEY or "")[:10] + "...")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("❌ Supabase ENV variables missing")

# Auth client (login)
SUPABASE_AUTH: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Server client (read/write)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

print("🔑 SUPABASE CLIENT READY")

# =========================================================
# 🔌 Supabase REST helpers (used by insert/update)
# =========================================================
SUPABASE_REST = f"{SUPABASE_URL}/rest/v1"

SUPABASE_HEADERS = {
    "apikey": SUPABASE_SERVICE_ROLE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Prefer": "return=representation"
}
# =========================================================
# Missed call background worker
# =========================================================
def mark_call_missed_if_needed(call):
    """
    Marks a call as MISSED if it's still pending after 30 seconds
    """
    created_at = datetime.fromisoformat(call["created_at"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)

    if call["status"] == "pending" and (now - created_at).seconds >= 30:
        supabase.table("calls") \
            .update({"status": "missed"}) \
            .eq("id", call["id"]) \
            .execute()

        supabase_insert("call_logs", {
            "call_id": call["id"],
            "caller_id": call["caller_id"],
            "caller_username": call["caller_username"],
            "receiver_id": call["receiver_id"],
            "receiver_username": call["receiver_username"],
            "message": call.get("message_to_deliver"),
            "status": "missed"
        })

def missed_call_worker():
    while True:
        try:
            # 🔥 KEEP SUPABASE ACTIVE (THIS IS THE FIX)
            supabase.table("calls").select("id").limit(1).execute()

            # 👇 your existing logic (KEEP IT)
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=30)

            rows = supabase.table("calls") \
                .select("*") \
                .eq("status", "pending") \
                .lt("created_at", cutoff.isoformat()) \
                .execute()

            for call in rows.data or []:
                supabase.table("calls") \
                    .update({"status": "missed"}) \
                    .eq("id", call["id"]) \
                    .execute()

                supabase_insert("call_logs", {
                    "call_id": call["id"],
                    "caller_id": call["caller_id"],
                    "caller_username": call["caller_username"],
                    "receiver_id": call["receiver_id"],
                    "receiver_username": call["receiver_username"],
                    "message": call.get("message_to_deliver"),
                    "status": "missed"
                })

                print(f"📵 Call marked MISSED: {call['id']}")

            print("💓 Supabase keep-alive ping")

        except Exception as e:
            print("❌ Missed call worker error:", e)

        time.sleep(20)  

# =========================================================
#  FastAPI Initialization
# =========================================================
app = FastAPI(title="AI Voice RTC Backend - Stable Interactive Edition")
threading.Thread(target=missed_call_worker, daemon=True).start()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

USE_SERVER_TTS = os.getenv("USE_SERVER_TTS", "false").lower() == "true"


# =========================================================
# Health Check
# =========================================================
@app.get("/health")
def health():
    try:
        supabase.table("calls").select("id").limit(1).execute()

        return {
            "ok": True,
            "db": "connected",
            "mode": "real-time",
            "engine": "vosk" if SUPABASE_URL else "unknown",
            "server_tts": USE_SERVER_TTS,
        }

    except Exception as e:
        return {
            "ok": False,
            "db": "disconnected",
            "error": str(e),
        }

# =========================================================
# Contacts using Supabase
# =========================================================
@app.get("/api/contacts")
def get_contacts(current_user_id: str = None):
    """
    Returns all profiles (id, username).
    If current_user_id is given, that id is excluded.
    """
    try:
        response = supabase.table("profiles").select("id, username").execute()
        users = response.data or []

        if current_user_id:
            users = [u for u in users if u.get("id") != current_user_id]

        return {"ok": True, "contacts": users}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# =========================================================
# Supabase REST helpers
# =========================================================
def supabase_insert(table: str, payload: dict):
    url = f"{SUPABASE_REST}/{table}"
    resp = requests.post(url, headers=SUPABASE_HEADERS, json=payload)
    resp.raise_for_status()
    return resp.json()


def supabase_update(table: str, pk: str, pk_value, payload: dict):
    url = f"{SUPABASE_REST}/{table}?{pk}=eq.{pk_value}"
    resp = requests.patch(url, headers=SUPABASE_HEADERS, json=payload)
    resp.raise_for_status()
    return resp.json()


def supabase_select(table: str, filters: str):
    if filters:
        url = f"{SUPABASE_REST}/{table}?{filters}"
    else:
        url = f"{SUPABASE_REST}/{table}"
    resp = requests.get(url, headers=SUPABASE_HEADERS)
    resp.raise_for_status()
    return resp.json()

# =========================================================
# Load Vosk Model
# =========================================================
try:
    print(" Loading Vosk model...")
    vosk_model = Model(model_name="vosk-model-small-en-us-0.15")
    print("✅ Vosk model loaded successfully.")
except Exception as e:
    print(f"⚠ Failed to load Vosk model: {e}")
    vosk_model = None

# =========================================================
# Helpers
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
        "board": "bored",
    }

    for wrong, right in phonetic_map.items():
        if wrong in lower:
            lower = lower.replace(wrong, right)
    return lower

# =========================================================
# Reply Logic
# =========================================================
def get_offline_reply(text: str) -> str:
    lower = normalize_names(text.lower().strip())

    # --- Custom personality / names ---
    if "lubna" in lower:
        return "Yes, I know Lubna — she has a very bad sense of humor and she is stupid, hahahaha"
    if "amaan" in lower or "amaan shaikh" in lower:
        return "Of course! Master Amaan is my creator — the brilliant mind behind me."
    if "raza" in lower:
        return "Yes, I know Raza — he’s stupid, hahahaha"
    if any(k in lower for k in ["night fury", "nite fury", "nite fewri", "night fewri", "light theory"]):
        return ("Yes, I know Night Fury... but Master Amaan told me not to say much about it............. "
                "Something about a secret mission")
    if "kartikay" in lower or "kohli" in lower:
        return "Yes i know kartikay, He is very smart"

    # --- Greetings ---
    if match_phrase(lower, ["good morning", "morning"]):
        return "Good morning! Hope your day starts with a smile"
    if match_phrase(lower, ["good night", "night"]):
        return "Good night! Don’t forget to dream big "
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
        return f"The time now is {datetime.now().strftime('%I:%M %p')}."
    if "date" in lower or "day" in lower:
        return f"Today is {datetime.now().strftime('%A, %B %d, %Y')}."

    # --- Mood ---
    if any(w in lower for w in ["i'm fine", "i am fine", "i'm good", "doing good"]):
        return "That’s awesome to hear! "
    if any(w in lower for w in ["sad", "tired", "not good"]):
        return "I'm sorry to hear that. Want to talk about it?"

    # --- Fun / Jokes ---
    jokes = [
        "Why did the computer go to therapy? Because it had too many bytes of emotional data ",
        "Why do programmers prefer dark mode? Because light attracts bugs ",
        "There are only 10 kinds of people in the world — those who understand binary and those who don’t ",
        "Why did the developer go broke? Because he used up all his cache ",
        "What do you call a programmer’s favorite hangout spot? The Foo Bar ",
        "How many programmers does it take to change a light bulb? None, that’s a hardware problem ",
        "Why was the computer cold? It forgot to close its Windows ",
        "A SQL query walks into a bar, walks up to two tables, and asks — ‘Can I join you?’, hahahaha"
    ]

    if "joke" in lower or "another one" in lower or "make me laugh" in lower:
        chosen_joke = random.choice(jokes)
        reaction = random.choice([
            "Haha! That one never gets old ",
            "Classic programmer humor ",
            "Hope that made you smile ",
            "Good one, right? "
        ])
        return f"{chosen_joke} {reaction}"

    if "funny" in lower or "laugh" in lower:
        return "Haha! I’ll try to be funnier next time "
    if "cool" in lower or "fact" in lower:
        return "Did you know dolphins actually have names for each other?"

    # --- Identity ---
    if "your name" in lower or "who are you" in lower:
        return "I'm your AI assistant — offline, smart, and kind of funny sometimes!"
    if "who made you" in lower or "creator" in lower:
        return "I was made by Amaan Shaikh — a genius coder from Daund, Pune 🔥"

    # --- Politeness ---
    if "thank" in lower:
        return "You're very welcome! "
    if "please" in lower:
        return "Of course! What do you need?"

    # --- Goodbye ---
    if match_phrase(lower, ["bye", "goodbye", "see you", "later"]):
        return "Goodbye! Talk to you soon "

    # --- Default ---
    return f"You said: {text}. I'm still learning to understand more topics."

# =========================================================
# Server-side TTS (optional; off on Render)
# =========================================================
def speak_offline(reply_text: str):
    if not USE_SERVER_TTS:
        print(f"🔊 (Render mode) Skipping server TTS. Reply: {reply_text}")
        return

    if pyttsx3 is None:
        print("⚠ pyttsx3 not available; skipping server TTS.")
        return

    def _tts():
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", 170)
            engine.say(reply_text)
            engine.runAndWait()
            print(f"🔊 AI spoke (server): {reply_text}")
        except Exception as e:
            print(f"⚠ TTS error: {e}")

    threading.Thread(target=_tts, daemon=True).start()

# =========================================================
# Authentication Endpoint
# =========================================================
@app.post("/auth/login")
async def login_user(request: Request):
    data = await request.json()
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return {"ok": False, "error": "Email and password required"}

    try:
        res = SUPABASE_AUTH.auth.sign_in_with_password(
            {"email": email, "password": password}
        )
        if res and res.user:
            return {
                "ok": True,
                "user_id": res.user.id,
                "email": res.user.email,
                "session": res.session.access_token  # Optional for future security
            }
        else:
            return {"ok": False, "error": "Invalid credentials"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def get_profile(user_id: str):
    try:
        rows = supabase_select("profiles", f"id=eq.{user_id}")
        if rows:
            return {"ok": True, "profile": rows[0]}
        else:
            return {"ok": False, "error": "Profile not found"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# =========================================================
# 1) Initiate a Call
# =========================================================
@app.post("/api/calls/initiate")
async def initiate_call(request: Request):
    """
    Expected JSON body:
    {
      "caller_id": "UUID",
      "caller_username": "string",
      "receiver_id": "UUID",
      "receiver_username": "string",
      "message": "string",
      "message_to_deliver": "string"   # optional, text the AI will say
    }
    """
    body = await request.json()

    required = [
        "caller_id", "caller_username",
        "receiver_id", "receiver_username",
        "message"
    ]
    for field in required:
        if field not in body:
            return {"ok": False, "error": f"Missing field: {field}"}

    row = {
        "caller_id": body["caller_id"],
        "caller_username": body["caller_username"],
        "receiver_id": body["receiver_id"],
        "receiver_username": body["receiver_username"],
        "message": body["message"],  
        "message_to_deliver": body.get("message_to_deliver", ""),  
        "status": "pending"
    }

    try:
        print("📞 INSERTING CALL ROW:", row)
        created = supabase_insert("calls", row)
        print("✅ SUPABASE INSERT RESPONSE:", created)
        return {"ok": True, "call": created}

    except Exception as e:
        return {"ok": False, "error": str(e)}

# =========================================================
# 2) Check Pending Calls
# =========================================================
@app.get("/api/calls/pending")
def get_pending_calls(receiver_id: str):
    try:
        rows = supabase_select(
            "calls",
            f"receiver_id=eq.{receiver_id}&status=eq.pending&order=created_at.asc&limit=1"
        )

        calls = []
        for row in rows:
            calls.append({
                "id": row["id"],
                "caller_username": row["caller_username"],
                "message": row["message"],
                "message_to_deliver": row.get("message_to_deliver")
            })

        return {"ok": True, "calls": calls}

    except Exception as e:
        return {"ok": False, "error": str(e)}
# =========================================================
# 3) Update call status + log
# =========================================================
from fastapi import Body


@app.post("/api/calls/update_status")
async def update_call_status(request: Request):
    payload = await request.json()

    call_id = payload.get("call_id")
    status = payload.get("status")

    if not call_id or not status:
        return {"ok": False}

    # 1️⃣ Fetch call
    call_resp = (
        supabase.table("calls")
        .select("*")
        .eq("id", call_id)
        .limit(1)
        .execute()
    )

    if not call_resp.data:
        return {"ok": True}

    call = call_resp.data[0]

    supabase.table("calls") \
        .update({"status": status}) \
        .eq("id", call_id) \
        .execute()

    supabase_insert("call_logs", {
    "call_id": call["id"],
    "caller_id": call["caller_id"],
    "caller_username": call["caller_username"],
    "receiver_id": call["receiver_id"],
    "receiver_username": call["receiver_username"],
    "message": call.get("message_to_deliver"),
    "status": status
})

    return {"ok": True}

def mark_missed_calls():
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=30)

    # fetch old pending calls
    rows = supabase.table("calls") \
        .select("*") \
        .eq("status", "pending") \
        .lt("created_at", cutoff.isoformat()) \
        .execute()

    for call in rows.data or []:
        # mark missed
        supabase.table("calls") \
            .update({"status": "missed"}) \
            .eq("id", call["id"]) \
            .execute()

        # log missed call
        supabase_insert("call_logs", {
            "call_id": call["id"],
            "caller_id": call["caller_id"],
            "caller_username": call["caller_username"],
            "receiver_id": call["receiver_id"],
            "receiver_username": call["receiver_username"],
            "message": call.get("message_to_deliver"),
            "status": "missed"
        })

# =========================================================
# 4) Profiles endpoint (optional, for debugging)
# =========================================================
@app.get("/api/profiles")
def get_profiles(exclude_id: str = None):
    """
    Optional ?exclude_id=<uuid> to skip yourself.
    """
    try:
        filters = None
        if exclude_id:
            filters = f"id=neq.{exclude_id}"
        rows = supabase_select("profiles", filters) if filters else supabase_select("profiles", "")
        return {"ok": True, "profiles": rows}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# =========================================================
# Real-time Audio Stream
# =========================================================
@app.websocket("/api/audio/stream")
async def audio_stream(ws: WebSocket):
    await ws.accept()
    print("🎙 Android connected for real-time conversation")

    call_id = ws.query_params.get("call_id")
    print(f"🎯 WebSocket started for call_id={call_id}")

    call_resp = supabase.table("calls") \
        .select("message_to_deliver") \
        .eq("id", call_id) \
        .limit(1) \
        .execute()

    if call_resp.data:
        original_message = call_resp.data[0].get("message_to_deliver", "Sorry, I couldn't find the original message.")
    else:
        original_message = "Sorry, I couldn't find the original message."

    if vosk_model is None:
        await ws.send_text("Speech recognition model not loaded on server.")
        await ws.close()
        return

    recognizer = KaldiRecognizer(vosk_model, 16000)

    last_text = ""
    last_reply = ""

    try:
        while True:
            # Receive base64 PCM audio
            data = await ws.receive_text()
            if not data:
                continue

            audio_chunk = base64.b64decode(data)

            # FULL speech recognized
            if recognizer.AcceptWaveform(audio_chunk):
                result = json.loads(recognizer.Result())
                text = (result.get("text") or "").strip()

                if not text:
                    final = json.loads(recognizer.FinalResult())
                    text = (final.get("text") or "").strip()

                if not text:
                    continue

                print(f"🗣 Recognized phrase: {text}")
                lower = text.lower()

                # Repeat
                if "repeat" in lower:
                    reply = original_message
                    speak_offline(reply)
                    await ws.send_text(reply)

                # End call
                elif any(w in lower for w in ["stop", "bye", "goodbye", "end call"]):
                    reply = "Okay, ending the call now."
                    
                    
                    await ws.send_text(json.dumps({
                        "type": "end_call",
                        "message": reply
                    }))   
                    print("📤 Sent end_call signal")      
                    await ws.close()
                    break

                # Normal AI reply
                else:
                    reply = get_offline_reply(text)

                    speak_offline(reply)
                    await ws.send_text(reply)

                    last_text = text
                    last_reply = reply

            # PARTIAL speech (ignore logically)
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

# =========================================================
# Call History (User-specific)
# =========================================================
@app.get("/api/calls/logs")
def get_call_logs(user_id: str):
    try:
        # 1️⃣ Get latest log per call
        rows = supabase_select(
            "call_logs",
            f"or=(caller_id.eq.{user_id},receiver_id.eq.{user_id})&order=created_at.desc"
        )

        seen = set()
        logs = []

        for row in rows:
            call_id = row["call_id"]
            if call_id in seen:
                continue
            seen.add(call_id)

            # 2️⃣ Fetch call (source of truth)
            call_resp = (
                supabase.table("calls")
                .select("caller_id,caller_username,receiver_id,receiver_username")
                .eq("id", call_id)
                .single()
                .execute()
            )

            call = call_resp.data
            if not call:
                continue

            direction = "out" if call["caller_id"] == user_id else "in"
            other_user = (
                call["receiver_username"]
                if direction == "out"
                else call["caller_username"]
            )

            logs.append({
                "callId": call_id,
                "otherUser": other_user,
                "direction": direction,
                "message": row.get("message", ""),
                "status": row["status"],
                "time": row["created_at"]
            })

        return {"ok": True, "logs": logs}

    except Exception as e:
        return {"ok": False, "error": str(e)}


