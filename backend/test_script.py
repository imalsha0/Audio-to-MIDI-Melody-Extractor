import os
import sys
from pathlib import Path
from main import process_audio_pipeline

if __name__ == "__main__":
    test_file = Path("test_audio/song2.wav")
    try:
        res = process_audio_pipeline(test_file, "song2")
        print("Success:", res)
    except Exception as e:
        import traceback
        traceback.print_exc()
