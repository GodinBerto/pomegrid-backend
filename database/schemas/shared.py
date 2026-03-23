def create_shared_tables(cursor):
    cursor.execute(
        '''
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
            verification_channel TEXT CHECK(verification_channel IN ('email', 'phone')),
            verification_target TEXT,
            verification_code_expires_at TIMESTAMP,
            verified_at TIMESTAMP,
            accepted_policy BOOLEAN NOT NULL DEFAULT 0,
            policy_accepted_at TIMESTAMP,
            address TEXT,
            profile_image_url TEXT,
            avatar TEXT,
            is_active BOOLEAN NOT NULL DEFAULT 1,
            is_admin BOOLEAN NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

    cursor.execute(
        '''
            CREATE TABLE IF NOT EXISTS Admins(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES Users(id)
            )
        '''
    )


def create_shared_indexes(cursor):
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_conv_participants_user_id ON conversation_participants(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON notifications(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_notifications_is_read ON notifications(is_read)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_role ON Users(role)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_status ON Users(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_admin_conversations_user_id ON admin_conversations(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_admin_messages_conversation_id ON admin_messages(conversation_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_admin_messages_is_read ON admin_messages(is_read)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_admin_notifications_read ON admin_notifications(read)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_inventory_items_category ON inventory_items(category)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_inventory_items_is_active ON inventory_items(is_active)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_inventory_movements_item_id ON inventory_movements(item_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_payment_gateways_is_active ON payment_gateways(is_active)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sync_runs_status ON sync_runs(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sync_runs_started_at ON sync_runs(started_at)")
