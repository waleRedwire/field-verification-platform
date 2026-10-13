"""
Audio helpers: download from URL. Transcription optional via OpenAI API only.
Local Whisper removed for lighter Cloud deploys.
"""
from typing import Optional, Tuple, Dict, Any
import tempfile
from pathlib import Path
import requests


def download_audio_bytes(url: str, timeout: int = 60) -> Tuple[Optional[bytes], Optional[str], Optional[str]]:
    """
    Returns (data, suffix, error).
    Only http(s) URLs allowed.
    """
    if not url or not str(url).strip():
        return None, None, "Empty audio URL"
    url = str(url).strip()
    if not url.lower().startswith(("http://", "https://")):
        return None, None, "Only http/https audio links are allowed"

    try:
        r = requests.get(url, timeout=timeout, stream=True)
        r.raise_for_status()
        data = r.content
        # guess extension
        suffix = ".mp3"
        ct = (r.headers.get("Content-Type") or "").lower()
        if "wav" in ct:
            suffix = ".wav"
        elif "ogg" in ct:
            suffix = ".ogg"
        elif "m4a" in ct or "mp4" in ct:
            suffix = ".m4a"
        elif url.lower().endswith((".wav", ".mp3", ".ogg", ".m4a", ".webm")):
            suffix = "." + url.lower().rsplit(".", 1)[-1].split("?")[0]
        return data, suffix, None
    except Exception as e:
        return None, None, f"Could not download audio: {e}"


def transcribe_english(
    audio_url: str,
    model_size: str = "base",
    use_openai_api: bool = False,
    openai_api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Transcription only if OpenAI API is enabled and a key is provided.
    Local Whisper is disabled.
    """
    if not use_openai_api or not openai_api_key:
        return {
            "text": None,
            "error": "Transcription is off. Enable OpenAI API and set a key, or play audio only.",
        }

    data, suffix, err = download_audio_bytes(audio_url)
    if err:
        return {"text": None, "error": err}

    try:
        from openai import OpenAI
        client = OpenAI(api_key=openai_api_key)
        with tempfile.NamedTemporaryFile(suffix=suffix or ".mp3", delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        with open(tmp_path, "rb") as f:
            result = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language="en",
            )
        Path(tmp_path).unlink(missing_ok=True)
        return {"text": result.text, "error": None}
    except Exception as e:
        return {"text": None, "error": f"API transcription failed: {e}"}