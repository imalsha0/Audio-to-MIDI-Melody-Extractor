# Audio to MIDI Melody Extractor

Web app that converts audio (YouTube link, file upload, or mic recording)
into a MIDI file of the detected melody.

## Status: In development

Uploaded and URL-downloaded audio, including temporary vocal stems, is removed
after processing. Generated per-track MIDI files remain available for one hour
after processing or the latest download, then are automatically removed.

Generated melody and chord MIDI files can be previewed with a built-in
synthesized tone in the browser before downloading.

## Run locally

Use Python 3.10 for this project. Install the dependencies into a
virtual environment, then start the local server:

```powershell
python -m venv .venv310
.\.venv310\Scripts\python.exe -m pip install -r requirements.txt
.\run.ps1
```

Open `http://127.0.0.1:8000/` in a browser. The server hosts both the
frontend and the API, so YouTube links, audio uploads, MIDI previews, and
downloads use the same local address.

The frontend includes piano, melodic-track, and guitar audio-to-MIDI demos
with waveform players. Creative Commons tracks credit their uploaders below
the demo cards.
