"""
FastAPI backend for Audio-to-MIDI Melody & Chord Extractor.
Run with: uvicorn main:app --reload
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
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

UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
SEPARATED_DIR.mkdir(exist_ok=True)


class URLRequest(BaseModel):
    url: str


@app.get("/")
@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "message": "Universal Audio to MIDI API is running",
        "features": ["audio-upload", "url-extraction", "bpm-detection", "key-detection", "chord-recognition", "midi-export"]
    }


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

    # 2. Separate Vocals with Demucs using python -m demucs
    print(f"[Demucs] Isolating vocal melody stem...")
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

    audio_for_pitch = vocals_path if vocals_path.exists() else input_audio_path

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
        "has_vocals": vocals_path.exists(),
        "paths": {
            "melody_midi": f"/download-melody/{song_name}",
            "chords_midi": f"/download-chords/{song_name}"
        }
    }


@app.post("/process-audio")
async def process_audio_file(file: UploadFile = File(...)):
    """Upload audio file or mic recording for analysis & extraction."""
    filename = file.filename or "recording.wav"
    song_name = Path(filename).stem.replace(" ", "_")
    input_path = UPLOAD_DIR / filename

    with open(input_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    res = process_audio_pipeline(input_path, song_name)
    return JSONResponse(content=res)


@app.post("/process-url")
async def process_url(req: URLRequest):
    """Download audio from ANY web URL (YouTube, SoundCloud, direct MP3 link) & extract MIDI/Chords."""
    if not req.url or not req.url.strip():
        raise HTTPException(status_code=400, detail="URL cannot be empty.")

    try:
        downloaded_file = download_audio_from_url(req.url.strip(), UPLOAD_DIR)
        song_name = downloaded_file.stem.replace(" ", "_")
        res = process_audio_pipeline(downloaded_file, song_name)
        return JSONResponse(content=res)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"URL Processing failed: {str(e)}")


@app.get("/download-melody/{song_name}")
def download_melody(song_name: str, transpose: int = 0):
    """Download Melody MIDI file with optional semitone transposition."""
    orig_midi = OUTPUT_DIR / song_name / "vocals_basic_pitch.mid"
    if not orig_midi.exists():
        raise HTTPException(status_code=404, detail="Melody MIDI file not found.")

    if transpose == 0:
        target_path = orig_midi
    else:
        target_path = OUTPUT_DIR / song_name / f"melody_transposed_{transpose}.mid"
        transpose_midi_file(str(orig_midi), str(target_path), transpose)

    return FileResponse(
        path=target_path,
        filename=f"{song_name}_melody_key{transpose:+d}.mid",
        media_type="audio/midi",
    )


@app.get("/download-chords/{song_name}")
def download_chords(song_name: str, transpose: int = 0):
    """Download Chords MIDI file with optional semitone transposition."""
    orig_midi = OUTPUT_DIR / song_name / "chords.mid"
    if not orig_midi.exists():
        raise HTTPException(status_code=404, detail="Chords MIDI file not found.")

    target_path = OUTPUT_DIR / song_name / f"chords_transposed_{transpose}.mid"
    transpose_midi_file(str(orig_midi), str(target_path), transpose)

    return FileResponse(
        path=target_path,
        filename=f"{song_name}_chords_key{transpose:+d}.mid",
        media_type="audio/midi",
    )