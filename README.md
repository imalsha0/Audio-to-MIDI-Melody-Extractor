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

## Deploying

The browser UI can be hosted on Vercel, but audio extraction should run on a
separate Python web service: Demucs and Basic Pitch are CPU- and memory-heavy
and do not fit Vercel's serverless function model.

1. Deploy the repository to Render using the included `render.yaml` blueprint.
   The build installs Deno and yt-dlp's JavaScript challenge support for
   YouTube links. The free-plan configuration skips Demucs to reduce memory
   use and runs melody detection on the original audio, which may reduce
   melody accuracy. Basic Pitch processing can still exceed free-plan memory
   limits. Some media sites may block downloads from cloud servers; use an
   audio upload or direct audio-file URL in that case. Keep the service as a
   single instance because uploaded audio and generated MIDI files are stored
   temporarily on that instance.
2. In Vercel, import the same repository and set **Root Directory** to
   `frontend`. It is a static site; no build command is required.
3. After Render creates the API service, copy its public URL (for example,
   `https://your-api-service.onrender.com`) into the
   `audio-midi-api-url` meta tag in `frontend/index.html`, then redeploy the
   Vercel site. Leave the value empty for local development.
4. In Supabase **Authentication → URL Configuration**, set the Vercel URL as
   the site URL and add it to the allowed redirect URLs. Also configure Google
   OAuth with that production redirect URL if Google sign-in is enabled.

The API enables CORS for the Vercel frontend. Keep the Render API URL public;
do not place Supabase secret keys or Google client secrets in the frontend.

## Authentication setup

The studio supports Supabase email/password sign-up and login, plus Google
sign-in. A valid signed-in session is required to run audio extraction or
download generated MIDI files; the API verifies the Supabase access token.
Email confirmation behavior follows the Supabase project's Auth settings.
Signed-in users can edit their display name, upload or remove a
private profile photo, and change their password from the profile control in
the header. Avatar images are limited to 5 MB and are stored in the private
Supabase `avatars` bucket under the user's own folder. The app's publishable
key is safe for browser use; never put a Supabase secret key or Google client
secret in this repository.

The profile-photo bucket and its per-user Storage policies are defined in
`supabase/migrations/20261112000100_profile_avatar_storage.sql`.

To enable Google sign-in in the Supabase project:

1. Create a Google OAuth web client in Google Cloud. Add this authorized
   redirect URI:
   `https://aooiagzhcqfexqyddmrz.supabase.co/auth/v1/callback`
2. In the Supabase dashboard, open **Authentication → Sign In / Providers →
   Google**, enable Google, and enter the Google client ID and client secret.
3. In **Authentication → URL Configuration**, allow the local app redirect
   `http://127.0.0.1:8000/`. If you open the static frontend on port 8080,
   also allow `http://127.0.0.1:8080/`.

When deploying the app, set the production site URL and add its redirect URL
to the same allow list.

The frontend includes piano, melodic-track, and guitar audio-to-MIDI demos
with waveform players. Creative Commons tracks credit their uploaders below
the demo cards.
