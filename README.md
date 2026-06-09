# Macau Invitation Webpage

A simple invitation flow: register email → accept Macau invite → pick activities → pick a date → receive an email from `houhonuhh@gmail.com`.

## Run locally

1. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and set your **Gmail App Password** (16 characters).
3. Start the server:

   ```bash
   python server.py
   ```

4. Open [http://127.0.0.1:5000](http://127.0.0.1:5000)

## Public link (permanent — no tunnel)

Deploy to **[Render](https://render.com)** for a stable URL like `https://macau-invitation.onrender.com`:

1. Push this folder to a **GitHub** repository.
2. Sign in to [Render](https://dashboard.render.com) → **New** → **Blueprint** → connect your repo.
3. Render reads `render.yaml` automatically.
4. When prompted, set **`GMAIL_APP_PASSWORD`** to your 16-character Google App Password.
5. Click **Apply** — your public URL appears on the service page when deploy finishes.

Share that Render URL with anyone. No tunnel, no keeping your PC on.

## Flow

1. User enters their email.
2. “Would you accept the invitation to Macau?” — **No** dodges the cursor with Singlish messages.
3. **Yes** → choose activities in Macau.
4. Pick a date (`YYYY/DD/MM`) — invitation email sends automatically.
5. Email includes chosen date and activities.
