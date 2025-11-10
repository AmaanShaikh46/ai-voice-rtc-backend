# tts_worker.py
import sys, os
import pyttsx3

def main():
    text = " ".join(sys.argv[1:]).strip() or "Hello."
    out_path = "reply.wav"

    tts = pyttsx3.init()
    tts.setProperty("rate", 170)
    tts.save_to_file(text, out_path)
    tts.runAndWait()

    # Play the file without blocking the main server
    # Windows: use 'start' to open the default player
    if os.name == "nt":
        os.system(f'start "" "{out_path}"')
    else:
        # Linux/mac fallback (adjust to your player if needed)
        os.system(f'xdg-open "{out_path}" >/dev/null 2>&1 || open "{out_path}"')

if __name__ == "__main__":
    main()
