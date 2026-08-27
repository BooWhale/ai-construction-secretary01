import streamlit as st
import pandas as pd
import sqlite3
import requests
import os
import json
from datetime import datetime
from streamlit_calendar import calendar

# ==========================================
# 1. ตั้งค่าระบบและ API KEYS
# ==========================================
st.set_page_config(page_title="Executive Task & AI Consultant", layout="wide", page_icon="🏢")

# Google Gemini API Key
GEMINI_API_KEY = "AQ.Ab8RN6Kunr9nWeB3KCAG6T-ZnIub9062uHa3OybohkPeiIEdiA"

# LINE Messaging API Credentials
LINE_CHANNEL_ACCESS_TOKEN = "tczZhOEGhupttNJGtkFywMJDNsgTO5Wib99thpNy+ORanz1nyKP1roZw4HNTwu/sStmF4FO/WILjtMMXLRwqvjBs1TYHgSVgNnNdtIu7MrABP7SdLLYWZ+xtlosdlmE654odeJ0JDr/Y2uwFd9/hDQdB04t89/1O/w1cDnyilFU="
LINE_RECEIVER_ID = "U87c3ee67a45f19e3539bbb0963aba4c8"

# โฟลเดอร์สำหรับจัดเก็บรูปภาพหน้างาน
UPLOAD_FOLDER = "uploaded_images"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ==========================================
# 2. ฟังก์ชันเรียกใช้งาน Native Google Gemini API (gemini-3.6-flash)
# ==========================================
def query_gemini_api(prompt_text):
    """ส่งคำขอไปยัง Google Gemini API"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    headers = {
        "Content-Type": "application/json"
    }
    
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt_text}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.5,
            "maxOutputTokens": 2048
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=90)
        if response.status_code == 200:
            result_json = response.json()
            candidates = result_json.get("candidates", [])
            if candidates and "content" in candidates[0]:
                parts = candidates[0]["content"].get("parts", [])
                if parts:
                    return parts[0].get("text", "ไม่มีข้อความตอบกลับจากโมเดล")
            return "❌ ไม่พบข้อความตอบกลับจากระบบ"
        else:
            # Fallback หากโมเดลเปลี่ยนเวอร์ชัน
            fallback_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
            fallback_res = requests.post(fallback_url, headers=headers, json=payload, timeout=90)
            if fallback_res.status_code == 200:
                return fallback_res.json()["candidates"][0]["content"]["parts"][0]["text"]
                
            return f"❌ เกิดข้อผิดพลาดจาก Gemini API (Code {response.status_code}): {response.text}"
    except requests.exceptions.Timeout:
        return "⏳ เซิร์ฟเวอร์ AI กำลังประมวลผลข้อมูลขนาดใหญ่ กรุณากดลองใหม่อีกครั้ง"
    except Exception as e:
        return f"❌ ข้อผิดพลาดในการเชื่อมต่อ: {str(e)}"

# ==========================================
# 3. ฐานข้อมูล SQLite
# ==========================================
def init_db():
    conn = sqlite3.connect("company_work.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password TEXT,
                    fullname TEXT,
                    department TEXT,
                    role TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS tasks (
                    task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_name TEXT,
                    department TEXT,
                    assignee_username TEXT,
                    due_date TEXT,
                    status TEXT,
                    progress_note TEXT,
                    image_path TEXT,
                    last_updated TEXT)''')
    conn.commit()
    conn.close()

init_db()

def get_db_connection():
    return sqlite3.connect("company_work.db")

# ==========================================
# 4. ฟังก์ชันส่ง LINE Push Message
# ==========================================
def send_line_push(message_text):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }
    payload = {
        "to": LINE_RECEIVER_ID,
        "messages": [{"type": "text", "text": message_text}]
    }
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=15)
        return res.status_code == 200, res.text
    except Exception as e:
        return False, str(e)

# ==========================================
# 5. ฟังก์ชันจัดรูปแบบปฏิทิน FullCalendar
# ==========================================
def format_tasks_to_events(task_df):
    events = []
    color_map = {
        "Completed": "#28a745",    # เขียว
        "In Progress": "#ffc107",  # เหลือง
        "Pending": "#dc3545"       # แดง
    }
    
    for _, row in task_df.iterrows():
        status = row.get("status", "Pending")
        bg_color = color_map.get(status, "#17a2b8")
        text_color = "#000000" if status == "In Progress" else "#ffffff"
        assignee = row.get("assignee", row.get("assignee_username", ""))
        title_str = f"[{status}] {row['task_name']} ({assignee})"
        
        events.append({
            "id": str(row["task_id"]),
            "title": title_str,
            "start": str(row["due_date"]),
            "backgroundColor": bg_color,
            "borderColor": bg_color,
            "textColor": text_color,
            "allDay": True
        })
    return events

calendar_options = {
    "headerToolbar": {
        "left": "today prev,next",
        "center": "title",
        "right": "dayGridMonth,timeGridWeek,listMonth"
    },
    "initialView": "dayGridMonth",
    "navLinks": True,
    "selectable": True,
    "editable": False
}

# ==========================================
# 6. ส่วนตรวจสอบสิทธิ์ (Authentication)
# ==========================================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user = None

if not st.session_state.logged_in:
    st.title("🏢 ระบบบริหารงานก่อสร้าง & AI เลขานุการผู้บริหาร")
    
    tab_login, tab_reg = st.tabs(["🔑 เข้าสู่ระบบ (Login)", "📝 สมัครสมาชิก (Register)"])
    
    with tab_login:
        st.subheader("เข้าสู่ระบบ")
        login_user = st.text_input("ชื่อผู้ใช้ (Username)")
        login_pass = st.text_input("รหัสผ่าน (Password)", type="password")
        if st.button("เข้าสู่ระบบ", use_container_width=True, type="primary"):
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT username, fullname, department, role FROM users WHERE username=? AND password=?", (login_user, login_pass))
            user_data = c.fetchone()
            conn.close()
            
            if user_data:
                st.session_state.logged_in = True
                st.session_state.user = {
                    "username": user_data[0],
                    "fullname": user_data[1],
                    "department": user_data[2],
                    "role": user_data[3]
                }
                st.rerun()
            else:
                st.error("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")

    with tab_reg:
        st.subheader("สร้างบัญชีผู้ใช้งานใหม่")
        new_user = st.text_input("สร้างชื่อผู้ใช้ (Username)", key="reg_user")
        new_pass = st.text_input("สร้างรหัสผ่าน (Password)", type="password", key="reg_pass")
        new_name = st.text_input("ชื่อ - นามสกุลจริง")
        new_dept = st.selectbox("แผนก", ["ควบคุมคุณภาพ (QC)", "วิศวกรรม/หน้างาน", "จัดซื้อจัดจ้าง", "บัญชีและการเงิน", "สนับสนุนโครงการ", "สถาปัตย์/Landscape", "Executive Office"])
        new_role = st.selectbox("บทบาท (Role)", ["พนักงาน (Employee)", "หัวหน้า/ผู้บริหาร (Manager)"])
        
        if st.button("ลงทะเบียน", use_container_width=True):
            if new_user and new_pass and new_name:
                try:
                    conn = get_db_connection()
                    c = conn.cursor()
                    role_code = "Manager" if "หัวหน้า" in new_role else "Employee"
                    c.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?)", (new_user, new_pass, new_name, new_dept, role_code))
                    conn.commit()
                    conn.close()
                    st.success("ลงทะเบียนสำเร็จ! กรุณาสลับไปแท็บเข้าสู่ระบบ")
                except sqlite3.IntegrityError:
                    st.error("ชื่อผู้ใช้นี้ถูกใช้งานแล้ว กรุณาตั้งชื่ออื่น")
            else:
                st.warning("กรุณากรอกข้อมูลให้ครบทุกช่อง")

else:
    user = st.session_state.user
    
    with st.sidebar:
        st.write(f"👤 **ผู้ใช้งาน:** {user['fullname']}")
        st.write(f"🏢 **แผนก:** {user['department']}")
        st.write(f"🎖️ **ระดับ:** {'👑 หัวหน้า / ผู้บริหาร' if user['role'] == 'Manager' else '🛠️ พนักงาน'}")
        if st.button("🚪 ออกจากระบบ (Logout)", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.user = None
            st.rerun()

    # =============================================================
    # 📌 ส่วนหน้าจอสำหรับ "พนักงาน" (Employee) - บังคับเลือกจากงานที่มีอยู่
    # =============================================================
    if user['role'] == "Employee":
        st.title(f"🛠️ หน้าส่งงานและปฏิทินงาน - คุณ {user['fullname']}")
        tab_cal, tab_update_task = st.tabs(["📅 ปฏิทินงานของฉัน (Calendar)", "✍️ อัปเดตความคืบหน้างาน (จากงานที่ได้รับมอบหมาย)"])
        
        conn = get_db_connection()
        my_tasks = pd.read_sql_query("SELECT * FROM tasks WHERE assignee_username=?", conn, params=(user['username'],))
        conn.close()

        with tab_cal:
            st.subheader("📅 ตารางกำหนดส่งงานของคุณ")
            if my_tasks.empty:
                st.info("ยังไม่มีรายการงานในปฏิทิน")
            else:
                events = format_tasks_to_events(my_tasks)
                calendar(events=events, options=calendar_options, key="emp_calendar")

        with tab_update_task:
            if my_tasks.empty:
                st.info("💡 ขณะนี้คุณยังไม่มีงานที่ได้รับมอบหมายจากหัวหน้างาน")
            else:
                st.subheader("📋 รายการงานที่ต้องรับผิดชอบ")
                st.dataframe(my_tasks[['task_id', 'task_name', 'due_date', 'status', 'progress_note', 'last_updated']], use_container_width=True)
                
                st.divider()
                st.subheader("✍️ รายงานผลและเปลี่ยนสถานะงาน")
                
                # ตัวเลือกงานที่สร้างโดยหัวหน้า บังคับเลือกตาม ID เพื่อป้องกันการสร้างชื่อซ้ำ
                task_options = {
                    f"งาน #{row['task_id']} : {row['task_name']} (กำหนดส่ง: {row['due_date']})": row['task_id'] 
                    for _, row in my_tasks.iterrows()
                }
                
                selected_label = st.selectbox("📌 เลือกงานที่ต้องการรายงานผล:", list(task_options.keys()))
                selected_id = task_options[selected_label]
                
                # ดึงข้อมูลเดิมมาแสดง
                current_task_row = my_tasks[my_tasks['task_id'] == selected_id].iloc[0]
                status_index = 0
                if current_task_row['status'] == "In Progress":
                    status_index = 1
                elif current_task_row['status'] == "Completed":
                    status_index = 2

                with st.form("update_progress_form"):
                    st.info(f"กำลังอัปเดตงาน: **{current_task_row['task_name']}**")
                    
                    new_status = st.selectbox(
                        "🚦 ปรับสถานะงาน",
                        ["Pending (ยังไม่เริ่ม/ติดขัด)", "In Progress (กำลังดำเนินการ)", "Completed (เสร็จสิ้นเรียบร้อย)"],
                        index=status_index
                    )
                    
                    progress_text = st.text_area(
                        "📝 รายละเอียดผลการดำเนินงาน / ความคืบหน้า",
                        value=current_task_row['progress_note'] if current_task_row['progress_note'] else ""
                    )
                    
                    uploaded_img = st.file_uploader("📸 แนบรูปภาพรายงานหน้างาน (JPG, PNG)", type=["jpg", "png", "jpeg"])
                    
                    if st.form_submit_button("💾 บันทึกและส่งรายงานความคืบหน้า", type="primary"):
                        status_clean = new_status.split(" ")[0]
                        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                        img_path = current_task_row['image_path']
                        
                        if uploaded_img:
                            img_filename = f"task_{selected_id}_{int(datetime.now().timestamp())}.png"
                            img_path = os.path.join(UPLOAD_FOLDER, img_filename)
                            with open(img_path, "wb") as f:
                                f.write(uploaded_img.getbuffer())
                        
                        conn = get_db_connection()
                        c = conn.cursor()
                        c.execute("""
                            UPDATE tasks 
                            SET status=?, progress_note=?, image_path=?, last_updated=? 
                            WHERE task_id=?
                        """, (status_clean, progress_text, img_path, now_str, selected_id))
                        conn.commit()
                        conn.close()
                        
                        st.success(f"✅ บันทึกความคืบหน้างาน #{selected_id} เรียบร้อยแล้ว!")
                        st.rerun()

    # =============================================================
    # 📌 ส่วนหน้าจอสำหรับ "หัวหน้า/ผู้บริหาร" (Manager)
    # =============================================================
    elif user['role'] == "Manager":
        st.title("👑 แดชบอร์ดผู้บริหาร & AI เลขาติดตามงาน")
        
        conn = get_db_connection()
        all_tasks = pd.read_sql_query("""
            SELECT t.task_id, t.task_name, t.department, u.fullname as assignee, t.due_date, t.status, t.progress_note, t.image_path, t.last_updated
            FROM tasks t
            LEFT JOIN users u ON t.assignee_username = u.username
        """, conn)
        
        employees = pd.read_sql_query("SELECT username, fullname, department FROM users WHERE role='Employee'", conn)
        conn.close()

        tab_cal, tab_overview, tab_create, tab_delete, tab_ai, tab_chat = st.tabs([
            "📅 ปฏิทินงานรวมทุกคน (Calendar View)", 
            "📊 ตารางงาน & รูปภาพหน้างาน", 
            "➕ มอบหมายงานใหม่", 
            "🗑️ ลบ/จัดการงานที่ผิดพลาด",
            "🤖 AI เลขาสรุปและส่ง LINE",
            "💬 ปรึกษา AI ผู้ช่วยบริหาร"
        ])
        
        with tab_cal:
            st.subheader("📅 ปฏิทิน Deadline และสถานะงานของทุกคนในทีม")
            st.markdown("""
            **คำอธิบายสี:** 
            🔴 **สีแดง:** Pending (รอดำเนินการ/ยังไม่เสร็จ) | 
            🟡 **สีเหลือง:** In Progress (กำลังดำเนินการ) | 
            🟢 **สีเขียว:** Completed (เสร็จสิ้น)
            """)
            if all_tasks.empty:
                st.info("ยังไม่มีข้อมูลงานในปฏิทิน")
            else:
                events = format_tasks_to_events(all_tasks)
                calendar(events=events, options=calendar_options, key="manager_calendar")

        with tab_overview:
            st.subheader("ภาพรวมสถานะงานทั้งหมด")
            if all_tasks.empty:
                st.info("ยังไม่มีข้อมูลงานในระบบ")
            else:
                st.dataframe(all_tasks[['task_id', 'task_name', 'department', 'assignee', 'due_date', 'status', 'progress_note', 'last_updated']], use_container_width=True)
                
                st.divider()
                st.subheader("🖼️ ตรวจสอบรูปภาพหน้างานล่าสุด")
                tasks_with_images = all_tasks[all_tasks['image_path'].notnull()]
                if tasks_with_images.empty:
                    st.info("ยังไม่มีพนักงานแนบรูปภาพเข้ามา")
                else:
                    cols = st.columns(3)
                    for idx, row in tasks_with_images.iterrows():
                        col = cols[idx % 3]
                        with col:
                            if os.path.exists(str(row['image_path'])):
                                st.image(row['image_path'], caption=f"งาน #{row['task_id']}: {row['task_name']}", use_container_width=True)
                                st.caption(f"👤 ผู้ส่ง: {row['assignee']} ({row['department']})")
                                st.caption(f"📝 ความคืบหน้า: {row['progress_note']}")

        with tab_create:
            st.subheader("สร้างงานและกำหนดลงปฏิทิน")
            if employees.empty:
                st.warning("ยังไม่มีพนักงานสมัครสมาชิกในระบบ")
            else:
                with st.form("assign_form"):
                    task_title = st.text_input("ชื่องาน / รายละเอียดสั้นๆ")
                    emp_choices = {f"{row['fullname']} ({row['department']})": row['username'] for _, row in employees.iterrows()}
                    selected_emp_name = st.selectbox("มอบหมายให้", list(emp_choices.keys()))
                    assigned_username = emp_choices[selected_emp_name]
                    
                    emp_dept = employees[employees['username'] == assigned_username]['department'].values[0]
                    due = st.date_input("กำหนดส่ง (Due Date)")
                    
                    if st.form_submit_button("บันทึกและลงปฏิทิน"):
                        if task_title:
                            conn = get_db_connection()
                            c = conn.cursor()
                            c.execute("INSERT INTO tasks (task_name, department, assignee_username, due_date, status, progress_note, image_path, last_updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                      (task_title, emp_dept, assigned_username, str(due), "Pending", "รอดำเนินการ", None, datetime.now().strftime("%Y-%m-%d %H:%M")))
                            conn.commit()
                            conn.close()
                            st.success(f"ลงงานในปฏิทินให้ {selected_emp_name} เรียบร้อยแล้ว!")
                            st.rerun()
                        else:
                            st.error("กรุณากรอกชื่องาน")

        with tab_delete:
            st.subheader("🗑️ ลบรายการงานที่กรอกผิดพลาด")
            st.caption("เฉพาะหัวหน้า/ผู้บริหาร สามารถเลือกลบงานที่สร้างผิด หรือข้อมูลที่ไม่ถูกต้องออกจากระบบและปฏิทินได้")
            
            if all_tasks.empty:
                st.info("ไม่มีรายการงานในระบบให้ลบ")
            else:
                delete_options = {
                    f"#{row['task_id']} | {row['task_name']} (ผู้รับผิดชอบ: {row['assignee'] or 'ยังไม่ระบุ'}, กำหนดส่ง: {row['due_date']})": row['task_id']
                    for _, row in all_tasks.iterrows()
                }
                
                selected_task_label = st.selectbox("เลือกงานที่ต้องการลบออกจากระบบ:", list(delete_options.keys()))
                target_task_id = delete_options[selected_task_label]
                
                selected_task_info = all_tasks[all_tasks['task_id'] == target_task_id].iloc[0]
                with st.expander("🔍 ดูรายละเอียดงานที่เลือกก่อนลบ", expanded=True):
                    st.write(f"📌 **ชื่องาน:** {selected_task_info['task_name']}")
                    st.write(f"🏢 **แผนก:** {selected_task_info['department']}")
                    st.write(f"👤 **ผู้รับผิดชอบ:** {selected_task_info['assignee']}")
                    st.write(f"📅 **กำหนดส่ง:** {selected_task_info['due_date']}")
                    st.write(f"🚦 **สถานะ:** {selected_task_info['status']}")
                    if selected_task_info['progress_note']:
                        st.write(f"📝 **บันทึกความคืบหน้า:** {selected_task_info['progress_note']}")

                st.divider()
                confirm_delete = st.checkbox("⚠️ ยืนยันว่าต้องการลบงานนี้อย่างถาวร (ไม่สามารถกู้คืนได้)")
                
                if st.button("🗑️ ลบงานนี้ออกจากระบบทันที", type="primary", disabled=not confirm_delete):
                    conn = get_db_connection()
                    c = conn.cursor()
                    
                    c.execute("SELECT image_path FROM tasks WHERE task_id=?", (target_task_id,))
                    row_img = c.fetchone()
                    if row_img and row_img[0] and os.path.exists(row_img[0]):
                        try:
                            os.remove(row_img[0])
                        except Exception:
                            pass
                    
                    c.execute("DELETE FROM tasks WHERE task_id=?", (target_task_id,))
                    conn.commit()
                    conn.close()
                    
                    st.success(f"✅ ลบงานรหัส #{target_task_id} สำเร็จเรียบร้อยแล้ว!")
                    st.rerun()

        with tab_ai:
            st.subheader("สรุปความคืบหน้างานรายบุคคลด้วย AI")
            if st.button("✨ ให้ AI เลขาวิเคราะห์และสรุปงานเดี๋ยวนี้", type="primary"):
                if all_tasks.empty:
                    st.warning("ไม่มีงานให้วิเคราะห์")
                else:
                    with st.spinner("AI เลขากำลังอ่านปฏิทินและสถานะงาน..."):
                        today_str = datetime.now().strftime("%Y-%m-%d")
                        ai_prompt = f"""
                        คุณเป็นเลขา AI ประจำตัวผู้บริหาร สรุปข้อมูลให้อ่านเข้าใจง่าย รวดเร็ว และกระชับที่สุด (เน้น Bullet Points)
                        วันที่ปัจจุบัน: {today_str}

                        ข้อมูลงานในระบบ:
                        {all_tasks[['task_name', 'department', 'assignee', 'due_date', 'status', 'progress_note']].to_string(index=False)}

                        โครงสร้างการตอบ (สั้น กระชับ ตรงประเด็น):
                        1. 📊 ภาพรวมสถานะ (เช่น เสร็จ X, กำลังทำ Y, ค้าง Z)
                        2. ⚠️ จุดวิกฤต / งานล่าช้า / งานค้าง (ระบุ ชื่องาน + ผู้รับผิดชอบ สั้นๆ)
                        3. 💡 ข้อเสนอแนะเชิงบริหาร 1-2 ข้อ (Action Plan สั้นๆ)
                        *ไม่ต้องเกริ่นนำยาว เข้าประเด็นทันที*
                        """
                        st.session_state.ai_summary = query_gemini_api(ai_prompt)
            
            if "ai_summary" in st.session_state:
                st.markdown(st.session_state.ai_summary)
                st.divider()
                if st.button("🚀 ยิงข้อความเข้า LINE ผู้บริหารทันที"):
                    success, res_msg = send_line_push(st.session_state.ai_summary)
                    if success:
                        st.success("✅ ส่งข้อความสรุปเข้า LINE ผู้บริหารเรียบร้อยแล้ว!")
                    else:
                        st.error(f"❌ ส่งไม่สำเร็จ: {res_msg}")

        with tab_chat:
            st.subheader("💬 ปรึกษาเชิงกลยุทธ์กับ AI Executive Consultant")
            st.caption("AI วิเคราะห์ข้อมูลสถานะงานและสรุปแนวทางบริหารให้แบบกระชับ ตรงประเด็น")

            system_instruction = f"""
            คุณคือ "ที่ปรึกษาอาวุโสของผู้บริหาร (Executive Consultant)" 
            
            กฎการตอบคำถาม:
            1. สรุปเนื้อหาให้ "สั้น กระชับ ตรงเป้าหมายที่สุด" โดยรักษาเนื้อหาหลักและข้อเท็จจริงครบถ้วน
            2. ใช้โครงสร้าง Bullet Points สั้นๆ ไม่เวิ่นเว้อ ไม่ต้องเกริ่นนำยาว
            3. เน้น: ปัญหาคืออะไร (Root Cause) -> ผลกระทบ -> แนวทางแก้ปัญหาที่ทำได้ทันที (Actionable Solution)
            4. อ้างอิงข้อมูลจากตารางงานด้านล่างนี้:
            {all_tasks[['task_name', 'department', 'assignee', 'due_date', 'status', 'progress_note']].to_string(index=False)}
            """

            if "manager_chat_messages" not in st.session_state:
                st.session_state.manager_chat_messages = [
                    {"role": "assistant", "content": "สวัสดีครับท่านผู้บริหาร มีประเด็นงานหรือสถานะจุดใดที่ต้องการให้ผมสรุปและวิเคราะห์ด่วนไหมครับ?"}
                ]

            for msg in st.session_state.manager_chat_messages:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

            if prompt_input := st.chat_input("พิมพ์ประเด็นที่ต้องการปรึกษา (เช่น 'หาสาเหตุที่งานล่าช้า', 'ใครมีงานโหลดเกินไป')..."):
                st.session_state.manager_chat_messages.append({"role": "user", "content": prompt_input})
                with st.chat_message("user"):
                    st.markdown(prompt_input)

                with st.chat_message("assistant"):
                    with st.spinner("กำลังวิเคราะห์ข้อมูล..."):
                        full_prompt = f"{system_instruction}\n\nคำถามจากผู้บริหาร: {prompt_input}"
                        reply_text = query_gemini_api(full_prompt)
                        st.markdown(reply_text)
                        st.session_state.manager_chat_messages.append({"role": "assistant", "content": reply_text})
