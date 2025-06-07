import sqlalchemy
from connect_connector import connect_with_connector
#import yaml # Import yaml


from google.cloud import secretmanager # Import Secret Manager client

# Initialize Secret Manager client
client = secretmanager.SecretManagerServiceClient()

# Replace with your Google Cloud Project ID
PROJECT_ID = "enduring-maxim-453423-h4"

def get_secret_value(secret_name):
    """Fetches a secret from Google Secret Manager."""
    try:
        name = f"projects/{PROJECT_ID}/secrets/{secret_name}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        print(f"Error accessing secret '{secret_name}': {e}")
        # Depending on your application's needs, you might want to raise an exception
        # or return a default/fallback value. For critical credentials, raising is better.
        raise


# Retrieve credentials from Secret Manager
try:
    connection_name = get_secret_value("mathArena-connection-name")
    db_user = get_secret_value("mathArena-db-user")
    db_pass = get_secret_value("mathArena-db-pass")
    db_name = get_secret_value("mathArena-db-name")
except Exception as e:
    print(f"Failed to retrieve database credentials from Secret Manager: {e}")
    print("Please ensure the service account running the application has 'Secret Manager Secret Accessor' role and the secrets exist with correct names.")
    raise # Re-raise the exception as credentials are critical


sql_db = None
sql_connector = None # New global variable for the connector

def init_connection_pool() -> sqlalchemy.engine.base.Engine:
    """Sets up connection pool for the app."""
    global sql_db, sql_connector # Declare sql_connector as global
    try:
        if not connection_name:
            raise ValueError(
                "Missing database connection name"
            )
        
        # The connect_with_connector function now returns both the engine and the connector
        sql_db, sql_connector = connect_with_connector(
            instance_connection_name=connection_name,
            db_user=db_user,
            db_pass=db_pass,
            db_name=db_name
        )

        with sql_db.connect() as conn:
            conn.execute(sqlalchemy.text('''
                CREATE TABLE IF NOT EXISTS rooms (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    room_state ENUM('empty', 'setup', 'joinable', 'busy') NOT NULL DEFAULT 'empty',
                    collaborative BOOLEAN,
                    filter_name VARCHAR(255),
                    time_limit INT,
                    start_time TIMESTAMP,
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
    except Exception as e:
        print(f"Error creating rooms table: {e}")
        raise # Re-raise the exception to prevent further execution with a bad connection

    try:
        with sql_db.connect() as conn:
            conn.execute(sqlalchemy.text('''
                CREATE TABLE IF NOT EXISTS room1 (
                    username VARCHAR(255) PRIMARY KEY,
                    score FLOAT DEFAULT 0,
                    claimed_problem_indices TEXT
                )
            '''))
            conn.commit()
            conn.execute(sqlalchemy.text('''
                CREATE TABLE IF NOT EXISTS room2 (
                    username VARCHAR(255) PRIMARY KEY,
                    score FLOAT DEFAULT 0,
                    claimed_problem_indices TEXT
                )
            '''))
            conn.commit()
            conn.execute(sqlalchemy.text('''
                CREATE TABLE IF NOT EXISTS room3 (
                    username VARCHAR(255) PRIMARY KEY,
                    score FLOAT DEFAULT 0,
                    claimed_problem_indices TEXT
                )
            '''))
            conn.commit()
            conn.execute(sqlalchemy.text('''
                CREATE TABLE IF NOT EXISTS room4 (
                    username VARCHAR(255) PRIMARY KEY,
                    score FLOAT DEFAULT 0,
                    claimed_problem_indices TEXT
                )
            '''))
            conn.commit()
            conn.execute(sqlalchemy.text('''
                CREATE TABLE IF NOT EXISTS room5 (
                    username VARCHAR(255) PRIMARY KEY,
                    score FLOAT DEFAULT 0,
                    claimed_problem_indices TEXT
                )
            '''))
            conn.commit()
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
    except Exception as e:
        print(f"Error creating arena table: {e}")
        raise # Re-raise the exception
    print("Connection pool initialized successfully.")
    return sql_db

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

init_connection_pool()
