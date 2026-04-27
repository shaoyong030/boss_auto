"""
进一步调试：检查 job-salary 内部的图片/canvas结构，看薪资数字如何渲染
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

# 检查 job-salary 元素的完整内部结构
result = page.run_js('''
    const salaries = document.querySelectorAll('.job-salary');
    const info = [];
    for (const sal of Array.from(salaries).slice(0, 5)) {
        info.push("=== job-salary ===");
        info.push("text: " + sal.textContent);
        info.push("innerHTML: " + sal.innerHTML.substring(0, 500));
        info.push("outerHTML: " + sal.outerHTML.substring(0, 500));
        // 检查子元素
        for (const child of sal.children) {
            info.push(`  child: ${child.tagName}.${child.className} text="${child.textContent}" style="${child.getAttribute('style') || ''}"` );
            if (child.tagName === 'IMG') {
                info.push(`    img src: ${child.src}`);
            }
            if (child.tagName === 'CANVAS') {
                info.push(`    canvas: ${child.width}x${child.height}`);
            }
        }
        // 检查 ::before / ::after 的 computed style
        const before = window.getComputedStyle(sal, '::before');
        if (before.content && before.content !== 'none') {
            info.push(`  ::before content: ${before.content}`);
        }
        info.push("---");
    }
    return info.join("\\n");
''')
print("=== job-salary 内部结构分析 ===")
print(result)

# 同时看一下 .job-title 里的完整 innerHTML
print("\n=== job-title 内部结构 ===")
result2 = page.run_js('''
    const titles = document.querySelectorAll('.job-title');
    const info = [];
    for (const t of Array.from(titles).slice(0, 5)) {
        info.push("innerHTML: " + t.innerHTML.substring(0, 600));
        info.push("---");
    }
    return info.join("\\n");
''')
print(result2)

# OCR 测试：对 job-salary 元素截图并 OCR
print("\n=== OCR 测试 ===")
import ddddocr
ocr = ddddocr.DdddOcr(show_ad=False)

cards = page.eles('css=.job-card-box')
for i, card in enumerate(cards[:5]):
    job_name_ele = card.ele('css=.job-name', timeout=0.3)
    job_name = job_name_ele.text if job_name_ele else "?"
    
    # 对 .job-salary 截图 OCR
    salary_ele = card.ele('css=.job-salary', timeout=0.3)
    if salary_ele:
        try:
            img_bytes = salary_ele.get_screenshot()
            res = ocr.classification(img_bytes)
            print(f"  卡片{i+1} [{job_name}]: .job-salary OCR = '{res}', text = '{salary_ele.text}'")
        except Exception as e:
            print(f"  卡片{i+1} [{job_name}]: OCR 失败 - {e}")
    
    # 对整个 .job-title 截图 OCR
    title_ele = card.ele('css=.job-title', timeout=0.3)
    if title_ele:
        try:
            img_bytes = title_ele.get_screenshot()
            res = ocr.classification(img_bytes)
            print(f"  卡片{i+1} [{job_name}]: .job-title OCR = '{res}'")
        except Exception as e:
            print(f"  卡片{i+1} [{job_name}]: title OCR 失败 - {e}")
