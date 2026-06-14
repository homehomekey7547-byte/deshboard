import os, re, json, requests, copy

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
DB_ID = os.environ.get("DB_ID", "")
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

base = os.path.dirname(os.path.abspath(__file__))
src = base + '/dashboard.html'
dst = base + '/index.html'
cache_file = base + '/task_cache.json'

with open(src, 'r', encoding='utf-8') as f:
    html = f.read()

VALUE_MAP = {d: 0 for d in range(10)}
VALUE_MAP.update({1: 0.25, 2: 1.0, 3: 2.0})
LABEL_MAP = {d: '?' for d in range(10)}
LABEL_MAP.update({1: 'L', 2: 'M', 3: 'H'})
DIM_KEYS = ['時', '技', '影', '複']

def code_to_score_map(code_str):
    sm = {}
    for i, ch in enumerate(code_str):
        d = int(ch)
        sm[DIM_KEYS[i]] = {"label": LABEL_MAP.get(d, '?'), "value": VALUE_MAP.get(d, 0)}
    return sm

def code_to_task_pts(code_str):
    return sum(VALUE_MAP.get(int(ch), 0) for ch in code_str)

# ── Strategy classification ──
strategy_rules_path = base + '/strategy_rules.json'
if os.path.exists(strategy_rules_path):
    with open(strategy_rules_path, 'r', encoding='utf-8') as f:
        STRATEGY_RULES = json.load(f)
else:
    STRATEGY_RULES = {}
    print("WARNING: strategy_rules.json not found")

def classify_strategy(desc):
    for strat, keywords in STRATEGY_RULES.items():
        for kw in keywords:
            if kw in desc:
                return strat
    return ''

# ── Extract JSON object by brace matching ──
def extract_js_obj(text, start_pos):
    """Find the matching } for { at start_pos, return (json_str, end_pos)"""
    if text[start_pos] != '{':
        return None, -1
    depth = 0
    in_str = False
    esc = False
    for i in range(start_pos, len(text)):
        ch = text[i]
        if esc:
            esc = False
            continue
        if ch == '\\' and in_str:
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start_pos:i+1], i + 1
    return None, -1

# ── Find const declarations ──
def find_const(name, text):
    """Find 'const NAME = {' and return (start_of_const, brace_start, json_str, brace_end, after_semicolon)"""
    pat = f'const {name} = '
    idx = text.find(pat)
    if idx < 0:
        return None
    brace_start = idx + len(pat)
    json_str, brace_end = extract_js_obj(text, brace_start)
    if json_str is None:
        return None
    # After the closing }, find the ;
    semi = text.find(';', brace_end)
    if semi < 0:
        return None
    return (idx, brace_start, json_str, brace_end, semi + 1)

# ── Parse tasks (Notion API) ──
person_tasks = {'俊': {}, '盈萱': {}, '岍叡': {}}
PERSON_LOOKUP = {'俊': '俊', '萱': '盈萱', '岍': '岍叡'}

def add_task(person, wk, code, desc):
    t = {
        "code": code,
        "desc": desc,
        "section": "00",
        "is_subtask": False,
        "project": "",
        "strategy": classify_strategy(desc),
        "score_map": code_to_score_map(code),
        "task_pts": code_to_task_pts(code)
    }
    if wk not in person_tasks[person]:
        person_tasks[person][wk] = []
    person_tasks[person][wk].append(t)

def parse_task_line(line, week_no):
    line = line.strip()
    if '🆕_' not in line:
        return
    idx_arrow = line.find('🆕_')
    prefix = line[:idx_arrow]
    # Determine owners
    if '全' in prefix:
        owners = ['俊', '盈萱', '岍叡']
    else:
        owners = [PERSON_LOOKUP[c] for c in prefix if c in PERSON_LOOKUP]
        owners = list(dict.fromkeys(owners))  # unique, preserve order
    if not owners:
        return
    rest = line[idx_arrow + len('🆕_'):]
    m = re.search(r'(\d{4})[\-－ー]', rest)
    if m:
        code_str = m.group(1)
        desc = rest[m.end():].strip()
    else:
        code_str = rest[:4]
        if not code_str.isdigit():
            return
        desc = rest[4:].lstrip('-－ー').strip()
    for owner in owners:
        add_task(owner, week_no, code_str, desc)

try:
    qurl = f"https://api.notion.com/v1/databases/{DB_ID}/query"
    all_rows = []
    has_more = True
    start_cursor = None
    while has_more:
        body = {"page_size": 100}
        if start_cursor:
            body["start_cursor"] = start_cursor
        resp = requests.post(qurl, headers=HEADERS, json=body, timeout=15)
        if resp.status_code != 200:
            raise Exception(f"Notion API returned {resp.status_code}")
        data = resp.json()
        all_rows.extend(data["results"])
        has_more = data.get("has_more", False)
        start_cursor = data.get("next_cursor")

    print(f"Notion rows: {len(all_rows)}")
    row_errors = []

    for row in all_rows:
        props = row.get("properties", {})
        week_no = None
        for name, prop in props.items():
            if prop["type"] == "title":
                raw = prop.get("title", [])
                titles = raw if isinstance(raw, list) else raw.get("title", [])
                no_str = "".join(t.get("plain_text","") for t in titles)
                try:
                    week_no = int(no_str)
                except:
                    pass
                break
        if week_no is None:
            continue

        try:
            c_url = f"https://api.notion.com/v1/blocks/{row['id']}/children"
            c_resp = requests.get(c_url, headers=HEADERS, params={"page_size": 100}, timeout=15)
            if c_resp.status_code != 200:
                continue
            for block in c_resp.json().get("results", []):
                btype = block["type"]
                if btype not in ("paragraph", "numbered_list_item", "bulleted_list_item"):
                    continue
                key = "paragraph" if btype == "paragraph" else ("numbered_list_item" if btype == "numbered_list_item" else "bulleted_list_item")
                content = block.get(key, {})
                texts = [rt.get("plain_text", "") for rt in content.get("rich_text", [])]
                para_text = "".join(texts)
                if not para_text:
                    continue
                for line in para_text.split('\n'):
                    parse_task_line(line, week_no)
        except Exception as row_e:
            print(f"  Skipping week {week_no}: [{type(row_e).__name__}] {row_e}")
            row_errors.append(week_no)
    # Save to cache only if all weeks had no errors
    if not row_errors:
        cache = {p: {str(w): tlist for w, tlist in wks.items()} for p, wks in person_tasks.items()}
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False)
        print(f'Cache saved: {cache_file}')
    else:
        print(f'Cache NOT saved: {len(row_errors)} weeks had errors')
except Exception as e:
    print(f"Notion API failed: {e}")
    # Try loading from cache
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cache = json.load(f)
            for person, wks in cache.items():
                for wk_s, tlist in wks.items():
                    person_tasks[person][int(wk_s)] = tlist
            print(f'Loaded from cache: {cache_file}')
        except Exception as ce:
            print(f"Cache load failed: {ce}")
    else:
        print("No Notion token or DB_ID set; tasks loaded from cache only.")

all_weeks = set()
for p, wks in person_tasks.items():
    all_weeks.update(wks.keys())
print(f"Weeks: {sorted(all_weeks)}")
print(f"Total tasks: 俊={sum(len(v) for v in person_tasks['俊'].values())} 盈萱={sum(len(v) for v in person_tasks['盈萱'].values())} 岍叡={sum(len(v) for v in person_tasks['岍叡'].values())}")

# ── Extract and update CHART_DATA ──
cinfo = find_const('CHART_DATA', html)
if not cinfo:
    print("ERROR: CHART_DATA not found")
    exit(1)
c_start, c_brace_start, c_json_str, c_brace_end, c_semi = cinfo
chart = json.loads(c_json_str)
ch_weeks = list(chart['weeks'])

PERSON_MAP = {'俊': 'jun', '盈萱': 'xuan', '岍叡': 'qian'}

# Compute all Notion weeks >= 61
all_nw = set()
for p in person_tasks:
    for wk in person_tasks[p]:
        if wk >= 61:
            all_nw.add(wk)
existing = set(ch_weeks)
new_weeks = sorted(all_nw - existing)

# Remove any weeks < 61 that may have leaked in
for arr_key in ('weeks','dates','labels','qian_points','xuan_points','qian_tasks','xuan_tasks'):
    arr = chart.get(arr_key)
    if arr and len(arr) == len(ch_weeks):
        chart[arr_key] = [v for i, v in enumerate(arr) if ch_weeks[i] >= 61]
ch_weeks = [w for w in ch_weeks if w >= 61]

if new_weeks:
    from datetime import datetime, timedelta
    base_wk = 61
    base_date = datetime(2026, 2, 23)
    new_entries = []
    for wk in new_weeks:
        offset_days = (wk - base_wk) * 7
        d = base_date + timedelta(days=offset_days)
        ds = d.strftime('%Y-%m-%d')
        new_entries.append((wk, ds, f'W{wk}\n{ds}'))
        print(f'Added week {wk} ({ds})')
    for wk, ds, lbl in new_entries:
        idx = 0
        while idx < len(ch_weeks) and ch_weeks[idx] < wk:
            idx += 1
        ch_weeks.insert(idx, wk)
        chart['dates'].insert(idx, ds)
        chart['labels'].insert(idx, lbl)
        chart['qian_points'].insert(idx, 0)
        chart['xuan_points'].insert(idx, 0)
        chart['qian_tasks'].insert(idx, 0)
        chart['xuan_tasks'].insert(idx, 0)
    chart['weeks'] = ch_weeks

# Limit to last 12 weeks (~3 months)
if len(ch_weeks) > 12:
    keep_set = set(ch_weeks[-12:])
    keep_sorted = sorted(keep_set)
    orig_weeks = ch_weeks[:]
    ch_weeks = keep_sorted
    chart['weeks'] = keep_sorted
    for k in ('dates','labels'):
        if len(chart.get(k, [])) == len(orig_weeks):
            chart[k] = [chart[k][i] for i, w in enumerate(orig_weeks) if w in keep_set]

# Compute chart data for all 3 persons
for person, prefix in PERSON_MAP.items():
    pts_key = f'{prefix}_points'
    tasks_key = f'{prefix}_tasks'
    pts_list = []
    tasks_list = []
    for wk in ch_weeks:
        tlist = person_tasks[person].get(wk, [])
        pts = sum(t['task_pts'] for t in tlist)
        pts_list.append(round(pts / 4, 4))
        tasks_list.append(len(tlist))
    chart[pts_key] = pts_list
    chart[tasks_key] = tasks_list

new_chart = 'const CHART_DATA = ' + json.dumps(chart, separators=(',',':')) + ';\n'
html = html[:c_start] + new_chart + html[c_semi:]

# ── Extract and update DETAIL_DATA ──
dinfo = find_const('DETAIL_DATA', html)
if not dinfo:
    print("ERROR: DETAIL_DATA not found")
    exit(1)
d_start, d_brace_start, d_json_str, d_brace_end, d_semi = dinfo
detail = json.loads(d_json_str)

for person in ('俊', '盈萱', '岍叡'):
    p_detail = {}
    for wk_no in ch_weeks:
        wk_s = str(wk_no)
        tlist = person_tasks[person].get(wk_no, [])
        total_pts = round(sum(t['task_pts'] for t in tlist), 4)
        p_detail[wk_s] = {
            "count": len(tlist),
            "tasks": tlist,
            "total_task_pts": total_pts,
            "actual_points": round(total_pts / 4, 4)
        }
    detail[person] = p_detail

new_detail = 'const DETAIL_DATA = ' + json.dumps(detail, ensure_ascii=False, separators=(',',':')) + ';\n'
html = html[:d_start] + new_detail + html[d_semi:]
d_semi = d_start + len(new_detail)

# ── Compute STRATEGY_TREND_DATA ──
STD = {}
for person in PERSON_MAP:
    p_weeks = {}
    for wk in ch_weeks:
        tlist = person_tasks[person].get(wk, [])
        strats = {}
        for t in tlist:
            if t.get('is_subtask', False):
                continue
            s = t.get('strategy', '') or ''
            strats[s] = strats.get(s, 0) + 1
        p_weeks[str(wk)] = strats
    STD[person] = p_weeks

std_const_str = 'const STRATEGY_TREND_DATA = ' + json.dumps(STD, ensure_ascii=False, separators=(',',':')) + ';\n'
existing_std = html.find('const STRATEGY_TREND_DATA')
if existing_std < 0:
    html = html[:d_semi] + '\n' + std_const_str + html[d_semi:]
else:
    std_semi = html.find(';', existing_std)
    html = html[:existing_std] + std_const_str + html[std_semi+1:]

# ── Compute EVOLUTION_DATA ──
ED = {}
for person in PERSON_MAP:
    p_weeks = {}
    for wk in ch_weeks:
        wk_s = str(wk)
        tlist = person_tasks[person].get(wk, [])
        unique_descs = set(t['desc'] for t in tlist)
        breadth = len(unique_descs)
        depth = round(sum(t['task_pts'] for t in tlist) / max(len(tlist), 1), 4)
        current_strats = set()
        for t in tlist:
            if not t.get('is_subtask', False) and t.get('strategy') and t['strategy'] != '行政營運':
                current_strats.add(t['strategy'])
        past_strats = set()
        past_wks = [w for w in ch_weeks if w < wk][-4:]
        for pw in past_wks:
            for t in person_tasks[person].get(pw, []):
                if not t.get('is_subtask', False) and t.get('strategy') and t['strategy'] != '行政營運':
                    past_strats.add(t['strategy'])
        structure_shift = sorted(set(list(current_strats) + list(past_strats)) - (current_strats & past_strats))
        prev4_strats_sorted = sorted(past_strats)
        p_weeks[wk_s] = {"breadth": breadth, "depth": depth, "structure_shift": structure_shift, "prev4Strats": prev4_strats_sorted}
    ED[person] = p_weeks

ed_const_str = 'const EVOLUTION_DATA = ' + json.dumps(ED, ensure_ascii=False, separators=(',',':')) + ';\n'
existing_ed = html.find('const EVOLUTION_DATA')
d_semi_after_std = d_semi
if existing_std < 0:
    d_semi_after_std = d_semi + len(std_const_str) + 1
if existing_ed < 0:
    html = html[:d_semi_after_std] + '\n' + ed_const_str + html[d_semi_after_std:]
else:
    ed_semi = html.find(';', existing_ed)
    html = html[:existing_ed] + ed_const_str + html[ed_semi+1:]

# ── Compute RADIAL_DATA (scatter: each task = one point) ──
RD = {}
DIM_KEYS = ['時','技','影','複']
for person in ('俊', '盈萱', '岍叡'):
    points = []
    for wk, tasks in person_tasks[person].items():
        for t in tasks:
            if t.get('is_subtask', False):
                continue
            s = classify_strategy(t['desc'])
            if not s:
                s = '未分類'
            sm = t.get('score_map', {})
            dim_vals = [sm.get(dk, {}).get('value', 0) for dk in DIM_KEYS]
            avg_r = sum(dim_vals) / 4.0 / 2.0  # normalize to 0-1
            points.append({"s": s, "r": round(avg_r, 4), "pts": t['task_pts'], "wk": wk, "desc": t['desc']})
    RD[person] = points

rd_const_str = 'const RADIAL_DATA = ' + json.dumps(RD, ensure_ascii=False, separators=(',',':')) + ';\n'
existing_rd = html.find('const RADIAL_DATA')
if existing_rd < 0:
    # Insert after EVOLUTION_DATA
    ed_semi_pos = html.find(';', html.rfind('const EVOLUTION_DATA'))
    if ed_semi_pos >= 0:
        html = html[:ed_semi_pos+1] + '\n\n' + rd_const_str + html[ed_semi_pos+1:]
        print('RADIAL_DATA inserted')
    else:
        print("WARNING: EVOLUTION_DATA not found, inserting at end of JS")
        js_end = html.rfind('</script>')
        if js_end >= 0:
            html = html[:js_end] + '\n' + rd_const_str + html[js_end:]
else:
    rd_semi = html.find(';', existing_rd)
    if rd_semi >= 0:
        html = html[:existing_rd] + rd_const_str + html[rd_semi+1:]
        print('RADIAL_DATA updated')

# ── Inject LAST_UPDATED timestamp ──
from datetime import datetime
now_str = datetime.now().strftime('%Y/%m/%d %H:%M')
build_ts = f'const LAST_UPDATED = "{now_str}";\n'
existing_ts = html.find('const LAST_UPDATED')
if existing_ts < 0:
    rd_semi_pos = html.find(';', html.rfind('const RADIAL_DATA'))
    if rd_semi_pos >= 0:
        html = html[:rd_semi_pos+1] + '\n\n' + build_ts + html[rd_semi_pos+1:]
        print(f'LAST_UPDATED injected: {now_str}')
    else:
        print("WARNING: RADIAL_DATA not found, LAST_UPDATED not injected")
else:
    ts_semi = html.find(';', existing_ts)
    if ts_semi >= 0:
        html = html[:existing_ts] + build_ts + html[ts_semi+1:]
        print(f'LAST_UPDATED updated: {now_str}')

# ── CSS / Legend / Dataset / Prefix (skip if already present) ──
if '.person-badge.jun' not in html:
    html = html.replace(
        '.detail-title .person-badge.xuan { background: #2980B9; }',
        '.detail-title .person-badge.xuan { background: #2980B9; }\n.detail-title .person-badge.jun { background: #27AE60; }'
    )
    print('CSS updated')

if '俊培' not in html:
    html = html.replace(
        '<span style="display:inline-block; width:12px; height:3px; background:#2980B9; margin-left:12px; margin-right:4px;"></span> 盈萱',
        '<span style="display:inline-block; width:12px; height:3px; background:#2980B9; margin-left:12px; margin-right:4px;"></span> 盈萱\n        <span style="display:inline-block; width:12px; height:3px; background:#27AE60; margin-left:12px; margin-right:4px;"></span> 俊培'
    )
    print('Legend updated')

if "getPersonData('俊'" not in html:
    # Add 3rd dataset
    dd_pos = html.find('const DETAIL_DATA')
    dd_pos = html.find(';', dd_pos) + 1
    third_ds = '''        {
          label: '俊培',
          data: getPersonData('俊', mode),
          borderColor: '#27AE60',
          backgroundColor: 'rgba(39,174,96,0.1)',
          pointBackgroundColor: '#27AE60',
          pointBorderColor: '#fff',
          pointBorderWidth: 2,
          pointRadius: 6,
          pointHoverRadius: 9,
          tension: 0.25,
          fill: true,
          spanGaps: false,
          borderWidth: 2.5
        }'''
    pat_end = 'borderWidth: 2.5\n        }\n      ]'
    dd_to_options = html[dd_pos:]
    idx = dd_to_options.find(pat_end)
    if idx >= 0:
        insert_pos = idx + len(pat_end) - 1
        html = html[:dd_pos+insert_pos] + ',\n' + third_ds + html[dd_pos+insert_pos:]
        print('Dataset added')
    else:
        print("WARNING: dataset insertion point not found")

if 'PERSON_PREFIX' not in html:
    old_prefix = "const prefix = person === '岍叡' ? 'qian' : 'xuan';"
    new_prefix = "const prefix = {'岍叡':'qian','盈萱':'xuan','俊':'jun'}[person] || 'qian';"
    prefix_idx = html.find(old_prefix)
    if prefix_idx >= 0:
        html = html[:prefix_idx] + new_prefix + html[prefix_idx+len(old_prefix):]
        print('Prefix updated')

old_click = "const person = dsIdx === 0 ? '岍叡' : '盈萱';"
new_click = "const person = ['岍叡','盈萱','俊'][dsIdx] || '岍叡';"
idx_ch = html.find(old_click)
if idx_ch >= 0:
    html = html[:idx_ch] + new_click + html[idx_ch+len(old_click):]
    print('Click handler updated')

# ── Write ──
with open(dst, 'w', encoding='utf-8') as f:
    f.write(html)
print(f'Written to {dst}')

# ── Verify ──
with open(dst, 'r', encoding='utf-8') as f:
    html_v = f.read()

if 'jun_points' in html_v:
    print('CHART_DATA: OK')
if "'俊'" in html_v:
    print('DETAIL_DATA: OK')

# Verify JSON integrity of CHART_DATA
cinfo2 = find_const('CHART_DATA', html_v)
if cinfo2:
    try:
        chart2 = json.loads(cinfo2[2])
        print(f'CHART_DATA valid: {len(chart2)} keys, weeks={chart2["weeks"]}')
        print(f'jun_points={chart2.get("jun_points", [])}')
        print(f'jun_tasks={chart2.get("jun_tasks", [])}')
    except Exception as e:
        print(f'CHART_DATA invalid: {e}')

dinfo2 = find_const('DETAIL_DATA', html_v)
if dinfo2:
    try:
        detail2 = json.loads(dinfo2[2])
        has_jun = '俊' in detail2
        print(f'DETAIL_DATA valid: {len(detail2)} persons, has_jun={has_jun}')
        if has_jun:
            jw = sorted(detail2['俊'].keys(), key=int)
            print(f'  俊 has {len(jw)} weeks: {jw[:5]}...{jw[-3:]}')
    except Exception as e:
        print(f'DETAIL_DATA invalid: {e}')
