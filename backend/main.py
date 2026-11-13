"""
FastAPI backend for Audio-to-MIDI Melody & Chord Extractor.
Run with: uvicorn main:app --reload
"""

import asyncio
import os
import sys
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

import httpx
import yt_dlp
from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from extract_melody import extract_melody
from url_audio_downloader import download_audio_from_url
from audio_analyzer import (
    analyze_audio_file,
    create_chords_midi,
    transpose_midi_file,
    transpose_chord_name
)

app = FastAPI(title="Universal Audio to MIDI & Chord Extractor API")

PROJECT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_DIR / "frontend"

# Enable CORS for all origins and methods
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("output")
SEPARATED_DIR = Path("separated")
OUTPUT_RETENTION_SECONDS = 60 * 60
OUTPUT_CLEANUP_INTERVAL_SECONDS = 60
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://aooiagzhcqfexqyddmrz.supabase.co")
SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable__ZzBcSiuhdJ_mfeSyRNBuQ_YuTMLzEX")

UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
SEPARATED_DIR.mkdir(exist_ok=True)

cleanup_task: Optional[asyncio.Task] = None
processing_semaphore = asyncio.Semaphore(1)


class URLRequest(BaseModel):
    url: str


class AuthRequest(BaseModel):
    email: str
    password: str
    name: Optional[str] = None


async def require_authenticated_user(request: Request) -> dict:
    """Verify the Supabase access token before allowing extraction or MIDI downloads."""
    authorization = request.headers.get("authorization", "")
    scheme, _, access_token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not access_token.strip():
        raise HTTPException(status_code=401, detail="Log in to extract melody and chords.")

    headers = {
        "apikey": SUPABASE_PUBLISHABLE_KEY,
        "Authorization": f"Bearer {access_token.strip()}",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            response = await client.get(f"{SUPABASE_URL}/auth/v1/user", headers=headers)
    except httpx.HTTPError as error:
        print(f"[Supabase Auth] Session verification failed: {type(error).__name__}: {error}")
        raise HTTPException(status_code=503, detail="Cannot verify your login with Supabase right now.")

    if response.status_code in (401, 403):
        raise HTTPException(status_code=401, detail="Your login session expired. Please log in again.")
    if response.status_code != 200:
        raise HTTPException(status_code=503, detail="Supabase could not verify your login right now.")
    return response.json()


def cleanup_expired_outputs(now: Optional[float] = None) -> int:
    """Remove per-song output folders after one hour without a download."""
    current_time = time.time() if now is None else now
    removed_count = 0

    for song_output_dir in OUTPUT_DIR.iterdir():
        if not song_output_dir.is_dir():
            continue

        try:
            if current_time - song_output_dir.stat().st_mtime >= OUTPUT_RETENTION_SECONDS:
                shutil.rmtree(song_output_dir)
                removed_count += 1
                print(f"[Cleanup] Removed expired MIDI output folder: {song_output_dir}")
        except FileNotFoundError:
            continue
        except OSError as e:
            print(f"[Cleanup] Could not remove expired MIDI output folder {song_output_dir}: {e}")

    return removed_count


async def cleanup_expired_outputs_loop():
    while True:
        await asyncio.to_thread(cleanup_expired_outputs)
        await asyncio.sleep(OUTPUT_CLEANUP_INTERVAL_SECONDS)


@app.on_event("startup")
async def start_output_cleanup():
    global cleanup_task
    cleanup_task = asyncio.create_task(cleanup_expired_outputs_loop())


@app.on_event("shutdown")
async def stop_output_cleanup():
    if cleanup_task is not None:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass


def mark_output_downloaded(song_name: str):
    song_output_dir = OUTPUT_DIR / song_name
    if song_output_dir.is_dir():
        os.utime(song_output_dir, None)


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "message": "Universal Audio to MIDI API is running",
        "features": ["audio-upload", "url-extraction", "bpm-detection", "key-detection", "chord-recognition", "midi-export"]
    }


async def supabase_auth_request(path: str, payload: dict) -> JSONResponse:
    """Forward email/password authentication through the local server.

    Some local browser setups route external requests through a proxy that
    cannot reach Supabase. The backend uses a direct HTTPS connection instead.
    """
    headers = {
        "apikey": SUPABASE_PUBLISHABLE_KEY,
        "Authorization": f"Bearer {SUPABASE_PUBLISHABLE_KEY}",
        "Content-Type": "application/json",
    }
    last_error: Optional[httpx.HTTPError] = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
                response = await client.post(f"{SUPABASE_URL}{path}", headers=headers, json=payload)
            try:
                content = response.json()
            except ValueError:
                content = {"message": "Supabase returned an invalid response."}
            return JSONResponse(status_code=response.status_code, content=content)
        except httpx.HTTPError as error:
            last_error = error
            if attempt < 2:
                await asyncio.sleep(attempt + 1)

    print(f"[Supabase Auth] Connection failed after retries: {type(last_error).__name__}: {last_error}")
    raise HTTPException(status_code=503, detail="Cannot connect to Supabase authentication service.")


@app.post("/auth/signup")
async def auth_signup(request: AuthRequest):
    return await supabase_auth_request(
        "/auth/v1/signup",
        {
            "email": request.email,
            "password": request.password,
            "data": {"display_name": request.name or ""},
        },
    )


@app.post("/auth/login")
async def auth_login(request: AuthRequest):
    return await supabase_auth_request(
        "/auth/v1/token?grant_type=password",
        {"email": request.email, "password": request.password},
    )


@app.get("/", include_in_schema=False)
def frontend():
    """Serve the browser interface from the same local server as the API."""
    return FileResponse(FRONTEND_DIR / "index.html")


def process_audio_pipeline(input_audio_path: Path, song_name: str) -> dict:
    """
    Core Pipeline:
    1. Analyze full audio for BPM, Key, and Chords.
    2. Run Demucs to isolate vocal stem.
    3. Run Basic Pitch on vocal stem to extract Melody MIDI.
    4. Return full JSON analysis + paths to generated files.
    """
    song_output_dir = OUTPUT_DIR / song_name
    song_output_dir.mkdir(parents=True, exist_ok=True)

    # Clean up old output files in song_output_dir to avoid basic_pitch overwrite error
    for old_file in song_output_dir.glob("*.mid"):
        try:
            old_file.unlink()
        except Exception:
            pass

    # 1. Run Audio Analysis (BPM, Key, Chords) on original audio
    print(f"[Analysis] Running BPM, Key, and Chord extraction on {input_audio_path}")
    analysis_result = analyze_audio_file(str(input_audio_path))

    # Demucs can exceed the memory available on small hosted instances.
    skip_demucs = os.getenv("SKIP_DEMUCS", "").lower() in {"1", "true", "yes"}
    if skip_demucs:
        print("[Demucs] Skipped by configuration; using original audio for pitch detection.")
    else:
        print("[Demucs] Isolating vocal melody stem...")
        try:
            subprocess.run(
                [sys.executable, "-m", "demucs", "--two-stems=vocals", "-o", str(SEPARATED_DIR), str(input_audio_path)],
                check=True,
                capture_output=True,
                text=True,
            )
        except Exception as e:
            print(f"Demucs Warning/Error: {e}. Falling back to original audio for pitch detection.")

    # Locate vocals wav or fallback to input_audio_path
    vocals_stem_name = input_audio_path.stem
    vocals_path = SEPARATED_DIR / "htdemucs" / vocals_stem_name / "vocals.wav"
    if not vocals_path.exists():
        # Check alternative folder names if demucs created sanitized folder name
        possible_vocals = list(SEPARATED_DIR.glob(f"**/{vocals_stem_name}/vocals.wav"))
        if possible_vocals:
            vocals_path = possible_vocals[0]

    try:
        audio_for_pitch = input_audio_path
        if vocals_path.exists():
            try:
                import librosa
                import numpy as np
                y, sr = librosa.load(vocals_path, sr=None, mono=True)
                # If the vocal stem has very low volume, it's likely an instrumental track
                if np.max(np.abs(y)) > 0.02:
                    audio_for_pitch = vocals_path
                else:
                    print(f"[Demucs] Vocal stem is too quiet (Instrumental track). Bypassing stem separation.")
            except Exception as e:
                print(f"Error checking vocal volume: {e}")
                audio_for_pitch = vocals_path

        has_vocals = vocals_path.exists()

        # 3. Generate Melody MIDI with Basic Pitch
        print(f"[Basic Pitch] Extracting melody notes from {audio_for_pitch}...")
        extract_melody(str(audio_for_pitch), output_dir=str(song_output_dir))

        # Find the generated MIDI file from basic pitch
        generated_midis = list(song_output_dir.glob("*.mid"))
        if not generated_midis:
            raise HTTPException(status_code=500, detail="Melody MIDI generation failed.")

        target_melody_midi = song_output_dir / "vocals_basic_pitch.mid"
        if generated_midis[0] != target_melody_midi:
            if target_melody_midi.exists():
                target_melody_midi.unlink()
            shutil.move(str(generated_midis[0]), str(target_melody_midi))

        # 4. Create default Chords MIDI
        chords_midi_path = song_output_dir / "chords.mid"
        create_chords_midi(analysis_result["chords"], semitones=0, output_path=str(chords_midi_path))

        return {
            "song_name": song_name,
            "bpm": analysis_result["bpm"],
            "key": analysis_result["key"],
            "key_root": analysis_result["key_root"],
            "key_mode": analysis_result["key_mode"],
            "chords": analysis_result["chords"],
            "has_vocals": has_vocals,
            "paths": {
                "melody_midi": f"/download-melody/{song_name}",
                "chords_midi": f"/download-chords/{song_name}"
            }
        }
    finally:
        if vocals_path.exists():
            try:
                shutil.rmtree(vocals_path.parent)
            except OSError as e:
                print(f"[Cleanup] Could not remove Demucs audio stems at {vocals_path.parent}: {e}")


@app.post("/process-audio")
async def process_audio_file(file: UploadFile = File(...), user: dict = Depends(require_authenticated_user)):
    """Upload audio file or mic recording for analysis & extraction."""
    filename = file.filename or "recording.wav"
    song_name = Path(filename).stem.replace(" ", "_")
    input_path: Optional[Path] = None

    try:
        with tempfile.NamedTemporaryFile(
            prefix=f"{song_name}_",
            suffix=Path(filename).suffix,
            dir=UPLOAD_DIR,
            delete=False,
        ) as temp_file:
            input_path = Path(temp_file.name)
            await asyncio.to_thread(shutil.copyfileobj, file.file, temp_file)

        async with processing_semaphore:
            res = await asyncio.to_thread(process_audio_pipeline, input_path, song_name)
        return JSONResponse(content=res)
    finally:
        if input_path is not None and input_path.exists():
            input_path.unlink()


@app.post("/process-url")
async def process_url(req: URLRequest, user: dict = Depends(require_authenticated_user)):
    """Download audio from ANY web URL (YouTube, SoundCloud, direct MP3 link) & extract MIDI/Chords."""
    if not req.url or not req.url.strip():
        raise HTTPException(status_code=400, detail="URL cannot be empty.")

    downloaded_file: Optional[Path] = None
    try:
        async with processing_semaphore:
            downloaded_file = await asyncio.to_thread(
                download_audio_from_url, req.url.strip(), UPLOAD_DIR
            )
            song_name = downloaded_file.stem.replace(" ", "_")
            res = await asyncio.to_thread(process_audio_pipeline, downloaded_file, song_name)
        return JSONResponse(content=res)
    except yt_dlp.utils.DownloadError as e:
        print(f"[URL Download] yt-dlp failed: {e}")
        raise HTTPException(
            status_code=422,
            detail=(
                "Could not download audio from that link. YouTube may block downloads from cloud servers; "
                "try uploading an audio file or using a direct audio-file URL."
            ),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"URL Processing failed: {str(e)}")
    finally:
        if downloaded_file is not None and downloaded_file.exists():
            downloaded_file.unlink()


@app.get("/download-melody/{song_name}")
def download_melody(song_name: str, transpose: int = 0, user: dict = Depends(require_authenticated_user)):
    """Download Melody MIDI file with optional semitone transposition."""
    orig_midi = OUTPUT_DIR / song_name / "vocals_basic_pitch.mid"
    if not orig_midi.exists():
        raise HTTPException(status_code=404, detail="Melody MIDI file not found.")

    if transpose == 0:
        target_path = orig_midi
    else:
        target_path = OUTPUT_DIR / song_name / f"melody_transposed_{transpose}.mid"
        transpose_midi_file(str(orig_midi), str(target_path), transpose)

    mark_output_downloaded(song_name)
    return FileResponse(
        path=target_path,
        filename=f"{song_name}_melody_key{transpose:+d}.mid",
        media_type="audio/midi",
    )


@app.get("/download-chords/{song_name}")
def download_chords(song_name: str, transpose: int = 0, user: dict = Depends(require_authenticated_user)):
    """Download Chords MIDI file with optional semitone transposition."""
    orig_midi = OUTPUT_DIR / song_name / "chords.mid"
    if not orig_midi.exists():
        raise HTTPException(status_code=404, detail="Chords MIDI file not found.")

    target_path = OUTPUT_DIR / song_name / f"chords_transposed_{transpose}.mid"
    transpose_midi_file(str(orig_midi), str(target_path), transpose)

    mark_output_downloaded(song_name)
    return FileResponse(
        path=target_path,
        filename=f"{song_name}_chords_key{transpose:+d}.mid",
        media_type="audio/midi",
    )


@app.get("/audio-midi-mark.png", include_in_schema=False)
def logo():
    return FileResponse(FRONTEND_DIR / "audio-midi-mark.png")


app.mount(
    "/demo-assets",
    StaticFiles(directory=FRONTEND_DIR / "demo-assets"),
    name="demo-assets",
)
