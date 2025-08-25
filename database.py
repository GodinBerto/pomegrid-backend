import sqlite3

def db_connection():
    # Connect to SQLite database (or create if it doesn't exist)
    conn = sqlite3.connect("instance/pomegrid.db")
    conn.row_factory = sqlite3.Row
    return conn, conn.cursor()

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
    
    conn.commit()
    conn.close()

# Execute table creation
create_tables()
