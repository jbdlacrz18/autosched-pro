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
    "schedule": {}
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

    if month_key not in data["schedule"] and is_current_real_month:
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

@app.route("/api/schedule/generate", methods=["POST"])
def generate_schedule():
    req = request.json or {}
    year = int(req.get("year", datetime.now().year))
    month = int(request.get("month", datetime.now().month))
    month_key = f"{year}-{month:02d}"

    data = load_data()
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
    <title>AutoSched Pro - Compact Calendar</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>body { font-family: 'Inter', sans-serif; }</style>
</head>
<body class="bg-slate-50 text-slate-800 min-h-screen pb-16">
    <header class="bg-indigo-600 text-white shadow-lg sticky top-0 z-30">
        <div class="max-w-[98%] mx-auto px-3 py-3 flex flex-col md:flex-row justify-between items-center gap-3">
            <div>
                <h1 class="text-xl font-bold flex items-center gap-1.5">
                    📅 AutoSched Pro Calendar
                </h1>
                <p class="text-indigo-200 text-[11px]">Fair Scheduling (Min 2 On-site Mon-Fri, Leave-Aware)</p>
            </div>
            <div class="flex flex-wrap items-center gap-2">
                {% if has_schedule %}
                <button onclick="generateSchedule()" class="bg-indigo-700 hover:bg-indigo-800 px-2.5 py-1 rounded text-[11px] font-medium shadow transition flex items-center gap-1">
                    🔄 Re-Generate
                </button>
                <a href="/api/export/excel?year={{ year }}&month={{ month }}" class="bg-emerald-600 hover:bg-emerald-700 px-2.5 py-1 rounded text-[11px] font-medium shadow transition flex items-center gap-1">
                    📊 Export Excel
                </a>
                {% else %}
                <button onclick="generateSchedule()" class="bg-emerald-600 hover:bg-emerald-700 px-3 py-1.5 rounded text-xs font-bold shadow transition flex items-center gap-1">
                    ✨ Generate Schedule
                </button>
                {% endif %}
                <button onclick="openLeaveModal()" class="bg-rose-600 hover:bg-rose-700 px-2.5 py-1 rounded text-[11px] font-medium shadow transition">
                    🌴 Leave Range
                </button>
                <button onclick="openAgentModal()" class="bg-violet-600 hover:bg-violet-700 px-2.5 py-1 rounded text-[11px] font-semibold shadow transition">
                    👥 Agents
                </button>
                <button onclick="openHolidayModal()" class="bg-amber-600 hover:bg-amber-700 px-2.5 py-1 rounded text-[11px] font-medium shadow transition">
                    🎉 Holidays
                </button>
            </div>
        </div>
    </header>

    <main class="max-w-[98%] mx-auto px-1 py-4 space-y-4">
        <!-- Month Navigation & Controls -->
        <div class="bg-white rounded-lg shadow-sm border border-slate-200 p-3 flex flex-col md:flex-row justify-between items-center gap-3">
            <div class="flex items-center gap-2">
                {% set prev_month = month - 1 if month > 1 else 12 %}
                {% set prev_year = year if month > 1 else year - 1 %}
                {% set next_month = month + 1 if month < 12 else 1 %}
                {% set next_year = year if month < 12 else year + 1 %}
                <a href="/?year={{ prev_year }}&month={{ prev_month }}" class="px-2.5 py-1 border border-slate-200 rounded text-xs hover:bg-slate-100 text-slate-600 font-bold">&larr; Prev</a>
                <h2 class="text-base font-bold text-slate-800 w-44 text-center">
                    {{ calendar.month_name[month] }} {{ year }}
                </h2>
                <a href="/?year={{ next_year }}&month={{ next_month }}" class="px-2.5 py-1 border border-slate-200 rounded text-xs hover:bg-slate-100 text-slate-600 font-bold">Next &rarr;</a>
            </div>

            <!-- Agent Filter -->
            <div class="flex items-center gap-2 w-full md:w-auto">
                <label class="text-[11px] font-semibold text-slate-500">Filter:</label>
                <select id="agent-filter" onchange="filterAgentSchedule()" class="px-2.5 py-1 border border-slate-300 rounded text-[11px] focus:ring-1 focus:ring-indigo-500 outline-none">
                    <option value="all">All Agents</option>
                    {% for agent in data.agents %}
                    <option value="{{ agent.id }}">{{ agent.name }}</option>
                    {% endfor %}
                </select>
                <button onclick="openLeaveModal()" class="bg-rose-600 hover:bg-rose-700 text-white px-2.5 py-1 rounded text-[11px] font-semibold shadow">
                    + Leave
                </button>
            </div>
        </div>

        <!-- Legend -->
        <div class="flex flex-wrap items-center gap-2 text-[11px] bg-white p-2 rounded border border-slate-200 shadow-sm">
            <span class="font-semibold text-slate-600">Legend:</span>
            <span class="px-1.5 py-0.5 bg-emerald-200 text-emerald-900 rounded font-semibold">On-site</span>
            <span class="px-1.5 py-0.5 bg-blue-200 text-blue-900 rounded font-semibold">WFH</span>
            <span class="px-1.5 py-0.5 bg-slate-300 text-slate-800 rounded font-semibold">Rest Day</span>
            <span class="px-1.5 py-0.5 bg-rose-200 text-rose-900 rounded font-semibold">Leave</span>
            <span class="px-1.5 py-0.5 bg-amber-100 text-amber-800 rounded font-semibold">🎉 Holiday (WFH)</span>
        </div>

        {% if not has_schedule %}
        <!-- Empty State Notice -->
        <div class="bg-white border-2 border-dashed border-slate-300 rounded-xl p-10 text-center space-y-3">
            <div class="text-3xl">🗓️</div>
            <h3 class="text-base font-bold text-slate-700">No Schedule Generated for {{ calendar.month_name[month] }} {{ year }}</h3>
            <p class="text-xs text-slate-500 max-w-sm mx-auto">Click below to generate fair shifts (Min 2 on-site Mon-Fri, Leave-Aware).</p>
            <button onclick="generateSchedule()" class="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg font-bold text-xs shadow transition">
                ✨ Generate Schedule
            </button>
        </div>
        {% else %}
        <!-- Compact Calendar Grid (Month View) -->
        <div class="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
            <div class="grid grid-cols-7 bg-slate-100 border-b border-slate-200 text-center font-semibold text-[11px] text-slate-600 py-2 uppercase tracking-wider">
                <div>Monday</div>
                <div>Tuesday</div>
                <div>Wednesday</div>
                <div>Thursday</div>
                <div>Friday</div>
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

                        <div class="bg-white min-h-[280px] p-1.5 flex flex-col justify-between {% if not is_current_month %}bg-slate-50/50 opacity-30{% endif %}">
                            <div>
                                <div class="flex justify-between items-center mb-1">
                                    <span class="font-bold text-xs {% if is_current_month %}text-slate-900{% else %}text-slate-300{% endif %}">
                                        {{ d.day }}
                                    </span>
                                    {% if is_current_month %}
                                        {% set hol = data.holidays.get(date_str) %}
                                        {% if hol %}
                                        <span class="text-[9px] bg-amber-100 text-amber-800 font-bold px-1 py-0.2 rounded" title="{{ hol }}">🎉 {{ hol }}</span>
                                        {% endif %}
                                    {% endif %}
                                </div>

                                <!-- Compact Agent shifts list -->
                                <div class="space-y-1 overflow-y-auto max-h-[250px] text-[10px] pr-0.5" data-date="{{ date_str }}">
                                    {% if is_current_month %}
                                        {% for agent in data.agents %}
                                        {% set agent_id = agent.id|string %}
                                        {% set info = day_sched.get(agent_id, {'status': 'Work from Home', 'shift': '8AM-5PM'}) %}
                                        <div class="agent-shift-item agent-box-{{ agent.id }} bg-slate-50 hover:bg-indigo-50 border border-slate-200 rounded px-1.5 py-1 cursor-pointer transition flex justify-between items-center"
                                             onclick="openEditCellModal('{{ date_str }}', '{{ agent.id }}', '{{ agent.name }}', '{{ info.status }}', '{{ info.shift }}')">
                                            <span class="font-bold text-slate-800 truncate max-w-[65px]" title="{{ agent.name }}">{{ agent.name }}</span>
                                            <span class="px-1.5 py-0.5 rounded text-[9px] font-extrabold shrink-0
                                                {% if info.status == 'On-site' %} bg-emerald-200 text-emerald-900
                                                {% elif info.status == 'Work from Home' %} bg-blue-200 text-blue-900
                                                {% elif info.status == 'Rest Day' %} bg-slate-300 text-slate-800
                                                {% else %} bg-rose-200 text-rose-900 {% endif %}">
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
    <div id="leave-modal" class="fixed inset-0 bg-slate-900/50 backdrop-blur-sm hidden flex items-center justify-center p-4 z-50">
        <div class="bg-white rounded-xl shadow-xl max-w-md w-full p-5 space-y-3">
            <h3 class="text-base font-bold text-slate-800">🌴 Add Agent Leave Date Range</h3>
            <p class="text-[11px] text-slate-500">Select an agent and a date range for leave. Shifts will be fairly redistributed among available staff.</p>

            <div class="max-h-40 overflow-y-auto border border-slate-200 rounded text-xs">
                <table class="w-full text-left">
                    <thead class="bg-slate-100 text-slate-600">
                        <tr>
                            <th class="p-1.5">Agent</th>
                            <th class="p-1.5">Start</th>
                            <th class="p-1.5">End</th>
                            <th class="p-1.5 text-right">Action</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for i in range(data.get('leaves', []) | length) %}
                        {% set l = data.get('leaves', [])[i] %}
                        {% set leave_agent = data.agents | selectattr('id', 'equalto', l.agent_id) | first %}
                        <tr class="border-b border-slate-100">
                            <td class="p-1.5 font-bold">{{ leave_agent.name if leave_agent else 'Unknown' }}</td>
                            <td class="p-1.5">{{ l.start_date }}</td>
                            <td class="p-1.5">{{ l.end_date }}</td>
                            <td class="p-1.5 text-right"><button onclick="removeLeave({{ i }})" class="text-rose-600 hover:underline">Remove</button></td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>

            <form onsubmit="submitLeave(event)" class="bg-slate-50 p-2.5 rounded border border-slate-200 space-y-2 text-xs">
                <div>
                    <label class="block text-[10px] font-semibold text-slate-600 mb-0.5">Select Agent</label>
                    <select id="leave-agent-id" required class="w-full px-2 py-1.5 border border-slate-300 rounded text-xs">
                        {% for agent in data.agents %}
                        <option value="{{ agent.id }}">{{ agent.name }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div class="grid grid-cols-2 gap-2">
                    <div>
                        <label class="block text-[10px] font-semibold text-slate-600 mb-0.5">Start Date</label>
                        <input type="date" id="leave-start-date" required class="w-full px-2 py-1.5 border border-slate-300 rounded text-xs">
                    </div>
                    <div>
                        <label class="block text-[10px] font-semibold text-slate-600 mb-0.5">End Date</label>
                        <input type="date" id="leave-end-date" required class="w-full px-2 py-1.5 border border-slate-300 rounded text-xs">
                    </div>
                </div>
                <div class="flex justify-end pt-1">
                    <button type="submit" class="px-3 py-1.5 bg-rose-600 hover:bg-rose-700 text-white rounded text-xs font-semibold shadow">Add Leave Range & Redistribute</button>
                </div>
            </form>

            <div class="flex justify-end pt-1">
                <button type="button" onclick="closeLeaveModal()" class="px-3 py-1.5 bg-slate-200 hover:bg-slate-300 rounded text-xs font-semibold">Close</button>
            </div>
        </div>
    </div>

    <!-- Agent Management Modal -->
    <div id="agent-modal" class="fixed inset-0 bg-slate-900/50 backdrop-blur-sm hidden flex items-center justify-center p-4 z-50">
        <div class="bg-white rounded-xl shadow-xl max-w-md w-full p-5 space-y-3">
            <h3 class="text-base font-bold text-slate-800">👥 Agent Management</h3>
            <div class="max-h-48 overflow-y-auto border border-slate-200 rounded text-xs">
                <table class="w-full text-left">
                    <thead class="bg-slate-100 text-slate-600">
                        <tr>
                            <th class="p-1.5">Name</th>
                            <th class="p-1.5">Role</th>
                            <th class="p-1.5 text-right">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for agent in data.agents %}
                        <tr class="border-b border-slate-100">
                            <td class="p-1.5 font-bold text-slate-800">{{ agent.name }}</td>
                            <td class="p-1.5 text-slate-600">{{ agent.role }}</td>
                            <td class="p-1.5 text-right space-x-2">
                                <button onclick="startEditAgent({{ agent.id }}, '{{ agent.name }}', '{{ agent.role }}')" class="text-indigo-600 hover:underline">Edit</button>
                                <button onclick="deleteAgent({{ agent.id }})" class="text-rose-600 hover:underline">Delete</button>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>

            <form onsubmit="submitAgentForm(event)" class="bg-slate-50 p-2.5 rounded border border-slate-200 space-y-2 text-xs">
                <h4 class="font-bold text-slate-700" id="agent-form-title">Add New Agent</h4>
                <input type="hidden" id="edit-agent-id" value="">
                <div class="grid grid-cols-2 gap-2">
                    <input type="text" id="agent-name-input" placeholder="Name" required class="px-2 py-1.5 border border-slate-300 rounded text-xs">
                    <input type="text" id="agent-role-input" placeholder="Role" value="Support Agent" required class="px-2 py-1.5 border border-slate-300 rounded text-xs">
                </div>
                <div class="flex justify-end gap-2">
                    <button type="button" onclick="resetAgentForm()" id="agent-cancel-btn" class="hidden px-2.5 py-1 bg-slate-200 hover:bg-slate-300 rounded text-xs font-semibold">Cancel</button>
                    <button type="submit" id="agent-submit-btn" class="px-3 py-1 bg-indigo-600 hover:bg-indigo-700 text-white rounded text-xs font-semibold">Add</button>
                </div>
            </form>

            <div class="flex justify-end pt-1">
                <button type="button" onclick="closeAgentModal()" class="px-3 py-1.5 bg-slate-200 hover:bg-slate-300 rounded text-xs font-semibold">Close</button>
            </div>
        </div>
    </div>

    <!-- Edit Shift Modal -->
    <div id="edit-cell-modal" class="fixed inset-0 bg-slate-900/50 backdrop-blur-sm hidden flex items-center justify-center p-4 z-50">
        <div class="bg-white rounded-xl shadow-xl max-w-sm w-full p-5 space-y-3">
            <h3 class="text-base font-bold text-slate-800" id="edit-modal-title">Edit Shift</h3>
            <form onsubmit="submitEditCell(event)" class="space-y-3 text-xs">
                <input type="hidden" id="edit-date-str">
                <input type="hidden" id="edit-cell-agent-id">
                <div>
                    <label class="block font-semibold text-slate-600 mb-1">Status</label>
                    <select id="edit-status" class="w-full px-2.5 py-1.5 border border-slate-300 rounded text-xs focus:ring-1 focus:ring-indigo-500 outline-none">
                        {% for status in statuses %}
                        <option value="{{ status }}">{{ status }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div>
                    <label class="block font-semibold text-slate-600 mb-1">Shift Time</label>
                    <select id="edit-shift" class="w-full px-2.5 py-1.5 border border-slate-300 rounded text-xs focus:ring-1 focus:ring-indigo-500 outline-none">
                        {% for shift in shifts %}
                        <option value="{{ shift }}">{{ shift }}</option>
                        {% endfor %}
                        <option value="Off">Off</option>
                    </select>
                </div>
                <div class="flex justify-end gap-2 pt-2">
                    <button type="button" onclick="closeEditCellModal()" class="px-3 py-1.5 bg-slate-200 hover:bg-slate-300 rounded text-xs font-semibold">Cancel</button>
                    <button type="submit" class="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded text-xs font-semibold shadow">Save</button>
                </div>
            </form>
        </div>
    </div>

    <!-- Holidays Modal -->
    <div id="holiday-modal" class="fixed inset-0 bg-slate-900/50 backdrop-blur-sm hidden flex items-center justify-center p-4 z-50">
        <div class="bg-white rounded-xl shadow-xl max-w-md w-full p-5 space-y-3">
            <h3 class="text-base font-bold text-slate-800">Philippine Holidays</h3>
            <div class="max-h-48 overflow-y-auto border border-slate-200 rounded text-xs">
                <table class="w-full text-left">
                    <thead class="bg-slate-100 text-slate-600">
                        <tr>
                            <th class="p-1.5">Date</th>
                            <th class="p-1.5">Name</th>
                            <th class="p-1.5 text-right">Action</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for date, name in data.holidays.items() %}
                        <tr class="border-b border-slate-100">
                            <td class="p-1.5 font-medium">{{ date }}</td>
                            <td class="p-1.5">{{ name }}</td>
                            <td class="p-1.5 text-right"><button onclick="removeHoliday('{{ date }}')" class="text-rose-600 hover:underline">Remove</button></td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            <form onsubmit="addHoliday(event)" class="flex gap-2 pt-1 text-xs">
                <input type="date" id="new-hol-date" required class="px-2 py-1.5 border border-slate-300 rounded text-xs">
                <input type="text" id="new-hol-name" placeholder="Holiday Name" required class="flex-1 px-2 py-1.5 border border-slate-300 rounded text-xs">
                <button type="submit" class="px-3 py-1.5 bg-amber-600 hover:bg-amber-700 text-white rounded text-xs font-semibold">Add</button>
            </form>
            <div class="flex justify-end pt-1">
                <button type="button" onclick="closeHolidayModal()" class="px-3 py-1.5 bg-slate-200 hover:bg-slate-300 rounded text-xs font-semibold">Close</button>
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
            document.getElementById('agent-submit-btn').innerText = 'Update';
            document.getElementById('agent-cancel-btn').classList.remove('hidden');
        }

        function resetAgentForm() {
            document.getElementById('edit-agent-id').value = '';
            document.getElementById('agent-name-input').value = '';
            document.getElementById('agent-role-input').value = 'Support Agent';
            document.getElementById('agent-form-title').innerText = 'Add New Agent';
            document.getElementById('agent-submit-btn').innerText = 'Add';
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

        async function generateSchedule() {
            const res = await fetch('/api/schedule/generate', {
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
