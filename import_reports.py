"""reports/ 폴더의 .json 보고서를 Supabase DB로 한 번 옮기는 일회용 스크립트.

실행: GitHub Actions의 'DB 이관(일회용)' 워크플로에서 [Run workflow] 클릭.
(로컬 터미널 없이 웹에서 실행 가능)
"""
import glob
import json

from modules import db

count = 0
for path in sorted(glob.glob("reports/*.json")):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    slug = db.save_report(data)
    print(f"이관 완료: {path} → {slug}")
    count += 1

print(f"\n총 {count}건 이관됨.")
