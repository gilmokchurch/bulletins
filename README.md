# 길목교회 주보 사본

길목교회 블로그(https://thewaynews.tistory.com)에 올라온 주보 PDF의 사본입니다.
홈페이지(https://theway.news/bulletin)에서 주보를 빨리 띄우려고 둡니다.

- `pdf/<블로그 글 번호>.pdf` — 주보 파일
- 매시간 GitHub Actions(`.github/workflows/sync.yml`)가 `sync.py`로 새 주보를 복사해 GitHub Pages로 내보냅니다.
- 3개월(92일)이 지난 주보 사본은 자동으로 지웁니다. 지운 주보는 홈페이지에서 블로그 파일을 거쳐 (조금 느리게) 열립니다.
- 블로그에서 주보 파일을 고쳐 다시 올렸다면, 여기서 해당 `pdf/<글 번호>.pdf`를 지우면 다음 실행 때 새로 복사됩니다.
- 직접 실행: 저장소의 **Actions → 주보 복사 → Run workflow**
