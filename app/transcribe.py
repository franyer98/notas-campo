import os
import httpx

# Groq ofrece Whisper large-v3 a una fracción del costo/latencia de OpenAI.
# Si prefieres OpenAI, cambia GROQ_API_URL y el header de auth por el de OpenAI.
GROQ_API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_API_KEY = os.environ["GROQ_API_KEY"]


async def transcribir_audio(audio_bytes: bytes, filename: str = "nota.ogg") -> str:
    """Envía el audio a Whisper (vía Groq) y devuelve el texto transcrito.

    Con reintentos simples porque en campo la subida puede caerse a mitad
    de transferencia incluso con señal débil (mismo criterio que
    retry-with-backoff en reporte-cuadrillas).
    """
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
    files = {"file": (filename, audio_bytes)}
    data = {
        "model": "whisper-large-v3",
        "language": "es",
        "response_format": "text",
    }

    ultimo_error = None
    for intento in range(3):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(GROQ_API_URL, headers=headers, files=files, data=data)
                resp.raise_for_status()
                return resp.text.strip()
        except Exception as e:
            ultimo_error = e
            continue

    raise RuntimeError(f"Fallo la transcripción tras 3 intentos: {ultimo_error}")
