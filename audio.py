"""
Audio transcription and comparison against form answers.
Supports:
- Uploaded audio files
- Audio links / paths stored in a column of the dataset
"""
from typing import Optional, Dict, Any
import tempfile
from pathlib import Path
import re
import requests

try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

_model = None


def load_whisper(model_size: str = "base"):
    """
    Lazy-load Whisper model.
    Options: "tiny", "base", "small", "medium", "large"
    """
    global _model
    if not WHISPER_AVAILABLE:
        raise RuntimeError("openai-whisper is not installed. Run: pip install openai-whisper")
    if _model is None:
        _model = whisper.load_model(model_size)
    return _model


def transcribe_audio(file_path: str, model_size: str = "base") -> Dict[str, Any]:
    model = load_whisper(model_size)
    result = model.transcribe(file_path, fp16=False)
    return {
        "text": result.get("text", "").strip(),
        "language": result.get("language"),
        "segments": result.get("segments", [])
    }


def simple_text_similarity(a: str, b: str) -> float:
    """Lightweight token overlap similarity (0-1)."""
    if not a or not b:
        return 0.0
    tokens_a = set(re.findall(r"\w+", a.lower()))
    tokens_b = set(re.findall(r"\w+", b.lower()))
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    return len(intersection) / max(len(tokens_a), len(tokens_b))


def compare_transcription_to_form(
    transcription: str,
    form_answers: Dict[str, Any],
    threshold: float = 0.6
) -> Dict[str, Any]:
    form_text = " ".join(str(v) for v in form_answers.values() if v is not None)
    overall = simple_text_similarity(transcription, form_text)

    field_scores = {}
    for field, answer in form_answers.items():
        if answer is None or str(answer).strip() == "":
            continue
        score = simple_text_similarity(transcription, str(answer))
        field_scores[field] = {
            "answer": str(answer),
            "score": round(score, 3),
            "matched": score >= threshold
        }

    return {
        "transcription": transcription,
        "overall_similarity": round(overall, 3),
        "overall_match": overall >= threshold,
        "field_scores": field_scores,
        "threshold": threshold
    }


def download_audio_from_url(url: str) -> str:
    """Download audio from a URL and save it to a temporary file."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    response = requests.get(url, headers=headers, timeout=60, stream=True)
    response.raise_for_status()

    suffix = ".mp3"
    if ".wav" in url.lower():
        suffix = ".wav"
    elif ".m4a" in url.lower():
        suffix = ".m4a"
    elif ".ogg" in url.lower():
        suffix = ".ogg"
    elif ".flac" in url.lower():
        suffix = ".flac"

    content_type = response.headers.get("Content-Type", "")
    if "wav" in content_type:
        suffix = ".wav"
    elif "mpeg" in content_type or "mp3" in content_type:
        suffix = ".mp3"

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    for chunk in response.iter_content(chunk_size=8192):
        if chunk:
            tmp.write(chunk)
    tmp.close()
    return tmp.name


def process_audio_from_path_or_url(
    path_or_url: str,
    form_row: Optional[Dict] = None,
    threshold: float = 0.6,
    model_size: str = "base"
) -> Dict[str, Any]:
    """Transcribe audio from a local path or remote URL."""
    path_or_url = str(path_or_url).strip()
    if not path_or_url or path_or_url.lower() in ("nan", "none", ""):
        return {"success": False, "error": "Empty audio path/URL"}

    tmp_path = None
    try:
        if path_or_url.lower().startswith(("http://", "https://")):
            tmp_path = download_audio_from_url(path_or_url)
            audio_path = tmp_path
        else:
            audio_path = path_or_url
            if not Path(audio_path).exists():
                return {"success": False, "error": f"Local file not found: {audio_path}"}

        result = transcribe_audio(audio_path, model_size=model_size)
        out = {
            "transcription": result["text"],
            "language": result.get("language"),
            "success": True,
            "source": path_or_url
        }

        if form_row:
            comparison = compare_transcription_to_form(
                result["text"], form_row, threshold=threshold
            )
            out["comparison"] = comparison

        return out

    except Exception as e:
        return {"success": False, "error": str(e), "source": path_or_url}
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


def process_audio_upload(
    uploaded_file,
    form_row: Optional[Dict] = None,
    threshold: float = 0.6,
    model_size: str = "base"
) -> Dict[str, Any]:
    """Keep the old upload method for manual testing."""
    suffix = Path(uploaded_file.name).suffix or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded_file.read())
        tmp_path = tmp.name

    try:
        result = transcribe_audio(tmp_path, model_size=model_size)
        out = {
            "transcription": result["text"],
            "language": result.get("language"),
            "success": True
        }
        if form_row:
            comparison = compare_transcription_to_form(
                result["text"], form_row, threshold=threshold
            )
            out["comparison"] = comparison
        return out
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        Path(tmp_path).unlink(missing_ok=True)