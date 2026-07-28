import sqlite3

def create_console_tables(cursor: sqlite3.Cursor):
    # User Roles
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS Console_User_Roles (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            role TEXT CHECK( role IN ('admin', 'super admin', 'worker', 'manager') ) NOT NULL DEFAULT 'worker',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES Users(id) ON DELETE CASCADE
        )
        """
    )

    # Categories
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS Console_Categories (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            created_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(created_by) REFERENCES Users(id) ON DELETE SET NULL
        )
        """
    )

    # Expenses
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS Console_Expenses (
            id TEXT PRIMARY KEY,
            expense_number TEXT UNIQUE NOT NULL,
            category_id TEXT,
            category_name TEXT,
            vendor_name TEXT,
            amount REAL NOT NULL DEFAULT 0.0,
            description TEXT,
            expense_date DATE NOT NULL,
            status TEXT CHECK( status IN ('pending', 'paid', 'rejected', 'void') ) NOT NULL DEFAULT 'pending',
            created_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(category_id) REFERENCES Console_Categories(id) ON DELETE SET NULL,
            FOREIGN KEY(created_by) REFERENCES Users(id) ON DELETE SET NULL
        )
        """
    )

    # Monthly Budgets
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS Console_Monthly_Budgets (
            id TEXT PRIMARY KEY,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            budget_amount REAL NOT NULL DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # Expense Reports
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS Console_Expense_Reports (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            report_type TEXT,
            generated_by TEXT,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            file_url TEXT,
            FOREIGN KEY(generated_by) REFERENCES Users(id) ON DELETE SET NULL
        )
        """
    )

    # Workers
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS Console_Workers (
            id TEXT PRIMARY KEY,
            full_name TEXT NOT NULL,
            role TEXT,
            status TEXT CHECK( status IN ('active', 'on_leave') ) NOT NULL DEFAULT 'active',
            email TEXT,
            phone TEXT,
            salary REAL NOT NULL DEFAULT 0.0,
            joined_date DATE,
            left_date DATE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

def create_console_indexes(cursor: sqlite3.Cursor):
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_console_user_roles_user_id ON Console_User_Roles(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_console_expenses_category_id ON Console_Expenses(category_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_console_expenses_expense_date ON Console_Expenses(expense_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_console_expenses_status ON Console_Expenses(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_console_monthly_budgets_year_month ON Console_Monthly_Budgets(year, month)")
