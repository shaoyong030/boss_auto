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

# --- 加载配置 ---
env_path = os.path.join(os.path.dirname(__file__), 'tg.env')
if not os.path.exists(env_path):
    print(f"[{datetime.now()}] 未找到环境文件: {env_path}")
    sys.exit(1)
load_dotenv(env_path)

TOKEN = os.environ.get('TG_BOT_TOKEN')
CHAT_ID = os.environ.get('TG_CHAT_ID')
PROXY_URL = os.environ.get('TG_PROXY')
MIN_SALARY = int(os.environ.get('MIN_SALARY', 40))

state = {
    "auto_enabled": False,
    "task_running": False,
    "interrupt_flag": False,
    "block_today": False,
    "block_date": None,
    "need_manual": False
}

# 增加更精准的关键词
TARGET_KEYWORDS = ["产品总监", "AI产品", "产品负责人", "资深产品", "高级产品", "AI方向"]
tg_app = None 

def log_info(msg):
    t = datetime.now().strftime('%H:%M:%S')
    print(f"[{t}] {msg}")

async def notify_tg(text: str):
    if not tg_app or not CHAT_ID: return
    try:
        await tg_app.bot.send_message(chat_id=CHAT_ID, text=text)
    except Exception as e:
        log_info(f"TG 通知发送失败: {e}")

# 解码 Boss 加密字体的核心逻辑
def parse_salary_strict(text):
    if not text: return 0
    # 尝试标准提取
    match = re.search(r'(\d+)-', text)
    if match: return int(match.group(1))
    
    # 针对加密字体的暴力特征提取
    nums = ""
    for c in text:
        if c.isdigit(): nums += c
        elif 0xE000 <= ord(c) <= 0xF8FF:
            # 提取加密字符的 16 进制最后一位
            digit = hex(ord(c))[-1]
            if digit.isdigit(): nums += digit
        elif c in ['-', 'K', 'k', '·']: break
    try: return int(nums) if nums else 0
    except: return 0

# ==========================================
# 核心区域：DrissionPage 物理级接管逻辑
# ==========================================
def sync_delivery_worker():
    delivered = []
    try:
        co = ChromiumOptions().set_local_port(9223)
        page = ChromiumPage(co)
        
        # 强力寻找 Boss 页面
        target_tab = None
        for tab_id in page.tab_ids:
            tab = page.get_tab(tab_id)
            if "zhipin.com/web/geek" in tab.url:
                target_tab = tab
                break
        
        if not target_tab:
            log_info("❌ 未发现 Boss 页面，请确保浏览器已停留在职位列表。")
            return delivered
        
        page = target_tab
        log_info(f"🚀 启动鹰眼扫描模式 | 薪资门槛: {MIN_SALARY}K")
        
        processed_keys = set()
        
        while len(delivered) < 20:
            if state["interrupt_flag"]: break
            
            # 封禁与风控检测
            if page.ele('text:今日沟通人数已达上限', timeout=0.5):
                state["block_today"] = True
                log_info("🛑 今日沟通已达上限，休息一下吧。")
                break

            # 抓取左侧卡片
            cards = page.eles('css=.job-card-wrapper') or page.eles('css=.job-card-box')
            if not cards:
                time.sleep(2); continue
            
            found_action = False
            for card in cards:
                if state["interrupt_flag"] or len(delivered) >= 20: break
                
                try:
                    job_name_ele = card.ele('css=.job-name', timeout=0.5)
                    if not job_name_ele: continue
                    job_name = job_name_ele.text
                    
                    # 关键词初筛
                    if not any(kw.lower() in job_name.lower() for kw in TARGET_KEYWORDS):
                        continue
                    
                    company_name = (card.ele('css=.company-name', timeout=0.5) or 
                                   card.ele('css=.boss-name', timeout=0.5)).text
                    
                    if (job_name + company_name) in processed_keys: continue
                    processed_keys.add(job_name + company_name)
                    
                    # --- 第一步：点击进入详情页 ---
                    found_action = True
                    log_info(f"👀 正在查看详情: {company_name} | {job_name}")
                    card.scroll.to_see()
                    job_name_ele.click()
                    time.sleep(2.0) # 关键休眠：等右侧详情刷出来
                    
                    # --- 第二步：右侧详情页“鹰眼”二次校验 ---
                    # 这里重点锁定右侧面板的薪资（.s-info-salary 是详情页特有的）
                    detail_salary = page.ele('css=.s-info-salary', timeout=1) or page.ele('css=.salary', timeout=1)
                    if detail_salary:
                        real_val = parse_salary_strict(detail_salary.text)
                        if 0 < real_val < MIN_SALARY:
                            log_info(f"⏭️  右侧确认薪资为 {real_val}K，不符门槛，撤退。")
                            continue
                        log_info(f"✅ 薪资确认通过: {real_val}K")

                    # --- 第三步：确认没投过，执行沟通 ---
                    if page.ele('text:继续沟通', timeout=0.5):
                        log_info("⏭️ 发现‘继续沟通’，说明以前聊过，跳过。")
                        continue
                    
                    btn = page.ele('text:立即沟通', timeout=1)
                    if btn:
                        btn.click()
                        delivered.append(f"{company_name} | {job_name}")
                        log_info(f"✨ 成功投递 [{len(delivered)}]: {company_name}")
                        
                        # 点掉可能出现的弹窗
                        time.sleep(1)
                        stay = page.ele('text:留在此页', timeout=1)
                        if stay: stay.click()
                        
                        time.sleep(random.uniform(5, 10))
                except:
                    continue
            
            if not found_action:
                page.scroll.down(600)
                time.sleep(2)

    except Exception as e:
        log_info(f"异常状况: {e}")
    return delivered

# --- Telegram 交互逻辑保持原有即可 ---
async def execute_delivery_round():
    if state["task_running"]: return
    state["task_running"] = True
    delivered = await asyncio.to_thread(sync_delivery_worker)
    state["task_running"] = False
    if delivered:
        await notify_tg(f"✅ 投递战报：成功出击 {len(delivered)} 份简历。")

async def handle_tg_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == "1":
        if not state["task_running"]: asyncio.create_task(execute_delivery_round())
    elif text == "2":
        state["interrupt_flag"] = True
        await update.message.reply_text("🛑 正在停止...")
    elif text == "5":
        status = "工作中" if state["task_running"] else "待命中"
        await update.message.reply_text(f"机器人状态: {status}\n薪资门槛: {MIN_SALARY}K")

async def main():
    global tg_app
    print("🚀 鹰眼版机器人已就位...")
    if PROXY_URL:
        os.environ["HTTP_PROXY"] = PROXY_URL
        os.environ["HTTPS_PROXY"] = PROXY_URL
    tg_app = ApplicationBuilder().token(TOKEN).build()
    tg_app.add_handler(MessageHandler(filters.TEXT, handle_tg_message))
    await tg_app.initialize()
    await tg_app.start()
    await tg_app.updater.start_polling()
    await asyncio.Event().wait()

if __name__ == '__main__':
    asyncio.run(main())