"""Speech-to-text and text-to-speech providers.

Primary: Bhashini (Government of India ULCA pipeline API; needs BHASHINI_USER_ID and BHASHINI_ULCA_API_KEY).
Fallback STT: faster-whisper running locally (optional extra `uv sync --extra whisper`, WHISPER_MODEL set).
Fallback TTS: none on the server; the web client uses the browser's Marathi voice only if one exists.

When nothing is configured the functions return an "unavailable" result and the UI offers typing.
Audio is converted to 16 kHz mono WAV with ffmpeg before recognition.
"""
from __future__ import annotations

import base64
import logging
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from app.core.config import DATA_DIR, get_settings

log = logging.getLogger("fasalalert.voice")
ULCA_CONFIG_URL = "https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/getModelsPipeline"
AUDIO_DIR = DATA_DIR / "cache" / "tts"


@dataclass
class SttResult:
    available: bool
    text: str | None = None
    confidence: float | None = None
    provider: str | None = None
    low_confidence_words: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class TtsResult:
    available: bool
    audio_id: str | None = None
    provider: str | None = None
    error: str | None = None


def bhashini_configured() -> bool:
    s = get_settings()
    return bool(s.bhashini_user_id and s.bhashini_ulca_api_key)


def whisper_configured() -> bool:
    if not get_settings().whisper_model:
        return False
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def stt_available() -> bool:
    return bhashini_configured() or whisper_configured()


def to_wav16k(audio: bytes) -> bytes:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required to decode recorded audio")
    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d) / "in", Path(d) / "out.wav"
        src.write_bytes(audio)
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(src), "-ac", "1", "-ar", "16000",
                        "-t", "35", str(dst)], check=True, timeout=30)
        return dst.read_bytes()


def _wav_duration_s(wav: bytes) -> float:
    return max(0.0, (len(wav) - 44) / 32000.0)  # 16 kHz, 16-bit mono


def _wav_is_silent(wav: bytes, threshold: int = 300) -> bool:
    import array

    samples = array.array("h", wav[44:])
    if not samples:
        return True
    peak = max(abs(x) for x in samples[:: max(1, len(samples) // 4000)])
    return peak < threshold


def _ulca_pipeline(task: str, lang: str) -> tuple[str, str, str, str]:
    s = get_settings()
    r = httpx.post(ULCA_CONFIG_URL, headers={"userID": s.bhashini_user_id, "ulcaApiKey": s.bhashini_ulca_api_key},
                   json={"pipelineTasks": [{"taskType": task, "config": {"language": {"sourceLanguage": lang}}}],
                         "pipelineRequestConfig": {"pipelineId": s.bhashini_pipeline_id}}, timeout=20)
    r.raise_for_status()
    cfg = r.json()
    service_id = cfg["pipelineResponseConfig"][0]["config"][0]["serviceId"]
    ep = cfg["pipelineInferenceAPIEndPoint"]
    return ep["callbackUrl"], ep["inferenceApiKey"]["name"], ep["inferenceApiKey"]["value"], service_id


def transcribe(audio: bytes, lang: str) -> SttResult:
    try:
        wav = to_wav16k(audio)
    except (RuntimeError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        return SttResult(False, error=f"audio_decode_failed: {type(e).__name__}")
    if _wav_duration_s(wav) < 0.4 or _wav_is_silent(wav):
        return SttResult(True, text="", confidence=0.0, provider="vad")  # PRD §7.5: "did not catch that"
    if bhashini_configured():
        try:
            url, kname, kval, sid = _ulca_pipeline("asr", lang)
            r = httpx.post(url, headers={kname: kval}, timeout=40, json={
                "pipelineTasks": [{"taskType": "asr", "config": {"language": {"sourceLanguage": lang}, "serviceId": sid,
                                                                 "audioFormat": "wav", "samplingRate": 16000}}],
                "inputData": {"audio": [{"audioContent": base64.b64encode(wav).decode()}]}})
            r.raise_for_status()
            out = r.json()["pipelineResponse"][0]["output"][0]
            # Bhashini ASR does not return a confidence; None is reported rather than a made-up value.
            return SttResult(True, text=out.get("source", "").strip(), confidence=None, provider="bhashini")
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
            log.warning("bhashini asr failed: %s", type(e).__name__)
            if not whisper_configured():
                return SttResult(False, error="bhashini_failed")
    if whisper_configured():
        return _whisper(wav, lang)
    return SttResult(False, error="stt_not_configured")


_whisper_model = None


def _whisper(wav: bytes, lang: str) -> SttResult:
    global _whisper_model
    from faster_whisper import WhisperModel

    if _whisper_model is None:
        _whisper_model = WhisperModel(get_settings().whisper_model, device="cpu", compute_type="int8")
    with tempfile.NamedTemporaryFile(suffix=".wav") as f:
        f.write(wav)
        f.flush()
        segments, _info = _whisper_model.transcribe(f.name, language=lang, word_timestamps=True, vad_filter=True)
        words, low = [], []
        for seg in segments:
            for w in seg.words or []:
                words.append(w)
                if w.probability < 0.5:
                    low.append(w.word.strip())
    if not words:
        return SttResult(True, text="", confidence=0.0, provider="whisper")
    text = "".join(w.word for w in words).strip()
    conf = sum(w.probability for w in words) / len(words)
    return SttResult(True, text=text, confidence=round(conf, 3), provider="whisper", low_confidence_words=low)


def synthesize(text: str, lang: str) -> TtsResult:
    if not bhashini_configured():
        return TtsResult(False, error="tts_not_configured")
    try:
        url, kname, kval, sid = _ulca_pipeline("tts", lang)
        r = httpx.post(url, headers={kname: kval}, timeout=40, json={
            "pipelineTasks": [{"taskType": "tts", "config": {"language": {"sourceLanguage": lang}, "serviceId": sid, "gender": "female"}}],
            "inputData": {"input": [{"source": text[:1500]}]}})
        r.raise_for_status()
        audio_b64 = r.json()["pipelineResponse"][0]["audio"][0]["audioContent"]
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
        return TtsResult(False, error=f"bhashini_tts_failed: {type(e).__name__}")
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    audio_id = uuid.uuid4().hex
    (AUDIO_DIR / f"{audio_id}.wav").write_bytes(base64.b64decode(audio_b64))
    return TtsResult(True, audio_id=audio_id, provider="bhashini")


def audio_path(audio_id: str) -> Path | None:
    """Path-traversal safe lookup (PRD §12): ids are hex only and must resolve inside AUDIO_DIR."""
    if not audio_id.isalnum() or len(audio_id) != 32:
        return None
    p = (AUDIO_DIR / f"{audio_id}.wav").resolve()
    if AUDIO_DIR.resolve() not in p.parents or not p.exists():
        return None
    return p
