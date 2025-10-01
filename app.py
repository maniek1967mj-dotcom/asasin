import os
from flask import Flask, request, jsonify
from openai import OpenAI
import psycopg2

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
DATABASE_URL = os.environ.get("DATABASE_URL")

client = OpenAI(api_key=OPENAI_API_KEY)
app = Flask(__name__)

@app.get("/health")
def health():
    return jsonify(ok=True, service="my restaurant"),
    has_openai=bool(OPENAI_API_KEY),
    has_db=bool(DATABASE_URL))

@app.post("/haiku")
def haiku():
    data = request.get_json(silent=True) or {}
    topic = data.get("topic", "programowanie")
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": f"Napisz krótkie haiku o: {topic}"}],
            temperature=0.7
        )
        text = resp.choices[0].message.content.strip()
        return jsonify(haiku=text)
    except Exception as e:
        return jsonify(error=str(e)), 500

@app.get("/db-ping")
def db_ping():
    if not DATABASE_URL:
        return jsonify(ok=False, error="Brak DATABASE_URL"), 500
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT 1;")
        row = cur.fetchone()
        cur.close()
        conn.close()
        return jsonify(ok=True, result=row[0])
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port)
