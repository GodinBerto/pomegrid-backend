import json
import sqlite3


ALLOWED_USER_TYPES = (
    "user",
    "worker",
    "admin",
)


DEFAULT_FARM_SERVICES = [
    {
        "title": "Hatchery Setup and Fry Management",
        "description": "Structured hatchery support for broodstock handling, incubation flow, and early-stage fry survival planning.",
        "icon": "settings",
        "features": [
            "Broodstock and spawning workflow review",
            "Incubation tray and tank layout guidance",
            "Fry grading and stocking density plan",
            "Feed schedule setup for first growth stages",
            "Biosecurity checklist for hatchery rooms",
        ],
        "pricing": {
            "basic": {"price": 450, "duration": "One-time visit"},
            "premium": {"price": 1200, "duration": "3-day support"},
            "enterprise": {"price": 3200, "duration": "Monthly support"},
        },
    },
    {
        "title": "Pond and Tank System Setup",
        "description": "Technical setup support for earthen ponds, lined ponds, tanks, aeration layouts, and flow management before stocking.",
        "icon": "wrench",
        "features": [
            "Site inspection and layout recommendations",
            "Water inlet and outlet planning",
            "Aeration and circulation equipment checks",
            "Stocking capacity estimate by unit size",
            "Maintenance plan for pumps and plumbing",
        ],
        "pricing": {
            "basic": {"price": 600, "duration": "One-time visit"},
            "premium": {"price": 1750, "duration": "5-day setup"},
            "enterprise": {"price": 4200, "duration": "Project support"},
        },
    },
    {
        "title": "Water Quality Monitoring Program",
        "description": "Routine monitoring and corrective action planning for dissolved oxygen, pH, temperature, ammonia, and turbidity control.",
        "icon": "settings",
        "features": [
            "On-site water parameter testing",
            "Threshold alerts and action limits",
            "Pond or tank treatment recommendations",
            "Sampling log and reporting template",
            "Monthly trend review with corrective notes",
        ],
        "pricing": {
            "basic": {"price": 300, "duration": "One-time sampling"},
            "premium": {"price": 900, "duration": "Monthly checks"},
            "enterprise": {"price": 2400, "duration": "Quarterly program"},
        },
    },
    {
        "title": "Farm Staff Training and SOP Coaching",
        "description": "Hands-on training for farm teams covering daily operations, fish handling, feeding control, record keeping, and loss prevention.",
        "icon": "graduationCap",
        "features": [
            "Daily husbandry procedure training",
            "Safe fish handling and transfer drills",
            "Feed management and waste reduction coaching",
            "Recordkeeping templates for growth and mortality",
            "Supervisor checklist for shift handover",
        ],
        "pricing": {
            "basic": {"price": 500, "duration": "1-day training"},
            "premium": {"price": 1400, "duration": "3-day training"},
            "enterprise": {"price": 3600, "duration": "5-day training"},
        },
    },
    {
        "title": "On-Site Farm Operations Support",
        "description": "Practical farm support for production reviews, health observations, feeding efficiency, harvest preparation, and team coordination.",
        "icon": "users",
        "features": [
            "Weekly operations performance review",
            "Fish health and stress observation rounds",
            "Feeding response and conversion monitoring",
            "Harvest readiness and logistics planning",
            "Management summary with action priorities",
        ],
        "pricing": {
            "basic": {"price": 700, "duration": "One-time visit"},
            "premium": {"price": 1900, "duration": "Monthly support"},
            "enterprise": {"price": 4800, "duration": "Quarterly retainer"},
        },
    },
]


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
        and "'farmer'" not in users_sql
        and "'super admin'" not in users_sql
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
                user_type TEXT NOT NULL CHECK(user_type IN ('user', 'worker', 'admin')),
                role TEXT NOT NULL DEFAULT 'user',
                status TEXT NOT NULL DEFAULT 'active',
                date_of_birth DATE,
                is_verified BOOLEAN NOT NULL DEFAULT 0,
                verification_code TEXT,
                address TEXT,
                profile_image_url TEXT,
                avatar TEXT,
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
                role, status, date_of_birth, is_verified, verification_code, address,
                profile_image_url, avatar, is_active, is_admin, created_at, updated_at
            )
            SELECT
                id,
                username,
                email,
                password_hash,
                full_name,
                phone,
                CASE
                    WHEN LOWER(TRIM(user_type)) = 'super admin' THEN 'admin'
                    WHEN LOWER(TRIM(user_type)) = 'admin' OR COALESCE(is_admin, 0) = 1 THEN 'admin'
                    WHEN LOWER(TRIM(user_type)) = 'worker' THEN 'worker'
                    WHEN LOWER(TRIM(user_type)) = 'farmer' THEN 'user'
                    ELSE 'user'
                END AS user_type,
                CASE
                    WHEN LOWER(TRIM(user_type)) = 'super admin' THEN 'admin'
                    WHEN LOWER(TRIM(user_type)) = 'admin' OR COALESCE(is_admin, 0) = 1 THEN 'admin'
                    WHEN LOWER(TRIM(user_type)) = 'worker' THEN 'worker'
                    WHEN LOWER(TRIM(user_type)) = 'farmer' THEN 'user'
                    ELSE 'user'
                END AS role,
                CASE
                    WHEN COALESCE(is_active, 1) = 1 THEN 'active'
                    ELSE 'inactive'
                END AS status,
                date_of_birth,
                is_verified,
                verification_code,
                address,
                profile_image_url,
                profile_image_url AS avatar,
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
    has_confirmed = "'confirmed'" in bookings_sql
    has_in_progress = "'in_progress'" in bookings_sql
    if has_user_id and has_user_fk and has_confirmed and has_in_progress:
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
                    CHECK(status IN ('pending', 'accepted', 'confirmed', 'in_progress', 'rejected', 'completed', 'cancelled')),
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


def ensure_worker_services_schema(cursor):
    ensure_column(cursor, "worker_services", "service_id", "service_id INTEGER")
    ensure_column(cursor, "worker_services", "custom_price", "custom_price INTEGER")
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_worker_services_unique_worker_service
        ON worker_services(worker_id, service_id)
        WHERE service_id IS NOT NULL
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_worker_services_service_id ON worker_services(service_id)"
    )


def ensure_bookings_extended_fields(cursor):
    ensure_column(cursor, "bookings", "code", "code TEXT")
    ensure_column(cursor, "bookings", "customer_id", "customer_id INTEGER")
    ensure_column(cursor, "bookings", "service_name_snapshot", "service_name_snapshot TEXT")
    ensure_column(cursor, "bookings", "description", "description TEXT")
    ensure_column(cursor, "bookings", "address", "address TEXT")
    ensure_column(cursor, "bookings", "scheduled_date", "scheduled_date DATE")
    ensure_column(cursor, "bookings", "scheduled_time", "scheduled_time TEXT")
    ensure_column(cursor, "bookings", "total_price", "total_price INTEGER")
    ensure_column(cursor, "bookings", "is_custom_service", "is_custom_service BOOLEAN DEFAULT 0")
    ensure_column(cursor, "bookings", "admin_note", "admin_note TEXT")

    cursor.execute(
        """
        UPDATE bookings
        SET customer_id = user_id
        WHERE customer_id IS NULL AND user_id IS NOT NULL
        """
    )
    cursor.execute(
        """
        UPDATE bookings
        SET service_name_snapshot = service_name
        WHERE (service_name_snapshot IS NULL OR service_name_snapshot = '')
          AND service_name IS NOT NULL
        """
    )
    cursor.execute(
        """
        UPDATE bookings
        SET description = job_description
        WHERE (description IS NULL OR description = '')
          AND job_description IS NOT NULL
        """
    )
    cursor.execute(
        """
        UPDATE bookings
        SET address = service_address
        WHERE (address IS NULL OR address = '')
          AND service_address IS NOT NULL
        """
    )
    cursor.execute(
        """
        UPDATE bookings
        SET scheduled_date = requested_date
        WHERE scheduled_date IS NULL
          AND requested_date IS NOT NULL
        """
    )
    cursor.execute(
        """
        UPDATE bookings
        SET total_price = estimated_price
        WHERE total_price IS NULL
          AND estimated_price IS NOT NULL
        """
    )
    cursor.execute(
        """
        UPDATE bookings
        SET is_custom_service = CASE WHEN service_code = 'other' THEN 1 ELSE 0 END
        WHERE is_custom_service IS NULL
        """
    )


def seed_farm_services(cursor):
    for sort_order, service in enumerate(DEFAULT_FARM_SERVICES, start=1):
        cursor.execute(
            """
            INSERT OR IGNORE INTO farm_services (
                title,
                description,
                icon,
                features_json,
                pricing_json,
                sort_order,
                is_active
            )
            VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            (
                service["title"],
                service["description"],
                service["icon"],
                json.dumps(service["features"]),
                json.dumps(service["pricing"]),
                sort_order,
            ),
        )
        cursor.execute(
            """
            UPDATE farm_services
            SET
                description = ?,
                icon = ?,
                features_json = ?,
                pricing_json = ?,
                sort_order = ?,
                is_active = 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE title = ?
            """,
            (
                service["description"],
                service["icon"],
                json.dumps(service["features"]),
                json.dumps(service["pricing"]),
                sort_order,
                service["title"],
            ),
        )


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
            user_type TEXT NOT NULL CHECK(user_type IN ('user', 'worker', 'admin')),
            role TEXT NOT NULL DEFAULT 'user',
            status TEXT NOT NULL DEFAULT 'active',
            date_of_birth DATE,
            is_verified BOOLEAN NOT NULL DEFAULT 0,
            verification_code TEXT,
            address TEXT,
            profile_image_url TEXT,
            avatar TEXT,
            is_active BOOLEAN NOT NULL DEFAULT 1,
            is_admin BOOLEAN NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    ensure_users_user_type_constraint(conn, cursor)

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS ConnectProfiles (
            user_id INTEGER PRIMARY KEY,
            account_type TEXT NOT NULL CHECK(account_type IN ('farmer', 'importer')),
            company TEXT,
            country TEXT,
            bio TEXT,
            min_order_qty TEXT,
            response_time TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES Users(id) ON DELETE CASCADE
        )
        '''
    )

    # Create categories table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT
        )
    ''')

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS ProductTypes (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT
        )
        '''
    )

    # Create products table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            category_id INTEGER,
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
            image_urls TEXT,
            video_urls TEXT,
            rating REAL DEFAULT 4.5,
            discount_percentage INTEGER DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES Users(id),
            FOREIGN KEY (category_id) REFERENCES Categories(id),
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
            payment_method TEXT,
            shipping_address TEXT,
            notes TEXT,
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
               email TEXT,
               phone_number TEXT,
               phone_number_2 TEXT,
               profession TEXT NOT NULL,
               bio TEXT,
               image TEXT,
               location TEXT,
               ratings REAL DEFAULT 0,
               reviews_count INTEGER DEFAULT 0,
               is_available BOOLEAN DEFAULT 1,
               is_varified BOOLEAN DEFAULT false,
               hourly_rate INTEGER DEFAULT 0,
               years_experience INTEGER DEFAULT 0,
               completed_jobs INTEGER DEFAULT 0,
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
                service_id INTEGER,
                service_code TEXT NOT NULL,
                service_name TEXT NOT NULL,
                description TEXT,
                base_price INTEGER,
                custom_price INTEGER,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(worker_id, service_code),
                UNIQUE(worker_id, service_id),
                FOREIGN KEY (worker_id) REFERENCES Workers(id) ON DELETE CASCADE,
                FOREIGN KEY (service_id) REFERENCES services(id) ON DELETE SET NULL
            )
        '''
    )
    ensure_worker_services_schema(cursor)

    # Create worker profiles table
    cursor.execute(
        '''
            CREATE TABLE IF NOT EXISTS worker_profiles(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                profession TEXT,
                bio TEXT,
                location TEXT,
                hourly_rate INTEGER DEFAULT 0,
                is_available BOOLEAN DEFAULT 1,
                ratings REAL DEFAULT 0,
                reviews_count INTEGER DEFAULT 0,
                verified BOOLEAN DEFAULT 0,
                legacy_worker_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES Users(id) ON DELETE CASCADE,
                FOREIGN KEY (legacy_worker_id) REFERENCES Workers(id) ON DELETE SET NULL
            )
        '''
    )

    # Create service catalog table
    cursor.execute(
        '''
            CREATE TABLE IF NOT EXISTS services(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                worker_type TEXT,
                base_price INTEGER,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        '''
    )

    cursor.execute(
        '''
            CREATE TABLE IF NOT EXISTS farm_services(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL,
                icon TEXT NOT NULL CHECK(icon IN ('users', 'settings', 'graduationCap', 'wrench')),
                features_json TEXT NOT NULL,
                pricing_json TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        '''
    )
    ensure_column(cursor, "farm_services", "sort_order", "sort_order INTEGER NOT NULL DEFAULT 0")
    ensure_column(cursor, "farm_services", "is_active", "is_active BOOLEAN NOT NULL DEFAULT 1")
    seed_farm_services(cursor)

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
                    CHECK(status IN ('pending', 'accepted', 'confirmed', 'in_progress', 'rejected', 'completed', 'cancelled')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (worker_id) REFERENCES Workers(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES Users(id) ON DELETE CASCADE,
                FOREIGN KEY (service_id) REFERENCES worker_services(id) ON DELETE SET NULL
            )
        '''
    )
    ensure_bookings_user_link(conn, cursor)
    ensure_bookings_extended_fields(cursor)

    cursor.execute(
        '''
            CREATE TABLE IF NOT EXISTS job_status_history(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                from_status TEXT,
                to_status TEXT NOT NULL,
                changed_by INTEGER NOT NULL,
                note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (job_id) REFERENCES bookings(id) ON DELETE CASCADE,
                FOREIGN KEY (changed_by) REFERENCES Users(id) ON DELETE CASCADE
            )
        '''
    )

    cursor.execute(
        '''
            CREATE TABLE IF NOT EXISTS reviews(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                worker_id INTEGER NOT NULL,
                customer_id INTEGER NOT NULL,
                rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
                comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (job_id) REFERENCES bookings(id) ON DELETE CASCADE,
                FOREIGN KEY (worker_id) REFERENCES Users(id) ON DELETE CASCADE,
                FOREIGN KEY (customer_id) REFERENCES Users(id) ON DELETE CASCADE
            )
        '''
    )

    cursor.execute(
        '''
            CREATE TABLE IF NOT EXISTS wallets(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                balance REAL DEFAULT 0,
                pending_balance REAL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES Users(id) ON DELETE CASCADE
            )
        '''
    )

    cursor.execute(
        '''
            CREATE TABLE IF NOT EXISTS wallet_transactions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_id INTEGER NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('credit', 'debit')),
                amount REAL NOT NULL,
                title TEXT,
                reference TEXT,
                status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (wallet_id) REFERENCES wallets(id) ON DELETE CASCADE
            )
        '''
    )

    cursor.execute(
        '''
            CREATE TABLE IF NOT EXISTS payments(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                order_id INTEGER,
                provider TEXT NOT NULL DEFAULT 'paystack',
                reference TEXT NOT NULL UNIQUE,
                access_code TEXT,
                authorization_url TEXT,
                amount REAL NOT NULL,
                currency TEXT NOT NULL DEFAULT 'NGN',
                status TEXT NOT NULL DEFAULT 'initialized',
                gateway_response TEXT,
                gateway_payload_json TEXT,
                channel TEXT,
                customer_email TEXT,
                metadata_json TEXT,
                paid_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES Users(id) ON DELETE CASCADE,
                FOREIGN KEY (order_id) REFERENCES Orders(id) ON DELETE SET NULL
            )
        '''
    )

    cursor.execute(
        '''
            CREATE TABLE IF NOT EXISTS withdrawal_requests(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                bank_name TEXT,
                account_number_masked TEXT,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'approved', 'rejected', 'paid')),
                processed_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP,
                FOREIGN KEY (worker_id) REFERENCES Users(id) ON DELETE CASCADE,
                FOREIGN KEY (processed_by) REFERENCES Users(id) ON DELETE SET NULL
            )
        '''
    )

    cursor.execute(
        '''
            CREATE TABLE IF NOT EXISTS conversations(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL
                    CHECK(type IN ('worker_admin', 'worker_customer', 'admin_customer')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        '''
    )

    cursor.execute(
        '''
            CREATE TABLE IF NOT EXISTS conversation_participants(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                UNIQUE(conversation_id, user_id),
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES Users(id) ON DELETE CASCADE
            )
        '''
    )

    cursor.execute(
        '''
            CREATE TABLE IF NOT EXISTS messages(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                sender_id INTEGER NOT NULL,
                body TEXT NOT NULL,
                channel TEXT NOT NULL DEFAULT 'in_app'
                    CHECK(channel IN ('in_app', 'whatsapp', 'email')),
                read_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
                FOREIGN KEY (sender_id) REFERENCES Users(id) ON DELETE CASCADE
            )
        '''
    )

    cursor.execute(
        '''
            CREATE TABLE IF NOT EXISTS notifications(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                type TEXT,
                title TEXT,
                message TEXT,
                is_read BOOLEAN DEFAULT 0,
                payload_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES Users(id) ON DELETE CASCADE
            )
        '''
    )

    cursor.execute(
        '''
            CREATE TABLE IF NOT EXISTS admin_conversations(
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                admin_id INTEGER,
                last_message_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES Users(id) ON DELETE CASCADE,
                FOREIGN KEY (admin_id) REFERENCES Users(id) ON DELETE SET NULL
            )
        '''
    )

    cursor.execute(
        '''
            CREATE TABLE IF NOT EXISTS admin_messages(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                is_read BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id) REFERENCES admin_conversations(id) ON DELETE CASCADE,
                FOREIGN KEY (sender_id) REFERENCES Users(id) ON DELETE CASCADE,
                FOREIGN KEY (receiver_id) REFERENCES Users(id) ON DELETE CASCADE
            )
        '''
    )

    cursor.execute(
        '''
            CREATE TABLE IF NOT EXISTS admin_notifications(
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL CHECK(type IN ('order', 'message', 'system')),
                title TEXT NOT NULL,
                description TEXT,
                href TEXT,
                read BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        '''
    )

    cursor.execute(
        '''
            CREATE TABLE IF NOT EXISTS inventory_items(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sku TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                category TEXT,
                quantity INTEGER DEFAULT 0,
                unit_cost REAL DEFAULT 0,
                reorder_level INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        '''
    )

    cursor.execute(
        '''
            CREATE TABLE IF NOT EXISTS inventory_movements(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL,
                movement_type TEXT NOT NULL CHECK(movement_type IN ('in', 'out', 'adjustment')),
                quantity INTEGER NOT NULL,
                note TEXT,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (item_id) REFERENCES inventory_items(id) ON DELETE CASCADE,
                FOREIGN KEY (created_by) REFERENCES Users(id) ON DELETE SET NULL
            )
        '''
    )

    cursor.execute(
        '''
            CREATE TABLE IF NOT EXISTS payment_gateways(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                provider TEXT NOT NULL,
                config_json TEXT,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        '''
    )

    cursor.execute(
        '''
            CREATE TABLE IF NOT EXISTS sync_runs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT,
                status TEXT NOT NULL CHECK(status IN ('running', 'success', 'failed')),
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ended_at TIMESTAMP,
                log_text TEXT
            )
        '''
    )

    cursor.execute(
        '''
            CREATE TABLE IF NOT EXISTS admin_settings(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL UNIQUE,
                value_json TEXT,
                updated_by INTEGER,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (updated_by) REFERENCES Users(id) ON DELETE SET NULL
            )
        '''
    )

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
    ensure_column(cursor, "Users", "role", "role TEXT NOT NULL DEFAULT 'user'")
    ensure_column(cursor, "Users", "status", "status TEXT NOT NULL DEFAULT 'active'")
    ensure_column(cursor, "Users", "avatar", "avatar TEXT")
    ensure_column(cursor, "ConnectProfiles", "company", "company TEXT")
    ensure_column(cursor, "ConnectProfiles", "country", "country TEXT")
    ensure_column(cursor, "ConnectProfiles", "bio", "bio TEXT")
    ensure_column(cursor, "ConnectProfiles", "min_order_qty", "min_order_qty TEXT")
    ensure_column(cursor, "ConnectProfiles", "response_time", "response_time TEXT")
    ensure_column(cursor, "Products", "category_id", "category_id INTEGER")
    ensure_column(cursor, "Products", "image_urls", "image_urls TEXT")
    ensure_column(cursor, "Products", "video_urls", "video_urls TEXT")
    ensure_column(cursor, "Orders", "payment_method", "payment_method TEXT")
    ensure_column(cursor, "Orders", "payment_reference", "payment_reference TEXT")
    ensure_column(cursor, "Orders", "payment_status", "payment_status TEXT")
    ensure_column(cursor, "Orders", "paid_at", "paid_at TIMESTAMP")
    ensure_column(cursor, "Orders", "shipping_address", "shipping_address TEXT")
    ensure_column(cursor, "Orders", "notes", "notes TEXT")
    ensure_column(cursor, "Jobs", "status", "status TEXT NOT NULL DEFAULT 'pending'")
    ensure_column(cursor, "Jobs", "budget", "budget REAL")
    ensure_column(cursor, "Jobs", "address", "address TEXT")
    ensure_column(cursor, "Jobs", "scheduled_at", "scheduled_at TIMESTAMP")
    ensure_column(cursor, "Jobs", "completed_at", "completed_at TIMESTAMP")

    cursor.execute(
        """
        UPDATE Users
        SET role = CASE
            WHEN LOWER(COALESCE(user_type, '')) = 'admin' OR COALESCE(is_admin, 0) = 1 THEN 'admin'
            WHEN LOWER(COALESCE(user_type, '')) = 'worker' THEN 'worker'
            ELSE 'user'
        END
        WHERE role IS NULL OR TRIM(role) = ''
        """
    )
    cursor.execute(
        """
        UPDATE Users
        SET status = CASE WHEN COALESCE(is_active, 1) = 1 THEN 'active' ELSE 'inactive' END
        WHERE status IS NULL OR TRIM(status) = ''
        """
    )

    cursor.execute("SELECT DISTINCT animal_type FROM Products WHERE animal_type IS NOT NULL AND TRIM(animal_type) != ''")
    for animal_type_row in cursor.fetchall():
        animal_type_value = str(animal_type_row["animal_type"]).strip()
        cursor.execute(
            """
            INSERT OR IGNORE INTO ProductTypes (id, name)
            VALUES (?, ?)
            """,
            (animal_type_value, animal_type_value),
        )

    cursor.execute("SELECT id, image_url, image_urls, video_urls FROM Products")
    for product in cursor.fetchall():
        product_id = int(product["id"])
        stored_image_url = product["image_url"]
        stored_image_urls = product["image_urls"]
        stored_video_urls = product["video_urls"]

        parsed_image_urls = []
        if stored_image_urls:
            try:
                parsed = json.loads(stored_image_urls)
                if isinstance(parsed, list):
                    parsed_image_urls = [str(item).strip() for item in parsed if str(item).strip()]
            except Exception:
                parsed_image_urls = []

        if stored_image_url and stored_image_url not in parsed_image_urls:
            parsed_image_urls.insert(0, str(stored_image_url).strip())

        first_image_url = parsed_image_urls[0] if parsed_image_urls else None

        parsed_video_urls = []
        if stored_video_urls:
            try:
                parsed_videos = json.loads(stored_video_urls)
                if isinstance(parsed_videos, list):
                    parsed_video_urls = [str(item).strip() for item in parsed_videos if str(item).strip()]
            except Exception:
                parsed_video_urls = []

        cursor.execute(
            """
            UPDATE Products
            SET image_url = ?, image_urls = ?, video_urls = ?
            WHERE id = ?
            """,
            (
                first_image_url,
                json.dumps(parsed_image_urls),
                json.dumps(parsed_video_urls),
                product_id,
            ),
        )

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
        "CREATE INDEX IF NOT EXISTS idx_bookings_customer_id ON bookings(customer_id)"
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
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_bookings_code_unique ON bookings(code)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_worker_profiles_user_id ON worker_profiles(user_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_worker_profiles_location ON worker_profiles(location)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_worker_profiles_verified ON worker_profiles(verified)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_services_worker_type ON services(worker_type)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_services_is_active ON services(is_active)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_farm_services_sort_order ON farm_services(sort_order)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_farm_services_is_active ON farm_services(is_active)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_job_status_history_job_id ON job_status_history(job_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_reviews_worker_id ON reviews(worker_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_reviews_customer_id ON reviews(customer_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_wallet_transactions_wallet_id ON wallet_transactions(wallet_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_wallet_transactions_status ON wallet_transactions(status)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_payments_order_id ON payments(order_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_withdrawal_requests_worker_id ON withdrawal_requests(worker_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_withdrawal_requests_status ON withdrawal_requests(status)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_conv_participants_user_id ON conversation_participants(user_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON notifications(user_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_notifications_is_read ON notifications(is_read)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_users_role ON Users(role)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_users_status ON Users(status)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_connect_profiles_account_type ON ConnectProfiles(account_type)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_connect_profiles_country ON ConnectProfiles(country)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_products_category_id ON Products(category_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_orders_created_at ON Orders(created_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_orders_status ON Orders(status)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON OrderItems(order_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_order_items_product_id ON OrderItems(product_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_admin_conversations_user_id ON admin_conversations(user_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_admin_messages_conversation_id ON admin_messages(conversation_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_admin_messages_is_read ON admin_messages(is_read)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_admin_notifications_read ON admin_notifications(read)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_inventory_items_category ON inventory_items(category)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_inventory_items_is_active ON inventory_items(is_active)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_inventory_movements_item_id ON inventory_movements(item_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_payment_gateways_is_active ON payment_gateways(is_active)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_sync_runs_status ON sync_runs(status)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_sync_runs_started_at ON sync_runs(started_at)"
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
