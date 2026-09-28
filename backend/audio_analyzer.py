"""
Audio Analyzer for BPM estimation, Key detection, Chord recognition, and Chord MIDI generation.
"""

import math
import numpy as np
import librosa
import pretty_midi
from pathlib import Path
import re

# Note names array for indexing
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Krumhansl-Schmuckler Key Profiles
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

# Basic Chord Templates (relative pitch classes from root)
CHORD_TEMPLATES = {
    "": [0, 4, 7],         # Major (e.g. C = C, E, G)
    "m": [0, 3, 7],        # Minor (e.g. Cm = C, Eb, G)
    "7": [0, 4, 7, 10],    # Dominant 7th (e.g. C7 = C, E, G, Bb)
    "maj7": [0, 4, 7, 11], # Major 7th
    "m7": [0, 3, 7, 10],   # Minor 7th
    "dim": [0, 3, 6],      # Diminished
}

def analyze_bpm(y: np.ndarray, sr: int) -> float:
    """Estimates BPM (Tempo) from audio array."""
    try:
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        if isinstance(tempo, np.ndarray):
            tempo = float(tempo[0]) if len(tempo) > 0 else 120.0
        else:
            tempo = float(tempo)
        return round(tempo, 1) if tempo > 0 else 120.0
    except Exception as e:
        print(f"BPM calculation error: {e}")
        return 120.0


def analyze_key(chroma: np.ndarray) -> dict:
    """
    Estimates key signature using Krumhansl-Schmuckler key-finding algorithm.
    Returns dict: {"key": "C Major", "root": "C", "mode": "Major", "root_index": 0}
    """
    # Average chroma over time
    chroma_sum = np.sum(chroma, axis=1)
    if np.sum(chroma_sum) == 0:
        return {"key": "C Major", "root": "C", "mode": "Major", "root_index": 0}

    best_corr = -1
    best_key = ("C", "Major", 0)

    for i in range(12):
        # Rotate profiles to match root i
        maj_profile = np.roll(MAJOR_PROFILE, i)
        min_profile = np.roll(MINOR_PROFILE, i)

        maj_corr = np.corrcoef(chroma_sum, maj_profile)[0, 1]
        min_corr = np.corrcoef(chroma_sum, min_profile)[0, 1]

        if maj_corr > best_corr:
            best_corr = maj_corr
            best_key = (NOTE_NAMES[i], "Major", i)

        if min_corr > best_corr:
            best_corr = min_corr
            best_key = (NOTE_NAMES[i], "Minor", i)

    root, mode, root_idx = best_key
    return {
        "key": f"{root} {mode}",
        "root": root,
        "mode": mode,
        "root_index": root_idx
    }


def analyze_chords(y: np.ndarray, sr: int, bpm: float) -> list:
    """
    Extracts chord progression bar-by-bar (or 2-beat intervals).
    Returns list of dicts: [ {"start": 0.0, "end": 2.0, "chord": "C", "root": "C", "type": ""}, ... ]
    """
    try:
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        duration = librosa.get_duration(y=y, sr=sr)

        # Determine segment interval (1 bar = 4 beats = 240 / bpm seconds)
        beat_duration = 60.0 / (bpm if bpm > 30 else 120.0)
        bar_duration = beat_duration * 2.0  # Every 2 beats for good chord resolution

        frames_per_sec = chroma.shape[1] / duration if duration > 0 else 1.0
        chords = []

        curr_time = 0.0
        while curr_time < duration:
            end_time = min(curr_time + bar_duration, duration)

            start_frame = int(curr_time * frames_per_sec)
            end_frame = max(start_frame + 1, int(end_time * frames_per_sec))

            seg_chroma = chroma[:, start_frame:end_frame]
            seg_chroma_mean = np.mean(seg_chroma, axis=1)

            # Match segment chroma against chord templates
            best_score = -1.0
            best_chord_name = "C"
            best_root = "C"
            best_type = ""

            for root_idx in range(12):
                root_name = NOTE_NAMES[root_idx]
                for chord_type, pitch_offsets in CHORD_TEMPLATES.items():
                    # Build expected vector for this chord
                    template = np.zeros(12)
                    for offset in pitch_offsets:
                        template[(root_idx + offset) % 12] = 1.0

                    # Calculate cosine similarity or correlation
                    norm_seg = np.linalg.norm(seg_chroma_mean)
                    norm_tpl = np.linalg.norm(template)
                    if norm_seg > 0 and norm_tpl > 0:
                        score = np.dot(seg_chroma_mean, template) / (norm_seg * norm_tpl)
                    else:
                        score = 0.0

                    if score > best_score:
                        best_score = score
                        best_chord_name = f"{root_name}{chord_type}"
                        best_root = root_name
                        best_type = chord_type

            # Merge consecutive identical chords if short
            if chords and chords[-1]["chord"] == best_chord_name:
                chords[-1]["end"] = round(end_time, 2)
            else:
                chords.append({
                    "start": round(curr_time, 2),
                    "end": round(end_time, 2),
                    "chord": best_chord_name,
                    "root": best_root,
                    "type": best_type
                })

            curr_time = end_time

        return chords
    except Exception as e:
        print(f"Chord recognition error: {e}")
        return [{"start": 0.0, "end": 4.0, "chord": "C", "root": "C", "type": ""}]


def analyze_audio_file(file_path: str) -> dict:
    """
    Runs full analysis (BPM, Key, Chords) on an audio file.
    """
    y, sr = librosa.load(file_path, sr=22050, mono=True)
    bpm = analyze_bpm(y, sr)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    key_info = analyze_key(chroma)
    chords = analyze_chords(y, sr, bpm)

    return {
        "bpm": bpm,
        "key": key_info["key"],
        "key_root": key_info["root"],
        "key_mode": key_info["mode"],
        "chords": chords
    }


def transpose_chord_name(chord_str: str, semitones: int) -> str:
    """Transposes a chord string (e.g. Am7, C#) by N semitones."""
    if semitones == 0:
        return chord_str

    # Extract root note (C#, Bb, etc.)
    match = re.match(r"^([A-G][#b]?)(.*)$", chord_str)
    if not match:
        return chord_str

    root, suffix = match.groups()

    # Normalize flat to sharp if needed for note index lookup
    flats_to_sharps = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#"}
    root_norm = flats_to_sharps.get(root, root)

    if root_norm in NOTE_NAMES:
        curr_idx = NOTE_NAMES.index(root_norm)
        new_idx = (curr_idx + semitones) % 12
        return f"{NOTE_NAMES[new_idx]}{suffix}"
    return chord_str


def create_chords_midi(chords: list, semitones: int = 0, output_path: str = "chords.mid"):
    """
    Generates a MIDI file for the given chord progression with transposition.
    Chords are played as voicings in octave 4 (MIDI 60+).
    """
    pm = pretty_midi.PrettyMIDI()
    piano_program = pretty_midi.instrument_name_to_program('Acoustic Grand Piano')
    piano = pretty_midi.Instrument(program=piano_program)

    for chord_item in chords:
        chord_str = chord_item["chord"]
        transposed_chord = transpose_chord_name(chord_str, semitones)

        match = re.match(r"^([A-G][#b]?)(.*)$", transposed_chord)
        if not match:
            continue
        root, suffix = match.groups()

        flats_to_sharps = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#"}
        root_norm = flats_to_sharps.get(root, root)

        if root_norm not in NOTE_NAMES:
            continue

        root_pitch = 60 + NOTE_NAMES.index(root_norm)  # Middle C octave
        offsets = CHORD_TEMPLATES.get(suffix, [0, 4, 7])

        start_time = float(chord_item["start"])
        end_time = float(chord_item["end"])

        for offset in offsets:
            note_pitch = root_pitch + offset
            note = pretty_midi.Note(
                velocity=80,
                pitch=note_pitch,
                start=start_time,
                end=end_time
            )
            piano.notes.append(note)

    pm.instruments.append(piano)
    pm.write(output_path)
    return output_path


def transpose_midi_file(input_midi_path: str, output_midi_path: str, semitones: int):
    """
    Transposes all notes in an existing MIDI file by `semitones`.
    """
    pm = pretty_midi.PrettyMIDI(input_midi_path)
    for instrument in pm.instruments:
        for note in instrument.notes:
            note.pitch = max(0, min(127, note.pitch + semitones))
    pm.write(output_midi_path)
    return output_midi_path
