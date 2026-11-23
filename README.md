# CivicEye — AI Civic Issue Reporter

A local college prototype that accepts a public-issue photo, uses Gemini image understanding to suggest a category/description/priority, and stores the report in SQLite.

## Requirements
- macOS, Python 3.10+ recommended
- Gemini API key from Google AI Studio
- Internet connection for AI analysis

## Setup (Mac)
1. Open Terminal and move into this folder:
   `cd CivicEye`
2. Create a virtual environment:
   `python3 -m venv .venv`
3. Activate it:
   `source .venv/bin/activate`
4. Install packages:
   `pip install -r requirements.txt`
5. Copy `.env.example` to `.env`:
   `cp .env.example .env`
6. Open `.env` in a text editor and replace the placeholder with your own Gemini API key.
7. Run:
   `python app.py`
8. Open `http://127.0.0.1:5000` in your browser.

## Important
- Never share your API key or commit `.env` to GitHub.
- The Gemini model can be changed in `.env` if the selected model is unavailable for your account.
- AI category and priority are suggestions, not official assessments.
- This local prototype does not send reports to a municipal authority.
- The admin status selector is intentionally open for a classroom demo. Do not deploy publicly without authentication, privacy controls, secure file handling, and moderation.
- Uploaded photos are stored in `static/uploads/`; the database is `civiceye.db`.
