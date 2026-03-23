import os
import sys
import re
import time
import random
import asyncio
from datetime import datetime, timedelta, time as dt_time
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from DrissionPage import ChromiumPage, ChromiumOptions

# --- 核心依赖检查 ---
try:
    import ddddocr
except ImportError:
    print("❌ 错误：未检测到 ddddocr。请先运行: pip3 install ddddocr")
    sys.exit(1)

# --- 环境加载 ---
env_path = os.path.join(os.path.dirname(__file__), 'tg.env')
if not os.path.exists(env_path):
    print(f"[{datetime.now()}] 未找到环境文件: {env_path}")
    sys.exit(1)
load_dotenv(env_path)

TOKEN = os.environ.get('TG_BOT_TOKEN')
CHAT_ID = os.environ.get('TG_CHAT_ID')
PROXY_URL = os.environ.get('TG_PROXY')
MIN_SALARY = int(os.environ.get('MIN_SALARY', 40))

# --- 全局状态 ---
state = {
    "auto_enabled": False,
    "task_running": False,
    "interrupt_flag": False,
    "block_today": False,
    "block_date": None,
    "next_run_time": None  # 防休眠精准时钟
}

TARGET_KEYWORDS = ["产品总监", "AI产品", "产品负责人", "资深产品", "高级产品", "AI经理", "AI方向"]
EXPECTATION_KEYWORDS = ["产品总监", "AI产品经理"]

tg_app = None 
ocr = ddddocr.DdddOcr(show_ad=False)

def log_info(msg):
    t = datetime.now().strftime('%H:%M:%S')
    print(f"[{t}] {msg}")

async def notify_tg(text: str):
    if not tg_app or not CHAT_ID: return
    try:
        await tg_app.bot.send_message(chat_id=CHAT_ID, text=text)
    except Exception as e:
        log_info(f"TG 通知失败: {e}")

def get_salary_by_ocr(salary_element):
    try:
        img_bytes = salary_element.get_screenshot()
        res = ocr.classification(img_bytes)
        res_clean = re.sub(r'[^\d-]', '', res)
        match = re.search(r'(\d+)', res_clean)
        return int(match.group(1)) if match else 0
    except:
        return 0

# ==========================================
# 核心区域：DrissionPage 物理级接管逻辑
# ==========================================
def sync_delivery_worker():
    delivered = []
    try:
        co = ChromiumOptions().set_local_port(9223)
        page = ChromiumPage(co)
        
        target_tab = None
        for tab_id in page.tab_ids:
            tab = page.get_tab(tab_id)
            if "zhipin.com/web/geek" in tab.url:
                target_tab = tab
                break
        
        if not target_tab:
            log_info("❌ 终端未发现 Boss 页面，请确保浏览器已打开求职列表。")
            return []
        
        page = target_tab

        log_info("⚖️ 正在强制重置浏览器缩放至 100%...")
        page.run_js('document.body.style.zoom = "1";')
        time.sleep(1) 
        
        log_info("🔄 刷新页面并执行模糊匹配筛选...")
        page.refresh()
        time.sleep(3) 
        
        tab_clicked = False
        for kw in EXPECTATION_KEYWORDS:
            exp_btn = page.ele(f'text:{kw}', timeout=3)
            if exp_btn:
                log_info(f"📍 命中预设标签: {exp_btn.text}")
                exp_btn.click()
                time.sleep(2.5) 
                tab_clicked = True
                break
        
        if not tab_clicked:
            log_info("ℹ️ 未发现匹配的预设标签，将在当前页面继续。")

        log_info(f"👁️ 鹰眼巡逻中 | 薪资门槛: {MIN_SALARY}K")
        processed_keys = set()
        
        while len(delivered) < 20:
            if state["interrupt_flag"]: break
            
            if page.ele('text:今日沟通人数已达上限', timeout=0.5):
                state["block_today"] = True
                state["block_date"] = datetime.now().date()
                log_info("🛑 触发沟通上限，停止今日任务。")
                break

            cards = page.eles('css=.job-card-wrapper') or page.eles('css=.job-card-box')
            if not cards: 
                time.sleep(3); continue
            
            found_action = False
            for card in cards:
                if state["interrupt_flag"] or len(delivered) >= 20: break
                
                try:
                    job_name_ele = card.ele('css=.job-name', timeout=0.5)
                    if not job_name_ele: continue
                    job_name = job_name_ele.text
                    
                    if not any(kw.lower() in job_name.lower() for kw in TARGET_KEYWORDS):
                        continue
                    
                    company_name = (card.ele('css=.company-name', timeout=0.5) or 
                                   card.ele('css=.boss-name', timeout=0.5)).text
                    
                    if (job_name + company_name) in processed_keys: continue
                    processed_keys.add(job_name + company_name)
                    
                    salary_ele = card.ele('css=.salary', timeout=0.5) or card.ele('css=.job-salary', timeout=0.5)
                    salary_val = get_salary_by_ocr(salary_ele)
                    
                    if 0 < salary_val < MIN_SALARY:
                        log_info(f"⏭️ 视觉拦截低薪: {company_name} ({salary_val}K)")
                        continue
                    
                    found_action = True
                    log_info(f"🎯 视觉验证通过({salary_val}K)，锁定: {company_name} | {job_name}")
                    card.scroll.to_see()
                    job_name_ele.click()
                    time.sleep(2.0)
                    
                    if page.ele('text:继续沟通', timeout=0.5): continue
                    
                    btn = page.ele('text:立即沟通', timeout=1.5)
                    if btn:
                        btn.click()
                        delivered.append(f"{company_name} | {job_name}")
                        log_info(f"✨ 成功出击: {company_name}")
                        
                        time.sleep(1.2)
                        stay = page.ele('text:留在此页', timeout=1.5)
                        if stay: stay.click()
                        
                        time.sleep(random.uniform(5, 10))
                except: continue
            
            if not found_action:
                page.scroll.down(800)
                time.sleep(2.5)
                
    except Exception as e:
        log_info(f"引擎异常: {e}")
    return delivered

# --- 调度与消息汇报 ---
async def execute_delivery_round():
    if state["task_running"]: return
    state["task_running"] = True
    state["interrupt_flag"] = False
    try:
        delivered = await asyncio.to_thread(sync_delivery_worker)
        if delivered:
            details = "\n".join(delivered)
            msg = f"✅ 战报：本次成功投递了 {len(delivered)} 份简历：\n{details}"
            await notify_tg(msg)
        else:
            await notify_tg("ℹ️ 本轮巡逻结束，未发现匹配的新岗位。")
    except Exception as e:
        log_info(f"任务外层异常: {e}")
    finally:
        state["task_running"] = False

async def handle_tg_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    if text == "指令":
        await update.message.reply_text("1 手动投递 (无视时间)\n2 停止\n3 关闭自动\n4 开启自动 (8-17点)\n5 状态查询")
        
    elif text == "1":
        if not state["task_running"]: 
            await update.message.reply_text("🚀 启动手动扫描（无视作息时间）...")
            asyncio.create_task(execute_delivery_round())
        else: 
            await update.message.reply_text("⛔ 机器人正在忙碌中...")
            
    elif text == "2":
        state["interrupt_flag"] = True
        await update.message.reply_text("🛑 正在停止...")
        
    elif text == "3":
        state["auto_enabled"] = False
        state["next_run_time"] = None
        await update.message.reply_text("🔴 自动投递已关闭")
        
    elif text == "4":
        state["auto_enabled"] = True
        now_obj = datetime.now()
        current_hour = now_obj.hour
        
        # 判断当前是否在 8:00 - 16:59 之间
        if 8 <= current_hour < 17:
            state["next_run_time"] = now_obj.timestamp() + 3600 + random.randint(-300, 300)
            await update.message.reply_text("🟢 自动投递开启！\n☀️ 当前为工作时间，将立刻执行一次扫描。")
            if not state["task_running"]: 
                asyncio.create_task(execute_delivery_round())
        else:
            # 不在工作时间，算出下一个早晨 8 点
            if current_hour >= 17:
                next_day = now_obj.date() + timedelta(days=1)
                next_8am = datetime.combine(next_day, dt_time(8, 0))
            else:
                next_8am = datetime.combine(now_obj.date(), dt_time(8, 0))
            
            # 加上 0~5 分钟的随机波动，模拟真人上班打卡
            state["next_run_time"] = next_8am.timestamp() + random.randint(0, 300)
            next_time_str = datetime.fromtimestamp(state["next_run_time"]).strftime('%m-%d %H:%M:%S')
            await update.message.reply_text(f"🟢 自动投递已激活！\n🌙 当前非工作时间(8-17点)，机器人已进入休眠。\n⏰ 将在 {next_time_str} 自动唤醒并开始首轮投递。")
            
    elif text == "5":
        status = "工作中 🏃" if state["task_running"] else "待命中 😴"
        auto_status = "开启 ✅" if state["auto_enabled"] else "关闭 ❌"
        limit_status = "触达上限 🛑" if state["block_today"] else "正常 🆗"
        
        next_time_str = "无"
        if state["auto_enabled"] and state["next_run_time"]:
            next_time_str = datetime.fromtimestamp(state["next_run_time"]).strftime('%Y-%m-%d %H:%M:%S')
            
        msg = (f"【工作状态汇报】\n"
               f"运行状态: {status}\n"
               f"自动挂机: {auto_status}\n"
               f"下次执行: {next_time_str}\n"
               f"今日上限: {limit_status}\n"
               f"薪资门槛: {MIN_SALARY}K")
        await update.message.reply_text(msg)

# --- 防休眠循环与时间窗口 ---
async def auto_delivery_loop():
    while True:
        await asyncio.sleep(5) 
        
        if state["auto_enabled"] and not state["task_running"]:
            now_obj = datetime.now()
            now_ts = now_obj.timestamp()
            current_hour = now_obj.hour
            
            if state["block_today"] and state["block_date"] != now_obj.date():
                state["block_today"] = False
                log_info("🌅 跨天重置投递限制。")
                
            if state["next_run_time"] and now_ts >= state["next_run_time"]:
                # 到点了，检查是否在合法时间窗口 (8:00 - 16:59)
                if 8 <= current_hour < 17:
                    if not state["block_today"]:
                        log_info("⏰ 定时自动投递触发...")
                        asyncio.create_task(execute_delivery_round())
                    # 正常往后延期一小时
                    state["next_run_time"] = now_ts + 3600 + random.randint(-300, 300)
                else:
                    # 到点了但天黑了（比如正好跨越 17:00），直接把下一次时间推迟到明早 8 点
                    if current_hour >= 17:
                        next_day = now_obj.date() + timedelta(days=1)
                        next_8am = datetime.combine(next_day, dt_time(8, 0))
                    else:
                        next_8am = datetime.combine(now_obj.date(), dt_time(8, 0))
                    
                    state["next_run_time"] = next_8am.timestamp() + random.randint(0, 300)
                    next_time_str = datetime.fromtimestamp(state["next_run_time"]).strftime('%Y-%m-%d %H:%M:%S')
                    log_info(f"🌙 非工作时间 (8-17点)。自动延期至明早，唤醒时间: {next_time_str}")

async def main():
    global tg_app
    log_info("🚀 Boss 终极朝九晚五版启动...")
    if PROXY_URL:
        os.environ["HTTP_PROXY"] = PROXY_URL
        os.environ["HTTPS_PROXY"] = PROXY_URL
    
    tg_app = ApplicationBuilder().token(TOKEN).build()
    tg_app.add_handler(MessageHandler(filters.TEXT, handle_tg_message))
    await tg_app.initialize()
    await tg_app.start()
    await tg_app.updater.start_polling()
    
    await auto_delivery_loop()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n停止。")