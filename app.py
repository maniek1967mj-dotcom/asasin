import os
import sys
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
import psycopg2
from psycopg2.extras import RealDictCursor
import json
from datetime import datetime

# ===================================
# KONFIGURACJA LOGOWANIA
# ===================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ===================================
# LOGI DEBUGOWANIA
# ===================================
logger.info(f"Python version: {sys.version}")
logger.info(f"Starting Flask app initialization...")
logger.info(f"PORT: {os.environ.get('PORT', 'not set')}")
logger.info(f"DATABASE_URL: {'set' if os.environ.get('DATABASE_URL') else 'not set'}")
logger.info(f"OPENAI_API_KEY: {'set' if os.environ.get('OPENAI_API_KEY') else 'not set'}")

# ===================================
# KONFIGURACJA ZMIENNYCH ŚRODOWISKOWYCH
# ===================================
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
DATABASE_URL = os.environ.get("DATABASE_URL")

# Inicjalizacja klienta OpenAI z obsługą błędów
client = None
if OPENAI_API_KEY:
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        logger.info("OpenAI client initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI client: {e}")
        client = None
else:
    logger.warning("OpenAI API key not found in environment variables")

# ===================================
# INICJALIZACJA FLASK
# ===================================
app = Flask(__name__)
CORS(app, origins="*", allow_headers="*", methods=["GET", "POST", "OPTIONS"])

# Dodaj konfigurację Flask
app.config['JSON_AS_ASCII'] = False
app.config['JSON_SORT_KEYS'] = False

# ===================================
# PODSTAWOWE ENDPOINTY
# ===================================
@app.route('/')
def index():
    return jsonify({
        "status": "API is running",
        "timestamp": datetime.now().isoformat(),
        "version": "1.1",
        "endpoints": [
            "/health",
            "/ping",
            "/test",
            "/api/chat",
            "/api/history",
            "/api/test-openai"
        ]
    })

@app.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/ping')
def ping():
    return jsonify({
        "status": "pong",
        "timestamp": datetime.now().isoformat(),
        "env_check": {
            "database": "configured" if DATABASE_URL else "missing",
            "openai": "configured" if OPENAI_API_KEY else "missing",
            "port": os.environ.get('PORT', 'not set')
        }
    })

@app.route('/test')
def test():
    return jsonify({
        "message": "Test successful!",
        "timestamp": datetime.now().isoformat()
    })

# ===================================
# FUNKCJE POMOCNICZE BAZY DANYCH
# ===================================
def get_db_connection():
    """Tworzy połączenie z bazą danych PostgreSQL"""
    if not DATABASE_URL:
        logger.warning("DATABASE_URL not configured")
        return None
    
    try:
        # Poprawka dla Railway PostgreSQL URLs
        db_url = DATABASE_URL
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
        
        conn = psycopg2.connect(
            db_url, 
            cursor_factory=RealDictCursor,
            connect_timeout=10,
            options='-c statement_timeout=30000'
        )
        return conn
    except psycopg2.OperationalError as e:
        logger.error(f"Database operational error: {e}")
        return None
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        return None

def init_database():
    """Inicjalizuje tabelę w bazie danych"""
    conn = get_db_connection()
    if not conn:
        logger.warning("Skipping database initialization - no connection")
        return False
    
    try:
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS conversations (
                id SERIAL PRIMARY KEY,
                user_message TEXT NOT NULL,
                assistant_message TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                model_used VARCHAR(100) DEFAULT 'gpt-4o-mini',
                tokens_used INTEGER DEFAULT 0
            )
        ''')
        conn.commit()
        logger.info("Database initialized successfully")
        return True
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

# ===================================
# ENDPOINT CHATBOTA
# ===================================
@app.route('/api/chat', methods=['POST', 'OPTIONS'])
def chat():
    """Endpoint do komunikacji z chatbotem"""
    # Obsługa CORS preflight
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    try:
        # Sprawdź czy OpenAI jest skonfigurowane
        if not client:
            logger.error("OpenAI client not available")
            return jsonify({
                "error": "OpenAI API key not configured",
                "details": "Please set OPENAI_API_KEY environment variable"
            }), 500
        
        # Pobierz wiadomość od użytkownika
        data = request.get_json(force=True)
        if not data:
            return jsonify({
                "error": "Invalid JSON data"
            }), 400
        
        user_message = data.get('message', '').strip()
        if not user_message:
            return jsonify({
                "error": "Message is required"
            }), 400
        
        logger.info(f"Processing chat message: {user_message[:50]}...")
        
        # Wywołaj OpenAI API
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant. Respond in the same language as the user's message."},
                    {"role": "user", "content": user_message}
                ],
                max_tokens=500,
                temperature=0.7,
                top_p=0.9
            )
            
            assistant_message = response.choices[0].message.content
            tokens_used = response.usage.total_tokens if hasattr(response, 'usage') else 0
            
            logger.info(f"OpenAI response received. Tokens used: {tokens_used}")
            
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            return jsonify({
                "error": "Failed to get response from OpenAI",
                "details": str(e)
            }), 500
        
        # Zapisz do bazy danych (jeśli połączona)
        conn = get_db_connection()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute(
                    '''INSERT INTO conversations 
                       (user_message, assistant_message, model_used, tokens_used) 
                       VALUES (%s, %s, %s, %s)''',
                    (user_message, assistant_message, "gpt-4o-mini", tokens_used)
                )
                conn.commit()
                logger.info("Conversation saved to database")
            except Exception as e:
                logger.error(f"Database save error: {e}")
                conn.rollback()
            finally:
                conn.close()
        
        return jsonify({
            "response": assistant_message,
            "tokens_used": tokens_used,
            "model": "gpt-4o-mini"
        })
        
    except Exception as e:
        logger.error(f"Chat endpoint error: {e}")
        return jsonify({
            "error": f"An unexpected error occurred",
            "details": str(e)
        }), 500

# ===================================
# ENDPOINT HISTORII
# ===================================
@app.route('/api/history', methods=['GET'])
def history():
    """Zwraca historię rozmów"""
    conn = get_db_connection()
    if not conn:
        logger.warning("Cannot fetch history - database not connected")
        return jsonify({
            "conversations": [],
            "error": "Database not connected"
        }), 200
    
    try:
        cur = conn.cursor()
        cur.execute('''
            SELECT id, user_message, assistant_message, timestamp, model_used, tokens_used 
            FROM conversations 
            ORDER BY timestamp DESC 
            LIMIT 20
        ''')
        rows = cur.fetchall()
        
        # Konwersja timestamp do ISO format
        for row in rows:
            if row.get('timestamp'):
                row['timestamp'] = row['timestamp'].isoformat()
        
        return jsonify({
            "conversations": rows,
            "count": len(rows)
        })
    except Exception as e:
        logger.error(f"History endpoint error: {e}")
        return jsonify({
            "conversations": [],
            "error": str(e)
        }), 500
    finally:
        conn.close()

# ===================================
# ENDPOINT TESTOWY DLA OPENAI
# ===================================
@app.route('/api/test-openai', methods=['GET'])
def test_openai():
    """Testuje połączenie z OpenAI"""
    if not client:
        return jsonify({
            "status": "error",
            "error": "OpenAI not configured",
            "details": "OPENAI_API_KEY environment variable not set"
        }), 500
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Say 'Hello, World!' in JSON format"}],
            max_tokens=50
        )
        
        return jsonify({
            "status": "success",
            "response": response.choices[0].message.content,
            "model": response.model,
            "tokens_used": response.usage.total_tokens if hasattr(response, 'usage') else 0
        })
    except Exception as e:
        logger.error(f"OpenAI test error: {e}")
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500

# ===================================
# ENDPOINT DO CZYSZCZENIA HISTORII
# ===================================
@app.route('/api/history/clear', methods=['DELETE'])
def clear_history():
    """Czyści historię rozmów"""
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database not connected"}), 500
    
    try:
        cur = conn.cursor()
        cur.execute('DELETE FROM conversations')
        deleted_count = cur.rowcount
        conn.commit()
        
        return jsonify({
            "status": "success",
            "deleted_count": deleted_count
        })
    except Exception as e:
        logger.error(f"Clear history error: {e}")
        conn.rollback()
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500
    finally:
        conn.close()

# ===================================
# ERROR HANDLERS
# ===================================
@app.errorhandler(404)
def not_found(e):
    return jsonify({
        "error": "Endpoint not found",
        "status": 404,
        "available_endpoints": ["/", "/health", "/api/chat", "/api/history"]
    }), 404

@app.errorhandler(500)
def server_error(e):
    logger.error(f"Internal server error: {e}")
    return jsonify({
        "error": "Internal server error",
        "status": 500
    }), 500

@app.errorhandler(Exception)
def handle_exception(e):
    logger.error(f"Unhandled exception: {e}")
    return jsonify({
        "error": "An unexpected error occurred",
        "details": str(e)
    }), 500

# ===================================
# INICJALIZACJA PRZY STARCIE
# ===================================
logger.info("Initializing database...")
db_initialized = init_database()
if db_initialized:
    logger.info("Database initialization completed successfully")
else:
    logger.warning("Database initialization failed or skipped")

# ===================================
# URUCHOMIENIE APLIKACJI
# ===================================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    logger.info(f"Starting Flask app on port {port}...")
    app.run(host='0.0.0.0', port=port, debug=False)
else:
    # Gdy uruchamiany przez Gunicorn
    logger.info("Flask app ready for Gunicorn")
