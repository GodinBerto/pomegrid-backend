import sqlite3

def db_connection():
    # Connect to SQLite database (or create if it doesn't exist)
    conn = sqlite3.connect("instance/pomegrid.db")
    conn.row_factory = sqlite3.Row
    return conn, conn.cursor()


def ensure_column(cursor, table_name, column_name, column_definition):
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row["name"] for row in cursor.fetchall()]
    if column_name not in columns:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_definition}")


def create_tables():
    conn, cursor = db_connection()
    
    # Create Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            user_type TEXT NOT NULL CHECK(user_type IN ('farmer', 'consumer')),
            date_of_birth DATE,
            is_verified BOOLEAN NOT NULL DEFAULT 0,
            verification_code TEXT,
            address TEXT,
            profile_image_url TEXT,
            is_active BOOLEAN NOT NULL DEFAULT 1,
            is_admin BOOLEAN NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Create categories table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT
        )
    ''')

    # Create products table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            animal_stage INTEGER CHECK (animal_stage IN ('0', '1')) DEFAULT NULL,
            animal_type TEXT,
            description TEXT,
            price REAL NOT NULL,
            quantity INTEGER NOT NULL,
            weight_per_unit REAL NOT NULL DEFAULT 1.0,
            is_alive BOOLEAN,
            is_fresh BOOLEAN,
            image_url TEXT,
            rating REAL DEFAULT 4.5,
            discount_percentage INTEGER DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES Users(id),
            FOREIGN KEY (animal_type) REFERENCES ProductTypes(id)
        )
    ''')
    
    
    #Create cart table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Cart (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES Users(id),
            FOREIGN KEY (product_id) REFERENCES Products(id)
        )
    ''')


    # Create orders table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            total_price REAL NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('pending', 'processing', 'completed', 'cancelled')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES Users(id)
        )
    ''')

    # Create order items table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS OrderItems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES Orders(id),
            FOREIGN KEY (product_id) REFERENCES Products(id),
            FOREIGN KEY (user_id) REFERENCES Users(id)
        )
    ''')
    
    #Create workers table
    cursor.execute('''
            CREATE TABLE IF NOT EXISTS Workers(
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               name TEXT NOT NULL,
               phone_number INTEGER NOT NULL,
               email TEXT,
               phone_number_2 NUMBER,
               bio TEXT,
               profession TEXT NOT NULL,
               is_varified BOOLEAN DEFAULT false,
               location TEXT NOT NULL,
               ratings INTEGER,
               image TEXT,
               is_available BOOLEAN DEFAULT false,
               created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
               updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
    ''')

    cursor.execute('''
            CREATE TABLE IF NOT EXISTS Admins(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES Users(id)
            )
    ''')
    
    # Create worker rating table
    cursor.execute('''
            CREATE TABLE IF NOT EXISTS Jobs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                job_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                budget REAL,
                address TEXT,
                scheduled_at TIMESTAMP,
                completed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (worker_id) REFERENCES Workers(id),
                FOREIGN KEY (user_id) REFERENCES Users(id)
            )
    ''')
    
    # Create worker rating table
    cursor.execute('''
            CREATE TABLE IF NOT EXISTS Worker_Ratings(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                job_id INTEGER NOT NULL,
                feedback TEXT,
                rating INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (worker_id) REFERENCES Workers(id),
                FOREIGN KEY (job_id) REFERENCES Jobs(id),
                FOREIGN KEY (user_id) REFERENCES Users(id)
            )
    ''')

    ensure_column(cursor, "Workers", "created_by_admin_id", "created_by_admin_id INTEGER")
    ensure_column(cursor, "Workers", "updated_by_admin_id", "updated_by_admin_id INTEGER")
    ensure_column(cursor, "Jobs", "status", "status TEXT NOT NULL DEFAULT 'pending'")
    ensure_column(cursor, "Jobs", "budget", "budget REAL")
    ensure_column(cursor, "Jobs", "address", "address TEXT")
    ensure_column(cursor, "Jobs", "scheduled_at", "scheduled_at TIMESTAMP")
    ensure_column(cursor, "Jobs", "completed_at", "completed_at TIMESTAMP")

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_workers_location ON Workers(location)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_worker_id ON Jobs(worker_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON Jobs(user_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_status ON Jobs(status)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_ratings_worker_id ON Worker_Ratings(worker_id)"
    )
    
    conn.commit()
    conn.close()

# Execute table creation
create_tables()
