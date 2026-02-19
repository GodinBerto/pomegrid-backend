import sqlite3


ALLOWED_USER_TYPES = (
    "user",
    "farmer",
    "worker",
    "admin",
    "super admin",
)


def db_connection():
    # Connect to SQLite database (or create if it doesn't exist)
    conn = sqlite3.connect("instance/pomegrid.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn, conn.cursor()


def ensure_column(cursor, table_name, column_name, column_definition):
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row["name"] for row in cursor.fetchall()]
    if column_name not in columns:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_definition}")


def ensure_users_user_type_constraint(conn, cursor):
    cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'Users'"
    )
    row = cursor.fetchone()
    if not row or not row["sql"]:
        return

    users_sql = row["sql"].lower()
    required_role_tokens = tuple(f"'{user_type}'" for user_type in ALLOWED_USER_TYPES)
    constraint_is_current = all(token in users_sql for token in required_role_tokens)
    if (
        constraint_is_current
        and "'normal consumer user'" not in users_sql
        and "'consumer'" not in users_sql
    ):
        return

    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS Users_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                full_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                user_type TEXT NOT NULL CHECK(user_type IN ('user', 'farmer', 'worker', 'admin', 'super admin')),
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
            """
        )

        cursor.execute(
            """
            INSERT INTO Users_new (
                id, username, email, password_hash, full_name, phone, user_type,
                date_of_birth, is_verified, verification_code, address,
                profile_image_url, is_active, is_admin, created_at, updated_at
            )
            SELECT
                id,
                username,
                email,
                password_hash,
                full_name,
                phone,
                CASE
                    WHEN LOWER(TRIM(user_type)) = 'super admin' THEN 'super admin'
                    WHEN LOWER(TRIM(user_type)) = 'admin' OR COALESCE(is_admin, 0) = 1 THEN 'admin'
                    WHEN LOWER(TRIM(user_type)) = 'worker' THEN 'worker'
                    WHEN LOWER(TRIM(user_type)) = 'farmer' THEN 'farmer'
                    ELSE 'user'
                END AS user_type,
                date_of_birth,
                is_verified,
                verification_code,
                address,
                profile_image_url,
                is_active,
                CASE
                    WHEN LOWER(TRIM(user_type)) IN ('admin', 'super admin') OR COALESCE(is_admin, 0) = 1 THEN 1
                    ELSE 0
                END AS is_admin,
                created_at,
                updated_at
            FROM Users
            """
        )

        cursor.execute("DROP TABLE Users")
        cursor.execute("ALTER TABLE Users_new RENAME TO Users")
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def ensure_bookings_user_link(conn, cursor):
    cursor.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'bookings'")
    row = cursor.fetchone()
    if not row or not row["sql"]:
        return

    cursor.execute("PRAGMA table_info(bookings)")
    columns = [column["name"] for column in cursor.fetchall()]
    has_user_id = "user_id" in columns

    bookings_sql = row["sql"].lower()
    has_user_fk = "foreign key (user_id) references users(id)" in bookings_sql
    if has_user_id and has_user_fk:
        return

    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS bookings_new(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_id INTEGER NOT NULL,
                user_id INTEGER,
                service_id INTEGER,
                service_code TEXT NOT NULL,
                service_name TEXT,
                custom_service_text TEXT,
                requested_date DATE NOT NULL,
                customer_phone TEXT NOT NULL,
                service_address TEXT NOT NULL,
                job_description TEXT NOT NULL,
                estimated_price INTEGER,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'accepted', 'rejected', 'completed', 'cancelled')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (worker_id) REFERENCES Workers(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES Users(id) ON DELETE CASCADE,
                FOREIGN KEY (service_id) REFERENCES worker_services(id) ON DELETE SET NULL
            )
            """
        )

        if has_user_id:
            cursor.execute(
                """
                INSERT INTO bookings_new (
                    id, worker_id, user_id, service_id, service_code, service_name,
                    custom_service_text, requested_date, customer_phone, service_address,
                    job_description, estimated_price, status, created_at, updated_at
                )
                SELECT
                    b.id,
                    b.worker_id,
                    CASE WHEN u.id IS NOT NULL THEN b.user_id ELSE NULL END AS user_id,
                    b.service_id,
                    b.service_code,
                    b.service_name,
                    b.custom_service_text,
                    b.requested_date,
                    b.customer_phone,
                    b.service_address,
                    b.job_description,
                    b.estimated_price,
                    b.status,
                    b.created_at,
                    b.updated_at
                FROM bookings b
                LEFT JOIN Users u ON u.id = b.user_id
                """
            )
        else:
            cursor.execute(
                """
                INSERT INTO bookings_new (
                    id, worker_id, user_id, service_id, service_code, service_name,
                    custom_service_text, requested_date, customer_phone, service_address,
                    job_description, estimated_price, status, created_at, updated_at
                )
                SELECT
                    id,
                    worker_id,
                    NULL AS user_id,
                    service_id,
                    service_code,
                    service_name,
                    custom_service_text,
                    requested_date,
                    customer_phone,
                    service_address,
                    job_description,
                    estimated_price,
                    status,
                    created_at,
                    updated_at
                FROM bookings
                """
            )

        cursor.execute("DROP TABLE bookings")
        cursor.execute("ALTER TABLE bookings_new RENAME TO bookings")
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


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
            user_type TEXT NOT NULL CHECK(user_type IN ('user', 'farmer', 'worker', 'admin', 'super admin')),
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
    ensure_users_user_type_constraint(conn, cursor)

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
    
    # Create workers table
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

    # Create worker services table
    cursor.execute(
        '''
            CREATE TABLE IF NOT EXISTS worker_services(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_id INTEGER NOT NULL,
                service_code TEXT NOT NULL,
                service_name TEXT NOT NULL,
                description TEXT,
                base_price INTEGER,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(worker_id, service_code),
                FOREIGN KEY (worker_id) REFERENCES Workers(id) ON DELETE CASCADE
            )
        '''
    )

    # Create bookings table
    cursor.execute(
        '''
            CREATE TABLE IF NOT EXISTS bookings(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_id INTEGER NOT NULL,
                user_id INTEGER,
                service_id INTEGER,
                service_code TEXT NOT NULL,
                service_name TEXT,
                custom_service_text TEXT,
                requested_date DATE NOT NULL,
                customer_phone TEXT NOT NULL,
                service_address TEXT NOT NULL,
                job_description TEXT NOT NULL,
                estimated_price INTEGER,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'accepted', 'rejected', 'completed', 'cancelled')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (worker_id) REFERENCES Workers(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES Users(id) ON DELETE CASCADE,
                FOREIGN KEY (service_id) REFERENCES worker_services(id) ON DELETE SET NULL
            )
        '''
    )
    ensure_bookings_user_link(conn, cursor)

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
    ensure_column(cursor, "Workers", "reviews_count", "reviews_count INTEGER DEFAULT 0")
    ensure_column(cursor, "Workers", "hourly_rate", "hourly_rate INTEGER DEFAULT 0")
    ensure_column(cursor, "Workers", "years_experience", "years_experience INTEGER DEFAULT 0")
    ensure_column(cursor, "Workers", "completed_jobs", "completed_jobs INTEGER DEFAULT 0")
    ensure_column(cursor, "Jobs", "status", "status TEXT NOT NULL DEFAULT 'pending'")
    ensure_column(cursor, "Jobs", "budget", "budget REAL")
    ensure_column(cursor, "Jobs", "address", "address TEXT")
    ensure_column(cursor, "Jobs", "scheduled_at", "scheduled_at TIMESTAMP")
    ensure_column(cursor, "Jobs", "completed_at", "completed_at TIMESTAMP")

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_workers_location ON Workers(location)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_workers_profession ON Workers(profession)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_workers_is_available ON Workers(is_available)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_workers_ratings ON Workers(ratings)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_worker_services_worker_id ON worker_services(worker_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_worker_services_service_code ON worker_services(service_code)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_bookings_worker_id ON bookings(worker_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_bookings_user_id ON bookings(user_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_bookings_service_id ON bookings(service_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings(status)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_bookings_requested_date ON bookings(requested_date)"
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
