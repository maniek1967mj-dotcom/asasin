import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
import psycopg2
from psycopg2.extras import RealDictCursor
import json
from datetime import datetime

# ===================================
# KONFIGURACJA ZMIENNYCH ŚRODOWISKOWYCH
# ===================================
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
DATABASE_URL = os.environ.get("DATABASE_URL")

# Inicjalizacja klienta OpenAI (tylko jeśli klucz istnieje)
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# Inicjalizacja aplikacji Flask
app = Flask(__name__)
CORS(app)  # Włącz CORS dla wszystkich endpointów

# ===================================
# ENDPOINT: /health
# Sprawdzenie stanu aplikacji
# ===================================
@app.route("/health", methods=["GET"])
def health():
    """Zwraca status aplikacji i dostępność usług"""
    return jsonify({
        "ok": True,
        "service": "restaurant_assistant",
        "timestamp": datetime.now().isoformat(),
        "has_openai": bool(OPENAI_API_KEY),
        "has_database": bool(DATABASE_URL),
        "version": "1.0.0"
    })

# ===================================
# ENDPOINT: /haiku
# Generator haiku przez OpenAI
# ===================================
@app.route("/haiku", methods=["POST"])
def haiku():
    """Generuje haiku na podany temat"""
    try:
        # Pobierz dane z requestu
        data = request.get_json(silent=True) or {}
        topic = data.get("topic", "restauracja")
        
        # Sprawdź dostępność OpenAI
        if not client:
            return jsonify({
                "error": "OpenAI API key not configured"
            }), 503
        
        # Wygeneruj haiku
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Jesteś poetą tworzącym haiku po polsku."
                },
                {
                    "role": "user",
                    "content": f"Napisz krótkie haiku o: {topic}"
                }
            ],
            temperature=0.7,
            max_tokens=100
        )
        
        haiku_text = response.choices[0].message.content.strip()
        
        return jsonify({
            "ok": True,
            "topic": topic,
            "haiku": haiku_text
        })
        
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500

# ===================================
# ENDPOINT: /db-ping
# Test połączenia z bazą danych
# ===================================
@app.route("/db-ping", methods=["GET"])
def db_ping():
    """Testuje połączenie z bazą PostgreSQL"""
    
    if not DATABASE_URL:
        return jsonify({
            "ok": False,
            "error": "DATABASE_URL not configured"
        }), 503
    
    conn = None
    try:
        # Połącz z bazą
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # Wykonaj testowe zapytanie
        cur.execute("SELECT version(), current_timestamp;")
        result = cur.fetchone()
        
        # Zamknij cursor
        cur.close()
        
        return jsonify({
            "ok": True,
            "database_version": result[0] if result else None,
            "server_time": str(result[1]) if result and len(result) > 1 else None
        })
        
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500
        
    finally:
        if conn:
            conn.close()

# ===================================
# ENDPOINT: /assistant
# Główny endpoint asystenta restauracji
# ===================================
@app.route("/assistant", methods=["POST"])
def assistant():
    """Główna funkcja asystenta restauracyjnego"""
    try:
        # Pobierz zapytanie użytkownika
        data = request.get_json(silent=True) or {}
        user_message = data.get("message", "")
        
        if not user_message:
            return jsonify({
                "ok": False,
                "error": "No message provided"
            }), 400
        
        # Sprawdź dostępność OpenAI
        if not client:
            return jsonify({
                "ok": False,
                "error": "OpenAI API key not configured"
            }), 503
        
        # System prompt dla asystenta restauracji
        system_prompt = """Jesteś profesjonalnym asystentem restauracji. 
        Pomagasz klientom w:
        - Wyborze dań z menu
        - Składaniu zamówień
        - Odpowiadaniu na pytania o składniki i alergeny
        - Rekomendowaniu dań
        - Informowaniu o czasie oczekiwania
        Bądź uprzejmy, profesjonalny i pomocny."""
        
        # Wygeneruj odpowiedź
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            temperature=0.7,
            max_tokens=500
        )
        
        assistant_reply = response.choices[0].message.content.strip()
        
        return jsonify({
            "ok": True,
            "user_message": user_message,
            "assistant_reply": assistant_reply,
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500

# ===================================
# ENDPOINT: /menu
# Pobieranie menu z bazy (przykład)
# ===================================
@app.route("/menu", methods=["GET"])
def get_menu():
    """Pobiera menu restauracji z bazy danych"""
    
    if not DATABASE_URL:
        # Zwróć przykładowe menu, jeśli baza nie jest skonfigurowana
        return jsonify({
            "ok": True,
            "menu": [
                {"id": 1, "name": "Pizza Margherita", "price": 25.00, "category": "pizza"},
                {"id": 2, "name": "Spaghetti Carbonara", "price": 28.00, "category": "pasta"},
                {"id": 3, "name": "Caesar Salad", "price": 22.00, "category": "salad"}
            ]
        })
    
    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Przykładowe zapytanie - dostosuj do swojej struktury bazy
        cur.execute("""
            SELECT id, name, price, category, description 
            FROM menu_items 
            WHERE available = true 
            ORDER BY category, name;
        """)
        
        items = cur.fetchall()
        cur.close()
        
        return jsonify({
            "ok": True,
            "menu": items
        })
        
    except Exception as e:
        # Jeśli tabela nie istnieje, zwróć przykładowe dane
        return jsonify({
            "ok": True,
            "menu": [
                {"id": 1, "name": "Pizza Margherita", "price": 25.00, "category": "pizza"},
                {"id": 2, "name": "Spaghetti Carbonara", "price": 28.00, "category": "pasta"}
            ],
            "note": "Using sample data - database table not found"
        })
        
    finally:
        if conn:
            conn.close()

# ===================================
# ENDPOINT: /
# Strona główna z dokumentacją API
# ===
