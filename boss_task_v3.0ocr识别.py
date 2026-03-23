import os
import sys
import re
import time
import random
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from DrissionPage import ChromiumPage, ChromiumOptions

# --- 核心依赖检查 ---
try:
    import ddddocr
except ImportError:
    print("❌ 错误：未检测到 ddddocr。请先在终端运行: pip3 install ddddocr")
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

# --- 全局状态记录 ---
state = {
    "auto_enabled": False,
    "task_running": False,
    "interrupt_flag": False,
    "block_today": False,
    "block_date": None
}

# 锁定你在上海关注的职位关键词
TARGET_KEYWORDS = ["产品总监", "AI产品", "产品负责人", "资深产品", "高级产品", "AI经理"]
tg_app = None 

# 初始化一次 OCR 引擎，放在全局避免重复加载
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

# --- 视觉识别薪资函数 ---
def get_salary_by_ocr(salary_element):
    try:
        img_bytes = salary_element.get_screenshot()
        res = ocr.classification(img_bytes)
        res_clean = re.sub(r'[^\d-]', '', res)
        match = re.search(r'(\d+)', res_clean)
        return int(match.group(1)) if match else 0
    except:
        return 0

# --- 核心投递逻辑 (DrissionPage) ---
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
            log_info("❌ 终端未发现 Boss 页面")
            return []
        
        page = target_tab
        log_info(f"👁️ 视觉巡逻中... 门槛: {MIN_SALARY}K")
        processed_keys = set()
        
        while len(delivered) < 20:
            if state["interrupt_flag"]: break
            
            # 沟通上限检查
            if page.ele('text:今日沟通人数已达上限', timeout=0.5):
                state["block_today"] = True
                state["block_date"] = datetime.now().date()
                log_info("🛑 触发今日沟通上限")
                break

            cards = page.eles('css=.job-card-wrapper') or page.eles('css=.job-card-box')
            if not cards: time.sleep(2); continue
            
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
                    
                    # OCR 薪资核准
                    salary_ele = card.ele('css=.salary', timeout=0.5) or card.ele('css=.job-salary', timeout=0.5)
                    salary_val = get_salary_by_ocr(salary_ele)
                    
                    if 0 < salary_val < MIN_SALARY:
                        log_info(f"⏭️ 视觉过滤低薪: {company_name} ({salary_val}K)")
                        continue
                    
                    # 执行点击
                    found_action = True
                    log_info(f"🎯 视觉锁定: {company_name} | {job_name} ({salary_val}K)")
                    card.scroll.to_see()
                    job_name_ele.click()
                    time.sleep(2.0)
                    
                    # 左右分屏适配：详情页复核
                    if page.ele('text:继续沟通', timeout=0.5): continue
                    
                    btn = page.ele('text:立即沟通', timeout=1)
                    if btn:
                        btn.click()
                        delivered.append(f"{company_name} | {job_name}")
                        time.sleep(1.2)
                        stay = page.ele('text:留在此页', timeout=1)
                        if stay: stay.click()
                        time.sleep(random.uniform(5, 8))
                except: continue
            
            if not found_action:
                page.scroll.down(600)
                time.sleep(2)
                
    except Exception as e:
        log_info(f"引擎异常: {e}")
    return delivered

# --- Telegram 指令处理中心 ---
async def execute_delivery_round():
    if state["task_running"]: return
    state["task_running"] = True
    state["interrupt_flag"] = False
    log_info("🚀 开始投递扫描...")
    delivered = await asyncio.to_thread(sync_delivery_worker)
    state["task_running"] = False
    if delivered:
        await notify_tg(f"✅ 完成！投递了 {len(delivered)} 份简历：\n" + "\n".join(delivered))
    else:
        log_info("ℹ️ 扫描结束，未发现新匹配。")

async def handle_tg_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    if text == "指令":
        menu = "1 手动投递\n2 停止投递\n3 关闭自动模式\n4 开启自动模式\n5 状态查询"
        await update.message.reply_text(menu)
    
    elif text == "1":
        if state["task_running"]:
            await update.message.reply_text("⛔ 机器人正忙...")
        else:
            await update.message.reply_text("🚀 启动手动扫描...")
            asyncio.create_task(execute_delivery_round())
            
    elif text == "2":
        state["interrupt_flag"] = True
        await update.message.reply_text("🛑 正在停止当前任务...")
        
    elif text == "3":
        state["auto_enabled"] = False
        await update.message.reply_text("🔴 自动投递模式已关闭。")
        
    elif text == "4":
        state["auto_enabled"] = True
        await update.message.reply_text("🟢 自动模式已开启！\n现在立即执行一次，随后每小时巡逻一次。")
        if not state["task_running"]:
            asyncio.create_task(execute_delivery_round())
            
    elif text == "5":
        work_status = "工作中 🏃" if state["task_running"] else "待命中 😴"
        auto_status = "已开启 ✅" if state["auto_enabled"] else "已关闭 ❌"
        limit_status = "今日已达上限 🛑" if state["block_today"] else "正常 🆗"
        msg = f"【机器人状态汇报】\n工作状态: {work_status}\n自动模式: {auto_status}\n今日上限: {limit_status}\n薪资门槛: {MIN_SALARY}K"
        await update.message.reply_text(msg)

# --- 定时与主逻辑 ---
async def auto_delivery_loop():
    while True:
        await asyncio.sleep(3600 + random.randint(-300, 300))
        # 检查是否跨天重置上限
        if state["block_today"] and state["block_date"] != datetime.now().date():
            state["block_today"] = False
            log_info("🌅 新的一天，重置投递上限。")
            
        if state["auto_enabled"] and not state["task_running"] and not state["block_today"]:
            log_info("⏰ 定时自动投递触发...")
            asyncio.create_task(execute_delivery_round())

async def main():
    global tg_app
    log_info("🚀 Boss 终极版机器人启动...")
    if PROXY_URL:
        os.environ["HTTP_PROXY"] = PROXY_URL
        os.environ["HTTPS_PROXY"] = PROXY_URL
    
    tg_app = ApplicationBuilder().token(TOKEN).build()
    tg_app.add_handler(MessageHandler(filters.TEXT, handle_tg_message))
    await tg_app.initialize()
    await tg_app.start()
    await tg_app.updater.start_polling()
    
    log_info("✅ Telegram 指令监听已启动")
    await auto_delivery_loop()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序手动结束。")