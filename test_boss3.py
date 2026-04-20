from DrissionPage import ChromiumPage, ChromiumOptions
import ddddocr
import re

ocr = ddddocr.DdddOcr(show_ad=False)
def get_salary_by_ocr(salary_element):
    if not salary_element:
        return 0, "No Element"
    try:
        img_bytes = salary_element.get_screenshot()
        res = ocr.classification(img_bytes)
        res_clean = res.replace('O', '0').replace('o', '0').replace('Q', '0')
        res_clean = re.sub(r'[^\d-]', '', res_clean)
        
        salary_val = 0
        if '-' in res_clean:
            start_str = res_clean.split('-')[0]
            if start_str.isdigit():
                salary_val = int(start_str)
        else:
            match = re.search(r'(\d+)', res_clean)
            salary_val = int(match.group(1)) if match else 0
        return salary_val, res
    except Exception as e:
        return 0, f"Error: {e}"

try:
    co = ChromiumOptions().set_local_port(9223)
    page = ChromiumPage(co)
    target_tab = page.get_tab(page.tab_ids[0])
    for tab_id in page.tab_ids:
        t = page.get_tab(tab_id)
        if "zhipin.com" in t.url:
            target_tab = t
            break
            
    page = target_tab
    cards = page.eles('css=.job-card-wrapper') or page.eles('css=.job-card-box') or page.eles('css=.job-card-wrap')
    
    for i, card in enumerate(cards):
        job_name_ele = card.ele('css=.job-name', timeout=0.5)
        if not job_name_ele: continue
        job_name = job_name_ele.text
        
        TARGET_KEYWORDS = ["产品总监", "AI产品", "产品负责人", "资深产品", "高级产品", "AI经理", "AI方向"]
        if not any(kw.lower() in job_name.lower() for kw in TARGET_KEYWORDS): continue
        
        salary_ele = card.ele('css=.salary', timeout=0.5) or card.ele('css=.job-salary', timeout=0.5)
        salary_val, ocr_res = get_salary_by_ocr(salary_ele)
        print(f"[{i}] {job_name} | Salary: {salary_val} (OCR: {ocr_res}) | Ele Text: {salary_ele.text if salary_ele else 'N/A'}")
except Exception as e:
    print(f"Error: {e}")
