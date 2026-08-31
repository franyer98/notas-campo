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
        # El prompt no se transcribe, pero le da a Whisper contexto del
        # vocabulario esperado — mejora mucho el reconocimiento de jerga
        # técnica que de otra forma confunde con palabras comunes en español.
        "prompt": (
            "Inspección de emisiones fugitivas con cámara OGI en Campo "
            "Rubiales, CPF-1, CPF-2. Términos: clúster, válvula, brida, "
            "conexión, tanque, fuga, mechero, separador, bomba, línea de "
            "crudo, manifold, sello mecánico, PSI, ppm, RB10, RB."
        ),
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
