def create_connect_tables(cursor):
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


def create_connect_indexes(cursor):
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_connect_profiles_account_type ON ConnectProfiles(account_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_connect_profiles_country ON ConnectProfiles(country)")
