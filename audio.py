"""
Download audio from URL, then play / transcribe as English.
Hausa / Yoruba / Igbo field audio is treated as translated English.
"""
from typing import Optional, Dict, Any, Tuple
import os
import tempfile
import requests

_whisper_model = None


def _get_whisper(model_size: str = "base"):
    global _whisper_model
    if _whisper_model is None:
        import whisper
        _whisper_model = whisper.load_model(model_size)
    return _whisper_model


def download_audio_bytes(url: str, timeout: int = 90) -> Tuple[Optional[bytes], Optional[str], Optional[str]]:
    """
    Download audio from URL.
    Returns (bytes, suggested_suffix, error_message).
    """
    if not url or str(url).strip() in ("", "nan", "None"):
        return None, None, "Empty audio URL"

    url = str(url).strip()
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; FieldVerificationPlatform/1.0)"
        }
        r = requests.get(url, stream=True, timeout=timeout, headers=headers, allow_redirects=True)
        r.raise_for_status()

        content_type = (r.headers.get("Content-Type") or "").lower()
        suffix = ".mp3"
        lower = url.lower()
        if ".wav" in lower or "wav" in content_type:
            suffix = ".wav"
        elif ".m4a" in lower or "mp4" in content_type or "m4a" in content_type:
            suffix = ".m4a"
        elif ".ogg" in lower or "ogg" in content_type:
            suffix = ".ogg"
        elif ".webm" in lower or "webm" in content_type:
            suffix = ".webm"
        elif "mpeg" in content_type or "mp3" in content_type:
            suffix = ".mp3"

        data = r.content
        if not data or len(data) < 100:
            return None, None, "Downloaded file is empty or too small (link may require login)."

        return data, suffix, None
    except Exception as e:
        return None, None, f"Download failed: {e}"


def download_audio_to_temp(url: str, timeout: int = 90) -> Tuple[Optional[str], Optional[str]]:
    """
    Download to a temp file.
    Returns (path, error).
    """
    data, suffix, err = download_audio_bytes(url, timeout=timeout)
    if err or data is None:
        return None, err or "Download failed"

    try:
        fd, path = tempfile.mkstemp(suffix=suffix or ".mp3")
        os.close(fd)
        with open(path, "wb") as f:
            f.write(data)
        return path, None
    except Exception as e:
        return None, str(e)


def transcribe_english(
    audio_path_or_url: str,
    model_size: str = "base",
    use_openai_api: bool = False,
    openai_api_key: Optional[str] = None
) -> Dict[str, Any]:
    result = {"text": None, "error": None, "source": None}
    path = audio_path_or_url
    cleanup = False

    if str(audio_path_or_url).startswith("http"):
        path, err = download_audio_to_temp(audio_path_or_url)
        cleanup = True
        if err or not path:
            result["error"] = err or "Could not download audio."
            return result

    try:
        if use_openai_api and openai_api_key:
            from openai import OpenAI
            client = OpenAI(api_key=openai_api_key)
            with open(path, "rb") as f:
                tr = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                    language="en"
                )
            result["text"] = (tr.text or "").strip()
            result["source"] = "openai-api"
        else:
            model = _get_whisper(model_size)
            tr = model.transcribe(path, language="en", task="transcribe")
            result["text"] = (tr.get("text") or "").strip()
            result["source"] = f"local-whisper-{model_size}"
    except Exception as e:
        result["error"] = str(e)
    finally:
        if cleanup and path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass

    return result