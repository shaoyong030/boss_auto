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

# 全局去重：记录今天已投递的岗位，持久化到文件防止进程重启丢失
DELIVERED_FILE = os.path.join(os.path.dirname(__file__), 'delivered_today.json')

def load_delivered_history():
    """从文件加载今天的投递记录，跨天自动清空"""
    today_str = datetime.now().strftime('%Y-%m-%d')
    try:
        if os.path.exists(DELIVERED_FILE):
            with open(DELIVERED_FILE, 'r') as f:
                data = __import__('json').load(f)
            if data.get('date') == today_str:
                return set(data.get('keys', []))
    except Exception:
        pass
    return set()

def save_delivered_history(history_set):
    """保存投递记录到文件"""
    today_str = datetime.now().strftime('%Y-%m-%d')
    try:
        with open(DELIVERED_FILE, 'w') as f:
            __import__('json').dump({'date': today_str, 'keys': list(history_set)}, f)
    except Exception:
        pass

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

def parse_salary_from_ocr_text(res):
    """从 OCR 文本中解析起始薪资（单位 K）。
    Boss 直聘薪资格式: XX-YYK, 其中 XX/YY 是 2-3 位数字。
    OCR 可能丢失短横线，例如 '3565' 实际是 '35-65K'。
    OCR 结果可能带有后缀噪声，如 '4565k16新' → 取 K 前面的 '4565'。
    返回值: 正数=起薪(K), 0=无法解析
    """
    # 将容易误识别的字母替换为数字0
    res = res.replace('O', '0').replace('o', '0').replace('Q', '0')
    
    # ===== 防误判：OCR 结果中数字太少说明识别失败 =====
    # 例如 't7mh'、't7h' 这种乱码不应该被当作有效薪资
    digit_count = sum(1 for c in res if c.isdigit())
    if digit_count < 2:
        log_info(f"   OCR 数字不足(仅{digit_count}位)，视为识别失败")
        return 0
    
    # 先尝试提取 K/k 前面的薪资部分，过滤掉后面的噪声
    k_match = re.search(r'([\d\-]+)\s*[Kk]', res)
    if k_match:
        salary_part = k_match.group(1)
    else:
        salary_part = res
    
    salary_clean = re.sub(r'[^\d-]', '', salary_part)
    
    # 情况1: 包含短横线，如 "40-60" → 取前半部分 40
    if '-' in salary_clean:
        start_str = salary_clean.split('-')[0]
        if start_str.isdigit():
            val = int(start_str)
            if 1 <= val <= 999:
                return val
    
    # 情况2: 没有短横线，纯数字
    match = re.search(r'(\d+)', salary_clean)
    if match:
        num = int(match.group(1))
        # 4位数字 → 对半拆分（如 3565 → 35 和 65，取起薪 35）
        if 1000 <= num <= 9999:
            start = num // 100  # 前两位
            end = num % 100     # 后两位
            if start < end:     # 合理的薪资范围（起薪 < 封顶）
                log_info(f"   薪资拆分: {num} → {start}-{end}K")
                return start
        # 2-3位数字 → 直接作为薪资
        elif 1 <= num <= 999:
            return num
    
    return 0

def get_salary_by_ocr(salary_element, fallback_element=None):
    """尝试通过 OCR 识别薪资。
    Boss 直聘使用反爬虫自定义字体渲染薪资数字，DOM 文本只有 '-K'。
    需要对元素截图后 OCR 识别。如果截图失败（窗口未激活等），返回 -1 表示无法识别。
    返回值: 正数=识别到的起薪(K), 0=识别到但数值为0, -1=无法识别
    """
    targets = [salary_element, fallback_element]
    for target in targets:
        if not target:
            continue
        try:
            img_bytes = target.get_screenshot()
            res = ocr.classification(img_bytes)
            log_info(f"   OCR 原始结果: '{res}'")
            val = parse_salary_from_ocr_text(res)
            if val > 0:
                return val
        except Exception as e:
            log_info(f"   OCR 截图失败: {str(e)[:60]}")
            continue
    
    # 所有尝试都失败，返回 -1 表示无法识别
    return -1

# ==========================================
# 核心区域：DrissionPage 投递逻辑
# ==========================================
def sync_delivery_worker(loop):
    delivered = []
    
    # 从文件加载今天的投递记录（跨天自动清空）
    delivered_history = load_delivered_history()
    log_info(f"📋 已加载今日投递记录: {len(delivered_history)} 条")
    
    try:
        co = ChromiumOptions().set_local_port(9223)
        page = ChromiumPage(co)
        
        target_tab = None
        for tab_id in page.tab_ids:
            tab = page.get_tab(tab_id)
            if "zhipin.com/web/geek" in tab.url and "/chat" not in tab.url:
                target_tab = tab
                break
        
        if not target_tab:
            msg = "❌ 终端未发现 Boss 页面，请确保浏览器已打开求职列表。"
            log_info(msg)
            asyncio.run_coroutine_threadsafe(notify_tg(msg), loop)
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

        no_card_count = 0
        no_action_count = 0
        while len(delivered) < 20:
            if "/chat" in page.url:
                page.back()
                time.sleep(3)
                continue

            if state["interrupt_flag"]: 
                msg = "🛑 收到中断指令，正在停止当前扫描..."
                log_info(msg)
                asyncio.run_coroutine_threadsafe(notify_tg(msg), loop)
                break
            
            # 第一处检测：页面通用提示
            if any(page.ele(f'text:{kw}', timeout=0.5) for kw in LIMIT_KEYWORDS):
                state["block_today"] = True
                state["block_date"] = datetime.now().date()
                msg = "🛑 提示：检测到页面有「已达上限」相关字眼，今日投递被锁定。"
                log_info(msg)
                asyncio.run_coroutine_threadsafe(notify_tg(msg), loop)
                break

            cards = page.eles('css=.job-card-box') or page.eles('css=.job-card-wrapper') or page.eles('css=.job-card-wrap')
            if not cards: 
                no_card_count += 1
                log_info(f"⚠️ 未检测到职位卡片 (第{no_card_count}次)，当前URL: {page.url[:80]}")
                if no_card_count >= 5:
                    log_info("⚠️ 连续多次未检测到职位卡片，可能页面结构改变或进入非列表页，强行结束本轮。")
                    break
                time.sleep(3); continue
            
            no_card_count = 0
            
            found_action = False
            for card in cards:
                if state["interrupt_flag"] or len(delivered) >= 20: break
                try:
                    job_name_ele = card.ele('css=.job-name', timeout=0.5)
                    if not job_name_ele: continue
                    job_name = job_name_ele.text
                    
                    # 公司名
                    company_ele = card.ele('css=.boss-name', timeout=0.5) or card.ele('css=.company-name', timeout=0.5)
                    company_name = company_ele.text if company_ele else "未知公司"
                    dedup_key = job_name + company_name
                    
                    # 跨轮去重：今天已经投过的跳过
                    if dedup_key in delivered_history:
                        continue
                    
                    # 点进详情页
                    found_action = True
                    card.scroll.to_see()
                    job_name_ele.click()
                    time.sleep(2.0)
                    
                    if page.ele('text:继续沟通', timeout=0.5):
                        log_info(f"   ⏭️ [{job_name}] 已沟通过，跳过")
                        delivered_history.add(dedup_key)
                        save_delivered_history(delivered_history)
                        page.back()
                        time.sleep(1.5)
                        continue
                    
                    btn = page.ele('text:立即沟通', timeout=1.5)
                    if btn:
                        btn.click()
                        time.sleep(2.0)
                        
                        # 处理"还剩30次"温馨提示弹窗
                        warning_prompt = page.ele('text:还剩30次', timeout=0.5) or page.ele('text:120位BOSS沟通', timeout=0.5)
                        if warning_prompt:
                            ok_btn = page.ele('text:好', timeout=1.0)
                            if ok_btn:
                                ok_btn.click()
                                time.sleep(1.5)
                                log_info("⚠️ 触发 [还剩30次] 沟通提醒，已点击「好」")
                                # 弹窗拦截了原始点击，沟通并未真正发起
                                # 需要再次点击「立即沟通」
                                btn2 = page.ele('text:立即沟通', timeout=1.5)
                                if btn2:
                                    btn2.click()
                                    time.sleep(2.0)

                        # 检测上限弹窗
                        if any(page.ele(f'text:{kw}', timeout=0.5) for kw in LIMIT_KEYWORDS):
                            state["block_today"] = True
                            state["block_date"] = datetime.now().date()
                            msg = "🛑 沟通时触发上限提示，本轮强行结束，今日投递锁定。"
                            log_info(msg)
                            asyncio.run_coroutine_threadsafe(notify_tg(msg), loop)
                            return delivered

                        # 验证投递是否真正成功
                        delivery_confirmed = False
                        confirm_reason = ""
                        
                        # 标志1：出现「留在此页」弹窗（最可靠）
                        stay = page.ele('text:留在此页', timeout=2.5)
                        if stay:
                            delivery_confirmed = True
                            confirm_reason = "留在此页"
                            stay.click()
                            time.sleep(1.0)
                        
                        # 标志2：页面跳转到了聊天页
                        if not delivery_confirmed and "/chat" in page.url:
                            delivery_confirmed = True
                            confirm_reason = "跳转聊天页"
                            # 返回列表页，避免卡在聊天页
                            page.back()
                            time.sleep(1.5)
                            if "/chat" in page.url:
                                page.back()
                                time.sleep(1.5)
                        
                        if delivery_confirmed:
                            delivered.append(f"{company_name} | {job_name}")
                            delivered_history.add(dedup_key)
                            save_delivered_history(delivered_history)
                            success_msg = f"✨ 成功出击：{company_name}\n💼 岗位：{job_name}"
                            log_info(f"✅ 成功投递 -> {company_name} | {job_name} [确认:{confirm_reason}]")
                            asyncio.run_coroutine_threadsafe(notify_tg(success_msg), loop)
                        else:
                            log_info(f"⚠️ 点击了立即沟通但未确认成功 -> {company_name} | {job_name}")
                        
                        time.sleep(random.uniform(5, 10))
                except Exception as inner_e: 
                    continue
            
            if not found_action:
                no_action_count += 1
                page.scroll.down(800)
                time.sleep(2.0)
                
                if no_action_count >= 2:
                    try:
                        # 尝试多种翻页选择器
                        next_btn = (page.ele('css=.ui-icon-arrow-right', timeout=0.5)
                                    or page.ele('text:下一页', timeout=0.5)
                                    or page.ele('css=.pagination .next', timeout=0.5)
                                    or page.ele('css=[ka="next"]', timeout=0.5)
                                    or page.ele('css=.options-pages a:last-child', timeout=0.5))
                        if next_btn:
                            next_btn.click()
                            log_info("📄 翻到下一页")
                            time.sleep(3)
                            no_action_count = 0
                        else:
                            log_info(f"⚠️ 未找到翻页按钮 (第{no_action_count}次)")
                    except Exception as page_err:
                        log_info(f"⚠️ 翻页异常: {str(page_err)[:60]}")
                
                if no_action_count >= 10:
                    log_info("⚠️ 连续10次未发现新岗位，结束本轮扫描。")
                    break
            else:
                no_action_count = 0
                
    except Exception as e:
        msg = f"❌ 引擎执行异常: {e}"
        log_info(msg)
        asyncio.run_coroutine_threadsafe(notify_tg(msg), loop)
        
    return delivered

async def execute_delivery_round():
    if state["task_running"] or state["block_today"]: return
    state["task_running"] = True
    state["interrupt_flag"] = False
    log_info("🚀 开始执行新一轮 Boss 简历投递扫描...")
    try:
        current_loop = asyncio.get_running_loop()
        delivered = await asyncio.to_thread(sync_delivery_worker, current_loop)
        
        # 汇报本轮结果给 TG
        if delivered:
            report_msg = f"✅ 战报：本次成功投递了 {len(delivered)} 份简历。"
            log_info(report_msg)
            await notify_tg(report_msg)
        else:
            # 如果没有投递且不是因为被 block 的，才发未找到的提示（避免被 block 时连发两条）
            if not state["block_today"]:
                empty_msg = "ℹ️ 本轮扫描结束，未找到符合条件或未成功投递的新岗位。"
                log_info(empty_msg)
                await notify_tg(empty_msg)
                
    except Exception as e:
        msg = f"❌ 任务调度异常: {e}"
        log_info(msg)
        await notify_tg(msg)
    finally:
        state["task_running"] = False

async def handle_tg_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text.strip()
    
    try:
        if text == "0" or text == "指令":
            help_text = (
                "📋 【指令大全】\n"
                "━━━━━━━━━━━━━━━\n"
                "0️⃣  发送 0 → 查看本帮助\n"
                "━━━━━━━━━━━━━━━\n"
                "1️⃣  发送 1 → 手动投递\n"
                "   立即启动一轮简历扫描投递\n"
                "   每轮最多投递 20 个岗位\n"
                "━━━━━━━━━━━━━━━\n"
                "2️⃣  发送 2 → 停止当前任务\n"
                "   中断正在进行的投递扫描\n"
                "━━━━━━━━━━━━━━━\n"
                "3️⃣  发送 3 → 关闭自动投递\n"
                "   停止定时自动扫描\n"
                "━━━━━━━━━━━━━━━\n"
                "4️⃣  发送 4 → 开启自动投递\n"
                "   工作时间 8:00-21:00 自动执行\n"
                "   每轮间隔约 1 小时（±5分钟随机）\n"
                "━━━━━━━━━━━━━━━\n"
                "5️⃣  发送 5 → 状态查询\n"
                "   查看运行状态/自动开关/\n"
                "   下次执行时间/今日上限\n"
                "━━━━━━━━━━━━━━━\n"
                f"🎯 目标岗位: {', '.join(TARGET_KEYWORDS[:4])}..."
            )
            await update.message.reply_text(help_text)
            
        elif text == "1":
            if state["block_today"]:
                await update.message.reply_text("🚫 今日已达上限")
                log_info("📱 TG指令: 请求手动投递失败，今日已达上限。")
            elif not state["task_running"]: 
                asyncio.create_task(execute_delivery_round())
                await update.message.reply_text("🚀 启动手动扫描...")
                log_info("📱 TG指令: 启动手动投递。")
            else:
                await update.message.reply_text("⏳ 任务正在运行中，请勿重复启动。")
            
        elif text == "2":
            state["interrupt_flag"] = True
            await update.message.reply_text("🛑 正在停止...")
            log_info("📱 TG指令: 收到停止指令。")
            
        elif text == "3":
            state["auto_enabled"] = False
            state["next_run_time"] = None
            await update.message.reply_text("🔴 自动投递已关闭")
            log_info("📱 TG指令: 自动投递已关闭。")
            
        elif text == "4":
            state["auto_enabled"] = True
            now = datetime.now()
            if 8 <= now.hour < 21:
                state["next_run_time"] = now.timestamp() + 3600
                await update.message.reply_text("🟢 开启！工作时间内将立刻执行。")
                log_info("📱 TG指令: 开启自动投递，即将执行。")
                if not state["task_running"]: asyncio.create_task(execute_delivery_round())
            else:
                target = datetime.combine(now.date() + (timedelta(days=1) if now.hour >= 21 else timedelta(0)), dt_time(8, 0))
                state["next_run_time"] = target.timestamp()
                await update.message.reply_text(f"🟢 已激活！将在 {target.strftime('%H:%M')} 唤醒。")
                log_info(f"📱 TG指令: 开启自动投递，将在 {target.strftime('%H:%M')} 唤醒。")
                
        elif text == "5":
            status = "工作中 🏃" if state["task_running"] else "待命中 😴"
            auto_status = "开启 ✅" if state["auto_enabled"] else "关闭 ❌"
            limit = "触达上限 🛑" if state["block_today"] else "正常 🆗"
            nxt = datetime.fromtimestamp(state["next_run_time"]).strftime('%H:%M:%S') if state["next_run_time"] else "无"
            
            await update.message.reply_text(f"【状态汇报】\n运行: {status}\n自动: {auto_status}\n下次: {nxt}\n上限: {limit}")
            log_info("📱 TG指令: 处理了状态查询请求。")
            
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
                msg = "🔄 新的一天，已重置今日触达上限状态。"
                log_info(msg)
                await notify_tg(msg)
            
            if state["next_run_time"] and now.timestamp() >= state["next_run_time"]:
                if 8 <= now.hour < 21:
                    if not state["block_today"]: 
                        asyncio.create_task(execute_delivery_round())
                    state["next_run_time"] = now.timestamp() + 3600 + random.randint(-300, 300)
                else:
                    target = datetime.combine(now.date() + (timedelta(days=1) if now.hour >= 21 else timedelta(0)), dt_time(8, 0))
                    state["next_run_time"] = target.timestamp() + random.randint(0, 300)
                    log_info(f"🌙 非工作时间，下次扫描定于 {datetime.fromtimestamp(state['next_run_time']).strftime('%Y-%m-%d %H:%M:%S')}。")

async def main():
    global tg_app
    now = datetime.now()
    if 8 <= now.hour < 21:
        state["next_run_time"] = now.timestamp()
    else:
        target = datetime.combine(now.date() + (timedelta(days=1) if now.hour >= 21 else timedelta(0)), dt_time(8, 0))
        state["next_run_time"] = target.timestamp()

    if PROXY_URL:
        os.environ["HTTP_PROXY"] = PROXY_URL
        os.environ["HTTPS_PROXY"] = PROXY_URL
        # 🚀 核心修复：大小写双保险，防止底层网络库拦截本地通讯
        os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1"
        os.environ["no_proxy"] = "localhost,127.0.0.1,::1"
    
    builder = ApplicationBuilder().token(TOKEN)
    if PROXY_URL:
        builder = builder.proxy(PROXY_URL).get_updates_proxy(PROXY_URL)
    tg_app = builder.build()
    tg_app.add_handler(MessageHandler(filters.TEXT, handle_tg_message))
    
    # 带重试的 TG 初始化，防止 cron 重启时代理瞬断导致进程反复崩溃
    max_retries = 5
    for attempt in range(1, max_retries + 1):
        try:
            await tg_app.initialize()
            await tg_app.start()
            await tg_app.updater.start_polling()
            break  # 成功，跳出重试循环
        except Exception as e:
            wait_sec = 5 * (2 ** (attempt - 1))  # 5s, 10s, 20s, 40s, 80s
            log_info(f"⚠️ TG 初始化失败 (第{attempt}/{max_retries}次): {e}")
            if attempt == max_retries:
                log_info(f"❌ TG 初始化连续失败 {max_retries} 次，放弃连接。程序将以无 TG 模式运行。")
                tg_app = None  # 标记为无 TG，后续 notify_tg 会静默跳过
                break
            log_info(f"   ⏳ 等待 {wait_sec}s 后重试...")
            await asyncio.sleep(wait_sec)
    
    # 初始化完成的提示
    await notify_tg("🟢 程序已启动，自动投递默认开启。异常状态将会在此同步。")
    log_info("✅ 机器人服务已启动，正在监听 TG 指令。")
    log_info("✅ 开始进入自动投递循环监听模式...")
    
    await auto_delivery_loop()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log_info("⏹️ 收到退出信号，程序已关闭。")