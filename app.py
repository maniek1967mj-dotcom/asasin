import os
import sys
import json
import time
import logging
from datetime import datetime
from typing import Optional, Dict, Any
import traceback

# Flask imports
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS

# Database imports
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool
import urllib.parse

# OpenAI imports
from openai import OpenAI

# Configure logging FIRST - before any other operations
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Log startup
logger.info("="*50)
logger.info("STARTING FLASK APPLICATION")
logger.info("="*50)
logger.info(f"Python version: {sys.version}")
logger.info(f"Current directory: {os.getcwd()}")

# Get PORT from environment - CRITICAL FOR RAILWAY
# Railway provides PORT dynamically - NEVER hardcode it!
PORT = os.environ.get('PORT')
if PORT:
    try:
        PORT = int(PORT)
        logger.info(f"PORT from environment: {PORT}")
    except ValueError:
        logger.error(f"Invalid PORT value: {PORT}, using default 5000")
        PORT = 5000
else:
    PORT = 5000
    logger.warning("PORT not found in environment, using default 5000")

# Validate port range
if not (1 <= PORT <= 65535):
    logger.error(f"PORT {PORT} out of valid range, using 5000")
    PORT = 5000

# Get other environment variables
DATABASE_URL = os.environ.get('DATABASE_URL', '')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
RAILWAY_ENVIRONMENT = os.environ.get('RAILWAY_ENVIRONMENT', 'development')

# Log environment status (without exposing sensitive data)
logger.info(f"PORT: {PORT}")
logger.info(f"DATABASE_URL: {'SET' if DATABASE_URL else 'NOT SET'}")
logger.info(f"OPENAI_API_KEY: {'SET' if OPENAI_API_KEY else 'NOT SET'}")
logger.info(f"RAILWAY_ENVIRONMENT: {RAILWAY_ENVIRONMENT}")

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Global variables for services
db_pool = None
openai_client = None

def fix_database_url(url: str) -> str:
    """Convert postgres:// to postgresql:// for compatibility"""
    if url and url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql://', 1)
        logger.info("Converted database URL from postgres:// to postgresql://")
    return url

def create_db_pool(max_retries: int = 3) -> Optional[psycopg2.pool.SimpleConnectionPool]:
    """Create PostgreSQL connection pool with retry logic"""
    global DATABASE_URL
    
    if not DATABASE_URL:
        logger.warning("DATABASE_URL not set, skipping database initialization")
        return None
    
    # Fix URL format
    DATABASE_URL = fix_database_url(DATABASE_URL)
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Attempting to create database connection pool (attempt {attempt + 1}/{max_retries})")
            
            # Parse database URL
            result = urllib.parse.urlparse(DATABASE_URL)
            
            pool = psycopg2.pool.SimpleConnectionPool(
                1, 20,  # min and max connections
                database=result.path[1:],
                user=result.username,
                password=result.password,
                host=result.hostname,
                port=result.port
            )
            
            # Test connection
            conn = pool.getconn()
            conn.close()
            pool.putconn(conn)
            
            logger.info("✓ Database connection pool created successfully")
            return pool
            
        except Exception as e:
            logger.error(f"Database connection attempt {attempt + 1} failed: {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                logger.error("Failed to create database connection pool after all retries")
                return None

def init_database():
    """Initialize database tables"""
    if not db_pool:
        logger.warning("Database pool not available, skipping table initialization")
        return
    
    conn = None
    cursor = None
    try:
        conn = db_pool.getconn()
        cursor = conn.cursor()
        
        # Create conversations table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(255),
                message TEXT NOT NULL,
                response TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                model VARCHAR(100),
                tokens_used INTEGER,
                error TEXT
            )
        """)
        
        # Create health_checks table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS health_checks (
                id SERIAL PRIMARY KEY,
                status VARCHAR(50),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                details JSONB
            )
        """)
        
        conn.commit()
        logger.info("✓ Database tables initialized successfully")
        
    except Exception as e:
        logger.error(f"Failed to initialize database tables: {str(e)}")
        if conn:
            conn.rollback()
    finally:
        if cursor:
            cursor.close()
        if conn:
            db_pool.putconn(conn)

def init_openai_client() -> Optional[OpenAI]:
    """Initialize OpenAI client with verification"""
    if not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not set, OpenAI features will be disabled")
        return None
    
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        
        # Test the API key
        models = client.models.list()
        logger.info("✓ OpenAI client initialized and verified successfully")
        return client
        
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI client: {str(e)}")
        return None

# Initialize services
logger.info("Initializing services...")
db_pool = create_db_pool()
openai_client = init_openai_client()
logger.info("✓ Services initialization completed")

# Initialize database tables
if db_pool:
    logger.info("Initializing database tables...")
    init_database()
    logger.info("✓ Database initialization completed")

# Health check endpoint - CRITICAL FOR RAILWAY
@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint for Railway"""
    health_status = {
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'port': PORT,
        'environment': RAILWAY_ENVIRONMENT,
        'services': {
            'database': 'connected' if db_pool else 'disconnected',
            'openai': 'connected' if openai_client else 'disconnected'
        }
    }
    
    # Test database connection
    if db_pool:
        conn = None
        try:
            conn = db_pool.getconn()
            cursor = conn.cursor()
            cursor.execute('SELECT 1')
            cursor.close()
            db_pool.putconn(conn)
        except Exception as e:
            health_status['services']['database'] = f'error: {str(e)}'
            health_status['status'] = 'degraded'
            if conn:
                db_pool.putconn(conn)
    
    status_code = 200 if health_status['status'] == 'healthy' else 503
    return jsonify(health_status), status_code

@app.route('/ping', methods=['GET'])
def ping():
    """Simple ping endpoint"""
    return jsonify({'pong': True, 'timestamp': datetime.utcnow().isoformat()})

@app.route('/status', methods=['GET'])
def status():
    """Detailed status endpoint"""
    return jsonify({
        'application': 'Flask ChatGPT App',
        'version': '1.0.0',
        'status': 'running',
        'port': PORT,
        'environment': RAILWAY_ENVIRONMENT,
        'timestamp': datetime.utcnow().isoformat(),
        'python_version': sys.version,
        'services': {
            'database': {
                'connected': bool(db_pool),
                'url_set': bool(DATABASE_URL)
            },
            'openai': {
                'connected': bool(openai_client),
                'api_key_set': bool(OPENAI_API_KEY)
            }
        }
    })

@app.route('/')
def home():
    """Home page"""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Flask ChatGPT App</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                max-width: 800px;
                margin: 0 auto;
                padding: 20px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
            }
            .container {
                background: rgba(255, 255, 255, 0.1);
                border-radius: 10px;
                padding: 30px;
                backdrop-filter: blur(10px);
            }
            h1 { color: white; }
            .status { 
                background: rgba(255, 255, 255, 0.2);
                padding: 15px;
                border-radius: 5px;
                margin: 10px 0;
            }
            .endpoint {
                background: rgba(0, 0, 0, 0.2);
                padding: 10px;
                margin: 5px 0;
                border-radius: 3px;
                font-family: monospace;
            }
            .online { color: #4ade80; }
            .offline { color: #f87171; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🚀 Flask ChatGPT App on Railway</h1>
            <div class="status">
                <h2>System Status</h2>
                <p>Port: <strong>{{ port }}</strong></p>
                <p>Environment: <strong>{{ environment }}</strong></p>
                <p>Database: <strong class="{{ 'online' if db_status else 'offline' }}">
                    {{ 'Connected' if db_status else 'Not Connected' }}
                </strong></p>
                <p>OpenAI API: <strong class="{{ 'online' if openai_status else 'offline' }}">
                    {{ 'Connected' if openai_status else 'Not Connected' }}
                </strong></p>
            </div>
            <div class="status">
                <h2>Available Endpoints</h2>
                <div class="endpoint">GET /health - Health check</div>
                <div class="endpoint">GET /ping - Simple ping</div>
                <div class="endpoint">GET /status - Detailed status</div>
                <div class="endpoint">POST /chat - Chat with AI</div>
            </div>
        </div>
    </body>
    </html>
    """
    return render_template_string(html, 
        port=PORT,
        environment=RAILWAY_ENVIRONMENT,
        db_status=bool(db_pool),
        openai_status=bool(openai_client)
    )

@app.route('/chat', methods=['POST'])
def chat():
    """Chat endpoint for OpenAI integration"""
    try:
        # Check if OpenAI is available
        if not openai_client:
            return jsonify({
                'error': 'OpenAI service not available',
                'message': 'Please configure OPENAI_API_KEY'
            }), 503
        
        # Get request data
        data = request.get_json()
        if not data or 'message' not in data:
            return jsonify({'error': 'No message provided'}), 400
        
        user_message = data['message']
        user_id = data.get('user_id', 'anonymous')
        model = data.get('model', 'gpt-3.5-turbo')
        
        logger.info(f"Chat request from user {user_id}: {user_message[:50]}...")
        
        # Call OpenAI API
        try:
            response = openai_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": user_message}
                ],
                max_tokens=1000,
                temperature=0.7
            )
            
            ai_response = response.choices[0].message.content
            tokens_used = response.usage.total_tokens if response.usage else 0
            
            # Store in database if available
            if db_pool:
                conn = None
                try:
                    conn = db_pool.getconn()
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO conversations (user_id, message, response, model, tokens_used)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (user_id, user_message, ai_response, model, tokens_used))
                    conn.commit()
                    cursor.close()
                except Exception as e:
                    logger.error(f"Failed to store conversation: {str(e)}")
                    if conn:
                        conn.rollback()
                finally:
                    if conn:
                        db_pool.putconn(conn)
            
            return jsonify({
                'response': ai_response,
                'tokens_used': tokens_used,
                'model': model
            })
            
        except Exception as e:
            logger.error(f"OpenAI API error: {str(e)}")
            
            # Store error in database if available
            if db_pool:
                conn = None
                try:
                    conn = db_pool.getconn()
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO conversations (user_id, message, response, model, error)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (user_id, user_message, '', model, str(e)))
                    conn.commit()
                    cursor.close()
                except Exception as db_error:
                    logger.error(f"Failed to store error: {str(db_error)}")
                    if conn:
                        conn.rollback()
                finally:
                    if conn:
                        db_pool.putconn(conn)
            
            return jsonify({
                'error': 'Failed to get AI response',
                'details': str(e)
            }), 500
            
    except Exception as e:
        logger.error(f"Chat endpoint error: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            'error': 'Internal server error',
            'details': str(e)
        }), 500

@app.errorhandler(404)
def not_found(e):
    """404 error handler"""
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def server_error(e):
    """500 error handler"""
    logger.error(f"Internal server error: {str(e)}")
    return jsonify({'error': 'Internal server error'}), 500

# CRITICAL: This is for running locally - Gunicorn will import 'app'
if __name__ == '__main__':
    # This block only runs when executing the script directly
    # Gunicorn imports the 'app' object, so this won't run in production
    logger.info("="*50)
    logger.info(f"STARTING DEVELOPMENT SERVER ON PORT {PORT}")
    logger.info("="*50)
    app.run(
        host='0.0.0.0',
        port=PORT,
        debug=(RAILWAY_ENVIRONMENT != 'production')
    )
else:
    # This runs when imported by Gunicorn
    logger.info("="*50)
    logger.info(f"FLASK APP READY FOR GUNICORN - Port from env: {PORT}")
    logger.info("="*50)
