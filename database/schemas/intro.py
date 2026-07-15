def create_intro_tables(cursor):
    # 1. Users Table (Maps your existing user_id to this app's role)
    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS IntroUsers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('fingerlings_seller', 'catfish_seller', 'tilapia_seller', 'feed_seller')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )

    # 2. Fingerlings Batches
    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS Fingerlings (
            id TEXT PRIMARY KEY,
            intro_user_id INTEGER NOT NULL,
            species TEXT NOT NULL CHECK(species IN ('catfish', 'tilapia')),
            count INTEGER NOT NULL DEFAULT 0,
            is_jumbo BOOLEAN DEFAULT false,
            ready_at TIMESTAMP NOT NULL,
            FOREIGN KEY(intro_user_id) REFERENCES IntroUsers(id) ON DELETE CASCADE
        )
        '''
    )

    # 3. Mature Stock (Handles both Catfish and Tilapia)
    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS MatureStock (
            id TEXT PRIMARY KEY,
            intro_user_id INTEGER NOT NULL,
            species TEXT NOT NULL CHECK(species IN ('catfish', 'tilapia')),
            pond TEXT NOT NULL,
            count INTEGER NOT NULL,
            avg_weight_kg REAL NOT NULL,
            price_per_kg REAL NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            FOREIGN KEY(intro_user_id) REFERENCES IntroUsers(id) ON DELETE CASCADE
        )
        '''
    )

    # 4. Feed Inventory
    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS FeedInventory (
            id TEXT PRIMARY KEY,
            intro_user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            brand TEXT NOT NULL,
            size_mm REAL NOT NULL,
            bags_in_stock INTEGER NOT NULL,
            price_per_bag REAL NOT NULL,
            reorder_level INTEGER NOT NULL,
            FOREIGN KEY(intro_user_id) REFERENCES IntroUsers(id) ON DELETE CASCADE
        )
        '''
    )

    # 5. Notifications
    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS Notifications (
            id TEXT PRIMARY KEY,
            intro_user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            level TEXT NOT NULL CHECK(level IN ('info', 'warning', 'success')),
            is_read BOOLEAN DEFAULT 0,
            created_at TIMESTAMP NOT NULL,
            FOREIGN KEY(intro_user_id) REFERENCES IntroUsers(id) ON DELETE CASCADE
        )
        '''
    )
