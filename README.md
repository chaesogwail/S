# SUT 재고와 가격

게이트 SUT/USDT 일봉 위에 핵심 지갑(게이트 거래소·유니스왑 풀·회사 매도지갑) 잔고를 기간 평균 대비 %로 겹쳐 보여 주고, 상세 페이지에서 오늘의 지갑 움직임과 이상 징후, 과거 이상 징후 날의 가격 반응을 정리한다. 정적 사이트라 GitHub Pages 에 그대로 올라간다.

## 올리는 법
1. 이 폴더를 새 저장소로 푸시한다 (`main` 브랜치).
2. Settings → Pages → Source: **Deploy from a branch**, Branch: `main` / `/ (root)`.
3. Settings → Secrets and variables → Actions → **New repository secret**: 이름 `POLYSCAN_KEY`, 값은 Etherscan API 키.
4. Actions 탭에서 `update-data` 를 한 번 수동 실행(Run workflow)해 `data/*.json` 이 갱신되는지 확인한다. 이후 15분마다 자동.

## 갱신 주기
- 온체인 집계(전송·일별 잔고·이상 징후): GitHub Actions 가 15분마다 `scripts/build_data.py` 를 돌려 `data/` 를 갱신한다.
- 지갑 잔고: 브라우저가 폴리곤 공개 RPC 로 1분마다 직접 읽는다 (키 불필요).
- 가격: 브라우저가 게이트 공개 API 를 1분마다 읽는다. 브라우저 CORS 정책에 막히면 상태줄에 표시되고 집계 종가로 대체된다.

## 파일
- `index.html` 한눈에(캔들 + 재고 선 + 게이지 + 이상 징후 띠)
- `detail.html` 오늘의 움직임, 규칙, 과거 이상 징후 표, 9월 회사 매도 사슬
- `assets/data.js` 데이터 로딩·실시간 조회·이상 징후 규칙 (두 페이지 공용)
- `scripts/build_data.py` 집계 빌더 (Actions 용)
- `data/daily.json`, `data/anomalies.json` 현재 담긴 것은 2026-03-01 ~ 09-08 실측

## 하루 경계
KST 09:00 = UTC 00:00. 게이트 일봉 경계와 같고, 회사 물량이 거래소에 도착하는 UTC 05시 배치(KST 14시)가 같은 날 안에 들어온다.

## 지갑
| 이름 | 주소 | 비고 |
|---|---|---|
| 게이트 거래소 | 0x0d0707963952f2fba59dd06f2b425ace40b492fe | 입금은 매일 UTC 05시 배치로만 찍힘 |
| 유니스왑 주풀 1% | 0x092295c92bab5e734c4a60dbc0f0ffdcdfc4e165 | |
| 유니스왑 보조풀 0.05% | 0xb700d11b26707015c04c0e03edbe905e08056878 | |
| 회사 매도지갑 | 0x686a2630ab724f07a1a1de7e2590efb621c5a6a6 | 9/5 200,001 수령 |
| 회사 환전지갑 | 0x1600ef50319d38a42dafcde831b06b55640a42ea | 게이트 송금 통로, 가장 앞선 신호 |
| MPC 금고 | 0xf46e16da9cf96c19bfc5c5d550857c7a53ea7bc8 | 예비 물량 |

지갑 라벨은 슈퍼세이브 자료실(revive065-glitch.github.io/Polygone_wallet_address)의 온체인 분석을 따른다. 이 사이트는 기록이지 예측이 아니다.
