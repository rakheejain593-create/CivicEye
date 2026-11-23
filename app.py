
import os
import io
import re
import json
import time
import base64
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
from PIL import Image, UnidentifiedImageError
from groq import Groq, APIStatusError

# ==========================================
# CONFIGURATION
# ==========================================

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=True)

API_KEY = os.getenv("GROQ_API_KEY", "").strip()
MODEL_NAME = os.getenv(
    "GROQ_MODEL", "qwen/qwen3.8-27b"
).strip()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

UPLOAD_DIR = BASE_DIR / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = BASE_DIR / "civiceye.db"

ALLOWED_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp"
}

CATEGORIES = [
    "Road damage", "Garbage", "Water leakage",
    "Streetlight", "Drainage", "Other"
]

PRIORITIES = ["Low", "Medium", "High"]

client = Groq(
    api_key=API_KEY,
    timeout=45.0,
    max_retries=1
) if API_KEY else None


# ==========================================
# DATABASE
# ==========================================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS complaints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                priority TEXT NOT NULL,
                department TEXT NOT NULL,
                location TEXT NOT NULL,
                details TEXT,
                image_filename TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Pending',
                created_at TEXT NOT NULL
            )
        """)


# ==========================================
# IMAGE PROCESSING
# ==========================================

def prepare_image(image_bytes):

    if not image_bytes:
        raise ValueError("Uploaded image is empty.")

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:

            if img.format not in ("JPEG", "PNG", "WEBP"):
                raise ValueError(
                    "Only JPG, PNG and WEBP images are allowed."
                )

            image = img.convert("RGB")
            image.thumbnail((1200, 1200))

            buffer = io.BytesIO()
            image.save(
                buffer,
                format="JPEG",
                quality=80
            )

    except UnidentifiedImageError:
        raise ValueError(
            "Invalid image. Please upload a clear photo."
        )

    encoded = base64.b64encode(
        buffer.getvalue()
    ).decode("utf-8")

    return f"data:image/jpeg;base64,{encoded}"


# ==========================================
# GROQ AI - TEXT AND IMAGE
# ==========================================

def ask_groq(prompt, image_url=None, system_prompt=None):

    if not client:
        raise RuntimeError(
            "GROQ_API_KEY missing in .env file."
        )

    if image_url:
        user_content = [
            {
                "type": "text",
                "text": prompt
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": image_url
                }
            }
        ]
    else:
        user_content = prompt

    messages = [
        {
            "role": "system",
            "content": system_prompt or (
                "You are CivicEye AI, a helpful civic "
                "issue reporting assistant."
            )
        },
        {
            "role": "user",
            "content": user_content
        }
    ]

    for attempt in range(2):
        try:
            print(
                f"Groq request: {MODEL_NAME}, "
                f"attempt {attempt + 1}",
                flush=True
            )

            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                temperature=0.3,
                max_completion_tokens=1500
            )

            answer = (
                response.choices[0].message.content or ""
            ).strip()

            if not answer:
                raise RuntimeError(
                    "Groq returned an empty response."
                )

            print("Groq response received!", flush=True)
            return answer

        except APIStatusError as exc:
            if (
                exc.status_code in (500, 502, 503, 504)
                and attempt == 0
            ):
                time.sleep(2)
                continue
            raise


# ==========================================
# AI IMAGE ANALYSIS
# ==========================================

def analyze_image(image_bytes, mime_type):

    image_url = prepare_image(image_bytes)

    prompt = """
You are CivicEye AI, a civic issue image analyzer.

Carefully inspect the uploaded image.

Identify whether it clearly shows a public civic
issue such as road damage, garbage, water leakage,
broken streetlights or drainage problems.

Return ONLY a valid JSON object.

Use these exact keys:

{
    "is_civic_issue": true,
    "category": "Road damage",
    "description": "Visible potholes on the road.",
    "priority": "Medium",
    "department": "Public Works Department"
}

Allowed categories:
Road damage, Garbage, Water leakage,
Streetlight, Drainage, Other.

Allowed priorities:
Low, Medium, High.

Low means a minor visible issue.
Medium means an issue requiring attention.
High means a serious visible hazard.

Do not invent information not visible in the photo.

If no clear civic issue is visible:
- is_civic_issue must be false
- category must be Other
- explain briefly in description

Department and priority are AI suggestions only.

Return JSON only.
No markdown or extra explanation.
"""

    answer = ask_groq(
        prompt=prompt,
        image_url=image_url
    )

    cleaned = answer.strip()

    if cleaned.startswith("```"):
        cleaned = re.sub(
            r"^```(?:json)?\s*",
            "",
            cleaned,
            flags=re.IGNORECASE
        )
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise ValueError(
                "AI did not return valid JSON. Please try again."
            )
        result = json.loads(match.group())

    if not isinstance(result, dict):
        raise ValueError("Invalid AI analysis format.")

    category = result.get("category", "Other")
    priority = result.get("priority", "Low")

    if category not in CATEGORIES:
        category = "Other"

    if priority not in PRIORITIES:
        priority = "Low"

    return {
        "is_civic_issue": (
            result.get("is_civic_issue") is True
        ),
        "category": category,
        "description": str(
            result.get(
                "description",
                "No description returned."
            )
        )[:500],
        "priority": priority,
        "department": str(
            result.get(
                "department",
                "Relevant local department"
            )
        )[:100]
    }


# ==========================================
# COMPLAINT FORMAT
# ==========================================

def complaint_to_dict(row):
    item = dict(row)

    item["image_url"] = (
        f"/static/uploads/{item.pop('image_filename')}"
    )

    return item


# ==========================================
# HOME PAGE
# ==========================================

@app.route("/")
def home():
    return render_template("index.html")


# ==========================================
# TEST GROQ CONNECTION
# ==========================================

@app.get("/test-groq")
def test_groq():
    try:
        answer = ask_groq(
            "Say hello as CivicEye AI in one sentence."
        )
        return jsonify({
            "success": True,
            "model": MODEL_NAME,
            "reply": answer
        })

    except Exception as exc:
        app.logger.exception("Groq test failed")
        return jsonify({
            "success": False,
            "error": str(exc)[:300]
        }), 502


# ==========================================
# GET COMPLAINTS
# ==========================================

@app.get("/api/complaints")
def list_complaints():

    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM complaints ORDER BY id DESC LIMIT 100"
        ).fetchall()

    return jsonify([
        complaint_to_dict(row) for row in rows
    ])


# ==========================================
# CREATE COMPLAINT
# ==========================================

@app.post("/api/complaints")
def create_complaint():

    image = request.files.get("image")
    location = (
        request.form.get("location") or ""
    ).strip()
    details = (
        request.form.get("details") or ""
    ).strip()

    if not image or not image.filename:
        return jsonify({
            "error": "Please choose an image first."
        }), 400

    if not location:
        return jsonify({
            "error": "Please enter the issue location."
        }), 400

    mime_type = image.mimetype

    if mime_type not in ALLOWED_TYPES:
        return jsonify({
            "error": "Use a JPG, PNG, or WEBP image."
        }), 400

    image_bytes = image.read()

    if not image_bytes:
        return jsonify({
            "error": "The selected image is empty."
        }), 400

    try:
        analysis = analyze_image(
            image_bytes,
            mime_type
        )

    except Exception as exc:
        app.logger.exception("Groq image analysis failed")
        return jsonify({
            "error": (
                "AI analysis failed. Check Groq model "
                "access, API key and rate limits."
            ),
            "technical_message": str(exc)[:300]
        }), 502

    if not analysis["is_civic_issue"]:
        return jsonify({
            "error": (
                "The AI could not identify a clear civic "
                "issue in this image. Try a clearer photo."
            ),
            "analysis": analysis
        }), 422

    extension = ALLOWED_TYPES[mime_type]
    filename = f"{uuid.uuid4().hex}{extension}"

    (UPLOAD_DIR / filename).write_bytes(image_bytes)

    created_at = datetime.now().strftime(
        "%Y-%m-%d %H:%M"
    )

    with get_db() as db:
        cursor = db.execute("""
            INSERT INTO complaints
            (category, description, priority, department,
             location, details, image_filename, status,
             created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'Pending', ?)
        """, (
            analysis["category"],
            analysis["description"],
            analysis["priority"],
            analysis["department"],
            location,
            details[:500],
            filename,
            created_at
        ))

        complaint_id = cursor.lastrowid

        row = db.execute(
            "SELECT * FROM complaints WHERE id = ?",
            (complaint_id,)
        ).fetchone()

    return jsonify({
        "message": "Your report was analyzed by AI and submitted.",
        "analysis": analysis,
        "complaint": complaint_to_dict(row)
    }), 201


# ==========================================
# UPDATE COMPLAINT STATUS
# ==========================================

@app.patch("/api/complaints/<int:complaint_id>")
def update_status(complaint_id):

    payload = request.get_json(silent=True) or {}
    status = payload.get("status", "")

    if status not in [
        "Pending", "In progress", "Resolved"
    ]:
        return jsonify({
            "error": "Invalid status."
        }), 400

    with get_db() as db:
        cursor = db.execute(
            "UPDATE complaints SET status = ? WHERE id = ?",
            (status, complaint_id)
        )

        if cursor.rowcount == 0:
            return jsonify({
                "error": "Complaint not found."
            }), 404

    return jsonify({
        "message": "Status updated."
    })


# ==========================================
# CIVICEYE CHATBOT
# ==========================================

@app.post("/api/chat")
def civic_chat():

    payload = request.get_json(silent=True) or {}
    message = (
        payload.get("message") or ""
    ).strip()

    if not message:
        return jsonify({
            "error": "Please type a message."
        }), 400

    if len(message) > 1200:
        return jsonify({
            "error": "Please keep your message under 1,200 characters."
        }), 400

    report_context = "No report details were requested."

    match = re.search(
        r"(?:CE[- ]?)?(\d+)",
        message,
        re.IGNORECASE
    )

    if match and any(
        word in message.lower()
        for word in [
            "status", "track", "complaint",
            "report", "ticket"
        ]
    ):
        report_id = int(match.group(1))

        with get_db() as db:
            row = db.execute("""
                SELECT id, category, description,
                       location, status, created_at
                FROM complaints
                WHERE id = ?
            """, (report_id,)).fetchone()

        if row:
            report_context = json.dumps(dict(row))
        else:
            report_context = (
                f"No complaint with report ID CE-{report_id} "
                "was found in this prototype database."
            )

    system_prompt = """
You are CivicEye Assistant, a friendly helpdesk
for a college civic-issue reporting prototype.

Help users report road damage, garbage,
water leakage, streetlight and drainage issues.

Rules:
- Keep answers simple, concise and polite.
- Explain how to upload a photo, enter a location,
  add optional details and submit a report.
- AI categories and priorities are suggestions.
- Never claim reports were sent to government.
- Reports are stored only in the local demo database.
- For emergencies, advise contacting local authorities.
- For complaint status, use only the context below.
- Do not invent report IDs or statuses.

Report context:
""" + report_context

    try:
        answer = ask_groq(
            prompt=message,
            system_prompt=system_prompt
        )

        return jsonify({
            "reply": answer
        })

    except Exception as exc:
        app.logger.exception("CivicEye chatbot failed")
        return jsonify({
            "error": (
                "The assistant is temporarily unavailable."
            ),
            "technical_message": str(exc)[:250]
        }), 502


# ==========================================
# FILE SIZE ERROR
# ==========================================

@app.errorhandler(413)
def too_large(_error):
    return jsonify({
        "error": "Image is too large. Maximum size is 5 MB."
    }), 413


# ==========================================
# START APPLICATION
# ==========================================

init_db()

if __name__ == "__main__":
    app.run(
        debug=True,
        host="127.0.0.1",
        port=5002
    )
