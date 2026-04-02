# Zone 배치 흐름 — 3단계 Fallback

![Zone Fallback Flow](C:\Users\roach\.gemini\antigravity\brain\a6b8a658-7891-41c9-9fda-449996de15a5\zone_flow_v2_1775037127257.png)

---

## 텍스트 버전 (이미지 보완)

```
예시: 오브젝트 5개, zone 4개

         entrance_zone    mid_zone    deep_zone    side_zone
               🟢            🔵          🟣           🟠
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[오브젝트 1: character_ryan]

  1단계 ─── Agent 3: "entrance_zone, inward"
             └→ 코드: entrance_zone 격자점 15개 순회
                 └→ 3번째 점에서 성공 ✅ → 확정

[오브젝트 2: shelf_3tier]

  1단계 ─── Agent 3: "mid_zone, wall_facing"
             └→ 코드: mid_zone 격자점 20개 순회
                 └→ 전부 실패 ❌ (character_ryan이 통로 차단)

             └→ 단독 배치 테스트: 혼자는 성공 → cascade!

  2단계 ─── Global Reset [1/2]
             └→ Choke Point: "character_ryan이 mid_zone 통로 차단"
             └→ Agent 3 재호출 (mid_zone 실패 정보 포함)
             └→ Agent 3: "side_zone, wall_facing"
             └→ 코드: side_zone 격자점 12개 순회
                 └→ 5번째 점에서 성공 ✅ → 확정

[오브젝트 3: photo_zone]

  1단계 ─── Agent 3: "deep_zone, center"
             └→ 전부 실패 ❌

             └→ 단독 배치 테스트: 혼자는 성공 → cascade!

  2단계 ─── Global Reset [1/2]
             └→ Agent 3: "mid_zone, center"
             └→ 전부 실패 ❌

             └→ Global Reset [2/2]
             └→ Agent 3: "entrance_zone, center"
             └→ 전부 실패 ❌

  3단계 ─── Deterministic Fallback
             └→ LLM 중단
             └→ 전체 floor polygon에서 탐색
             └→ 벽 최인접 + 입구 미차단 위치 발견 ✅
             └→ 강제 확정 (source: "fallback")

[오브젝트 4: large_display]

  1단계 ─── Agent 3: "mid_zone, wall_facing"
             └→ 전부 실패 ❌

             └→ 단독 배치 테스트: 혼자도 실패 ❌ → 물리적 한계

             └→ Graceful Degradation: 드랍
             └→ 리포트: "large_display: 공간 부족으로 배치 불가"

[오브젝트 5: banner_stand]

  (오브젝트 4 드랍으로 공간 확보됨)
  1단계 ─── Agent 3: "entrance_zone, wall_facing"
             └→ 성공 ✅ → 확정

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
최종 결과: 5개 중 4개 배치 (1개 드랍, 1개 fallback)
```

---

## 핵심 분기점

```
격자 순회 전부 실패
       │
       ▼
  단독 배치 테스트
       │
  ┌────┴────┐
  │         │
혼자도 실패  혼자는 성공
  │         │
  ▼         ▼
드랍      cascade
(물리적    (순서 문제)
 한계)        │
         Global Reset
         남은 횟수?
              │
        ┌─────┴─────┐
        │           │
      남음        소진 (2회)
        │           │
        ▼           ▼
  Agent 3 재호출  Deterministic
  (실패 zone 제외)  Fallback
        │           │
   1단계로 복귀   zone 무시
                전체 탐색
                    │
              ┌─────┴─────┐
              │           │
           성공         실패
              │           │
              ▼           ▼
     source:fallback    드랍
```
