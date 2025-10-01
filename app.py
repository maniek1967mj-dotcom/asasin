import os
import sys
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
import psycopg2
from psycopg2.extras import RealDictCursor
import json
from datetime import datetime

# ===================================
# LOGI DEBUGOWANIA
# ===================================
print(f"Python version: {sys.version}", flush=True)
print(f"Starting Flask app...", flush=True)
print(f"PORT: {os.environ.get('PORT', 'not set')}", flush=True)
print(f"DATABASE_URL: {'set' if os.environ.get('DATABASE_URL') else 'not set'}", flush=True)
print(f"OPENAI_API_KEY: {'set' if os.environ.get('OPENAI_API_KEY') else 'not set'}", flush=True)

# ===================================
# KONFIGURACJA ZMIENNYCH ŚRODOWISKOWYCH
# ===================================
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
DATABASE_URL = os.environ.get("DATABASE_URL")

# Inicjalizacja klienta OpenAI (tylko jeśli klucz istnieje)
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# ===================================
# INICJALIZACJA FLASK
# ===================================
app = Flask(__name__)
CORS(app)  # Włącz CORS dla wszystkich endpointów

# ===================================
# PODSTAWOWE ENDPOINTY
# ===================================
@app.route('/')
def index():
    return jsonify({
        "status": "API is running",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0"
    })

@app.route('/health')
def health():
    return jsonify({"status": "healthy"})

@app.route('/test')
def test():
    return "Test successful!"

# ===================================
# FUNKCJE POMOCNICZE BAZY DANYCH
# ===================================
def get_db_connection():
    """Tworzy połączenie z bazą danych PostgreSQL"""
    if not DATABASE_URL:
        return None
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        return conn
    except Exception as e:
        print(f"Database connection error: {e}", flush=True)
        return None

def init_database():
    """Inicjalizuje tabelę w bazie danych"""
    conn = get_db_connection()
    if not conn:
        print("Skipping database initialization - no connection", flush=True)
        return
    
    try:
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS conversations (
                id SERIAL PRIMARY KEY,
                user_message TEXT NOT NULL,
                assistant_message TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        print("Database initialized successfully", flush=True)
    except Exception as e:
        print(f"Database initialization error: {e}", flush=True)
    finally:
        conn.close()

# ===================================
# ENDPOINT CHATBOTA
# ===================================
@app.route('/api/chat', methods=['POST'])
def chat():
    """Endpoint do komunikacji z chatbotem"""
    try:
        # Sprawdź czy OpenAI jest skonfigurowane
        if not client:
            return jsonify({
                "error": "OpenAI API key not configured"
            }), 500
        
        # Pobierz wiadomość od użytkownika
        data = request.json
        user_message = data.get('message', '')
        
        if not user_message:
            return jsonify({
                "error": "Message is required"
            }), 400
        
        # Wywołaj OpenAI API (nowa składnia dla wersji 1.50.0)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": user_message}
            ],
            max_tokens=500,
            temperature=0.7
        )
        
        assistant_message = response.choices[0].message.content
        
        # Zapisz do bazy danych (jeśli połączona)
        conn = get_db_connection()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute(
                    'INSERT INTO conversations (user_message, assistant_message) VALUES (%s, %s)',
                    (user_message, assistant_message)
                )
                conn.commit()
            except Exception as e:
                print(f"Database save error: {e}", flush=True)
            finally:
                conn.close()
        
        return jsonify({
            "response": assistant_message
        })
        
    except Exception as e:
        print(f"Chat endpoint error: {e}", flush=True)
        return jsonify({
            "error": f"An error occurred: {str(e)}"
        }), 500

# ===================================
# ENDPOINT HISTORII
# ===================================
@app.route('/api/history', methods=['GET'])
def history():
    """Zwraca historię rozmów"""
    conn = get_db_connection()
    if not conn:
        return jsonify([])
    
    try:
        cur = conn.cursor()
        cur.execute('SELECT * FROM conversations ORDER BY timestamp DESC LIMIT 10')
        rows = cur.fetchall()
        return jsonify(rows)
    except Exception as e:
        print(f"History endpoint error: {e}", flush=True)
        return jsonify([])
    finally:
        conn.close()

# ===================================
# ENDPOINT TESTOWY DLA OPENAI
# ===================================
@app.route('/api/test-openai', methods=['GET'])
def test_openai():
    """Testuje połączenie z OpenAI"""
    if not client:
        return jsonify({"error": "OpenAI not configured"}), 500
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Say 'Hello, World!'"}],
            max_tokens=10
        )
        return jsonify({
            "status": "success",
            "response": response.choices[0].message.content
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500

# ===================================
# ERROR HANDLERS
# ===================================
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error"}), 500

# ===================================
# INICJALIZACJA PRZY STARCIE
# ===================================
print("Initializing database...", flush=True)
init_database()

# ===================================
# URUCHOMIENIE APLIKACJI
# ===================================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f"Starting Flask app on port {port}...", flush=True)
    app.run(host='0.0.0.0', port=port, debug=False)
else:
    # Gdy uruchamiany przez Gunicorn
    print(f"Flask app ready for Gunicorn", flush=True)
