from DrissionPage import ChromiumPage, ChromiumOptions

try:
    co = ChromiumOptions().set_local_port(9223)
    page = ChromiumPage(co)
    
    target_tab = None
    for tab_id in page.tab_ids:
        tab = page.get_tab(tab_id)
        if "zhipin.com" in tab.url:
            target_tab = tab
            break
            
    if target_tab:
        page = target_tab
        cards = page.eles('css=.job-card-wrapper') or page.eles('css=.job-card-box') or page.eles('css=.job-card-wrap')
        if cards:
            for i, card in enumerate(cards[:20]):
                job_name_ele = card.ele('css=.job-name', timeout=0.5)
                job_name = job_name_ele.text if job_name_ele else "N/A"
                
                # We need to simulate the click to see the button, but we shouldn't click all of them here 
                # Let's just check if there's any status element on the card itself
                info_pub = card.ele('css=.info-public', timeout=0.5)
                print(f"[{i}] {job_name} | {info_pub.text if info_pub else ''}")
except Exception as e:
    print(f"Error: {e}")
