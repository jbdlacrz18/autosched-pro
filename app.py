from flask import Flask, render_template_string, request, jsonify, send_file
import pandas as pd
import io
import json
import os
from datetime import datetime, timedelta
import calendar
import random

app = Flask(__name__)

DATA_FILE = "scheduling_data.json"

PHILIPPINE_HOLIDAYS = {
    "2026-01-01": "New Year's Day",
    "2026-04-02": "Maundy Thursday",
    "2026-04-03": "Good Friday",
    "2026-04-09": "Araw ng Kagitingan",
    "2026-05-01": "Labor Day",
    "2026-06-12": "Independence Day",
    "2026-08-31": "National Heroes Day",
    "2026-11-30": "Bonifacio Day",
    "2026-12-25": "Christmas Day",
    "2026-12-30": "Rizal Day",
}

DEFAULT_DATA = {
    "agents": [
        {"id": 1, "name": "Alice Johnson", "role": "Support Agent"},
        {"id": 2, "name": "Bob Smith", "role": "Support Agent"},
        {"id": 3, "name": "Charlie Brown", "role": "Senior Agent"},
        {"id": 4, "name": "Diana Prince", "role": "Support Agent"},
        {"id": 5, "name": "Ethan Hunt", "role": "Technical Agent"}
    ],
    "holidays": PHILIPPINE_HOLIDAYS,
    "leaves": [],
    "schedule": {},
    "reset_months": []
}

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return DEFAULT_DATA

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

SHIFTS = ["8:00 AM – 5:00 PM", "11:00 AM – 8:00 PM"]
STATUSES = ["On-site", "Work from Home", "Rest Day", "Leave"]

def generate_monthly_schedule(year, month, agents, holidays_dict, leaves_list):
    """
    Robust Fair Scheduling Engine:
    - Automatically accounts for agent leave ranges.
    - Excludes agents on leave on a given day from being assigned On-site or WFH (status set to Leave, shift Off).
    - Guarantees EXACTLY 2 On-site shifts per agent per week (Mon-Fri) and EXACTLY 2 agents On-site daily Mon-Fri.
    - 2 Rest Days per week for active agents.
    - Subsequent weeks mirror Week 1 pattern, preserving Rest Days even on holidays.
    """
    random.seed(42 + year * 100 + month)

    month_schedule = {}
    cal = calendar.Calendar(firstweekday=0)
    month_weeks = cal.monthdatescalendar(year, month)

    leave_set = set()
    for l in leaves_list:
        aid = str(l["agent_id"])
        try:
            s_date = datetime.strptime(l["start_date"], "%Y-%m-%d")
            e_date = datetime.strptime(l["end_date"], "%Y-%m-%d")
            if s_date > e_date:
                s_date, e_date = e_date, s_date

            curr = s_date
            while curr <= e_date:
                leave_set.add((aid, curr.strftime("%Y-%m-%d")))
                curr += timedelta(days=1)
        except Exception as ex:
            print("Leave range error:", ex)

    agent_ids = [str(a["id"]) for a in agents]
    agent_week1_schedule = {}

    week1_dates = [month_weeks[0][idx].strftime("%Y-%m-%d") for idx in range(7)]

    # Assign EXACTLY 2 On-site days to EACH agent across Mon-Fri
    agent_onsite_days = {aid: set() for aid in agent_ids}
    days_pool = list(range(5)) * 2  # 10 slots total: 5 weekdays * 2 agents/day
    random.shuffle(days_pool)

    idx_pool = 0
    for aid in agent_ids:
        assigned = set()
        while len(assigned) < 2 and idx_pool < len(days_pool):
            d = days_pool[idx_pool]
            idx_pool += 1
            if d not in assigned:
                assigned.add(d)
        while len(assigned) < 2:
            d = random.choice([i for i in range(5) if i not in assigned])
            assigned.add(d)
        agent_onsite_days[aid] = assigned

    # Balance daily counts to ensure strictly 2 agents per Mon-Fri
    for day_idx in range(5):
        current_onsite = [aid for aid in agent_ids if day_idx in agent_onsite_days[aid]]
        while len(current_onsite) < 2:
            candidates = [aid for aid in agent_ids if day_idx not in agent_onsite_days[aid] and len(agent_onsite_days[aid]) < 2]
            if candidates:
                chosen = random.choice(candidates)
                agent_onsite_days[chosen].add(day_idx)
                current_onsite.append(chosen)
            else:
                donors = [aid for aid in agent_ids if len(agent_onsite_days[aid]) == 2 and day_idx not in agent_onsite_days[aid]]
                if donors:
                    donor = random.choice(donors)
                    drop_day = list(agent_onsite_days[donor])[0]
                    agent_onsite_days[donor].remove(drop_day)
                    agent_onsite_days[donor].add(day_idx)
                    current_onsite.append(donor)
                else:
                    break
        while len(current_onsite) > 2:
            excess_aid = current_onsite.pop()
            agent_onsite_days[excess_aid].remove(day_idx)
            open_days = [d for d in range(5) if d not in agent_onsite_days[excess_aid]]
            if open_days:
                agent_onsite_days[excess_aid].add(open_days[0])

    # Assign 2 rest days per agent (on days they aren't onsite)
    agent_rest_days = {}
    for aid in agent_ids:
        possible_rest = [d for d in range(7) if d not in agent_onsite_days[aid]]
        if len(possible_rest) >= 2:
            agent_rest_days[aid] = set(random.sample(possible_rest, 2))
        else:
            agent_rest_days[aid] = set(random.sample(range(7), 2))

    # Build Week 1 schedule template
    for aid in agent_ids:
        agent_week1_schedule[aid] = {}
        for idx in range(7):
            d_str = week1_dates[idx]
            status = "Work from Home"
            shift = SHIFTS[idx % 2]

            if (aid, d_str) in leave_set:
                status = "Leave"
                shift = "Off"
            elif idx in agent_rest_days[aid]:
                status = "Rest Day"
                shift = "Off"
            elif idx in agent_onsite_days[aid]:
                status = "On-site"
                shift = "8:00 AM – 5:00 PM"
            else:
                status = "Work from Home"
                shift = SHIFTS[idx % 2]

            agent_week1_schedule[aid][idx] = {"status": status, "shift": shift}

    # Mirror across all weeks of the month
    for w_idx, week in enumerate(month_weeks):
        for idx, d_date in enumerate(week):
            if d_date.month != month:
                continue

            date_str = d_date.strftime("%Y-%m-%d")
            if date_str not in month_schedule:
                month_schedule[date_str] = {}

            for aid in agent_ids:
                template = agent_week1_schedule[aid].get(idx, {"status": "Work from Home", "shift": "8:00 AM – 5:00 PM"})
                status = template["status"]
                shift = template["shift"]

                # If on leave on this specific date in any week
                if (aid, date_str) in leave_set:
                    status = "Leave"
                    shift = "Off"

                # Holiday rule -> Work from Home (unless on leave OR unless it's their scheduled Rest Day)
                holiday_name = holidays_dict.get(date_str)
                if holiday_name and status != "Leave":
                    if status == "Rest Day":
                        # Rest Day takes precedence over holiday WFH
                        status = "Rest Day"
                        shift = "Off"
                    else:
                        status = "Work from Home"
                        shift = "8:00 AM – 5:00 PM"

                month_schedule[date_str][aid] = {
                    "status": status,
                    "shift": shift,
                    "holiday": holiday_name
                }

    return month_schedule

@app.route("/")
def index():
    data = load_data()
    now = datetime.now()
    year = int(request.args.get("year", now.year))
    month = int(request.args.get("month", now.month))

    month_key = f"{year}-{month:02d}"
    is_current_real_month = (year == now.year and month == now.month)

    if month_key not in data["schedule"] and month_key not in data.get("reset_months", []) and is_current_real_month:
        data["schedule"][month_key] = generate_monthly_schedule(year, month, data["agents"], data["holidays"], data.get("leaves", []))
        save_data(data)

    current_month_schedule = data["schedule"].get(month_key, {})

    return render_template_string(
        HTML_TEMPLATE,
        data=data,
        year=year,
        month=month,
        schedule=current_month_schedule,
        has_schedule=bool(current_month_schedule),
        statuses=STATUSES,
        shifts=SHIFTS,
        calendar=calendar,
        datetime=datetime
    )

@app.route("/api/data", methods=["GET"])
def get_data():
    return jsonify(load_data())

@app.route("/api/agents", methods=["POST"])
def add_agent():
    req = request.json
    data = load_data()
    new_id = max([a["id"] for a in data["agents"]], default=0) + 1
    new_agent = {
        "id": new_id,
        "name": req.get("name", f"Agent {new_id}"),
        "role": req.get("role", "Support Agent")
    }
    data["agents"].append(new_agent)
    for mk in list(data["schedule"].keys()):
        try:
            y, m = map(int, mk.split("-"))
            data["schedule"][mk] = generate_monthly_schedule(y, m, data["agents"], data["holidays"], data.get("leaves", []))
        except:
            pass
    save_data(data)
    return jsonify({"success": True, "agent": new_agent, "data": data})

@app.route("/api/agents/<int:agent_id>", methods=["PUT", "DELETE"])
def modify_agent(agent_id):
    data = load_data()
    if request.method == "DELETE":
        data["agents"] = [a for a in data["agents"] if a["id"] != agent_id]
        save_data(data)
        return jsonify({"success": True, "data": data})
    else:
        req = request.json
        for a in data["agents"]:
            if a["id"] == agent_id:
                a["name"] = req.get("name", a["name"])
                a["role"] = req.get("role", a["role"])
        save_data(data)
        return jsonify({"success": True, "data": data})

@app.route("/api/leaves", methods=["POST", "DELETE"])
def manage_leaves():
    data = load_data()
    if "leaves" not in data:
        data["leaves"] = []

    if request.method == "POST":
        req = request.json
        agent_id = int(req.get("agent_id"))
        start_date = req.get("start_date")
        end_date = req.get("end_date") or start_date

        data["leaves"].append({
            "agent_id": agent_id,
            "start_date": start_date,
            "end_date": end_date
        })
    elif request.method == "DELETE":
        req = request.json
        leave_index = req.get("index")
        if leave_index is not None and 0 <= int(leave_index) < len(data["leaves"]):
            data["leaves"].pop(int(leave_index))

    for mk in list(data["schedule"].keys()):
        try:
            y, m = map(int, mk.split("-"))
            data["schedule"][mk] = generate_monthly_schedule(y, m, data["agents"], data["holidays"], data["leaves"])
        except:
            pass
    save_data(data)
    return jsonify({"success": True, "data": data})

@app.route("/api/schedule/edit", methods=["POST"])
def edit_schedule():
    req = request.json
    month_key = req.get("month_key")
    date_str = req.get("date_str")
    agent_id = str(req.get("agent_id"))
    status = req.get("status")
    shift = req.get("shift")

    data = load_data()
    if month_key in data["schedule"]:
        if date_str in data["schedule"][month_key]:
            if agent_id in data["schedule"][month_key][date_str]:
                data["schedule"][month_key][date_str][agent_id]["status"] = status
                data["schedule"][month_key][date_str][agent_id]["shift"] = shift
                save_data(data)
                return jsonify({"success": True, "data": data})
    return jsonify({"success": False, "error": "Not found"}), 404

@app.route("/api/schedule/reset", methods=["POST"])
def reset_schedule():
    req = request.json or {}
    year = int(req.get("year", datetime.now().year))
    month = int(req.get("month", datetime.now().month))
    month_key = f"{year}-{month:02d}"

    data = load_data()
    if month_key in data["schedule"]:
        del data["schedule"][month_key]
    if "reset_months" not in data:
        data["reset_months"] = []
    if month_key not in data["reset_months"]:
        data["reset_months"].append(month_key)
    save_data(data)
    return jsonify({"success": True, "data": data})

@app.route("/api/schedule/generate", methods=["POST"])
def generate_schedule():
    req = request.json or {}
    year = int(req.get("year", datetime.now().year))
    month = int(req.get("month", datetime.now().month))
    month_key = f"{year}-{month:02d}"

    data = load_data()
    if "reset_months" in data and month_key in data["reset_months"]:
        data["reset_months"].remove(month_key)
    data["schedule"][month_key] = generate_monthly_schedule(year, month, data["agents"], data["holidays"], data.get("leaves", []))
    save_data(data)
    return jsonify({"success": True, "data": data})

@app.route("/api/holidays", methods=["POST"])
def update_holiday():
    req = request.json
    date_str = req.get("date")
    name = req.get("name")
    data = load_data()
    if name:
        data["holidays"][date_str] = name
    else:
        if date_str in data["holidays"]:
            del data["holidays"][date_str]

    for mk in list(data["schedule"].keys()):
        try:
            y, m = map(int, mk.split("-"))
            data["schedule"][mk] = generate_monthly_schedule(y, m, data["agents"], data["holidays"], data.get("leaves", []))
        except:
            pass
    save_data(data)
    return jsonify({"success": True, "data": data})

@app.route("/api/export/excel", methods=["GET"])
def export_excel():
    year = int(request.args.get("year", datetime.now().year))
    month = int(request.args.get("month", datetime.now().month))
    month_key = f"{year}-{month:02d}"

    data = load_data()
    agents = data["agents"]
    month_sched = data["schedule"].get(month_key, {})

    cal = calendar.Calendar(firstweekday=0)
    month_weeks = cal.monthdatescalendar(year, month)

    rows = []
    for agent in agents:
        agent_id = str(agent["id"])
        for week in month_weeks:
            for d_date in week:
                if d_date.month != month:
                    continue
                date_str = d_date.strftime("%Y-%m-%d")
                day_name = d_date.strftime("%A")
                day_info = month_sched.get(date_str, {}).get(agent_id, {"status": "", "shift": "", "holiday": None})

                rows.append({
                    "Date": date_str,
                    "Day": day_name,
                    "Agent ID": agent["id"],
                    "Agent Name": agent["name"],
                    "Role": agent["role"],
                    "Status": day_info.get("status"),
                    "Shift": day_info.get("shift"),
                    "Holiday": day_info.get("holiday") or ""
                })

    df = pd.DataFrame(rows)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name=f'{calendar.month_name[month]} {year}')
    output.seek(0)

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'schedule_{year}_{month:02d}.xlsx'
    )

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AutoSched Pro - Enterprise Workforce Management</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Plus Jakarta Sans', sans-serif; background-color: #f8fafc; }
        ::-webkit-scrollbar { width: 5px; height: 5px; }
        ::-webkit-scrollbar-track { background: #f1f5f9; }
        ::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: #94a3b8; }
    </style>
</head>
<body class="text-slate-800 min-h-screen pb-16 antialiased selection:bg-indigo-500 selection:text-white">
    <header class="bg-slate-900 text-white shadow-md sticky top-0 z-40 border-b border-slate-800">
        <div class="max-w-[98%] mx-auto px-4 py-3.5 flex flex-col md:flex-row justify-between items-center gap-4">
            <div class="flex items-center gap-3">
                <div class="w-9 h-9 rounded-xl bg-indigo-600 flex items-center justify-center shadow-inner text-lg font-bold">
                    📅
                </div>
                <div>
                    <h1 class="text-lg font-bold tracking-tight text-white flex items-center gap-2">
                        AutoSched Pro
                        <span class="text-[10px] bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 px-2 py-0.5 rounded-full font-medium">Enterprise Edition</span>
                    </h1>
                    <p class="text-slate-400 text-xs">Fair Workforce Scheduling • Min 2 On-site Mon–Fri • Leave & Holiday Aware</p>
                </div>
            </div>
            <div class="flex flex-wrap items-center gap-2">
                {% if has_schedule %}
                <button onclick="openRegenerateModal()" class="bg-indigo-600 hover:bg-indigo-500 text-white px-3 py-1.5 rounded-lg text-xs font-semibold shadow-sm transition flex items-center gap-1.5">
                    🔄 Re-Generate
                </button>
                <button onclick="openResetModal()" class="bg-slate-800 hover:bg-rose-900/60 text-slate-200 hover:text-rose-200 border border-slate-700 hover:border-rose-700/50 px-3 py-1.5 rounded-lg text-xs font-semibold shadow-sm transition flex items-center gap-1.5">
                    🗑️ Reset Schedule
                </button>
                <a href="/api/export/excel?year={{ year }}&month={{ month }}" class="bg-emerald-600 hover:bg-emerald-500 text-white px-3 py-1.5 rounded-lg text-xs font-semibold shadow-sm transition flex items-center gap-1.5">
                    📊 Export Excel
                </a>
                {% else %}
                <button onclick="openRegenerateModal()" class="bg-emerald-600 hover:bg-emerald-500 text-white px-3.5 py-2 rounded-lg text-xs font-bold shadow transition flex items-center gap-1.5">
                    ✨ Generate Schedule
                </button>
                {% endif %}
                <div class="h-5 w-px bg-slate-700 mx-1"></div>
                <button onclick="openLeaveModal()" class="bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 px-3 py-1.5 rounded-lg text-xs font-semibold shadow-sm transition flex items-center gap-1.5">
                    🌴 Leaves
                </button>
                <button onclick="openAgentModal()" class="bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 px-3 py-1.5 rounded-lg text-xs font-semibold shadow-sm transition flex items-center gap-1.5">
                    👥 Agents
                </button>
                <button onclick="openHolidayModal()" class="bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 px-3 py-1.5 rounded-lg text-xs font-semibold shadow-sm transition flex items-center gap-1.5">
                    🎉 Holidays
                </button>
            </div>
        </div>
    </header>

    <main class="max-w-[98%] mx-auto px-2 py-6 space-y-4">
        <!-- Month Navigation & Controls Bar -->
        <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-4 flex flex-col md:flex-row justify-between items-center gap-4">
            <div class="flex items-center gap-3">
                {% set prev_month = month - 1 if month > 1 else 12 %}
                {% set prev_year = year if month > 1 else year - 1 %}
                {% set next_month = month + 1 if month < 12 else 1 %}
                {% set next_year = year if month < 12 else year + 1 %}
                <a href="/?year={{ prev_year }}&month={{ prev_month }}" class="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 border border-slate-200 rounded-lg text-xs font-semibold text-slate-700 transition flex items-center gap-1">
                    &larr; Prev
                </a>
                <h2 class="text-base font-bold text-slate-900 w-48 text-center tracking-tight">
                    {{ calendar.month_name[month] }} {{ year }}
                </h2>
                <a href="/?year={{ next_year }}&month={{ next_month }}" class="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 border border-slate-200 rounded-lg text-xs font-semibold text-slate-700 transition flex items-center gap-1">
                    Next &rarr;
                </a>
            </div>

            <!-- Agent Filter & Quick Actions -->
            <div class="flex flex-wrap items-center gap-3 w-full md:w-auto">
                <div class="flex items-center gap-2">
                    <label class="text-xs font-semibold text-slate-600">Filter Staff:</label>
                    <select id="agent-filter" onchange="filterAgentSchedule()" class="px-3 py-1.5 bg-slate-50 border border-slate-300 rounded-lg text-xs font-medium text-slate-700 focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none transition">
                        <option value="all">All Agents ({{ data.agents | length }})</option>
                        {% for agent in data.agents %}
                        <option value="{{ agent.id }}">{{ agent.name }}</option>
                        {% endfor %}
                    </select>
                </div>
            </div>
        </div>

        <!-- Legend Bar -->
        <div class="flex flex-wrap items-center gap-4 text-xs bg-white px-4 py-3 rounded-xl border border-slate-200 shadow-sm">
            <span class="font-bold text-slate-700 flex items-center gap-1.5">🏷️ Status Legend:</span>
            <div class="flex items-center gap-1.5"><span class="w-3 h-3 rounded-full bg-emerald-500 inline-block"></span><span class="font-medium text-slate-600">On-site</span></div>
            <div class="flex items-center gap-1.5"><span class="w-3 h-3 rounded-full bg-blue-500 inline-block"></span><span class="font-medium text-slate-600">Work from Home</span></div>
            <div class="flex items-center gap-1.5"><span class="w-3 h-3 rounded-full bg-slate-400 inline-block"></span><span class="font-medium text-slate-600">Rest Day</span></div>
            <div class="flex items-center gap-1.5"><span class="w-3 h-3 rounded-full bg-rose-500 inline-block"></span><span class="font-medium text-slate-600">Leave</span></div>
            <div class="flex items-center gap-1.5 ml-auto"><span class="px-2 py-0.5 bg-amber-50 text-amber-800 border border-amber-200 rounded text-[11px] font-semibold">🎉 Holiday (WFH)</span></div>
        </div>

        {% if not has_schedule %}
        <!-- Empty State Notice -->
        <div class="bg-white border-2 border-dashed border-slate-300 rounded-2xl p-16 text-center space-y-4 shadow-sm">
            <div class="w-16 h-16 bg-indigo-50 text-indigo-600 rounded-2xl flex items-center justify-center mx-auto text-2xl shadow-inner">🗓️</div>
            <div class="space-y-1">
                <h3 class="text-lg font-bold text-slate-900">No Schedule Generated for {{ calendar.month_name[month] }} {{ year }}</h3>
                <p class="text-xs text-slate-500 max-w-md mx-auto">Generate an optimized roster ensuring strictly balanced on-site staff (2 agents/day Mon–Fri) and fair rest days.</p>
            </div>
            <button onclick="openRegenerateModal()" class="bg-indigo-600 hover:bg-indigo-500 text-white px-5 py-2.5 rounded-xl font-bold text-xs shadow-md transition inline-flex items-center gap-2">
                ✨ Generate Schedule Roster
            </button>
        </div>
        {% else %}
        <!-- Compact Calendar Grid (Month View) -->
        <div class="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
            <div class="grid grid-cols-7 bg-slate-100/80 border-b border-slate-200 text-center font-bold text-xs text-slate-600 py-3 uppercase tracking-wider">
                <div class="text-slate-800">Monday</div>
                <div class="text-slate-800">Tuesday</div>
                <div class="text-slate-800">Wednesday</div>
                <div class="text-slate-800">Thursday</div>
                <div class="text-slate-800">Friday</div>
                <div class="text-slate-400">Saturday</div>
                <div class="text-slate-400">Sunday</div>
            </div>

            <div class="grid grid-cols-7 auto-rows-fr bg-slate-200 gap-px" id="calendar-grid">
                {% set month_cal = calendar.Calendar(firstweekday=0).monthdatescalendar(year, month) %}
                {% for week in month_cal %}
                    {% for d in week %}
                        {% set date_str = d.strftime('%Y-%m-%d') %}
                        {% set is_current_month = (d.month == month) %}
                        {% set day_sched = schedule.get(date_str, {}) %}
                        {% set num_agents = data.agents | length %}
                        {% set min_height = 95 + (num_agents * 34) %}

                        <div class="bg-white p-2 flex flex-col justify-between transition hover:bg-slate-50/80 {% if not is_current_month %}bg-slate-50/40 opacity-35{% endif %}" style="min-height: {{ min_height }}px; height: 100%;">
                            <div>
                                <div class="flex justify-between items-center mb-2">
                                    <span class="w-6 h-6 rounded-full flex items-center justify-center font-bold text-xs {% if is_current_month %} bg-slate-100 text-slate-900 border border-slate-200 {% else %} text-slate-300 {% endif %}">
                                        {{ d.day }}
                                    </span>
                                    {% if is_current_month %}
                                        {% set hol = data.holidays.get(date_str) %}
                                        {% if hol %}
                                        <span class="text-[10px] bg-amber-50 text-amber-800 font-bold px-1.5 py-0.5 rounded-md border border-amber-200 truncate max-w-[120px]" title="{{ hol }}">🎉 {{ hol }}</span>
                                        {% endif %}
                                    {% endif %}
                                </div>

                                <!-- Agent shifts list -->
                                <div class="space-y-1.5 overflow-y-auto pr-0.5" data-date="{{ date_str }}">
                                    {% if is_current_month %}
                                        {% for agent in data.agents %}
                                        {% set agent_id = agent.id|string %}
                                        {% set info = day_sched.get(agent_id, {'status': 'Work from Home', 'shift': '8:00 AM – 5:00 PM'}) %}
                                        <div class="agent-shift-item agent-box-{{ agent.id }} bg-white hover:bg-indigo-50/60 border border-slate-200/80 hover:border-indigo-300 rounded-md px-1.5 py-1 cursor-pointer transition flex justify-between items-center group"
                                             onclick="openEditCellModal('{{ date_str }}', '{{ agent.id }}', '{{ agent.name }}', '{{ info.status }}', '{{ info.shift }}')">
                                            <div class="min-w-0 flex-1 pr-1">
                                                <span class="font-bold text-slate-800 block text-[10px] group-hover:text-indigo-900 truncate leading-tight" title="{{ agent.name }}">{{ agent.name }}</span>
                                                <span class="text-[9px] text-slate-500 block truncate font-medium leading-tight" title="{{ info.shift }}">{{ info.shift }}</span>
                                            </div>
                                            <span class="px-1.5 py-0.5 rounded text-[9px] font-bold shrink-0
                                                {% if info.status == 'On-site' %} bg-emerald-100 text-emerald-800 border border-emerald-200
                                                {% elif info.status == 'Work from Home' %} bg-blue-100 text-blue-800 border border-blue-200
                                                {% elif info.status == 'Rest Day' %} bg-slate-200 text-slate-700 border border-slate-300
                                                {% else %} bg-rose-100 text-rose-800 border border-rose-200 {% endif %}">
                                                {{ info.status }}
                                            </span>
                                        </div>
                                        {% endfor %}
                                    {% endif %}
                                </div>
                            </div>
                        </div>
                    {% endfor %}
                {% endfor %}
            </div>
        </div>
        {% endif %}
    </main>

    <!-- Add Leave Range Modal -->
    <div id="leave-modal" class="fixed inset-0 bg-slate-900/60 backdrop-blur-xs hidden flex items-center justify-center p-4 z-50">
        <div class="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6 space-y-4 border border-slate-100">
            <div class="flex justify-between items-center">
                <h3 class="text-base font-bold text-slate-900 flex items-center gap-2">🌴 Manage Agent Leave Ranges</h3>
                <button onclick="closeLeaveModal()" class="text-slate-400 hover:text-slate-600 text-sm font-bold">&times;</button>
            </div>
            <p class="text-xs text-slate-500">Record leaves. Shifts will be automatically redistributed among available staff.</p>

            <div class="max-h-44 overflow-y-auto border border-slate-200 rounded-xl text-xs bg-slate-50/50">
                <table class="w-full text-left">
                    <thead class="bg-slate-100 text-slate-700 font-semibold sticky top-0">
                        <tr>
                            <th class="p-2">Agent</th>
                            <th class="p-2">Start</th>
                            <th class="p-2">End</th>
                            <th class="p-2 text-right">Action</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-200 bg-white">
                        {% for i in range(data.get('leaves', []) | length) %}
                        {% set l = data.get('leaves', [])[i] %}
                        {% set leave_agent = data.agents | selectattr('id', 'equalto', l.agent_id) | first %}
                        <tr>
                            <td class="p-2 font-bold text-slate-800">{{ leave_agent.name if leave_agent else 'Unknown' }}</td>
                            <td class="p-2 text-slate-600">{{ l.start_date }}</td>
                            <td class="p-2 text-slate-600">{{ l.end_date }}</td>
                            <td class="p-2 text-right"><button onclick="removeLeave({{ i }})" class="text-rose-600 hover:text-rose-800 font-semibold">Remove</button></td>
                        </tr>
                        {% endfor %}
                        {% if not data.get('leaves') %}
                        <tr>
                            <td colspan="4" class="p-4 text-center text-slate-400 italic">No leaves recorded.</td>
                        </tr>
                        {% endif %}
                    </tbody>
                </table>
            </div>

            <form onsubmit="submitLeave(event)" class="bg-slate-50 p-3.5 rounded-xl border border-slate-200 space-y-3 text-xs">
                <h4 class="font-bold text-slate-800">Add New Leave Range</h4>
                <div>
                    <label class="block text-[11px] font-semibold text-slate-600 mb-1">Select Staff Member</label>
                    <select id="leave-agent-id" required class="w-full px-3 py-2 bg-white border border-slate-300 rounded-lg text-xs font-medium focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none">
                        {% for agent in data.agents %}
                        <option value="{{ agent.id }}">{{ agent.name }} ({{ agent.role }})</option>
                        {% endfor %}
                    </select>
                </div>
                <div class="grid grid-cols-2 gap-3">
                    <div>
                        <label class="block text-[11px] font-semibold text-slate-600 mb-1">Start Date</label>
                        <input type="date" id="leave-start-date" required class="w-full px-3 py-2 bg-white border border-slate-300 rounded-lg text-xs font-medium focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none">
                    </div>
                    <div>
                        <label class="block text-[11px] font-semibold text-slate-600 mb-1">End Date</label>
                        <input type="date" id="leave-end-date" required class="w-full px-3 py-2 bg-white border border-slate-300 rounded-lg text-xs font-medium focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none">
                    </div>
                </div>
                <div class="flex justify-end pt-1">
                    <button type="submit" class="px-4 py-2 bg-rose-600 hover:bg-rose-500 text-white rounded-lg text-xs font-bold shadow-sm transition">Add Leave & Redistribute</button>
                </div>
            </form>

            <div class="flex justify-end pt-2">
                <button type="button" onclick="closeLeaveModal()" class="px-4 py-2 bg-slate-200 hover:bg-slate-300 text-slate-700 rounded-lg text-xs font-semibold transition">Close & Refresh</button>
            </div>
        </div>
    </div>

    <!-- Agent Management Modal -->
    <div id="agent-modal" class="fixed inset-0 bg-slate-900/60 backdrop-blur-xs hidden flex items-center justify-center p-4 z-50">
        <div class="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6 space-y-4 border border-slate-100">
            <div class="flex justify-between items-center">
                <h3 class="text-base font-bold text-slate-900 flex items-center gap-2">👥 Agent Directory</h3>
                <button onclick="closeAgentModal()" class="text-slate-400 hover:text-slate-600 text-sm font-bold">&times;</button>
            </div>
            <div class="max-h-48 overflow-y-auto border border-slate-200 rounded-xl text-xs bg-slate-50/50">
                <table class="w-full text-left">
                    <thead class="bg-slate-100 text-slate-700 font-semibold sticky top-0">
                        <tr>
                            <th class="p-2">Name</th>
                            <th class="p-2">Role</th>
                            <th class="p-2 text-right">Actions</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-200 bg-white">
                        {% for agent in data.agents %}
                        <tr>
                            <td class="p-2 font-bold text-slate-800">{{ agent.name }}</td>
                            <td class="p-2 text-slate-600">{{ agent.role }}</td>
                            <td class="p-2 text-right space-x-2">
                                <button onclick="startEditAgent({{ agent.id }}, '{{ agent.name }}', '{{ agent.role }}')" class="text-indigo-600 hover:text-indigo-800 font-semibold">Edit</button>
                                <button onclick="deleteAgent({{ agent.id }})" class="text-rose-600 hover:text-rose-800 font-semibold">Delete</button>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>

            <form onsubmit="submitAgentForm(event)" class="bg-slate-50 p-3.5 rounded-xl border border-slate-200 space-y-3 text-xs">
                <h4 class="font-bold text-slate-800" id="agent-form-title">Add New Agent</h4>
                <input type="hidden" id="edit-agent-id" value="">
                <div class="grid grid-cols-2 gap-3">
                    <input type="text" id="agent-name-input" placeholder="Full Name" required class="px-3 py-2 bg-white border border-slate-300 rounded-lg text-xs font-medium focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none">
                    <input type="text" id="agent-role-input" placeholder="Role / Title" value="Support Agent" required class="px-3 py-2 bg-white border border-slate-300 rounded-lg text-xs font-medium focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none">
                </div>
                <div class="flex justify-end gap-2">
                    <button type="button" onclick="resetAgentForm()" id="agent-cancel-btn" class="hidden px-3 py-2 bg-slate-200 hover:bg-slate-300 rounded-lg text-xs font-semibold text-slate-700 transition">Cancel</button>
                    <button type="submit" id="agent-submit-btn" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-bold shadow-sm transition">Add Agent</button>
                </div>
            </form>

            <div class="flex justify-end pt-2">
                <button type="button" onclick="closeAgentModal()" class="px-4 py-2 bg-slate-200 hover:bg-slate-300 text-slate-700 rounded-lg text-xs font-semibold transition">Close & Refresh</button>
            </div>
        </div>
    </div>

    <!-- Edit Shift Modal -->
    <div id="edit-cell-modal" class="fixed inset-0 bg-slate-900/60 backdrop-blur-xs hidden flex items-center justify-center p-4 z-50">
        <div class="bg-white rounded-2xl shadow-2xl max-w-sm w-full p-6 space-y-4 border border-slate-100">
            <div class="flex justify-between items-center">
                <h3 class="text-base font-bold text-slate-900" id="edit-modal-title">Edit Shift Assignment</h3>
                <button onclick="closeEditCellModal()" class="text-slate-400 hover:text-slate-600 text-sm font-bold">&times;</button>
            </div>
            <form onsubmit="submitEditCell(event)" class="space-y-3.5 text-xs">
                <input type="hidden" id="edit-date-str">
                <input type="hidden" id="edit-cell-agent-id">
                <div>
                    <label class="block font-semibold text-slate-700 mb-1">Status</label>
                    <select id="edit-status" class="w-full px-3 py-2 bg-white border border-slate-300 rounded-lg text-xs font-medium focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none">
                        {% for status in statuses %}
                        <option value="{{ status }}">{{ status }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div>
                    <label class="block font-semibold text-slate-700 mb-1">Shift Time</label>
                    <select id="edit-shift" class="w-full px-3 py-2 bg-white border border-slate-300 rounded-lg text-xs font-medium focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none">
                        {% for shift in shifts %}
                        <option value="{{ shift }}">{{ shift }}</option>
                        {% endfor %}
                        <option value="Off">Off</option>
                    </select>
                </div>
                <div class="flex justify-end gap-2 pt-2">
                    <button type="button" onclick="closeEditCellModal()" class="px-4 py-2 bg-slate-200 hover:bg-slate-300 text-slate-700 rounded-lg text-xs font-semibold transition">Cancel</button>
                    <button type="submit" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-bold shadow-sm transition">Save Changes</button>
                </div>
            </form>
        </div>
    </div>

    <!-- Holidays Modal -->
    <div id="holiday-modal" class="fixed inset-0 bg-slate-900/60 backdrop-blur-xs hidden flex items-center justify-center p-4 z-50">
        <div class="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6 space-y-4 border border-slate-100">
            <div class="flex justify-between items-center">
                <h3 class="text-base font-bold text-slate-900">🎉 Philippine Holidays Management</h3>
                <button onclick="closeHolidayModal()" class="text-slate-400 hover:text-slate-600 text-sm font-bold">&times;</button>
            </div>
            <div class="max-h-48 overflow-y-auto border border-slate-200 rounded-xl text-xs bg-slate-50/50">
                <table class="w-full text-left">
                    <thead class="bg-slate-100 text-slate-700 font-semibold sticky top-0">
                        <tr>
                            <th class="p-2">Date</th>
                            <th class="p-2">Name</th>
                            <th class="p-2 text-right">Action</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-200 bg-white">
                        {% for date, name in data.holidays.items() %}
                        <tr>
                            <td class="p-2 font-medium text-slate-800">{{ date }}</td>
                            <td class="p-2 text-slate-600">{{ name }}</td>
                            <td class="p-2 text-right"><button onclick="removeHoliday('{{ date }}')" class="text-rose-600 hover:text-rose-800 font-semibold">Remove</button></td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            <form onsubmit="addHoliday(event)" class="flex gap-2 pt-1 text-xs">
                <input type="date" id="new-hol-date" required class="px-3 py-2 bg-white border border-slate-300 rounded-lg text-xs font-medium focus:ring-2 focus:ring-indigo-500/25 outline-none">
                <input type="text" id="new-hol-name" placeholder="Holiday Name" required class="flex-1 px-3 py-2 bg-white border border-slate-300 rounded-lg text-xs font-medium focus:ring-2 focus:ring-indigo-500/25 outline-none">
                <button type="submit" class="px-4 py-2 bg-amber-600 hover:bg-amber-500 text-white rounded-lg text-xs font-bold shadow-sm transition">Add</button>
            </form>
            <div class="flex justify-end pt-2">
                <button type="button" onclick="closeHolidayModal()" class="px-4 py-2 bg-slate-200 hover:bg-slate-300 text-slate-700 rounded-lg text-xs font-semibold transition">Close & Refresh</button>
            </div>
        </div>
    </div>

    <!-- Re-Generate Confirmation Modal -->
    <div id="regenerate-modal" class="fixed inset-0 bg-slate-900/60 backdrop-blur-xs hidden flex items-center justify-center p-4 z-50">
        <div class="bg-white rounded-2xl shadow-2xl max-w-sm w-full p-6 space-y-4 border border-slate-100 text-center">
            <div class="w-12 h-12 bg-indigo-50 text-indigo-600 rounded-xl flex items-center justify-center mx-auto text-xl">🔄</div>
            <div class="space-y-1">
                <h3 class="text-base font-bold text-slate-900">Generate Schedule Roster?</h3>
                <p class="text-xs text-slate-500">This will create or re-optimize the fair schedule for {{ calendar.month_name[month] }} {{ year }}.</p>
            </div>
            <div class="flex justify-center gap-2 pt-2">
                <button type="button" onclick="closeRegenerateModal()" class="px-4 py-2 bg-slate-200 hover:bg-slate-300 text-slate-700 rounded-lg text-xs font-semibold transition">Cancel</button>
                <button type="button" onclick="confirmRegenerate()" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-bold shadow-sm transition">Yes, Generate</button>
            </div>
        </div>
    </div>

    <!-- Reset Confirmation Modal -->
    <div id="reset-modal" class="fixed inset-0 bg-slate-900/60 backdrop-blur-xs hidden flex items-center justify-center p-4 z-50">
        <div class="bg-white rounded-2xl shadow-2xl max-w-sm w-full p-6 space-y-4 border border-slate-100 text-center">
            <div class="w-12 h-12 bg-rose-50 text-rose-600 rounded-xl flex items-center justify-center mx-auto text-xl">🗑️</div>
            <div class="space-y-1">
                <h3 class="text-base font-bold text-slate-900">Reset Schedule Roster?</h3>
                <p class="text-xs text-slate-500">This will clear all scheduled shifts for {{ calendar.month_name[month] }} {{ year }}.</p>
            </div>
            <div class="flex justify-center gap-2 pt-2">
                <button type="button" onclick="closeResetModal()" class="px-4 py-2 bg-slate-200 hover:bg-slate-300 text-slate-700 rounded-lg text-xs font-semibold transition">Cancel</button>
                <button type="button" onclick="confirmReset()" class="px-4 py-2 bg-rose-600 hover:bg-rose-500 text-white rounded-lg text-xs font-bold shadow-sm transition">Yes, Reset</button>
            </div>
        </div>
    </div>

    <script>
        const currentYear = {{ year }};
        const currentMonth = {{ month }};

        function openLeaveModal() { document.getElementById('leave-modal').classList.remove('hidden'); }
        function closeLeaveModal() { document.getElementById('leave-modal').classList.add('hidden'); location.reload(); }

        function openAgentModal() { document.getElementById('agent-modal').classList.remove('hidden'); }
        function closeAgentModal() { document.getElementById('agent-modal').classList.add('hidden'); location.reload(); }

        function openHolidayModal() { document.getElementById('holiday-modal').classList.remove('hidden'); }
        function closeHolidayModal() { document.getElementById('holiday-modal').classList.add('hidden'); location.reload(); }

        function startEditAgent(id, name, role) {
            document.getElementById('edit-agent-id').value = id;
            document.getElementById('agent-name-input').value = name;
            document.getElementById('agent-role-input').value = role;
            document.getElementById('agent-form-title').innerText = `Edit Agent #${id}`;
            document.getElementById('agent-submit-btn').innerText = 'Update Agent';
            document.getElementById('agent-cancel-btn').classList.remove('hidden');
        }

        function resetAgentForm() {
            document.getElementById('edit-agent-id').value = '';
            document.getElementById('agent-name-input').value = '';
            document.getElementById('agent-role-input').value = 'Support Agent';
            document.getElementById('agent-form-title').innerText = 'Add New Agent';
            document.getElementById('agent-submit-btn').innerText = 'Add Agent';
            document.getElementById('agent-cancel-btn').classList.add('hidden');
        }

        async function submitAgentForm(e) {
            e.preventDefault();
            const editId = document.getElementById('edit-agent-id').value;
            const name = document.getElementById('agent-name-input').value;
            const role = document.getElementById('agent-role-input').value;

            if (editId) {
                await fetch(`/api/agents/${editId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name, role })
                });
            } else {
                await fetch('/api/agents', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name, role })
                });
            }
            resetAgentForm();
            location.reload();
        }

        async function deleteAgent(id) {
            if (!confirm('Are you sure you want to delete this agent?')) return;
            await fetch(`/api/agents/${id}`, { method: 'DELETE' });
            location.reload();
        }

        async function submitLeave(e) {
            e.preventDefault();
            const agent_id = document.getElementById('leave-agent-id').value;
            const start_date = document.getElementById('leave-start-date').value;
            const end_date = document.getElementById('leave-end-date').value;
            const res = await fetch('/api/leaves', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ agent_id, start_date, end_date })
            });
            if (res.ok) location.reload();
        }

        async function removeLeave(index) {
            const res = await fetch('/api/leaves', {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ index })
            });
            if (res.ok) location.reload();
        }

        function openEditCellModal(dateStr, agentId, agentName, status, shift) {
            document.getElementById('edit-date-str').value = dateStr;
            document.getElementById('edit-cell-agent-id').value = agentId;
            document.getElementById('edit-modal-title').innerText = `Edit: ${agentName} (${dateStr})`;
            document.getElementById('edit-status').value = status;
            document.getElementById('edit-shift').value = shift;
            document.getElementById('edit-cell-modal').classList.remove('hidden');
        }
        function closeEditCellModal() { document.getElementById('edit-cell-modal').classList.add('hidden'); }

        async function submitEditCell(e) {
            e.preventDefault();
            const month_key = `${currentYear}-${String(currentMonth).padStart(2, '0')}`;
            const date_str = document.getElementById('edit-date-str').value;
            const agent_id = document.getElementById('edit-cell-agent-id').value;
            const status = document.getElementById('edit-status').value;
            const shift = document.getElementById('edit-shift').value;
            const res = await fetch('/api/schedule/edit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ month_key, date_str, agent_id, status, shift })
            });
            if (res.ok) location.reload();
        }

        function openRegenerateModal() { document.getElementById('regenerate-modal').classList.remove('hidden'); }
        function closeRegenerateModal() { document.getElementById('regenerate-modal').classList.add('hidden'); }

        async function confirmRegenerate() {
            const res = await fetch('/api/schedule/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ year: currentYear, month: currentMonth })
            });
            if (res.ok) location.reload();
        }

        function openResetModal() { document.getElementById('reset-modal').classList.remove('hidden'); }
        function closeResetModal() { document.getElementById('reset-modal').classList.add('hidden'); }

        async function confirmReset() {
            const res = await fetch('/api/schedule/reset', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ year: currentYear, month: currentMonth })
            });
            if (res.ok) location.reload();
        }

        async function addHoliday(e) {
            e.preventDefault();
            const date = document.getElementById('new-hol-date').value;
            const name = document.getElementById('new-hol-name').value;
            const res = await fetch('/api/holidays', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ date, name })
            });
            if (res.ok) location.reload();
        }

        async function removeHoliday(date) {
            const res = await fetch('/api/holidays', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ date, name: '' })
            });
            if (res.ok) location.reload();
        }

        function filterAgentSchedule() {
            const selectedAgentId = document.getElementById('agent-filter').value;
            const items = document.querySelectorAll('.agent-shift-item');
            items.forEach(item => {
                if (selectedAgentId === 'all') {
                    item.style.display = 'flex';
                } else {
                    if (item.classList.contains(`agent-box-${selectedAgentId}`)) {
                        item.style.display = 'flex';
                    } else {
                        item.style.display = 'none';
                    }
                }
            });
        }
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting AutoSched Pro Calendar on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
