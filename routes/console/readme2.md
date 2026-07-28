# Task 2
- we are goring to work on the monthly budget, analysis charts and settings.
- make sure you follow my structure.

## Monthly Budget
- i want this endpoint to update or create it using the month, year and amount
- if the month and year are already present, update the amount, otherwise create a new entry
"""
@console_bp.route("/monthly-budgets/<budget_id>", methods=["PUT"])
@jwt_required()
def update_monthly_budget(budget_id):
    data = request.get_json() or {}
    budget_amount = data.get("budget_amount")
    
    if budget_amount is None:
        return jsonify(envelope(None, "budget_amount is required", 400, False)), 400

    try:
        conn, cursor = db_connection()
        cursor.execute(
            "UPDATE Console_Monthly_Budgets SET budget_amount = ? WHERE id = ?", 
            (budget_amount, budget_id)
        )
        if cursor.rowcount == 0:
            return jsonify(envelope(None, "Monthly budget not found", 404, False)), 404
        conn.commit()
        return jsonify(envelope({"id": budget_id}, "Monthly budget updated successfully")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500

@console_bp.route("/monthly-budgets", methods=["POST"])
@jwt_required()
def create_monthly_budget():
    data = request.get_json() or {}
    
    year = data.get("year")
    month = data.get("month")
    budget_amount = data.get("budget_amount", 0.0)
    
    if year is None or month is None:
        now = datetime.now()
        year = now.year
        month = now.month
        
    budget_id = str(uuid.uuid4())
    try:
        conn, cursor = db_connection()
        cursor.execute(
            """
            INSERT INTO Console_Monthly_Budgets (id, year, month, budget_amount)
            VALUES (?, ?, ?, ?)
            """,
            (budget_id, year, month, budget_amount)
        )
        conn.commit()
        return jsonify(envelope({"id": budget_id}, "Monthly budget created successfully", 201)), 201
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500

"""

## Analytics Endpoints
- Create for Budget Efficiency. this chart is for how close spendsstays to budget. its a radial bar chart.
- for Monthly savings. This chart is for budget minus actual, per month. its a bar chart
- for Category momentum. spend shape accross categories.
- for Weekly rythem. when mony leaves the business. Area chart.

### How the Analystics page code looks like
"""
"use client";
import { PageHeader, Section, Card } from "@/components/page-header";
import {
  monthlySpend,
  categoryBreakdown,
  weeklyBurn,
} from "@/lib/dashboard-data";
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  RadialBarChart,
  RadialBar,
  PolarAngleAxis,
} from "recharts";

export default function AnalyticsPage() {
  const savings = monthlySpend.map((m) => ({
    month: m.month,
    savings: m.budget - m.actual,
  }));
  const efficiency = [
    { name: "Efficiency", value: 78, fill: "var(--color-chart-1)" },
  ];

  return (
    <>
      <PageHeader title="Analytics" />
      <Section>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <Card
            title="Budget efficiency"
            description="How close spend stays to budget"
            className="lg:col-span-1"
          >
            <div className="h-56 flex items-center justify-center">
              <ResponsiveContainer width="100%" height="100%">
                <RadialBarChart
                  innerRadius="70%"
                  outerRadius="100%"
                  data={efficiency}
                  startAngle={90}
                  endAngle={-270}
                >
                  <PolarAngleAxis
                    type="number"
                    domain={[0, 100]}
                    tick={false}
                  />
                  <RadialBar
                    dataKey="value"
                    cornerRadius={20}
                    background={{ fill: "var(--color-surface-muted)" }}
                  />
                </RadialBarChart>
              </ResponsiveContainer>
            </div>
            <div className="text-center -mt-34 pointer-events-none">
              <p className="text-3xl font-semibold text-brand">78%</p>
              <p className="text-xs text-muted-foreground">on-target months</p>
            </div>
            <div className="mt-16 text-xs text-muted-foreground text-center">
              9 of the last 12 months stayed within budget.
            </div>
          </Card>

          <Card
            title="Monthly savings"
            description="Budget minus actual, per month"
            className="lg:col-span-2"
          >
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={savings}
                  margin={{ left: -10, right: 8, top: 8, bottom: 0 }}
                >
                  <CartesianGrid
                    stroke="var(--color-border)"
                    strokeDasharray="3 3"
                    vertical={false}
                  />
                  <XAxis
                    dataKey="month"
                    stroke="var(--color-muted-foreground)"
                    fontSize={11}
                    tickLine={false}
                    axisLine={false}
                  />
                  <YAxis
                    stroke="var(--color-muted-foreground)"
                    fontSize={11}
                    tickLine={false}
                    axisLine={false}
                  />
                  <Tooltip
                    contentStyle={{
                      borderRadius: 8,
                      border: "1px solid var(--color-border)",
                      fontSize: 12,
                    }}
                  />
                  <Bar
                    dataKey="savings"
                    fill="var(--color-chart-1)"
                    radius={[4, 4, 0, 0]}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>
        </div>

        <div className="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Card
            title="Category momentum"
            description="Spend shape across categories"
          >
            <ul className="space-y-3">
              {categoryBreakdown.map((c) => {
                const total = categoryBreakdown.reduce(
                  (s, x) => s + x.value,
                  0,
                );
                const pct = Math.round((c.value / total) * 100);
                return (
                  <li key={c.name}>
                    <div className="flex items-center justify-between text-sm">
                      <span>{c.name}</span>
                      <span className="text-muted-foreground">
                        ${c.value.toLocaleString()} · {pct}%
                      </span>
                    </div>
                    <div className="mt-1 h-1.5 rounded-full bg-surface-muted overflow-hidden">
                      <div
                        className="h-full rounded-full"
                        style={{ width: pct + "%", background: c.color }}
                      />
                    </div>
                  </li>
                );
              })}
            </ul>
          </Card>

          <Card
            title="Weekly rhythm"
            description="When money leaves the business"
          >
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart
                  data={weeklyBurn}
                  margin={{ left: -20, right: 8, top: 8, bottom: 0 }}
                >
                  <defs>
                    <linearGradient id="ga" x1="0" y1="0" x2="0" y2="1">
                      <stop
                        offset="0%"
                        stopColor="var(--color-chart-2)"
                        stopOpacity={0.35}
                      />
                      <stop
                        offset="100%"
                        stopColor="var(--color-chart-2)"
                        stopOpacity={0}
                      />
                    </linearGradient>
                  </defs>
                  <CartesianGrid
                    stroke="var(--color-border)"
                    strokeDasharray="3 3"
                    vertical={false}
                  />
                  <XAxis
                    dataKey="day"
                    stroke="var(--color-muted-foreground)"
                    fontSize={11}
                    tickLine={false}
                    axisLine={false}
                  />
                  <YAxis
                    stroke="var(--color-muted-foreground)"
                    fontSize={11}
                    tickLine={false}
                    axisLine={false}
                  />
                  <Tooltip
                    contentStyle={{
                      borderRadius: 8,
                      border: "1px solid var(--color-border)",
                      fontSize: 12,
                    }}
                  />
                  <Area
                    type="monotone"
                    dataKey="spend"
                    stroke="var(--color-chart-2)"
                    fill="url(#ga)"
                    strokeWidth={2}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </Card>
        </div>
      </Section>
    </>
  );
}
"""
- make sure it follows my code. i mean the endpoint structure

## Settings Endpoint
- Create the endpoints for this page. 
- This settings is for the consol.
"""
"use client";
import { useState } from "react";
import { PageHeader, Section, Card } from "@/components/page-header";
import { toast } from "sonner";

const SECTIONS = [
  "Personal",
  "Security",
  "Notifications",
] as const;

export default function SettingsPage() {
  const [tab, setTab] = useState<(typeof SECTIONS)[number]>("Personal");

  return (
    <>
      <PageHeader
        title="Settings"
        description="Organization details, preferences, and security."
      />
      <Section>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-1">
            <nav className="text-sm space-y-1">
              {SECTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => setTab(s)}
                  className={
                    "w-full text-left px-3 py-2 rounded-md " +
                    (tab === s
                      ? "bg-surface-muted font-medium"
                      : "text-muted-foreground hover:text-foreground hover:bg-surface-muted")
                  }
                >
                  {s}
                </button>
              ))}
            </nav>
          </div>
          <div className="lg:col-span-2 space-y-4">
            {tab === "Personal" && <PersonalTab />}
            {tab === "Notifications" && <NotificationsTab />}
            {tab === "Security" && <SecurityTab />}
          </div>
        </div>
      </Section>
    </>
  );
}


function PersonalTab() {
  return (
    <Card title="Personal" description="Your personal information.">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          toast.success("Personal information saved");
        }}
        className="space-y-4"
      >
        <Field
          label="Full Name"
          defaultValue="Pomegrid"
          type="text"
        />
        <Field label="Phone Number" defaultValue="08012345678" />
        <Field label="Email" defaultValue="" type="email" />
        <div className="pt-2">
          <button className="h-9 px-4 rounded-md bg-brand text-brand-foreground text-sm font-medium hover:bg-brand/90">
            Save preferences
          </button>
        </div>
      </form>
    </Card>
  );
}

function NotificationsTab() {
  const [prefs, setPrefs] = useState({
    budget: true,
    payroll: true,
    weekly: false,
  });
  return (
    <Card
      title="Notifications"
      description="Choose when the console should email you."
    >
      <div className="space-y-3">
        <Toggle
          label="Budget threshold alerts"
          checked={prefs.budget}
          onChange={(v) => setPrefs({ ...prefs, budget: v })}
        />
        <Toggle
          label="Payroll reminders"
          checked={prefs.payroll}
          onChange={(v) => setPrefs({ ...prefs, payroll: v })}
        />
        <Toggle
          label="Weekly summary email"
          checked={prefs.weekly}
          onChange={(v) => setPrefs({ ...prefs, weekly: v })}
        />
      </div>
      <div className="pt-4">
        <button
          onClick={() => toast.success("Notifications saved")}
          className="h-9 px-4 rounded-md bg-brand text-brand-foreground text-sm font-medium hover:bg-brand/90"
        >
          Save
        </button>
      </div>
    </Card>
  );
}

function SecurityTab() {
  return (
    <Card title="Security" description="Password and access.">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          toast.success("Password updated");
        }}
        className="space-y-4"
      >
        <Field label="Current password" defaultValue="" type="password" />
        <Field label="New password" defaultValue="" type="password" />
        <Field label="Confirm new password" defaultValue="" type="password" />
        <div className="pt-2">
          <button className="h-9 px-4 rounded-md bg-brand text-brand-foreground text-sm font-medium hover:bg-brand/90">
            Update password
          </button>
        </div>
      </form>
    </Card>
  );
}

function Field({
  label,
  defaultValue,
  type = "text",
}: {
  label: string;
  defaultValue: string;
  type?: string;
}) {
  return (
    <div>
      <label className="text-xs font-medium">{label}</label>
      <input
        type={type}
        defaultValue={defaultValue}
        className="mt-1 w-full h-10 px-3 rounded-md border border-input bg-background text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
      />
    </div>
  );
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-4 p-3 rounded-md border border-border">
      <span className="text-sm">{label}</span>
      <button
        type="button"
        onClick={() => onChange(!checked)}
        className={
          "relative h-5 w-9 rounded-full transition " +
          (checked ? "bg-brand" : "bg-muted")
        }
      >
        <span
          className={
            "absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all " +
            (checked ? "left-4" : "left-0.5")
          }
        />
      </button>
    </label>
  );
}
""" this is the frontend page. create what will be needed here

## Notification Endpoints
- Update the general noification table to include app,  i mean the notification table so that when users get notifications we can use the selected app example like pomegid console or pomegrid farms. i will pass the app name string as a prop to the endpoints so that when i am fetching for the notification for that app i can do it.
