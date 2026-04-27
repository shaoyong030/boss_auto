"""
调试脚本：连接 9223 端口的 Chrome，抓取 Boss 直聘页面的真实 DOM 结构
"""
from DrissionPage import ChromiumPage, ChromiumOptions
import re

co = ChromiumOptions().set_local_port(9223)
page = ChromiumPage(co)

print("=" * 60)
print("当前所有 tab：")
for tab_id in page.tab_ids:
    tab = page.get_tab(tab_id)
    print(f"  URL: {tab.url}")
    print(f"  Title: {tab.title}")
    print()

# 查找 Boss 页面
target_tab = None
for tab_id in page.tab_ids:
    tab = page.get_tab(tab_id)
    if "zhipin.com" in tab.url:
        target_tab = tab
        print(f"✅ 找到 Boss 页面: {tab.url}")
        break

if not target_tab:
    print("❌ 未找到任何 zhipin.com 的页面")
    exit()

page = target_tab

# 1. 检查页面上所有可能的职位卡片容器
print("\n" + "=" * 60)
print("🔍 搜索职位卡片结构...")

# 尝试各种可能的选择器
selectors_to_try = [
    '.job-card-wrapper', '.job-card-box', '.job-card-wrap',
    '.job-card-left', '.job-card-right', '.job-card-body',
    '.job-list-box', '.search-job-result',
    '.job-card', '.job-card-container',
    'li.job-card', '.job-card-item',
    '[class*="job-card"]', '[class*="job_card"]',
    '[class*="jobCard"]', '[class*="JobCard"]',
    '[class*="position"]', '[class*="recommend"]',
    '.rec-job-list', '.job-recommend',
]

for sel in selectors_to_try:
    try:
        eles = page.eles(f'css={sel}', timeout=0.3)
        if eles:
            print(f"  ✅ '{sel}' -> 找到 {len(eles)} 个元素")
            # 打印第一个元素的 tag 和 class
            first = eles[0]
            print(f"     tag={first.tag}, class={first.attr('class')}")
            # 打印内部文本的前200字符
            txt = first.text[:200] if first.text else "(无文本)"
            print(f"     文本预览: {txt}")
    except:
        pass

# 2. 更宽泛的搜索：查找页面 body 直接子元素
print("\n" + "=" * 60)
print("🔍 查看页面主要结构（body 的直接子元素和关键容器）...")

# 获取页面 body 下所有主要的 class
try:
    result = page.run_js('''
        const cards = document.querySelectorAll('[class]');
        const classSet = new Set();
        cards.forEach(el => {
            const cls = el.className;
            if (typeof cls === 'string') {
                cls.split(' ').forEach(c => {
                    if (c && (c.toLowerCase().includes('job') || c.toLowerCase().includes('card') || 
                        c.toLowerCase().includes('list') || c.toLowerCase().includes('salary') ||
                        c.toLowerCase().includes('name') || c.toLowerCase().includes('company') ||
                        c.toLowerCase().includes('position') || c.toLowerCase().includes('recommend'))) {
                        classSet.add(c);
                    }
                });
            }
        });
        return Array.from(classSet).sort().join('\\n');
    ''')
    print("页面中包含 job/card/list/salary/name/company/position/recommend 的 CSS class：")
    print(result)
except Exception as e:
    print(f"JS 执行出错: {e}")

# 3. 额外检查是否有 "期望职位" 筛选按钮
print("\n" + "=" * 60)
print("🔍 搜索期望职位筛选按钮...")
for kw in ["产品总监", "AI产品经理", "产品负责人", "期望职位"]:
    ele = page.ele(f'text:{kw}', timeout=0.3)
    if ele:
        print(f"  ✅ 找到 '{kw}': tag={ele.tag}, class={ele.attr('class')}")
    else:
        print(f"  ❌ 未找到 '{kw}'")

# 4. 打印页面可见文本的前 3000 个字符
print("\n" + "=" * 60)
print("📄 页面可见文本（前 3000 字符）：")
body = page.ele('css=body', timeout=1)
if body:
    print(body.text[:3000])
