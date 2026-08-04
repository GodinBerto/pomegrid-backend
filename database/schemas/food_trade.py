def create_food_trade_tables(cursor):
    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS food_trade_user_roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES Users(id)
        )
        '''
    )

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS food_trade_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            sort_order INTEGER DEFAULT 0,
            image_url TEXT,
            is_active BOOLEAN NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )

    cursor.execute("PRAGMA table_info(food_trade_categories)")
    category_columns = [row[1] for row in cursor.fetchall()]
    if "image_url" not in category_columns:
        cursor.execute("ALTER TABLE food_trade_categories ADD COLUMN image_url TEXT")

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS food_trade_extended_user (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            address TEXT,
            region TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES Users(id)
        )
        '''
    )

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS food_trade_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            category_id INTEGER,
            price_ghs REAL NOT NULL,
            description TEXT,
            image_url TEXT,
            unit TEXT,
            min_order_qty INTEGER DEFAULT 1,
            is_active BOOLEAN NOT NULL DEFAULT 1,
            stock_qty INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (category_id) REFERENCES food_trade_categories(id)
        )
        '''
    )

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS food_trade_product_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            image_url TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0,
            is_primary BOOLEAN NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES food_trade_products(id) ON DELETE CASCADE
        )
        '''
    )

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS food_trade_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            contact_phone TEXT,
            delivery_address TEXT,
            delivery_region TEXT,
            total_ghs REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'confirmed', 'shipped', 'delivered', 'cancelled')),
            payment_reference TEXT UNIQUE,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES Users(id)
        )
        '''
    )

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS food_trade_order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            qty INTEGER NOT NULL,
            unit_price_ghs REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES food_trade_orders(id),
            FOREIGN KEY (product_id) REFERENCES food_trade_products(id)
        )
        '''
    )

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS food_trade_carts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES Users(id),
            FOREIGN KEY (product_id) REFERENCES food_trade_products(id)
        )
        '''
    )

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS food_trade_whatsapp_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            region TEXT NOT NULL,
            invite_url TEXT,
            description TEXT,
            is_active BOOLEAN NOT NULL DEFAULT 1,
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS food_trade_weekly_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            slug TEXT,
            description TEXT,
            price REAL NOT NULL,
            image_url TEXT,
            category_id INTEGER,
            status TEXT NOT NULL DEFAULT 'inactive' CHECK(status IN ('active', 'inactive')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS food_trade_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            provider TEXT DEFAULT 'paystack',
            reference TEXT UNIQUE NOT NULL,
            access_code TEXT,
            authorization_url TEXT,
            amount REAL NOT NULL,
            currency TEXT,
            status TEXT NOT NULL DEFAULT 'initialized',
            gateway_response TEXT,
            gateway_payload_json TEXT,
            channel TEXT,
            customer_email TEXT,
            metadata_json TEXT,
            paid_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES Users(id)
        )
        '''
    )


def create_food_trade_indexes(cursor):
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_food_trade_user_roles_user_id ON food_trade_user_roles(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_food_trade_categories_slug ON food_trade_categories(slug)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_food_trade_products_category_id ON food_trade_products(category_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_food_trade_products_slug ON food_trade_products(slug)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_food_trade_products_is_active ON food_trade_products(is_active)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_food_trade_product_images_product_id ON food_trade_product_images(product_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_food_trade_product_images_is_primary ON food_trade_product_images(is_primary)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_food_trade_orders_user_id ON food_trade_orders(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_food_trade_orders_status ON food_trade_orders(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_food_trade_order_items_order_id ON food_trade_order_items(order_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_food_trade_weekly_products_status ON food_trade_weekly_products(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_food_trade_payments_reference ON food_trade_payments(reference)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_food_trade_payments_user_id ON food_trade_payments(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_food_trade_carts_user_id ON food_trade_carts(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_food_trade_carts_product_id ON food_trade_carts(product_id)")
