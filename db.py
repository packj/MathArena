import sqlalchemy
from connect_connector import connect_with_connector

connection_name = r"enduring-maxim-453423-h4:us-east4:iroquoismath"
sqlCredentials = r"C:\Users\packj\OneDrive\Code\py\Mathcounts\Capture\OtherLanguages\Online\enduring-maxim-453423-h4-72bb5d48efab.json"

sql_db = None

def init_connection_pool() -> sqlalchemy.engine.base.Engine:
    """Sets up connection pool for the app."""
    global sql_db
    try:
        if connection_name:
            sql_db = connect_with_connector()

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
        else:
            raise ValueError(
                "Missing database connection type. Please define one of INSTANCE_HOST, INSTANCE_UNIX_SOCKET, or INSTANCE_CONNECTION_NAME"
            )
    except Exception as e:
        print(f"Error creating rooms table: {e}")

    try:
        if connection_name:
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
        else:
            raise ValueError(
                "Missing database connection type. Please define one of INSTANCE_HOST, INSTANCE_UNIX_SOCKET, or INSTANCE_CONNECTION_NAME"
            )
    except Exception as e:
        print(f"Error creating room tables: {e}")

    try:
        if connection_name:
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
        else:
            raise ValueError(
                "Missing database connection type. Please define one of INSTANCE_HOST, INSTANCE_UNIX_SOCKET, or INSTANCE_CONNECTION_NAME"
            )
    except Exception as e:
        print(f"Error creating arena table: {e}")
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
