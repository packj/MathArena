import sqlalchemy
import pymysql # Ensure pymysql is imported for direct connection
from sqlalchemy.pool import NullPool # Import NullPool for direct connections
import yaml # Import yaml for reading config file

def load_db_config():
    """Loads database configuration from config.yaml."""
    with open('config.yaml', 'r') as file:
        config = yaml.safe_load(file)
    return config['database']

db_config = load_db_config()

host = db_config['host']
port = db_config['port']
user = db_config['user']
password = db_config['password']
db_name = db_config['db_name']

sql_db = None

def init_connection_pool() -> sqlalchemy.engine.base.Engine:
    """Sets up connection pool for the app using AWS RDS."""
    global sql_db
    try:
        # Construct the connection string for SQLAlchemy
        # Using pymysql as the driver
        db_connection_str = (
            f"mysql+pymysql://{user}:{password}@{host}:{port}/{db_name}"
        )
        
        # Create the SQLAlchemy engine
        # Using NullPool because AWS RDS connections are typically managed by the application
        # or a connection proxy, and we don't want SQLAlchemy to manage a pool itself
        sql_db = sqlalchemy.create_engine(
            db_connection_str,
            poolclass=NullPool, # Use NullPool for direct connections
            pool_pre_ping=True # Optional: test connections before use
        )

        # Test the connection
        with sql_db.connect() as conn:
            conn.execute(sqlalchemy.text("SELECT 1"))
        print("Successfully connected to AWS RDS database.")
    except:
        print("Error connecting to AWS RDS database.")

    print("Connection pool initialized successfully for AWS RDS.")
    return sql_db

def create_all_tables(sql_db: sqlalchemy.engine.base.Engine):
    """Creates all necessary database tables if they do not already exist."""
    try:
        with sql_db.connect() as conn:
            conn.execute(sqlalchemy.text('''
                CREATE TABLE IF NOT EXISTS rooms (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    room_state ENUM('empty', 'setup', 'joinable', 'busy') NOT NULL DEFAULT 'empty',
                    collaborative BOOLEAN,
                    filter_name VARCHAR(255),
                    time_limit INT,
                    start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    live_scoreboard BOOLEAN )
            '''))
            conn.commit()

            # Check if the rooms table is empty and populate it if necessary
            result = conn.execute(sqlalchemy.text("SELECT COUNT(*) FROM rooms")).scalar()
            if result == 0:
                for i in range(1, 6):
                    conn.execute(sqlalchemy.text(
                        "INSERT INTO rooms (id, room_state) VALUES (:id, 'empty')"
                    ), {'id': i})
                conn.commit()
        # print("Rooms table ensured in the database.") # Removed redundant print
    except Exception as e:
        print(f"Error creating rooms table: {e}")
        raise # Re-raise the exception

    try:
        with sql_db.connect() as conn:
            conn.execute(sqlalchemy.text('''
                CREATE TABLE IF NOT EXISTS room1 (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(255) NOT NULL,
                    score FLOAT DEFAULT 0,
                    claimed_problem_indices TEXT
                )
            '''))
            conn.commit()
            conn.execute(sqlalchemy.text('''
                CREATE TABLE IF NOT EXISTS room2 (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(255) NOT NULL,
                    score FLOAT DEFAULT 0,
                    claimed_problem_indices TEXT
                )
            '''))
            conn.commit()
            conn.execute(sqlalchemy.text('''
                CREATE TABLE IF NOT EXISTS room3 (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(255) NOT NULL,
                    score FLOAT DEFAULT 0,
                    claimed_problem_indices TEXT
                )
            '''))
            conn.commit()
            conn.execute(sqlalchemy.text('''
                CREATE TABLE IF NOT EXISTS room4 (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(255) NOT NULL,
                    score FLOAT DEFAULT 0,
                    claimed_problem_indices TEXT
                )
            '''))
            conn.commit()
            conn.execute(sqlalchemy.text('''
                CREATE TABLE IF NOT EXISTS room5 (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(255) NOT NULL,
                    score FLOAT DEFAULT 0,
                    claimed_problem_indices TEXT
                )
            '''))
            conn.commit()
        # print("Room tables ensured in the database.") # Removed redundant print
    except Exception as e:
        print(f"Error creating room tables: {e}")
        raise # Re-raise the exception

    try:
        with sql_db.connect() as conn:
            conn.execute(sqlalchemy.text('''
                CREATE TABLE IF NOT EXISTS arena (
                    username VARCHAR(255) PRIMARY KEY,
                    in_room BOOLEAN,
                    last_active_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    room_id INT,
                    FOREIGN KEY (room_id) REFERENCES rooms(id)
                )
            '''))
            conn.commit()
        # print("Arena table ensured in the database.") # Removed redundant print
    except Exception as e:
        print(f"Error creating arena table: {e}")
        raise # Re-raise the exception

    try:
        with sql_db.connect() as conn:
            conn.execute(sqlalchemy.text('''
                CREATE TABLE IF NOT EXISTS users (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(255) NOT NULL UNIQUE,
                    password VARCHAR(255) NOT NULL,
                    first_name VARCHAR(255),
                    last_name VARCHAR(255),
                    grade VARCHAR(50),
                    school VARCHAR(255),
                    email VARCHAR(255),
                    note TEXT,
                    temp_password TEXT,
                    approved BOOLEAN DEFAULT FALSE
                )
            '''))
            conn.commit()
        # print("Users table ensured in the database.") # Removed redundant print
    except Exception as e:
        print(f"Error creating users table: {e}")
        raise # Re-raise the exception

    try:
        with sql_db.connect() as conn:
            conn.execute(sqlalchemy.text('''
                INSERT IGNORE INTO users (username, password, first_name, last_name, grade, school, email, note, temp_password, approved)
                VALUES (:username, :password, :first_name, :last_name, :grade, :school, :email, :note, :temp_password, :approved)
            '''), {
                'username': 'admin',
                'password': 'admin',
                'first_name': '',
                'last_name': '',
                'grade': '',
                'school': '',
                'email': '',
                'note': '',
                'temp_password': None,
                'approved': True
            })
            conn.commit()
        # print("Admin user ensured in the database.") # Removed redundant print
    except Exception as e:
        print(f"Error ensuring admin user: {e}")

    try:
        with sql_db.connect() as conn:
            conn.execute(sqlalchemy.text('''
                CREATE TABLE IF NOT EXISTS filters (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(255) UNIQUE NOT NULL,
                    start_year INT,
                    end_year INT,
                    formats TEXT,
                    levels TEXT,
                    classifications TEXT,
                    tags TEXT,
                    start_question INT,
                    end_question INT,
                    shuffle BOOLEAN
                )
            '''))
            conn.commit()
        # print("Filters table ensured in the database.") # Removed redundant print
    except Exception as e:
        print(f"Error creating filters table: {e}")
        raise # Re-raise the exception

    try:
        with sql_db.connect() as conn:
            conn.execute(sqlalchemy.text('''
                CREATE TABLE IF NOT EXISTS problems (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    classification VARCHAR(255),
                    link TEXT,
                    tags TEXT,
                    question_ref VARCHAR(255),
                    answer_ref VARCHAR(255),
                    year INT,
                    level VARCHAR(255),
                    format VARCHAR(255),
                    question_number INT,
                    true_answer TEXT
                )
            '''))
            conn.commit()
        # print("Problems table ensured in the database.") # Removed redundant print
    except Exception as e:
        print(f"Error creating problems table: {e}")
        raise # Re-raise the exception

    try:
        with sql_db.connect() as conn:
            conn.execute(sqlalchemy.text('''
                CREATE TABLE IF NOT EXISTS tag_recommendations (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    problem_id INT NOT NULL,
                    username VARCHAR(255) NOT NULL,
                    tags TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''))
            conn.commit()
        # print("Tag recommendations table ensured in the database.") # Removed redundant print
    except Exception as e:
        print(f"Error creating tag_recommendations table: {e}")
        raise # Re-raise the exception

    try:
        with sql_db.connect() as conn:
            conn.execute(sqlalchemy.text('''
                CREATE TABLE IF NOT EXISTS recommendations (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    problem_id INT NOT NULL,
                    username VARCHAR(255) NOT NULL,
                    classification VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''))
            conn.commit()
        # print("Recommendations table ensured in the database.") # Removed redundant print
    except Exception as e:
        print(f"Error creating recommendations table: {e}")
        raise # Re-raise the exception

    try:
        with sql_db.connect() as conn:
            conn.execute(sqlalchemy.text('''
                CREATE TABLE IF NOT EXISTS problem_reports (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(255) NOT NULL,
                    problem_id INT NOT NULL,
                    report_text TEXT NOT NULL,
                    date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''))
            conn.commit()
        # print("Problem reports table ensured in the database.") # Removed redundant print
    except Exception as e:
        print(f"Error creating problem_reports table: {e}")
        raise # Re-raise the exception

    try:
        with sql_db.connect() as conn:
            conn.execute(sqlalchemy.text('''
                CREATE TABLE IF NOT EXISTS suggested_links (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    problem_id INT NOT NULL,
                    username VARCHAR(255) NOT NULL,
                    suggested_link TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''))
            conn.commit()
        # print("Suggested links table ensured in the database.") # Removed redundant print
    except Exception as e:
        print(f"Error creating suggested_links table: {e}")
        raise # Re-raise the exception

    try:
        with sql_db.connect() as conn:
            conn.execute(sqlalchemy.text('''
                CREATE TABLE IF NOT EXISTS suggestions (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(255) NOT NULL,
                    suggestion_text TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''))
            conn.commit()
        # print("Suggestions table ensured in the database.") # Removed redundant print
    except Exception as e:
        print(f"Error creating suggestions table: {e}")
        raise # Re-raise the exception

    try:
        with sql_db.connect() as conn:
            conn.execute(sqlalchemy.text('''
                CREATE TABLE IF NOT EXISTS scoreboard (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(255) NOT NULL,
                    codename VARCHAR(255) NOT NULL,
                    points FLOAT NOT NULL
                )
            '''))
            conn.commit()
        # print("Scoreboard table ensured in the database.") # Removed redundant print
    except Exception as e:
        print(f"Error creating scoreboard table: {e}")
        raise # Re-raise the exception

    try:
        with sql_db.connect() as conn:
            conn.execute(sqlalchemy.text('''
                CREATE TABLE IF NOT EXISTS leaderboard (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(255) NOT NULL UNIQUE,
                    points FLOAT NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                )
            '''))
            conn.commit()
        # print("Leaderboard table ensured in the database.") # Removed redundant print
    except Exception as e:
        print(f"Error creating leaderboard table: {e}")
        raise # Re-raise the exception

    try:
        with sql_db.connect() as conn:
            conn.execute(sqlalchemy.text('''
                CREATE TABLE IF NOT EXISTS contribution_points (
                    username VARCHAR(255) PRIMARY KEY,
                    points INT DEFAULT NULL
                )
            '''))
            conn.commit()
        # print("Contribution points table ensured in the database.") # Removed redundant print
    except Exception as e:
        print(f"Error creating contribution_points table: {e}")
        raise # Re-raise the exception

    try:
        with sql_db.connect() as conn:
            conn.execute(sqlalchemy.text('''
                CREATE TABLE IF NOT EXISTS user_fidelity (
                    username VARCHAR(255) PRIMARY KEY,
                    accept_count INT DEFAULT 0,
                    reject_count INT DEFAULT 0
                )
            '''))
            conn.commit()
        # print("User fidelity table ensured in the database.") # Removed redundant print
    except Exception as e:
        print(f"Error creating user_fidelity table: {e}")
        raise # Re-raise the exception

    try:
        with sql_db.connect() as conn:
            conn.execute(sqlalchemy.text('''
                CREATE TABLE IF NOT EXISTS accepted_suggestions (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(255) NOT NULL,
                    suggestion_text TEXT NOT NULL,
                    accepted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''))
            conn.commit()
        # print("Accepted suggestions table ensured in the database.") # Removed redundant print
    except Exception as e:
        print(f"Error creating accepted_suggestions table: {e}")
        raise # Re-raise the exception

    try:
        with sql_db.connect() as conn:
            conn.execute(sqlalchemy.text('''
                CREATE TABLE IF NOT EXISTS resolved_reports (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(255) NOT NULL,
                    problem_id INT NOT NULL,
                    report_text TEXT NOT NULL,
                    report_date TIMESTAMP NOT NULL,
                    resolution_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''))
            conn.commit()
        # print("Resolved reports table ensured in the database.") # Removed redundant print
    except Exception as e:
        print(f"Error creating resolved_reports table: {e}")
        raise # Re-raise the exception

    try:
        with sql_db.connect() as conn:
            conn.execute(sqlalchemy.text('''
                CREATE TABLE IF NOT EXISTS rejected_reports (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(255) NOT NULL,
                    problem_id INT NOT NULL,
                    report_text TEXT NOT NULL,
                    report_date TIMESTAMP NOT NULL,
                    rejection_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''))
            conn.commit()
        # print("Rejected reports table ensured in the database.") # Removed redundant print
    except Exception as e:
        print(f"Error creating rejected_reports table: {e}")
        raise # Re-raise the exception

def get_users_in_room(sql_db, room_id):
    room_number = room_id
    room_table_name = f"room{room_number}"
    with sql_db.connect() as conn:
        result = conn.execute(sqlalchemy.text(f'''
            SELECT username FROM {room_table_name}
        ''')).fetchall()
        
        if result:
            users = [row[0] for row in result]  # Extract usernames from the result
            return users
        else:
            return []


sql_db = init_connection_pool()


# Check if users table exists before creating all tables
inspector = sqlalchemy.inspect(sql_db)
if not inspector.has_table('users'):
    create_all_tables(sql_db)
