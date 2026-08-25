import re

with open("shopee_page_dump.html", "r", encoding="utf-8") as f:
    html = f.read()

scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)

pattern = re.compile(r'"[a-zA-Z_]*[Pp]rice[a-zA-Z_]*"\s*:\s*(\d+)')

for i, s in enumerate(scripts):
    matches = list(pattern.finditer(s))
    if matches:
        print(
            f"=== Script #{i}: tìm thấy {len(matches)} field liên quan giá ===")
        for m in matches[:10]:  # in tối đa 10 kết quả đầu mỗi script, tránh tràn màn hình
            start = max(0, m.start() - 80)
            print(s[start:m.end() + 20])
            print("---")
