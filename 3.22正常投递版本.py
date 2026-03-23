import os
import sys
import re
import time
import random
import asyncio
import traceback
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
    "auto_enabled": True,  # 默认开启自动任务
    "task_running": False,
    "interrupt_flag": False,
    "block_today": False,
    "block_date": None,
    "next_run_time": None  
}

TARGET_KEYWORDS = ["产品总监", "AI产品", "产品负责人", "资深产品", "高级产品", "AI经理", "AI方向"]
EXPECTATION_KEYWORDS = ["产品总监", "AI产品经理"]
LIMIT_KEYWORDS = ['无法进行沟通', '150位BOSS沟通', '休息一下，明天再来', '已达上限']

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
# 核心区域：DrissionPage 投递逻辑
# ==========================================
def sync_delivery_worker(loop):
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
        page.run_js('document.body.style.zoom = "1";')
        time.sleep(1) 
        
        page.refresh()
        time.sleep(3) 
        
        for kw in EXPECTATION_KEYWORDS:
            exp_btn = page.ele(f'text:{kw}', timeout=3)
            if exp_btn:
                exp_btn.click()
                time.sleep(2.5) 
                break

        processed_keys = set()
        while len(delivered) < 20:
            if state["interrupt_flag"]: break
            
            if any(page.ele(f'text:{kw}', timeout=0.5) for kw in LIMIT_KEYWORDS):
                state["block_today"] = True
                state["block_date"] = datetime.now().date()
                asyncio.run_coroutine_threadsafe(notify_tg("⚠️ 提示：检测到今日已达上限！"), loop)
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
                    if not any(kw.lower() in job_name.lower() for kw in TARGET_KEYWORDS): continue
                    
                    company_name = (card.ele('css=.company-name', timeout=0.5) or 
                                   card.ele('css=.boss-name', timeout=0.5)).text
                    if (job_name + company_name) in processed_keys: continue
                    processed_keys.add(job_name + company_name)
                    
                    salary_ele = card.ele('css=.salary', timeout=0.5) or card.ele('css=.job-salary', timeout=0.5)
                    salary_val = get_salary_by_ocr(salary_ele)
                    if 0 < salary_val < MIN_SALARY: continue
                    
                    found_action = True
                    card.scroll.to_see()
                    job_name_ele.click()
                    time.sleep(2.0)
                    
                    if page.ele('text:继续沟通', timeout=0.5): continue
                    
                    btn = page.ele('text:立即沟通', timeout=1.5)
                    if btn:
                        btn.click()
                        time.sleep(1.5)
                        if any(page.ele(f'text:{kw}', timeout=0.5) for kw in LIMIT_KEYWORDS):
                            state["block_today"] = True
                            state["block_date"] = datetime.now().date()
                            return delivered

                        delivered.append(f"{company_name} | {job_name}")
                        success_msg = f"✨ 成功出击：{company_name}\n💼 岗位：{job_name}\n💰 薪资：{salary_val}K"
                        asyncio.run_coroutine_threadsafe(notify_tg(success_msg), loop)
                        
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

async def execute_delivery_round():
    if state["task_running"] or state["block_today"]: return
    state["task_running"] = True
    state["interrupt_flag"] = False
    try:
        current_loop = asyncio.get_running_loop()
        delivered = await asyncio.to_thread(sync_delivery_worker, current_loop)
        if delivered:
            await notify_tg(f"✅ 战报：本次成功投递了 {len(delivered)} 份简历。")
    except Exception as e:
        log_info(f"任务异常: {e}")
    finally:
        state["task_running"] = False

async def handle_tg_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text.strip()
    
    try:
        if text == "指令":
            await update.message.reply_text("1 手动投递\n2 停止\n3 关闭自动\n4 开启自动 (8-17点)\n5 状态查询")
            
        elif text == "1":
            if state["block_today"]:
                await update.message.reply_text("🚫 今日已达上限")
            elif not state["task_running"]: 
                asyncio.create_task(execute_delivery_round())
                await update.message.reply_text("🚀 启动手动扫描...")
            
        elif text == "2":
            state["interrupt_flag"] = True
            await update.message.reply_text("🛑 正在停止...")
            
        elif text == "3":
            state["auto_enabled"] = False
            state["next_run_time"] = None
            await update.message.reply_text("🔴 自动投递已关闭")
            
        elif text == "4":
            state["auto_enabled"] = True
            now = datetime.now()
            if 8 <= now.hour < 17:
                state["next_run_time"] = now.timestamp() + 3600
                await update.message.reply_text("🟢 开启！工作时间内将立刻执行。")
                if not state["task_running"]: asyncio.create_task(execute_delivery_round())
            else:
                target = datetime.combine(now.date() + (timedelta(days=1) if now.hour >= 17 else timedelta(0)), dt_time(8, 0))
                state["next_run_time"] = target.timestamp()
                await update.message.reply_text(f"🟢 已激活！将在 {target.strftime('%H:%M')} 唤醒。")
                
        elif text == "5":
            status = "工作中 🏃" if state["task_running"] else "待命中 😴"
            auto_status = "开启 ✅" if state["auto_enabled"] else "关闭 ❌"
            limit = "触达上限 🛑" if state["block_today"] else "正常 🆗"
            nxt = datetime.fromtimestamp(state["next_run_time"]).strftime('%H:%M:%S') if state["next_run_time"] else "无"
            
            await update.message.reply_text(f"【状态汇报】\n运行: {status}\n自动: {auto_status}\n下次: {nxt}\n上限: {limit}")
            
    except Exception as e:
        log_info(f"处理指令出错: {e}")
        traceback.print_exc()

async def auto_delivery_loop():
    while True:
        await asyncio.sleep(10)
        now = datetime.now()
        if state["auto_enabled"] and not state["task_running"]:
            if state["block_today"] and state["block_date"] != now.date():
                state["block_today"] = False
            
            if state["next_run_time"] and now.timestamp() >= state["next_run_time"]:
                if 8 <= now.hour < 17:
                    if not state["block_today"]: asyncio.create_task(execute_delivery_round())
                    state["next_run_time"] = now.timestamp() + 3600 + random.randint(-300, 300)
                else:
                    target = datetime.combine(now.date() + (timedelta(days=1) if now.hour >= 17 else timedelta(0)), dt_time(8, 0))
                    state["next_run_time"] = target.timestamp() + random.randint(0, 300)

async def main():
    global tg_app
    now = datetime.now()
    if 8 <= now.hour < 17:
        state["next_run_time"] = now.timestamp()
    else:
        target = datetime.combine(now.date() + (timedelta(days=1) if now.hour >= 17 else timedelta(0)), dt_time(8, 0))
        state["next_run_time"] = target.timestamp()

    if PROXY_URL:
        os.environ["HTTP_PROXY"] = PROXY_URL
        os.environ["HTTPS_PROXY"] = PROXY_URL
    
    tg_app = ApplicationBuilder().token(TOKEN).build()
    tg_app.add_handler(MessageHandler(filters.TEXT, handle_tg_message))
    await tg_app.initialize()
    await tg_app.start()
    await tg_app.updater.start_polling()
    
    await notify_tg("🟢 程序已重启，自动投递默认开启。")
    await auto_delivery_loop()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass