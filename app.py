import os
import sys
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from dotenv import load_dotenv

# ===================================
# ŁADOWANIE ZMIENNYCH ŚRODOWISKOWYCH
# ===================================
load_dotenv()  # Załaduj zmienne z .env (dla lokalnego testowania)

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
# INFORMACJE STARTOWE
# ===================================
logger.info("=" * 50)
logger.info("STARTING FLASK APPLICATION")
logger.info("=" * 50)
logger.info(f"Python version: {sys.version}")
logger.info(f"Current directory: {os.getcwd()}")
logger.info(f"PORT: {os.environ.get('PORT', 'NOT SET - will use 8080')}")
logger.info(f"DATABASE_URL: {'SET' if os.environ.get('DATABASE_URL') else 'NOT SET'}")
logger.info(f"OPENAI_API_KEY: {'SET' if os.environ.get('OPENAI_API_KEY') else 'NOT SET'}")
logger.info(f"RAILWAY_ENVIRONMENT: {os.environ.get('RAILWAY_ENVIRONMENT', 'NOT RAILWAY')}")

# ===================================
# KONFIGURACJA ZMIENNYCH ŚRODOWISKOWYCH
# ===================================
PORT = int(os.environ.get('PORT', 8080))
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
DATABASE_URL = os.environ.get('DATABASE_URL')

# Poprawka dla Railway PostgreSQL URLs
if DATABASE_URL and DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
    logger.info("Converted postgres:// to postgresql:// for compatibility")

# ===================================
# INICJALIZACJA OPENAI CLIENT
# ===================================
client = None
if OPENAI_API_KEY:
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        # Test połączenia
        test_response = client.models.list()
        logger.info("✓ OpenAI client initialized and verified successfully")
    except Exception as e:
        logger.error(f"✗ Failed to initialize OpenAI client: {e}")
        client = None
else:
    logger.warning("⚠ OpenAI API key not found - chat functionality will be disabled")

# ===================================
# INICJALIZACJA FLASK
# ===================================
app = Flask(__name__)

# Konfiguracja CORS - bardziej liberalna dla Railway
CORS(app, 
     origins="*",
     allow_headers=["Content-Type", "Authorization"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
     supports_credentials=True)

# Konfiguracja Flask
app.config['JSON_AS_ASCII'] = False
app.config['JSON_SORT_KEYS'] = False
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = True

logger.info("✓ Flask app initialized")

# ===================================
# FUNKCJE POMOCNICZE BAZY DANYCH
# ===================================
def get_db_connection():
    """Tworzy połączenie z bazą danych PostgreSQL z retry logic"""
    if not DATABASE_URL:
        logger.debug("DATABASE_URL not configured")
        return None
    
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            conn = psycopg2.connect(
                DATABASE_URL,
                cursor_factory=RealDictCursor,
                connect_timeout=10,
                options='-c statement_timeout=30000',
                keepalives=1,
                keepalives_idle=30,
                keepalives_interval=10,
                keepalives_count=5
            )
            logger.debug("Database connection established")
            return conn
        except psycopg2.OperationalError as e:
            retry_count += 1
            logger.warning(f"Database connection attempt {retry_count}/{max_retries} failed: {e}")
            if retry_count >= max_retries:
                logger.error("Failed to connect to database after all retries")
                return None
        except Exception as e:
            logger.error(f"Unexpected database connection error: {e}")
            return None
    
    return None

def init_database():
    """Inicjalizuje tabelę w bazie danych"""
    if not DATABASE_URL:
        logger.warning("⚠ Skipping database initialization - DATABASE_URL not set")
        return False
    
    conn = get_db_connection()
    if not conn:
        logger.error("✗ Could not establish database connection for initialization")
        return False
    
    try:
        cur = conn.cursor()
        
        # Tworzenie tabeli conversations
        cur.execute('''
            CREATE TABLE IF NOT EXISTS conversations (
                id SERIAL PRIMARY KEY,
                user_message TEXT NOT NULL,
                assistant_message TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                model_used VARCHAR(100) DEFAULT 'gpt-4o-mini',
                tokens_used INTEGER DEFAULT 0,
                ip_address VARCHAR(45),
                user_agent TEXT
            )
        ''')
        
        # Tworzenie indeksu na timestamp dla szybszego sortowania
        cur.execute('''
            CREATE INDEX IF NOT EXISTS idx_conversations_timestamp 
            ON conversations(timestamp DESC)
        ''')
        
        conn.commit()
        logger.info("✓ Database tables initialized successfully")
        return True
        
    except Exception as e:
        logger.error(f"✗ Database initialization error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

# ===================================
# PODSTAWOWE ENDPOINTY
# ===================================
@app.route('/')
def index():
    """Główny endpoint z informacjami o API"""
    return jsonify({
        "service": "Flask Chat API",
        "status": "running",
        "timestamp": datetime.utcnow().isoformat() + 'Z',
        "version": "2.0",
        "environment": os.environ.get('RAILWAY_ENVIRONMENT', 'local'),
        "endpoints": {
            "health": "/health",
            "ping": "/ping", 
            "chat": "/api/chat",
            "history": "/api/history",
            "test_openai": "/api/test-openai",
            "system_status": "/api/status"
        }
    })

@app.route('/health')
def health():
    """Health check endpoint dla Railway"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat() + 'Z'
    }), 200

@app.route('/ping')
def ping():
    """Quick ping endpoint"""
    return jsonify({
        "pong": True,
        "timestamp": datetime.utcnow().isoformat() + 'Z'
    }), 200

@app.route('/api/status')
def system_status():
    """Szczegółowy status systemu"""
    db_status = "connected" if get_db_connection() else "disconnected"
    
    return jsonify({
        "status": "operational",
        "timestamp": datetime.utcnow().isoformat() + 'Z',
        "components": {
            "flask": "running",
            "database": db_status,
            "openai": "configured" if client else "not configured",
            "port": PORT
        },
        "environment": {
            "railway": os.environ.get('RAILWAY_ENVIRONMENT', 'not on railway'),
            "python_version": sys.version.split()[0]
        }
    })

# ===================================
# ENDPOINT CHATBOTA  
# ===================================
@app.route('/api/chat', methods=['POST', 'OPTIONS'])
def chat():
    """Główny endpoint do komunikacji z chatbotem"""
    # Obsługa CORS preflight
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        # Sprawdzenie konfiguracji OpenAI
        if not client:
            logger.error("Chat request received but OpenAI not configured")
            return jsonify({
                "error": "Chat service unavailable",
                "message": "OpenAI API is not configured. Please contact administrator."
            }), 503
        
        # Parsowanie danych
        data = request.get_json(force=True)
        if not data:
            return jsonify({
                "error": "Invalid request",
                "message": "Request body must be valid JSON"
            }), 400
        
        user_message = data.get('message', '').strip()
        if not user_message:
            return jsonify({
                "error": "Invalid request", 
                "message": "Message field is required and cannot be empty"
            }), 400
        
        # Logowanie request info
        client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        user_agent = request.headers.get('User-Agent', 'Unknown')
        logger.info(f"Chat request from {client_ip}: '{user_message[:50]}...'")
        
        # Wywołanie OpenAI API
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system", 
                        "content": "You are a helpful assistant. Respond concisely and clearly."
                    },
                    {
                        "role": "user", 
                        "content": user_message
                    }
                ],
                max_tokens=500,
                temperature=0.7,
                top_p=0.9,
                frequency_penalty=0.0,
                presence_penalty=0.0
            )
            
            assistant_message = response.choices[0].message.content
            tokens_used = response.usage.total_tokens if response.usage else 0
            model_used = response.model
            
            logger.info(f"OpenAI response successful. Tokens: {tokens_used}")
            
        except Exception as e:
            logger.error(f"OpenAI API call failed: {e}")
            return jsonify({
                "error": "AI service error",
                "message": "Failed to generate response. Please try again."
            }), 500
        
        # Zapis do bazy danych (opcjonalny - nie blokuje odpowiedzi)
        try:
            conn = get_db_connection()
            if conn:
                cur = conn.cursor()
                cur.execute('''
                    INSERT INTO conversations 
                    (user_message, assistant_message, model_used, tokens_used, ip_address, user_agent) 
                    VALUES (%s, %s, %s, %s, %s, %s)
                ''', (user_message, assistant_message, model_used, tokens_used, client_ip, user_agent))
                conn.commit()
                conn.close()
                logger.debug("Conversation saved to database")
        except Exception as e:
            logger.warning(f"Failed to save conversation to database: {e}")
            # Nie zwracamy błędu - zapis do bazy jest opcjonalny
        
        # Zwróć odpowiedź
        return jsonify({
            "response": assistant_message,
            "model": model_used,
            "tokens": tokens_used,
            "timestamp": datetime.utcnow().isoformat() + 'Z'
        }), 200
        
    except Exception as e:
        logger.error(f"Unexpected error in chat endpoint: {e}", exc_info=True)
        return jsonify({
            "error": "Internal server error",
            "message": "An unexpected error occurred. Please try again."
        }), 500

# ===================================
# ENDPOINT HISTORII
# ===================================
@app.route('/api/history', methods=['GET'])
def history():
    """Zwraca historię konwersacji"""
    try:
        limit = request.args.get('limit', 20, type=int)
        limit = min(limit, 100)  # Maksymalnie 100 rekordów
        
        conn = get_db_connection()
        if not conn:
            return jsonify({
                "conversations": [],
                "message": "Database not available"
            }), 200
        
        cur = conn.cursor()
        cur.execute('''
            SELECT id, user_message, assistant_message, 
                   timestamp, model_used, tokens_used 
            FROM conversations 
            ORDER BY timestamp DESC 
            LIMIT %s
        ''', (limit,))
        
        rows = cur.fetchall()
        conn.close()
        
        # Formatowanie timestamp
        for row in rows:
            if row.get('timestamp'):
                row['timestamp'] = row['timestamp'].isoformat() + 'Z'
        
        return jsonify({
            "conversations": rows,
            "count": len(rows),
            "limit": limit
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching history: {e}")
        return jsonify({
            "conversations": [],
            "error": "Failed to fetch history"
        }), 500

# ===================================
# ENDPOINT TESTOWY OPENAI
# ===================================
@app.route('/api/test-openai', methods=['GET'])
def test_openai():
    """Testuje połączenie z OpenAI"""
    if not client:
        return jsonify({
            "status": "error",
            "message": "OpenAI not configured"
        }), 503
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": "Respond with 'OK' if you receive this."
            }],
            max_tokens=10
        )
        
        return jsonify({
            "status": "success",
            "response": response.choices[0].message.content,
            "model": response.model
        }), 200
        
    except Exception as e:
        logger.error(f"OpenAI test failed: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

# ===================================
# ERROR HANDLERS
# ===================================
@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "error": "Not found",
        "message": "The requested endpoint does not exist",
        "status": 404
    }), 404

@app.errorhandler(500) 
def internal_error(error):
    logger.error(f"Internal server error: {error}")
    return jsonify({
        "error": "Internal server error",
        "message": "An internal error occurred",
        "status": 500
    }), 500

@app.errorhandler(Exception)
def handle_exception(e):
    logger.error(f"Unhandled exception: {e}", exc_info=True)
    return jsonify({
        "error": "Server error",
        "message": "An unexpected error occurred",
        "status": 500
    }), 500

# ===================================
# INICJALIZACJA APLIKACJI
# ===================================
logger.info("Initializing database...")
if init_database():
    logger.info("✓ Database initialization completed")
else:
    logger.warning("⚠ Database initialization skipped or failed")

logger.info("=" * 50)
logger.info(f"FLASK APP READY - Port: {PORT}")
logger.info("=" * 50)

# ===================================
# URUCHOMIENIE APLIKACJI
# ===================================
if __name__ == '__main__':
    logger.info(f"Running Flask development server on port {PORT}")
    app.run(host='0.0.0.0', port=PORT, debug=False)
else:
    logger.info(f"Flask app ready for Gunicorn on port {PORT}")
