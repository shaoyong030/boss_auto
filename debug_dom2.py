"""
调试脚本2：深入检查职位卡片的内部结构
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

page = target_tab

# 获取所有 job-card-box
cards = page.eles('css=.job-card-box')
print(f"找到 {len(cards)} 个 job-card-box 卡片\n")

for i, card in enumerate(cards[:3]):
    print(f"===== 卡片 {i+1} =====")
    print(f"完整文本: {card.text[:300]}")
    
    # 检查各种子元素选择器
    inner_selectors = [
        '.job-name', '.job-title', '.job-info', 
        '.salary', '.job-salary', '.pay',
        '.company-name', '.boss-name', '.company-info',
        '.job-card-left', '.job-card-right', '.job-card-body',
        '.info-public', '.info-desc', '.job-card-header',
        'span.job-name', 'a.job-name',
    ]
    
    for sel in inner_selectors:
        try:
            ele = card.ele(f'css={sel}', timeout=0.2)
            if ele:
                print(f"  ✅ '{sel}' -> text='{ele.text[:100]}', tag={ele.tag}, class={ele.attr('class')}")
        except:
            pass
    
    # 用 JS 看卡片的直接子元素的 class
    try:
        result = page.run_js('''
            const card = arguments[0];
            const info = [];
            function traverse(el, depth) {
                if (depth > 4) return;
                const indent = "  ".repeat(depth);
                const cls = el.className || '';
                const tag = el.tagName || '';
                const txt = el.textContent ? el.textContent.trim().substring(0, 50) : '';
                if (cls || txt) {
                    info.push(`${indent}${tag}.${cls} => "${txt}"`);
                }
                for (const child of el.children) {
                    traverse(child, depth + 1);
                }
            }
            traverse(card, 0);
            return info.join("\\n");
        ''', card)
        print(f"\n  DOM 树结构:")
        print(result)
    except Exception as e:
        print(f"  JS执行失败: {e}")
    
    print()

# 还看一下薪资元素
print("\n===== 薪资元素检查 =====")
salary_eles = page.eles('css=.salary', timeout=0.5)
if salary_eles:
    print(f"找到 {len(salary_eles)} 个 .salary 元素")
    for s in salary_eles[:3]:
        print(f"  text='{s.text}', tag={s.tag}, class={s.attr('class')}")
else:
    print("❌ 没有 .salary 元素")

# 检查薪资是否用图片展示
print("\n===== 薪资图片检查 =====")
result = page.run_js('''
    const cards = document.querySelectorAll('.job-card-box');
    const info = [];
    for (const card of Array.from(cards).slice(0, 3)) {
        // 查找所有包含 K 的 span
        const spans = card.querySelectorAll('span');
        for (const span of spans) {
            const text = span.textContent.trim();
            if (text.includes('K') || text.includes('k') || text.includes('薪')) {
                info.push(`span.${span.className}: "${text}"`);
            }
        }
        // 查找 img 标签
        const imgs = card.querySelectorAll('img');
        for (const img of imgs) {
            info.push(`img.${img.className}: src=${img.src.substring(0, 80)}`);
        }
        // 查找 svg 标签 
        const svgs = card.querySelectorAll('svg');
        for (const svg of svgs) {
            info.push(`svg.${svg.className.baseVal || ''}`);
        }
        info.push('---');
    }
    return info.join("\\n");
''')
print(result)
