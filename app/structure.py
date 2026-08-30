import os
import json
import httpx

# Reutilizamos la misma GROQ_API_KEY que ya usas para transcribir audio.
# Groq también sirve modelos de texto (Llama 3.3) gratis, así evitamos
# depender de una API de pago solo para estructurar el JSON.
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

PROMPT_SISTEMA = """Eres un asistente que convierte notas de voz dictadas en \
campo por un ingeniero de confiabilidad en inspecciones de emisiones \
fugitivas (cámara OGI) en Campo Rubiales, en un JSON estructurado.

Devuelve SOLO un objeto JSON, sin texto adicional, sin backticks, con estas \
claves:
- "cluster": string o null (número o nombre de clúster si se menciona)
- "componente": string o null (válvula, brida, conexión, tanque, etc.)
- "tipo_hallazgo": "fuga" | "anomalia" | "observacion" | "otro"
- "severidad": "baja" | "media" | "alta" | null
- "descripcion": resumen limpio y profesional de lo dictado, en español
- "accion_sugerida": string o null si el dictado menciona una acción a tomar
"""


async def estructurar_nota(texto: str) -> dict:
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": "llama-3.3-70b-versatile",
        "max_tokens": 500,
        "temperature": 0,
        "response_format": {"type": "json_object"},  # fuerza salida JSON válida
        "messages": [
            {"role": "system", "content": PROMPT_SISTEMA},
            {"role": "user", "content": texto},
        ],
    }

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(GROQ_CHAT_URL, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()

    texto_respuesta = data["choices"][0]["message"]["content"]

    try:
        return json.loads(texto_respuesta)
    except json.JSONDecodeError:
        # Si el modelo no devolvió JSON válido, no perdemos la nota:
        # la guardamos cruda y la marcamos para revisión manual.
        return {"error_parseo": True, "texto_crudo": texto_respuesta}
