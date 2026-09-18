"""
Phase 1 - Core script: Audio file -> MIDI melody
Usage: python extract_melody.py test_audio/sample.mp3
"""

import sys
import os
from basic_pitch.inference import predict_and_save
from basic_pitch import ICASSP_2022_MODEL_PATH


def extract_melody(audio_path: str, output_dir: str = None):
    if output_dir is None:
        # Create a unique output folder based on the input file's parent folder name
        song_name = os.path.basename(os.path.dirname(audio_path)) or "output"
        output_dir = os.path.join("output", song_name)
    if not os.path.exists(audio_path):
        print(f"Error: File not found -> {audio_path}")
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)

    print(f"Processing: {audio_path}")
    print("Detecting notes... (this may take a moment)")

    predict_and_save(
        audio_path_list=[audio_path],
        output_directory=output_dir,
        save_midi=True,
        sonify_midi=False,
        save_model_outputs=False,
        save_notes=False,
        model_or_model_path=ICASSP_2022_MODEL_PATH,
    )

    print(f"\nDone! MIDI file saved in: {output_dir}/")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_melody.py <path-to-audio-file>")
        sys.exit(1)

    input_file = sys.argv[1]
    extract_melody(input_file)