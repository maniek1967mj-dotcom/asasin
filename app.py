import os
import sys
import json
import logging
import time
from datetime import datetime, timedelta
from functools import wraps
import traceback
from flask import Flask, request, jsonify
from flask_cors import CORS
import jwt
import bcrypt
import psycopg2
from psycopg2 import pool, OperationalError
from psycopg2.extras import RealDictCursor
from openai import OpenAI
from werkzeug.exceptions import HTTPException

# ==================================================
# LOGGING CONFIGURATION
# ==================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('app')

# --- Begin: OpenAI version logging (added for debugging) ---
try:
    import openai as _openai
    ver = getattr(_openai, "__version__", "unknown")
    logger.info(
        f"OpenAI module: package={getattr(_openai, '__package__', None)}, "
        f"file={getattr(_openai, '__file__', None)}, version={ver}"
    )
except Exception as e:
    import traceback
    logger.error(f"Failed to check OpenAI version: {e}")
    logger.error(traceback.format_exc())
# --- End: OpenAI version logging ---

# ==================================================
# ENVIRONMENT VARIABLES
# ==================================================
logger.info("==================================================")
logger.info("STARTING FLASK APPLICATION")
logger.info("==================================================")
logger.info(f"Python version: {sys.version}")
logger.info(f"Current directory: {os.getcwd()}")

# Port handling - Railway provides PORT dynamically
PORT = os.environ.get('PORT')
if PORT:
    PORT = int(PORT)
    logger.info(f"PORT from environment: {PORT}")
else:
    PORT = 8080
    logger.info(f"PORT not found in environment, using default: {PORT}")

# Database configuration
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    # Fix postgres:// to postgresql:// for SQLAlchemy compatibility
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
        logger.info("Fixed DATABASE_URL format: postgres:// -> postgresql://")
    logger.info("DATABASE_URL: SET")
else:
    logger.warning("DATABASE_URL: NOT SET - Database features will be disabled")

# OpenAI configuration
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
if OPENAI_API_KEY:
    logger.info("OPENAI_API_KEY: SET")
else:
    logger.warning("OPENAI_API_KEY: NOT SET - AI features will be disabled")

# JWT configuration
JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'your-secret-key-change-in-production')
if JWT_SECRET_KEY == 'your-secret-key-change-in-production':
    logger.warning("JWT_SECRET_KEY: Using default key - CHANGE IN PRODUCTION!")

# Railway environment
RAILWAY_ENVIRONMENT = os.environ.get('RAILWAY_ENVIRONMENT', 'development')
logger.info(f"RAILWAY_ENVIRONMENT: {RAILWAY_ENVIRONMENT}")

# ==================================================
# FLASK APP INITIALIZATION
# ==================================================
app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

# CORS configuration
CORS(app, resources={
    r"/*": {
        "origins": ["*"],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})

# ==================================================
# DATABASE CONNECTION POOL
# ==================================================
db_pool = None

def create_db_pool(retries=3, delay=2):
    """Create PostgreSQL connection pool with retry logic"""
    global db_pool
    
    if not DATABASE_URL:
        logger.warning("Database URL not configured - skipping pool creation")
        return None
    
    for attempt in range(1, retries + 1):
        try:
            logger.info(f"Creating database connection pool (attempt {attempt}/{retries})")
            
            db_pool = psycopg2.pool.ThreadedConnectionPool(
                1,  # minconn
                20, # maxconn
                DATABASE_URL,
                cursor_factory=RealDictCursor
            )
            
            # Test connection
            conn = db_pool.getconn()
            conn.close()
            db_pool.putconn(conn)
            
            logger.info("✓ Database connection pool created successfully")
            return db_pool
            
        except Exception as e:
            logger.error(f"Database connection attempt {attempt} failed: {str(e)}")
            if attempt < retries:
                logger.info(f"Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                logger.error("✗ Failed to create database connection pool after all retries")
                return None

def get_db_connection():
    """Get a database connection from the pool"""
    if not db_pool:
        raise Exception("Database pool not initialized")
    return db_pool.getconn()

def release_db_connection(conn):
    """Release a database connection back to the pool"""
    if db_pool and conn:
        db_pool.putconn(conn)

# ==================================================
# OPENAI CLIENT
# ==================================================
openai_client = None

def initialize_openai_client():
    """Initialize OpenAI client"""
    global openai_client
    
    if not OPENAI_API_KEY:
        logger.warning("OpenAI API key not configured - AI features disabled")
        return None
    
    try:
        logger.info("=== DEBUG: About to initialize OpenAI client ===")
        logger.info(f"DEBUG: OpenAI class: {OpenAI}")
        logger.info(f"DEBUG: OpenAI.__init__ signature: {OpenAI.__init__}")
        
        # Initialize with ONLY api_key
        openai_client = OpenAI(api_key=OPENAI_API_KEY)
        
        logger.info("✓ OpenAI client initialized successfully")
        logger.info(f"DEBUG: Client type: {type(openai_client)}")
        return openai_client
        
    except TypeError as te:
        logger.error(f"TypeError during OpenAI initialization: {str(te)}")
        logger.error(f"Full traceback:")
        import traceback
        logger.error(traceback.format_exc())
        return None
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI client: {str(e)}")
        logger.error(f"Exception type: {type(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return None
# ==================================================
# DATABASE INITIALIZATION
# ==================================================
def initialize_database():
    """Create database tables if they don't exist"""
    if not db_pool:
        logger.warning("Database pool not available - skipping table initialization")
        return False
    
    conn = None
    cursor = None
    
    try:
        logger.info("Initializing database tables...")
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Create users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(255) UNIQUE NOT NULL,
                email VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create chats table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                title VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create messages table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                chat_id INTEGER REFERENCES chats(id) ON DELETE CASCADE,
                role VARCHAR(50) NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_chats_user_id ON chats(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages(chat_id)")
        
        conn.commit()
        logger.info("✓ Database tables initialized successfully")
        return True
        
    except Exception as e:
        logger.error(f"Failed to initialize database: {str(e)}")
        if conn:
            conn.rollback()
        return False
    finally:
        if cursor:
            cursor.close()
        if conn:
            release_db_connection(conn)

# ==================================================
# JWT AUTHENTICATION
# ==================================================
def generate_token(user_id):
    """Generate JWT token"""
    payload = {
        'user_id': user_id,
        'exp': datetime.utcnow() + timedelta(hours=24)
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm='HS256')

def verify_token(token):
    """Verify JWT token"""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=['HS256'])
        return payload['user_id']
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def token_required(f):
    """Decorator for routes that require authentication"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        
        if not token:
            return jsonify({'error': 'Token missing'}), 401
        
        try:
            if token.startswith('Bearer '):
                token = token.split(' ')[1]
            
            user_id = verify_token(token)
            if not user_id:
                return jsonify({'error': 'Invalid or expired token'}), 401
            
            return f(user_id, *args, **kwargs)
        except Exception as e:
            logger.error(f"Token verification error: {str(e)}")
            return jsonify({'error': 'Invalid token'}), 401
    
    return decorated

# ==================================================
# HEALTH CHECK ENDPOINTS
# ==================================================
@app.route('/', methods=['GET'])
def root():
    """Root endpoint"""
    return jsonify({
        'status': 'healthy',
        'message': 'Flask API is running',
        'environment': RAILWAY_ENVIRONMENT,
        'timestamp': datetime.utcnow().isoformat()
    })

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    health_status = {
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'environment': RAILWAY_ENVIRONMENT,
        'services': {
            'database': 'connected' if db_pool else 'disconnected',
            'openai': 'connected' if openai_client else 'disconnected'
        }
    }
    
    # Test database connection
    if db_pool:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT 1')
            cursor.close()
            release_db_connection(conn)
            health_status['services']['database'] = 'healthy'
        except Exception as e:
            health_status['services']['database'] = f'unhealthy: {str(e)}'
            health_status['status'] = 'degraded'
    
    return jsonify(health_status)

@app.route('/ping', methods=['GET'])
def ping():
    """Simple ping endpoint"""
    return jsonify({'pong': True, 'timestamp': datetime.utcnow().isoformat()})

@app.route('/status', methods=['GET'])
def status():
    """Detailed status endpoint"""
    return jsonify({
        'status': 'running',
        'environment': {
            'railway': RAILWAY_ENVIRONMENT,
            'port': PORT,
            'database_configured': bool(DATABASE_URL),
            'openai_configured': bool(OPENAI_API_KEY)
        },
        'version': '1.0.0',
        'timestamp': datetime.utcnow().isoformat()
    })

# ==================================================
# USER AUTHENTICATION ENDPOINTS
# ==================================================
@app.route('/api/register', methods=['POST'])
def register():
    """User registration endpoint"""
    if not db_pool:
        return jsonify({'error': 'Database not available'}), 503
    
    conn = None
    cursor = None
    
    try:
        data = request.json
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')
        
        if not all([username, email, password]):
            return jsonify({'error': 'Missing required fields'}), 400
        
        # Hash password
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if user exists
        cursor.execute(
            "SELECT id FROM users WHERE username = %s OR email = %s",
            (username, email)
        )
        if cursor.fetchone():
            return jsonify({'error': 'User already exists'}), 409
        
        # Create user
        cursor.execute(
            """INSERT INTO users (username, email, password_hash) 
               VALUES (%s, %s, %s) RETURNING id""",
            (username, email, password_hash)
        )
        user_id = cursor.fetchone()['id']
        conn.commit()
        
        # Generate token
        token = generate_token(user_id)
        
        return jsonify({
            'message': 'User registered successfully',
            'user_id': user_id,
            'token': token
        }), 201
        
    except Exception as e:
        logger.error(f"Registration error: {str(e)}")
        if conn:
            conn.rollback()
        return jsonify({'error': 'Registration failed'}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            release_db_connection(conn)

@app.route('/api/login', methods=['POST'])
def login():
    """User login endpoint"""
    if not db_pool:
        return jsonify({'error': 'Database not available'}), 503
    
    conn = None
    cursor = None
    
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')
        
        if not all([username, password]):
            return jsonify({'error': 'Missing credentials'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get user
        cursor.execute(
            "SELECT id, password_hash FROM users WHERE username = %s OR email = %s",
            (username, username)
        )
        user = cursor.fetchone()
        
        if not user:
            return jsonify({'error': 'Invalid credentials'}), 401
        
        # Verify password
        if not bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
            return jsonify({'error': 'Invalid credentials'}), 401
        
        # Generate token
        token = generate_token(user['id'])
        
        return jsonify({
            'message': 'Login successful',
            'user_id': user['id'],
            'token': token
        })
        
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        return jsonify({'error': 'Login failed'}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            release_db_connection(conn)

# ==================================================
# CHAT ENDPOINTS
# ==================================================
@app.route('/api/chats', methods=['GET'])
@token_required
def get_chats(user_id):
    """Get user's chats"""
    if not db_pool:
        return jsonify({'error': 'Database not available'}), 503
    
    conn = None
    cursor = None
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            """SELECT id, title, created_at, updated_at 
               FROM chats 
               WHERE user_id = %s 
               ORDER BY updated_at DESC""",
            (user_id,)
        )
        chats = cursor.fetchall()
        
        return jsonify({'chats': chats})
        
    except Exception as e:
        logger.error(f"Get chats error: {str(e)}")
        return jsonify({'error': 'Failed to fetch chats'}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            release_db_connection(conn)

@app.route('/api/chats', methods=['POST'])
@token_required
def create_chat(user_id):
    """Create a new chat"""
    if not db_pool:
        return jsonify({'error': 'Database not available'}), 503
    
    conn = None
    cursor = None
    
    try:
        data = request.json or {}
        title = data.get('title', 'New Chat')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            """INSERT INTO chats (user_id, title) 
               VALUES (%s, %s) 
               RETURNING id, title, created_at, updated_at""",
            (user_id, title)
        )
        chat = cursor.fetchone()
        conn.commit()
        
        return jsonify({'chat': chat}), 201
        
    except Exception as e:
        logger.error(f"Create chat error: {str(e)}")
        if conn:
            conn.rollback()
        return jsonify({'error': 'Failed to create chat'}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            release_db_connection(conn)

@app.route('/api/chats/<int:chat_id>', methods=['DELETE'])
@token_required
def delete_chat(user_id, chat_id):
    """Delete a chat"""
    if not db_pool:
        return jsonify({'error': 'Database not available'}), 503
    
    conn = None
    cursor = None
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Verify ownership
        cursor.execute(
            "SELECT id FROM chats WHERE id = %s AND user_id = %s",
            (chat_id, user_id)
        )
        if not cursor.fetchone():
            return jsonify({'error': 'Chat not found'}), 404
        
        # Delete chat (messages will cascade)
        cursor.execute("DELETE FROM chats WHERE id = %s", (chat_id,))
        conn.commit()
        
        return jsonify({'message': 'Chat deleted successfully'})
        
    except Exception as e:
        logger.error(f"Delete chat error: {str(e)}")
        if conn:
            conn.rollback()
        return jsonify({'error': 'Failed to delete chat'}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            release_db_connection(conn)

# ==================================================
# MESSAGE ENDPOINTS
# ==================================================
@app.route('/api/chats/<int:chat_id>/messages', methods=['GET'])
@token_required
def get_messages(user_id, chat_id):
    """Get messages for a chat"""
    if not db_pool:
        return jsonify({'error': 'Database not available'}), 503
    
    conn = None
    cursor = None
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Verify ownership
        cursor.execute(
            "SELECT id FROM chats WHERE id = %s AND user_id = %s",
            (chat_id, user_id)
        )
        if not cursor.fetchone():
            return jsonify({'error': 'Chat not found'}), 404
        
        # Get messages
        cursor.execute(
            """SELECT id, role, content, created_at 
               FROM messages 
               WHERE chat_id = %s 
               ORDER BY created_at ASC""",
            (chat_id,)
        )
        messages = cursor.fetchall()
        
        return jsonify({'messages': messages})
        
    except Exception as e:
        logger.error(f"Get messages error: {str(e)}")
        return jsonify({'error': 'Failed to fetch messages'}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            release_db_connection(conn)

@app.route('/api/chats/<int:chat_id>/messages', methods=['POST'])
@token_required
def send_message(user_id, chat_id):
    """Send a message and get AI response"""
    if not db_pool:
        return jsonify({'error': 'Database not available'}), 503
    
    conn = None
    cursor = None
    
    try:
        data = request.json
        message_content = data.get('message')
        
        if not message_content:
            return jsonify({'error': 'Message content required'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Verify ownership
        cursor.execute(
            "SELECT id, title FROM chats WHERE id = %s AND user_id = %s",
            (chat_id, user_id)
        )
        chat = cursor.fetchone()
        if not chat:
            return jsonify({'error': 'Chat not found'}), 404
        
        # Save user message
        cursor.execute(
            """INSERT INTO messages (chat_id, role, content) 
               VALUES (%s, %s, %s) 
               RETURNING id, role, content, created_at""",
            (chat_id, 'user', message_content)
        )
        user_message = cursor.fetchone()
        
        # Get AI response if OpenAI is configured
        ai_response = None
        if openai_client:
            try:
                # Get recent messages for context
                cursor.execute(
                    """SELECT role, content 
                       FROM messages 
                       WHERE chat_id = %s 
                       ORDER BY created_at DESC 
                       LIMIT 10""",
                    (chat_id,)
                )
                recent_messages = cursor.fetchall()
                recent_messages.reverse()
                
                # Prepare messages for OpenAI
                messages = [{"role": msg['role'], "content": msg['content']} 
                           for msg in recent_messages]
                
                # Get AI response
                completion = openai_client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=messages,
                    max_tokens=1000,
                    temperature=0.7
                )
                
                ai_content = completion.choices[0].message.content
                
                # Save AI response
                cursor.execute(
                    """INSERT INTO messages (chat_id, role, content) 
                       VALUES (%s, %s, %s) 
                       RETURNING id, role, content, created_at""",
                    (chat_id, 'assistant', ai_content)
                )
                ai_response = cursor.fetchone()
                
                # Update chat title if it's the first message
                if chat['title'] == 'New Chat' and len(recent_messages) == 1:
                    # Generate title from first message
                    title = message_content[:50] + '...' if len(message_content) > 50 else message_content
                    cursor.execute(
                        "UPDATE chats SET title = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                        (title, chat_id)
                    )
                
            except Exception as ai_error:
                logger.error(f"AI response error: {str(ai_error)}")
                # Save error message
                cursor.execute(
                    """INSERT INTO messages (chat_id, role, content) 
                       VALUES (%s, %s, %s) 
                       RETURNING id, role, content, created_at""",
                    (chat_id, 'assistant', 'Sorry, I encountered an error processing your request.')
                )
                ai_response = cursor.fetchone()
        else:
            # No OpenAI, save placeholder response
            cursor.execute(
                """INSERT INTO messages (chat_id, role, content) 
                   VALUES (%s, %s, %s) 
                   RETURNING id, role, content, created_at""",
                (chat_id, 'assistant', 'AI features are currently unavailable.')
            )
            ai_response = cursor.fetchone()
        
        # Update chat timestamp
        cursor.execute(
            "UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (chat_id,)
        )
        
        conn.commit()
        
        return jsonify({
            'user_message': user_message,
            'ai_response': ai_response
        }), 201
        
    except Exception as e:
        logger.error(f"Send message error: {str(e)}")
        if conn:
            conn.rollback()
        return jsonify({'error': 'Failed to send message'}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            release_db_connection(conn)

# ==================================================
# ERROR HANDLERS
# ==================================================
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal error: {str(error)}")
    return jsonify({'error': 'Internal server error'}), 500

@app.errorhandler(Exception)
def handle_exception(error):
    if isinstance(error, HTTPException):
        return jsonify({'error': error.description}), error.code
    
    logger.error(f"Unhandled exception: {str(error)}")
    logger.error(traceback.format_exc())
    return jsonify({'error': 'An unexpected error occurred'}), 500

# ==================================================
# INITIALIZATION
# ==================================================
def initialize_services():
    """Initialize all services"""
    logger.info("Initializing services...")
    
    # Initialize database pool
    create_db_pool()
    
    # Initialize OpenAI client
    initialize_openai_client()
    
    logger.info("✓ Services initialization completed")

def startup_sequence():
    """Complete startup sequence"""
    try:
        # Initialize services
        initialize_services()
        
        # Initialize database tables
        if db_pool:
            logger.info("Initializing database tables...")
            if initialize_database():
                logger.info("✓ Database initialization completed")
            else:
                logger.warning("✗ Database initialization failed - some features may not work")
        
        logger.info("==================================================")
        logger.info(f"FLASK APP READY - Port: {PORT}")
        logger.info("==================================================")
        
    except Exception as e:
        logger.error(f"Startup sequence failed: {str(e)}")
        logger.error(traceback.format_exc())

# Run startup sequence when module is imported
startup_sequence()

# ==================================================
# MAIN ENTRY POINT
# ==================================================
if __name__ == '__main__':
    # This block is for local development only
    # Railway uses Gunicorn, not this
    logger.info(f"Running Flask development server on port {PORT}")
    app.run(host='0.0.0.0', port=PORT, debug=False)
