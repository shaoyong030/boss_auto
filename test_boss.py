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
    
    target_tab = None
    for tab_id in page.tab_ids:
        tab = page.get_tab(tab_id)
        if "zhipin.com" in tab.url:
            target_tab = tab
            break
            
    if not target_tab:
        print("未找到zhipin.com的tab")
    else:
        page = target_tab
        cards = page.eles('css=.job-card-wrapper') or page.eles('css=.job-card-box') or page.eles('css=.job-card-wrap')
        if cards:
            for i, card in enumerate(cards[:10]):
                job_name_ele = card.ele('css=.job-name', timeout=0.5)
                job_name = job_name_ele.text if job_name_ele else "N/A"
                salary_ele = card.ele('css=.salary', timeout=0.5) or card.ele('css=.job-salary', timeout=0.5)
                salary_val, ocr_res = get_salary_by_ocr(salary_ele)
                print(f"[{i}] {job_name} | Salary: {salary_val} (OCR saw: {ocr_res}) | Salary Ele Text: {salary_ele.text if salary_ele else 'None'}")
except Exception as e:
    print(f"Error: {e}")
