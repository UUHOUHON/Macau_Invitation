# Dinner Invitation

Guests pick a language, register phone + email, say yes to dinner (the No button dodges on phone and desktop), choose cuisine and a date. You get notified at `houhonuhh@gmail.com`, and guests get a booking confirmation email.

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

## Public link (Render)

Deploy to **[Render](https://render.com)** for a stable public URL:

1. Code is at [github.com/UUHOUHON/Macau_Invitation](https://github.com/UUHOUHON/Macau_Invitation).
2. On Render, set `BREVO_API_KEY` (recommended) so confirmation emails can reach any guest. Resend free sandbox only emails your own Gmail.
3. Keep `SENDER_EMAIL` / `HOST_NOTIFY_EMAIL` as `houhonuhh@gmail.com`.

## Flow

1. Guest chooses a language.
2. Guest registers phone + email → emailed to `houhonuhh@gmail.com`.
3. “Interested in dinner?” — **No** dodges on mobile and desktop; **Yes** continues.
4. Pick cuisine(s) and a dinner date.
5. Host gets the RSVP; guest gets a “successfully booked” invitation email.
