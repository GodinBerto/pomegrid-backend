# Task
- I want you to create the backend endpoints for this.
- I want you to create the tables and indexes for the following models:
  - User: The table for the user is already created so dont touch it.
  - User Roles: Use the user id from the user table, For now use hese roles admin, super admin, worker and manager.
    - admin: Can do everything.
    - super admin: Can do everything except creating super admin.
    - worker: Can do nothing except creating workers.
    - manager: Can do everything except creating manager and super admin.
  - Categories:
        id (UUID)
        name
        description
        created_by
        created_at
        updated_at
  - Expenses: 
        id (UUID)
        expense_number (EXP-1042 - this is just an example but should start with EXP- and followed by 6 digits in descending order e.g., EXP-999999 and it should be unique for each expense)
        category_id (FK)
        category_name
        vendor_name
        amount
        description
        expense_date
        status (pending, paid, rejected, void)
        created_by
        created_at
        updated_at
  - monthly_budgets
        id
        year
        month
        budget_amount - by default it should be 0
        created_at
  - expense_reports
        id
        title
        report_type
        generated_by
        generated_at
        file_url
  - Workers
        id
        full_name
        role
        status (active, on_leave)
        email: can be null
        phone: can be null
        salary
        joined_date: should be date
        left_date: should be date and can be null
        created_at
        updated_at

# Endpoints
- User Roles:
  - POST: / - Create user roles.
  - GET: /roles/user - Use the token to get user id and use it fetch fetch the user roles.
  - GET: /roles - Get all user roles.
  - GET: /roles/{id} - Get user role by id.
  - PUT: /roles/{id} - Update user role by id.
  - DELETE: /roles/{id} - Delete user role by id.
- Expenses:
  - GET /expenses - for all expense: props=created-date, categoryid, vendor_name, highest_amount, lowest_amount
  - POST /expenses
  - GET /expenses/{id}
  - PUT /expenses/{id}
  - DELETE /expenses/{id}
  - POST /expenses/{id}/status - body {status:"pending" || "paid" || "rejected" || "void"} for he created by use the user id from the token
- Monthly Budgets: i want the montly budget to be simple with only updaing the budget amount and should use tme and date to track it for each month.
  - POST /monthly-budgets
  - GET /monthly-budgets
  - GET /monthly-budgets/{id}
  - PUT /monthly-budgets/{id}
- Expense Reports:
  - GET /expense-reports
  - POST /expense-reports
  - GET /expense-reports/{id}
  - PUT /expense-reports/{id}
  - DELETE /expense-reports/{id}
- Overview
  - GET /overview - Get overview of the console.
    - Monthly budget with percentage that it increased or decreased from the previous month.
    - Spent this month with percentage that it increased or decreased from the previous month.
    - Remaining budget with percentage that it increased or decreased from the previous month.
    - Active workers with number that it increased or decreased from the previous month.
  - GET / overviewBudgetChart - Get overview budget chart.
    - x = month - for budget chart.
    - y = total budget amount - for budget chart.
    - x = month - for actual spend
    - y = total amount spent - for actual spend.
  - GET / recent-expenses - Get recent expenses.
    - Get last 5 expenses.
    - Limit = 5
  - GET / weekly-burn-chart - Get weekly burn chart.
    - x = day
    - y = total amount spent
- Workers
  - GET /workers - Get all workers.
  - POST /workers - Create worker.
  - GET /workers/{id} - Get worker by id.
  - PUT /workers/{id} - Update worker by id.
  - DELETE /workers/{id} - Delete worker by id.
- Reports
  - Generate, download, and print reports to run and review the business.
  - GET /reports - Get all reports.
  - GET /reports/{id} - Get report by id.
  - GET /reports/{id}/download - Download report by id.
  - GET /reports/{id}/print - Print report by id.
  - GET /reports/monthly-expense-summary - Get monthly expense summary.
  - GET /reports/payroll-register - Get payroll register.
  - GET /reports/budget-vs-actual - Get budget vs actual.
  - GET /reports/vendor-spend - Get vendor spend.
  - GET /reports/cash-burn - Get cash burn.
  - GET /reports/tax-ready-ledger - Get tax ready ledger.
  - GET /reports/pdf - Download report as PDF.
  - GET /reports/csv - Download report as CSV.
  - GET /reports/print - Print report.

Note: Follow my structure by using everything inmy project. Also will use the authentication for logging in so use the token when looking for the user id. 