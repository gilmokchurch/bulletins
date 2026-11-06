"""블로그의 주보 PDF를 pdf/<글번호>.pdf 로 복사합니다. 이미 있는 파일은 건너뛰고, 3개월이 지난 사본은 지웁니다.

홈페이지(theway.news)의 주보 목록에서 글 번호를 받고, PDF는 블로그 글 페이지의 링크에서 바로 내려받습니다.
"""
import html
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

KEEP_DAYS = 92   # 약 3개월 동안의 주보만 사본으로 둠
SITE = 'https://theway.news'
BLOG = 'https://thewaynews.tistory.com'
UA = 'Mozilla/5.0 (compatible; GilmokChurchSite/1.0; +https://theway.news)'
OUT = sys.argv[1] if len(sys.argv) > 1 else 'pdf'


def get(url, referer=None, timeout=60):
    headers = {'user-agent': UA}
    if referer:
        headers['referer'] = referer
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
        return r.read()


def find_pdfs(page):
    """홈페이지의 findPdfs와 같은 규칙: PDF로 보이는 링크, 파일 이름이 보이는 링크를 앞으로."""
    out = []
    for m in re.finditer(r'<a\b[^>]*href="([^"]+)"[^>]*>([\s\S]*?)</a>', page, re.I):
        href = html.unescape(m.group(1))
        text = html.unescape(re.sub(r'<[^>]+>', '', m.group(2))).strip()
        if re.search(r'\.pdf(\?|$)', href, re.I) or re.search(r'\.pdf\b', text, re.I) or re.search(r'knm=[^&]*\.pdf', href, re.I):
            if href not in [u for _, u in out]:
                out.append((text, href))
    out.sort(key=lambda x: 0 if re.search(r'\.pdf', x[0], re.I) else 1)
    return out


def recent(p):
    """블로그에 올린 날이 KEEP_DAYS일 안이면 True."""
    try:
        at = datetime.fromisoformat(str(p.get('date', '')).replace('Z', '+00:00'))
    except ValueError:
        return False
    return at >= datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)


def main():
    os.makedirs(OUT, exist_ok=True)
    items = json.loads(get(f'{SITE}/api/posts?type=bulletin&limit=30'))['items']
    keep = {re.sub(r'\D', '', str(p.get('id', ''))) for p in items if p.get('hasPdf') and recent(p)}
    keep.discard('')
    # 3개월이 지난 사본은 지움 (홈페이지에서는 이 서버 대신 블로그 파일을 거쳐 열림)
    # 목록을 제대로 못 받았을 때 모두 지우는 일이 없도록, 남길 주보가 있을 때만
    if keep:
        for name in sorted(os.listdir(OUT)):
            if name.endswith('.pdf') and name[:-4] not in keep:
                os.remove(os.path.join(OUT, name))
                print(name[:-4], 'removed (older than', KEEP_DAYS, 'days)')
    failed = 0
    for p in items:
        pid = re.sub(r'\D', '', str(p.get('id', '')))
        if pid not in keep:
            continue
        dest = os.path.join(OUT, pid + '.pdf')
        if os.path.exists(dest):
            continue
        try:
            page = get(f'{BLOG}/{pid}').decode('utf-8', 'replace')
        except Exception as e:
            print(pid, 'page error', e); failed += 1; continue
        ok = False
        for _, url in find_pdfs(page):
            try:
                data = get(url, referer=BLOG + '/', timeout=180)
            except Exception as e:
                print(pid, 'download error', e); continue
            if data[:5] == b'%PDF-':
                with open(dest, 'wb') as f:
                    f.write(data)
                print(pid, 'saved', len(data)); ok = True; break
        if not ok:
            print(pid, 'no pdf'); failed += 1
    print('done, failed:', failed)


if __name__ == '__main__':
    main()
