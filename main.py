import flet as ft
import sqlite3
import json
import base64
from datetime import date, datetime, timedelta
from zhdate import ZhDate

# --- 1. 数据库初始化 ---
def init_db():
    conn = sqlite3.connect("attendance_lunar_pro_v140.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS workers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, daily_rate REAL)')
    cursor.execute('CREATE TABLE IF NOT EXISTS owners (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)')
    cursor.execute('''CREATE TABLE IF NOT EXISTS logs 
                      (date TEXT, worker_id INTEGER, am_owner_id INTEGER, pm_owner_id INTEGER, 
                       am INTEGER, pm INTEGER, PRIMARY KEY (date, worker_id))''')
    conn.commit()
    return conn

def main(page: ft.Page):
    # --- 基础配置 ---
    page.title = "极简考勤-农历明细版"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = ft.Padding.only(left=15, right=15, bottom=100, top=0)
    page.scroll = ft.ScrollMode.AUTO
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER

    db_conn = init_db()
    cursor = db_conn.cursor()
    
    state = {
        "view_date": date.today(), 
        "report_month": date.today(),
        "is_lunar_mode": True,  
        "pick_target_wid": None,
        "pick_target_period": "am",
        "add_mode": "worker"
    }

    # --- 2. 核心零件预定义 (解决 NameError) ---
    txt_date = ft.Text(size=18, weight="bold")
    txt_lunar = ft.Text(size=12, color="orange900")
    btn_back = ft.IconButton(ft.Icons.ARROW_BACK, icon_size=30)
    btn_next = ft.IconButton(ft.Icons.ARROW_FORWARD, icon_size=30)
    col_records = ft.Column(spacing=15)
    
    col_manage = ft.Column(spacing=10, tight=True, scroll=ft.ScrollMode.AUTO, height=400)
    col_report = ft.Column(spacing=10, tight=True, scroll=ft.ScrollMode.AUTO, height=400)
    col_detail = ft.Column(spacing=10, tight=True, scroll=ft.ScrollMode.AUTO, height=450)
    col_owners = ft.Column(spacing=10, tight=True, scroll=ft.ScrollMode.AUTO, height=400)
    
    in_name = ft.TextField(label="名称")
    in_rate = ft.TextField(label="日薪", keyboard_type="number")
    in_import = ft.TextField(label="粘贴备份文字", multiline=True, min_lines=5)
    txt_confirm = ft.Text("")
    on_confirm_cb = [None]

    # --- 3. 辅助功能 ---
    def get_lunar_text(d_obj):
        try:
            zd = ZhDate.from_datetime(datetime(d_obj.year, d_obj.month, d_obj.day))
            # chinese() 返回 "乙巳年正月十五"，提取 "正月十五"
            full = zd.chinese()
            return full[full.find("年")+1:]
        except: return "农历日期"

    def show_toast(text, is_error=False):
        page.snack_bar = ft.SnackBar(ft.Text(text, size=20), bgcolor="red700" if is_error else "green800", duration=1200)
        page.snack_bar.open = True; page.update()

    # --- 4. 弹窗对象预载 ---
    add_dlg = ft.AlertDialog(title=ft.Text("新增资料"), content=ft.Column([in_name, in_rate], tight=True))
    manage_dlg = ft.AlertDialog(title=ft.Text("管理名单"), content=col_manage, actions=[ft.TextButton("关闭", on_click=lambda _: (setattr(manage_dlg, "open", False), page.update()))])
    report_dlg = ft.AlertDialog(title=ft.Text("报表"))
    detail_dlg = ft.AlertDialog(title=ft.Text("明细"), content=col_detail)
    picker_dlg = ft.AlertDialog(title=ft.Text("选业主"), content=col_owners)
    import_dlg = ft.AlertDialog(title=ft.Text("恢复"), content=in_import)
    safe_dlg = ft.AlertDialog(title=ft.Text("确认"), content=txt_confirm)

    page.overlay.extend([add_dlg, manage_dlg, report_dlg, detail_dlg, picker_dlg, import_dlg, safe_dlg])

    # --- 5. 报表与明细切换逻辑 ---
    def get_logs_data():
        ref = state["report_month"]
        if state["is_lunar_mode"]:
            l_ref = ZhDate.from_datetime(datetime(ref.year, ref.month, ref.day))
            ly, lm = l_ref.lunar_year, l_ref.lunar_month
            title = f"农历 {ly}年{lm}月账"
            s, e = ref - timedelta(days=40), ref + timedelta(days=40)
            cursor.execute('SELECT l.*, w.name, w.daily_rate FROM logs l JOIN workers w ON l.worker_id=w.id WHERE date BETWEEN ? AND ?', (s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d")))
            valid = [r for r in cursor.fetchall() if ZhDate.from_datetime(datetime.strptime(r[0], "%Y-%m-%d")).lunar_year == ly and ZhDate.from_datetime(datetime.strptime(r[0], "%Y-%m-%d")).lunar_month == lm]
            return valid, title
        else:
            m_str = ref.strftime("%Y-%m")
            cursor.execute('SELECT l.*, w.name, w.daily_rate FROM logs l JOIN workers w ON l.worker_id=w.id WHERE date LIKE ?', (f"{m_str}%",))
            return cursor.fetchall(), f"阳历 {m_str} 账"

    def open_report_ui(mode="worker"):
        col_report.controls.clear()
        logs, title_text = get_logs_data()
        report_dlg.title.value = title_text
        
        if mode == "worker":
            res = {}
            for r in logs:
                wid, name, rate = r[1], r[6], r[7]
                days = (0.5 if r[4] else 0) + (0.5 if r[5] else 0)
                if wid not in res: res[wid] = {"n": name, "d": 0, "m": 0}
                res[wid]["d"] += days; res[wid]["m"] += days * rate
            for wid, d in res.items():
                col_report.controls.append(ft.Container(content=ft.Column([ft.Row([ft.Text(d['n'], size=22, weight="bold"), ft.Text("看明细 >")]), ft.Text(f"天数: {d['d']:g} | 工钱: {d['m']:g}元")]), padding=10, bgcolor="grey100", border_radius=8, on_click=lambda _, i=wid, nm=d['n']: open_drill_down(i, nm, "worker")))
        else:
            res = {}
            cursor.execute("SELECT id, name FROM owners"); o_map = {row[0]: row[1] for row in cursor.fetchall()}
            for r in logs:
                rate = r[7]
                if r[4] and r[2] in o_map: # 上午
                    if r[2] not in res: res[r[2]] = {"n": o_map[r[2]], "d": 0, "m": 0}
                    res[r[2]]["d"] += 0.5; res[r[2]]["m"] += 0.5 * rate
                if r[5] and r[3] in o_map: # 下午
                    if r[3] not in res: res[r[3]] = {"n": o_map[r[3]], "d": 0, "m": 0}
                    res[r[3]]["d"] += 0.5; res[r[3]]["m"] += 0.5 * rate
            for oid, d in res.items():
                col_report.controls.append(ft.Container(content=ft.Column([ft.Row([ft.Text(d['n'], size=22, weight="bold"), ft.Text("看账单 >")]), ft.Text(f"总额: {d['m']:g} 元 | 总工: {d['d']:g}", weight="bold", color="blue700")]), padding=10, bgcolor="blue50", border_radius=8, on_click=lambda _, i=oid, nm=d['n']: open_drill_down(i, nm, "owner")))

        report_dlg.content = ft.Column([
            ft.Row([ft.Text("阳历"), ft.Switch(value=state["is_lunar_mode"], on_change=lambda e: (state.update(is_lunar_mode=e.control.value), open_report_ui(mode))), ft.Text("农历")], alignment="center"),
            ft.Row([ft.TextButton("工人汇总", on_click=lambda _: open_report_ui("worker")), ft.TextButton("业主汇总", on_click=lambda _: open_report_ui("owner"))], alignment="center"),
            ft.Row([ft.IconButton(ft.Icons.ARROW_LEFT, on_click=lambda _: (state.update(report_month=state["report_month"]-timedelta(days=30)), open_report_ui(mode))), ft.Text("切换月份"), ft.IconButton(ft.Icons.ARROW_RIGHT, on_click=lambda _: (state.update(report_month=state["report_month"]+timedelta(days=30)), open_report_ui(mode)))], alignment="center"),
            ft.Divider(), col_report
        ], tight=True)
        report_dlg.open = True; page.update()

    def open_drill_down(tid, tname, type):
        col_detail.controls.clear()
        logs, _ = get_logs_data()
        detail_dlg.title.value = f"【{tname}】农历明细" if state["is_lunar_mode"] else f"【{tname}】阳历明细"
        
        for r in logs:
            # 确定显示日期
            solar_d = r[0]
            if state["is_lunar_mode"]:
                d_obj = datetime.strptime(solar_d, "%Y-%m-%d").date()
                display_date = get_lunar_text(d_obj)
            else:
                display_date = solar_d
            
            if type == "worker" and r[1] == tid:
                cursor.execute("SELECT name FROM owners WHERE id=?", (r[2],)); n1 = cursor.fetchone()
                cursor.execute("SELECT name FROM owners WHERE id=?", (r[3],)); n2 = cursor.fetchone()
                col_detail.controls.append(ft.Container(
                    content=ft.Column([
                        ft.Text(display_date, weight="bold"), 
                        ft.Text(f"上:{n1[0] if n1 else '-'} {'(来)' if r[4] else ''} 下:{n2[0] if n2 else '-'} {'(来)' if r[5] else ''}", size=14)
                    ]), padding=10, bgcolor="grey100", border_radius=8, 
                    on_click=lambda _, d=solar_d: (state.update(view_date=datetime.strptime(d, "%Y-%m-%d").date()), setattr(detail_dlg, "open", False), setattr(report_dlg, "open", False), refresh_ui())
                ))
            elif type == "owner":
                dv = (0.5 if r[4] and r[2]==tid else 0) + (0.5 if r[5] and r[3]==tid else 0)
                if dv > 0:
                    col_detail.controls.append(ft.Row([
                        ft.Text(display_date, width=100, weight="bold"), ft.Text(r[6], width=80), ft.Text(f"{dv:g}工", width=50), ft.Text(f"{(dv*r[7]):g}元")
                    ]))
        
        if not col_detail.controls: col_detail.controls.append(ft.Text("暂无记录"))
        detail_dlg.actions = [ft.TextButton("返回", on_click=lambda _: (setattr(detail_dlg, "open", False), open_report_ui(type)))]
        report_dlg.open, detail_dlg.open = False, True; page.update()

    # --- 6. 主界面刷新 (接回箭头逻辑) ---
    def refresh_ui():
        today, d_str = date.today(), state["view_date"].strftime("%Y-%m-%d")
        txt_date.value = d_str + (" (今)" if state["view_date"] == today else "")
        txt_lunar.value = "农历 " + get_lunar_text(state["view_date"])
        
        btn_back.on_click = lambda _: (state.update(view_date=state["view_date"]-timedelta(days=1)), refresh_ui())
        if state["view_date"] >= today:
            btn_next.disabled, btn_next.icon_color = True, "grey400"
            btn_next.on_click = lambda _: show_toast("不能记录未来", True)
        else:
            btn_next.disabled, btn_next.icon_color = False, "black"
            btn_next.on_click = lambda _: (state.update(view_date=state["view_date"]+timedelta(days=1)), refresh_ui())
        
        col_records.controls.clear()
        cursor.execute("SELECT id, name, daily_rate FROM workers")
        for wid, name, rate in cursor.fetchall():
            cursor.execute('SELECT am_owner_id, pm_owner_id, am, pm FROM logs WHERE date=? AND worker_id=?', (d_str, wid))
            log = cursor.fetchone()
            ao, po, am, pm = log if log else (None, None, 0, 0)
            cursor.execute("SELECT name FROM owners WHERE id=?", (ao,)); r1 = cursor.fetchone()
            cursor.execute("SELECT name FROM owners WHERE id=?", (po,)); r2 = cursor.fetchone()

            def make_toggle(i, n, k, c_log):
                def h(e):
                    if (k=='am' and c_log[0] is None) or (k=='pm' and c_log[1] is None): show_toast("先选业主！", True); return
                    def commit():
                        cursor.execute("INSERT OR REPLACE INTO logs VALUES (?,?,?,?,?,?)", (d_str, i, c_log[0], c_log[1], not c_log[2] if k=='am' else c_log[2], not c_log[3] if k=='pm' else c_log[3]))
                        db_conn.commit(); refresh_ui()
                    txt_confirm.value = f"修改 {n} 的出勤？"; on_confirm_cb[0] = commit; safe_dlg.actions = [ft.TextButton("取消", on_click=lambda _: (setattr(safe_dlg, "open", False), page.update())), ft.FilledButton("确定", on_click=lambda _: (on_confirm_cb[0](), setattr(safe_dlg, "open", False), page.update()))]; safe_dlg.open = True; page.update()
                return h

            col_records.controls.append(ft.Container(content=ft.Column([
                ft.Text(name, size=32, weight="bold"),
                ft.Row([
                    ft.Column([ft.TextButton(r1[0] if r1 else "选上业主 >", on_click=lambda _, i=wid: open_owner_picker_ui(i, "am")), ft.Container(content=ft.Text("上午来了" if am else "上午没来", weight="bold"), alignment=ft.Alignment(0,0), width=145, height=75, border_radius=10, bgcolor="green400" if am else "grey300", on_click=make_toggle(wid, name, 'am', (ao, po, am, pm)))], horizontal_alignment="center"),
                    ft.Column([ft.TextButton(r2[0] if r2 else "选下业主 >", on_click=lambda _, i=wid: open_owner_picker_ui(i, "pm")), ft.Container(content=ft.Text("下午来了" if pm else "下午没来", weight="bold"), alignment=ft.Alignment(0,0), width=145, height=75, border_radius=10, bgcolor="green400" if pm else "grey300", on_click=make_toggle(wid, name, 'pm', (ao, po, am, pm)))], horizontal_alignment="center"),
                ], alignment="center"),
                ft.Text(f"今日工资：{(((0.5 if am else 0)+(0.5 if pm else 0))*rate):g} 元", size=20, weight="bold", color="blue700"),
                ft.Divider()
            ]), padding=5))
        page.update()

    def open_owner_picker_ui(wid, period):
        state["pick_target_wid"], state["pick_target_period"] = wid, period
        col_owners.controls.clear(); cursor.execute("SELECT id, name FROM owners")
        for oid, onm in cursor.fetchall():
            def set_o(e, idx=oid):
                w, p, ds = state["pick_target_wid"], state["pick_target_period"], state["view_date"].strftime("%Y-%m-%d")
                cursor.execute("INSERT OR REPLACE INTO logs (date, worker_id, am_owner_id, pm_owner_id, am, pm) SELECT ?,?,?,?,?,? WHERE NOT EXISTS (SELECT 1 FROM logs WHERE date=? AND worker_id=?)", (ds, w, idx if p=='am' else None, idx if p=='pm' else None, 0, 0, ds, w))
                cursor.execute("UPDATE logs SET am_owner_id=? WHERE date=? AND worker_id=?" if p=='am' else "UPDATE logs SET pm_owner_id=? WHERE date=? AND worker_id=?", (idx, ds, w))
                db_conn.commit(); picker_dlg.open = False; refresh_ui()
            col_owners.controls.append(ft.ListTile(title=ft.Text(onm, size=24, weight="bold"), on_click=set_o))
        picker_dlg.open = True; page.update()

    # --- 7. 菜单配置 ---
    def on_add_confirm(e):
        if not in_name.value: return
        if state["add_mode"]=="worker": cursor.execute("INSERT INTO workers (name, daily_rate) VALUES (?,?)", (in_name.value, float(in_rate.value or 0)))
        else: cursor.execute("INSERT INTO owners (name) VALUES (?)", (in_name.value,))
        db_conn.commit(); in_name.value, in_rate.value, add_dlg.open = "", "", False; refresh_ui()

    add_dlg.actions = [ft.TextButton("取消", on_click=lambda _: (setattr(add_dlg, "open", False), page.update())), ft.FilledButton("确定", on_click=on_add_confirm)]

    def open_manage_list(m):
        col_manage.controls.clear(); table = "workers" if m=="worker" else "owners"
        for i, n in cursor.execute(f"SELECT id, name FROM {table}").fetchall():
            def do_del(idx=i, nm=n):
                cursor.execute(f"DELETE FROM {table} WHERE id=?", (idx,)); db_conn.commit(); manage_dlg.open = False; refresh_ui(); show_toast("已删除")
            col_manage.controls.append(ft.Row([ft.Text(n, size=24, weight="bold"), ft.IconButton(ft.Icons.DELETE, icon_color="red", on_click=lambda _, f=do_del: (on_confirm_cb.__setitem__(0, f), setattr(txt_confirm, "value", "确定删除？记录会消失"), setattr(safe_dlg, "open", True), page.update()))], alignment="spaceBetween"))
        manage_dlg.open = True; page.update()

    page.appbar = ft.AppBar(title=ft.Text("极简考勤"), bgcolor="blue50", actions=[
        ft.IconButton(ft.Icons.ASSESSMENT, on_click=lambda _: open_report_ui("worker"), icon_color="green", icon_size=35),
        ft.PopupMenuButton(items=[
            ft.PopupMenuItem(content=ft.Text("新增工人"), on_click=lambda _: (setattr(in_rate, "visible", True), state.update(add_mode="worker"), setattr(add_dlg, "open", True), page.update())),
            ft.PopupMenuItem(content=ft.Text("新增业主"), on_click=lambda _: (setattr(in_rate, "visible", False), state.update(add_mode="owner"), setattr(add_dlg, "open", True), page.update())),
            ft.PopupMenuItem(content=ft.Text("管理工人"), on_click=lambda _: open_manage_list("worker")),
            ft.PopupMenuItem(content=ft.Text("管理业主"), on_click=lambda _: open_manage_list("owner")),
            ft.PopupMenuItem(content=ft.Divider()),
            ft.PopupMenuItem(content=ft.Text("下载备份"), on_click=lambda _: page.launch_url(f"data:text/plain;charset=utf-8;base64,{base64.b64encode(json.dumps({'workers':cursor.execute('SELECT * FROM workers').fetchall(),'owners':cursor.execute('SELECT * FROM owners').fetchall(),'logs':cursor.execute('SELECT * FROM logs').fetchall()},ensure_ascii=False).encode('utf-8')).decode('utf-8')}")),
            ft.PopupMenuItem(content=ft.Text("恢复数据"), on_click=lambda _: (setattr(import_dlg, "open", True), page.update())),
        ])
    ])

    page.floating_action_button = ft.FloatingActionButton(bgcolor="blue700", content=ft.Row([ft.Icon(ft.Icons.REPLAY, color="white"), ft.Text("回今天", color="white", weight="bold")], alignment="center", spacing=5), width=120, on_click=lambda _: (state.update(view_date=date.today()), refresh_ui()))
    
    refresh_ui()
    page.add(ft.Container(content=ft.Row([btn_back, ft.Column([txt_date, txt_lunar], horizontal_alignment="center", spacing=-5), btn_next], alignment="spaceBetween"), bgcolor="amber50", height=55, border_radius=10), col_records)

if __name__ == "__main__":
    ft.app(main)