"""주보 PDF에서 예배순서와 광고(공동체 소식)를 뽑아 order/<글번호>.json 으로 저장하고, order/index.json(목록)을 다시 만듭니다.

    python3 order.py              pdf/ 안의 주보 중 아직 뽑지 않은 것만
    python3 order.py --all        전부 다시
    python3 order.py --check      이번 주일 주보가 이미 있으면 0, 없으면 1로 끝남 (찾기 작업에서 사용)

주보 틀(2026년 기준): 2~3쪽 예배순서, 8쪽 '공동체 소식'.
  · 묶음 제목(예배로 나아감 …)과 광고 제목은 제목용 글꼴(Cafe24Dangdanghae)
  · 순서 한 줄은 '이름 ······ 내용 ······ 담당'
  · 인도자/성도들/다같이 표시는 작은 글씨(10pt)로 왼쪽에
PDF는 3개월 뒤 지워지지만, 뽑아 둔 json은 계속 남겨 지난 주보 목록으로 씁니다.
"""
import json
import os
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone

import pdfplumber

PDF_DIR, OUT = 'pdf', 'order'
SITE = 'https://theway.news'
UA = 'Mozilla/5.0 (compatible; GilmokChurchSite/1.0; +https://theway.news)'
KST = timezone(timedelta(hours=9))
ROLES = ('인도자', '성도들', '다같이')
HEAD_FONT = 'Dangdanghae'


# 글꼴에 글자 정보가 빠져 (cid:번호)로 나오는 기호 (2026.9.6 주보에서 확인)
CID = {'13247': '-', '13249': '~', '13273': '(', '13274': ')', '13967': '>', '13968': '<', '14140': '/'}


def is_head(c):
    return HEAD_FONT in c['fontname']


def text_of(chars):
    """글자들을 한 줄 글로: 글자 사이가 벌어진 곳에만 띄어쓰기."""
    out, prev = '', None
    for c in chars:
        if prev is not None and c['text'].strip() and prev['text'].strip() and c['x0'] - prev['x1'] > min(c['size'], prev['size']) * 0.25:
            out += ' '
        out += c['text']
        prev = c
    out = re.sub(r'\(cid:(\d+)\)', lambda m: CID.get(m.group(1), ''), out)
    out = re.sub(r'\s+', ' ', out).strip()
    out = re.sub(r'\s+([.,!?)\]」』”])', r'\1', out)
    return re.sub(r'([(\[「『“])\s+', r'\1', out)


def page_lines(page):
    """한 쪽의 글자를 줄로 묶음. 같은 높이라도 작은 역할 표시(인도자 등)는 따로 떼어 냄."""
    # 글자는 PDF에 적힌 순서대로 (x 위치로 다시 정렬하면 일부 글꼴에서 글자 순서가 뒤섞임)
    chars = [c for c in page.chars if c['text'] != '\n']
    rows = []
    for c in chars:
        mid = (c['top'] + c['bottom']) / 2
        for r in rows:
            if abs(r['mid'] - mid) < 3 and abs(r['size'] - c['size']) < 0.6:
                r['chars'].append(c); break
        else:
            rows.append({'mid': mid, 'size': c['size'], 'chars': [c]})
    lines = []
    for r in rows:
        cs = r['chars']
        if not ''.join(c['text'] for c in cs).strip():
            continue
        ink = [c for c in cs if c['text'].strip()]
        lines.append({'y': r['mid'], 'x': min(c['x0'] for c in ink), 'size': r['size'], 'head': is_head(ink[0]), 'chars': cs, 'text': text_of(cs)})
    lines.sort(key=lambda l: (round(l['y']), l['x']))
    return lines


def fields(line):
    """'이름 ······ 내용 ······ 담당' → ['이름', '내용', '담당'] (점선 뒤에 숨은 글자도 살림)."""
    cs = [c for c in line['chars'] if c['text'] not in '·.']
    parts, cur = [], []
    for c in cs:
        ink = [x['x1'] for x in cur if x['text'].strip()]
        if ink and c['text'].strip() and c['x0'] - max(ink) > c['size'] * 1.5:
            parts.append(cur); cur = []
        cur.append(c)
    if cur:
        parts.append(cur)
    return [t for t in (text_of(p) for p in parts) if t]


def is_leader(line):
    return line['text'].count('·') >= 8


def parse_order(pages):
    sections, item = [], None
    labels = []          # 이번 순서의 (높이, 역할)
    pending = []         # 이번 순서의 (높이, 글) — 역할 표시와 나중에 짝지음

    def flush():
        nonlocal labels, pending
        if item is None:
            labels, pending = [], []
            return
        if labels:
            # 글 한 줄마다 가장 가까운 역할 표시를 붙이고, 같은 역할이 이어지면 한 묶음
            rows = []
            for y, t in pending:
                role = min(labels, key=lambda l: abs(l[0] - y))[1]
                if rows and rows[-1][0] == role and rows[-1][2] == min(labels, key=lambda l: abs(l[0] - y)):
                    rows[-1][1] += ' ' + t
                else:
                    rows.append([role, t, min(labels, key=lambda l: abs(l[0] - y))])
            item['lines'] = [[r, t] for r, t, _ in rows]
        elif pending:
            if item.get('song'):
                item['lyrics'] = [t for _, t in pending]
            else:
                item['hint'] = ' '.join(t for _, t in pending)
        labels, pending = [], []

    for lines in pages:
        for l in lines:
            if l['size'] >= 30:      # 쪽 제목 '주일예배'
                continue
            if l['head']:
                flush(); item = None
                sections.append({'title': re.sub(r'\s+', ' ', l['text']), 'items': []})
                continue
            if not sections:
                continue
            if is_leader(l):
                flush()
                f = fields(l)
                item = {'name': f[0]}
                if len(f) >= 3:
                    item['detail'], item['who'] = ' '.join(f[1:-1]), f[-1]
                elif len(f) == 2:
                    item['who'] = f[1]
                d = item.get('detail', '')
                # 곡 이름은 따옴표 안에 (따옴표 글자가 깨진 주보도 있어 '찬양', '~송'이면 곡으로 봄)
                if d and (d[0] in '“"' or re.search(r'찬양$|송$', f[0].replace(' ', ''))):
                    item['song'] = True
                if re.search(r'[가-힣]+\s*\d+\s*:\s*\d+', d) and not item.get('scripture') and '말씀읽기' in item['name'].replace(' ', ''):
                    item['scripture'] = True
                if '말씀묵상' in item['name'] or '설교' in item['name']:
                    item['preacher'] = True
                sections[-1]['items'].append(item)
                continue
            if item is None:
                continue
            # 작은 글씨의 역할 표시 (줄 앞에 붙어 있으면 떼어 냄)
            small = [c for c in l['chars'] if c['size'] <= 10.5 and c['text'].strip()]
            t = l['text']
            if small and text_of(small) in ROLES:
                labels.append((l['y'], text_of(small)))
                rest = [c for c in l['chars'] if c['size'] > 10.5]
                if not rest:
                    continue
                t = text_of(rest)
            pending.append((l['y'], t))
    flush()
    for s in sections:
        for it in s['items']:
            it['name'] = re.sub(r'\s*-\s*', ' · ', it['name'])
    return [s for s in sections if s['items']]


def parse_news(lines):
    news, cur = [], None
    para_x = None
    for l in lines:
        if l['size'] >= 30:
            continue
        if l['head']:
            cur = {'title': l['text'], 'body': []}
            news.append(cur); para_x = None
            continue
        if cur is None:
            continue
        t = l['text']
        body = cur['body']
        if t.startswith('▪') or t.startswith('•') or t.startswith('-'):
            body.append({'li': t.lstrip('▪•- ').strip()})
        elif para_x is None or abs(l['x'] - para_x) < 2:
            if para_x is None:
                para_x = l['x']
            if body and 'p' in body[-1]:
                body[-1]['p'] += ' ' + t
            else:
                body.append({'p': t})
        elif body:
            k = 'li' if 'li' in body[-1] else 'p'
            body[-1][k] += ' ' + t
        else:
            body.append({'p': t})
    return news


def parse(path):
    with pdfplumber.open(path) as pdf:
        all_lines = [page_lines(p) for p in pdf.pages]
        cover = re.sub(r'\s+', '', pdf.pages[0].extract_text() or '')
    def first(ls):
        return ''.join(l['text'] for l in ls[:2]).replace(' ', '')
    start = next(i for i, ls in enumerate(all_lines) if '주일예배' in first(ls))
    end = start
    while end + 1 < len(all_lines) and any(is_leader(l) for l in all_lines[end + 1]):
        end += 1
    news_page = next((ls for ls in all_lines if '공동체소식' in first(ls)), [])
    m = re.search(r'제(\d+)호', cover)
    return {
        'issue': int(m.group(1)) if m else None,
        'sections': parse_order(all_lines[start:end + 1]),
        'news': parse_news(news_page),
    }


def sunday_of(p):
    """홈페이지의 bulletinSunday와 같은 규칙."""
    m = re.search(r'(\d{4})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})', p.get('title') or '')
    if m:
        try:
            d = date(int(m[1]), int(m[2]), int(m[3]))
            if d.weekday() == 6:
                return d
        except ValueError:
            pass
    at = datetime.fromisoformat(str(p['date']).replace('Z', '+00:00')).astimezone(KST).date()
    return at + timedelta(days=(6 - at.weekday()) % 7)


def posts():
    req = urllib.request.Request(f'{SITE}/api/posts?type=bulletin&limit=30', headers={'user-agent': UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return {re.sub(r'\D', '', str(p['id'])): p for p in json.loads(r.read())['items']}


def coming_sunday():
    today = datetime.now(KST).date()
    return today + timedelta(days=(6 - today.weekday()) % 7)


def main():
    os.makedirs(OUT, exist_ok=True)
    index_path = os.path.join(OUT, 'index.json')
    index = json.load(open(index_path, encoding='utf-8')) if os.path.exists(index_path) else []
    if '--check' in sys.argv:
        sys.exit(0 if any(e['sunday'] == coming_sunday().isoformat() for e in index) else 1)
    redo = '--all' in sys.argv
    info = posts()
    by_id = {e['id']: e for e in index}
    for name in sorted(os.listdir(PDF_DIR)):
        pid = name[:-4]
        dest = os.path.join(OUT, pid + '.json')
        if not name.endswith('.pdf') or (os.path.exists(dest) and not redo):
            continue
        try:
            d = parse(os.path.join(PDF_DIR, name))
        except Exception as e:
            print(pid, 'parse error', e); continue
        if not d['sections']:
            print(pid, 'no order found'); continue
        p = info.get(pid)
        sunday = sunday_of(p).isoformat() if p else (by_id.get(pid) or {}).get('sunday')
        if not sunday:
            print(pid, 'no date'); continue
        d = {'id': pid, 'sunday': sunday, **d}
        with open(dest, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        its = [i for s in d['sections'] for i in s['items']]
        word = next((i.get('detail') for i in its if i.get('scripture')), None)
        who = next((i.get('who') for i in its if i.get('preacher')), None)
        by_id[pid] = {'id': pid, 'sunday': sunday, 'issue': d['issue'], 'word': word, 'preacher': who}
        print(pid, sunday, 'ok', len(its), 'items', len(d['news']), 'news')
    index = sorted(by_id.values(), key=lambda e: e['sunday'], reverse=True)
    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
