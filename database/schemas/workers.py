def create_worker_tables(cursor):
    cursor.execute(
        '''
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
               created_by_admin_id INTEGER,
               updated_by_admin_id INTEGER,
               reviews_count INTEGER DEFAULT 0,
               is_available BOOLEAN DEFAULT 1,
               is_varified BOOLEAN DEFAULT false,
               hourly_rate INTEGER DEFAULT 0,
               years_experience INTEGER DEFAULT 0,
               completed_jobs INTEGER DEFAULT 0,
               created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
               updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        '''
    )

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
        '''
    )

    cursor.execute(
        '''
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
        '''
    )


def create_worker_indexes(cursor):
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_workers_location ON Workers(location)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_workers_profession ON Workers(profession)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_workers_is_available ON Workers(is_available)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_workers_ratings ON Workers(ratings)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_worker_services_worker_id ON worker_services(worker_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_worker_services_service_code ON worker_services(service_code)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bookings_worker_id ON bookings(worker_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bookings_user_id ON bookings(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bookings_customer_id ON bookings(customer_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bookings_service_id ON bookings(service_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bookings_requested_date ON bookings(requested_date)")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_bookings_code_unique ON bookings(code)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_worker_profiles_user_id ON worker_profiles(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_worker_profiles_location ON worker_profiles(location)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_worker_profiles_verified ON worker_profiles(verified)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_services_worker_type ON services(worker_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_services_is_active ON services(is_active)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_job_status_history_job_id ON job_status_history(job_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reviews_worker_id ON reviews(worker_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reviews_customer_id ON reviews(customer_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wallet_transactions_wallet_id ON wallet_transactions(wallet_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wallet_transactions_status ON wallet_transactions(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_withdrawal_requests_worker_id ON withdrawal_requests(worker_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_withdrawal_requests_status ON withdrawal_requests(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_worker_id ON Jobs(worker_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON Jobs(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON Jobs(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ratings_worker_id ON Worker_Ratings(worker_id)")
