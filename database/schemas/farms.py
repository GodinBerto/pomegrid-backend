def create_farm_tables(cursor):
    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS Categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT
        )
        '''
    )

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS ProductTypes (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT
        )
        '''
    )

    cursor.execute(
        '''
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
            is_featured BOOLEAN NOT NULL DEFAULT 0,
            is_active BOOLEAN NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES Users(id),
            FOREIGN KEY (category_id) REFERENCES Categories(id),
            FOREIGN KEY (animal_type) REFERENCES ProductTypes(id)
        )
        '''
    )

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS ProductFeedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
            feedback TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES Products(id),
            FOREIGN KEY (user_id) REFERENCES Users(id)
        )
        '''
    )

    cursor.execute(
        '''
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
        '''
    )

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS Orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            total_price REAL NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('pending', 'processing', 'completed', 'cancelled')),
            payment_method TEXT,
            payment_reference TEXT,
            payment_status TEXT,
            paid_at TIMESTAMP,
            shipping_address TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES Users(id)
        )
        '''
    )

    cursor.execute(
        '''
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


def create_farm_indexes(cursor):
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_farm_services_sort_order ON farm_services(sort_order)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_farm_services_is_active ON farm_services(is_active)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_product_feedback_product_id ON ProductFeedback(product_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_product_feedback_user_id ON ProductFeedback(user_id)")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_product_feedback_product_user_unique ON ProductFeedback(product_id, user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_category_id ON Products(category_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_is_featured ON Products(is_featured)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_is_active ON Products(is_active)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_created_at ON Orders(created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON Orders(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON OrderItems(order_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_order_items_product_id ON OrderItems(product_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_payments_order_id ON payments(order_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status)")
