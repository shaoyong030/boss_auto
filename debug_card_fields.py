"""
调试：检查 job-card-box 里各字段的实际 class 和内容，
找出"公司名"到底在哪个元素里
"""
from DrissionPage import ChromiumPage, ChromiumOptions

co = ChromiumOptions().set_local_port(9223)
page = ChromiumPage(co)

target_tab = None
for tab_id in page.tab_ids:
    tab = page.get_tab(tab_id)
    if "zhipin.com" in tab.url and "/chat" not in tab.url:
        target_tab = tab
        break

if not target_tab:
    print("❌ 未找到 Boss 页面")
    exit()

page = target_tab

# 用 JS 提取前5张卡片里所有带 class 的子元素的 class 和 text
result = page.run_js('''
    const cards = document.querySelectorAll('.job-card-box, .job-card-wrapper, .job-card-wrap');
    const info = [];
    for (const card of Array.from(cards).slice(0, 5)) {
        info.push("════════════════════════════════");
        // 递归提取所有有 class 的元素
        const allEls = card.querySelectorAll('[class]');
        for (const el of allEls) {
            const cls = el.className;
            const text = el.textContent.trim().substring(0, 80);
            const tag = el.tagName.toLowerCase();
            if (text) {
                info.push(`  <${tag}> .${cls} → "${text}"`);
            }
        }
    }
    return info.join("\\n");
''')
print(result)
