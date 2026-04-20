TARGET_KEYWORDS = ["产品总监", "AI产品", "产品负责人", "资深产品", "高级产品", "AI经理", "AI方向"]

jobs = [
    "Senior Director, Product Management",
    "Sr AI & Seller Experience Manager",
    "产品合伙人（AI 漫剧海外互动娱乐方向）",
    "规划总监",
    "AI智能体用户端产品专家",
    "AI Product Manager, Risk Controls Mgt",
    "海外⼈⼒数字化技术负责⼈",
    "AI搜索产品专家",
    "部署负责人丨Thor/Orin丨算子量化剪枝",
    "物联网产品经理"
]

for job_name in jobs:
    job_name_lower = job_name.lower()
    is_target = any(kw.lower() in job_name_lower for kw in TARGET_KEYWORDS)
    
    if not is_target:
        if "ai" in job_name_lower and ("产品" in job_name_lower or "product" in job_name_lower):
            is_target = True
        elif any(kw in job_name_lower for kw in ["产品专家", "产品合伙人", "product manager", "product director"]):
            is_target = True

    print(f"{is_target} : {job_name}")
