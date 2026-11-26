# 3단계 스템 필터 에이전트 (`AUDYSSEY_FILTER=agent`)

분리 검증(`judge`)을 SAM Audio Judge 대신 **3단계 스템 필터 에이전트**로 하는 모드입니다. 캡스톤 첫 실험에서 만든 에이전트를 그대로 옮겼습니다(`src/audyssey/tools/filtering/stem_agent/`). 단계 로직, 프롬프트, 임계값은 바꾸지 않았고 입출력만 맞췄습니다. 기본 모드(`stub`/`real`/`remote`)의 동작은 바뀌지 않습니다.

## 판정 방식

분리 트랙마다 오디오 LLM(Qwen3-Omni-30B-A3B-Instruct)에게 세 가지를 차례로 묻습니다. 앞 단계에서 실패하면 멈춥니다.

| 단계 | 질문 | 입력 | 통과 / 실패 |
|---|---|---|---|
| 존재성 | 목표 소리가 들리는가 | 트랙 | P(존재) ≥ 0.85 / ≤ 0.70 |
| 순수성 | 목표 외 소리가 일반 재생 음량에서 들리는가 | 트랙 | P(다른 소리) ≤ 0.25 / ≥ 0.40 |
| 완전성 | 원본의 목표 소리가 빠짐없이 남았는가 | 원본 + 트랙 | P(누락) ≤ 0.69 / ≥ 0.75 |

- 질문마다 긍정형과 부정형을 함께 묻고, 첫 토큰 logprob에서 구한 P(YES)를 평균합니다.
- 두 임계값 사이는 "애매"입니다.
- 결정 규칙:
  - 모두 통과 → **ACCEPT**
  - 하나라도 실패 → **REJECT**
  - 실패는 없지만 애매한 단계가 있음 → **HOLD**

## AUDYSSEY 계약과의 대응

앱은 `scores["overall"] ≥ AUDYSSEY_JUDGE_PASS_THRESHOLD`(기본 0.5)로 합격을 다시 정합니다(`judge_verdict`). 그래서 에이전트 결정을 `overall`로 옮깁니다.

| 에이전트 결정 | `overall` | 기본 기준 0.5에서 |
|---|---|---|
| ACCEPT | 1.0 | 통과 |
| HOLD | 0.4 | 불합격 → 다시 분리 (애매한 트랙은 자동 선별하지 않음) |
| REJECT | 0.0 | 불합격 → 다시 분리 |

- `scores`에는 단계 확률이 같이 들어갑니다.
  - `p_present`: 존재 확률
  - `p_other`: 다른 소리가 들릴 확률
  - `p_missing`: 누락 확률
  - `recall` = 1 − `p_missing`, `precision` = 1 − `p_other` (SAM Audio Judge와 같은 뜻)
  - 앞 단계에서 멈추면 뒤 단계 확률은 없습니다.
- `reason`에는 실패한 단계와 이유가 남습니다(예: `judge overall 0.00 < 0.5: agent REJECT at purity: non-target sound audible (heard: crowd noise)`).
- `suggestion`은 완전성 실패에서 누락 구간을 찾았을 때만 만듭니다. 그 구간을 `spans`에 더해 다음 분리에서 SAM Audio의 양성 앵커로 쓰이게 합니다. 순수성·존재성 실패는 제안 없이 시드만 바꿔 다시 분리합니다.
- HOLD 트랙도 통과시키려면 `AUDYSSEY_JUDGE_PASS_THRESHOLD=0.4`로 둡니다. 다만 아래 재생 실험에서 정밀도가 0.84에서 0.62로 떨어졌습니다.

## 실행

판정 모델은 GPU 80GB급 서버에서 OpenAI 호환 API로 띄웁니다. main 서버는 GPU가 필요 없습니다.

```bash
# GPU 서버
vllm serve Qwen/Qwen3-Omni-30B-A3B-Instruct --port 8901 --dtype bfloat16 \
  --max-model-len 32768 --max-num-seqs 16 --limit-mm-per-prompt '{"audio": 3}'

# main 서버 (.env)
AUDYSSEY_FILTER=agent
AUDYSSEY_STEM_AGENT_URL=http://<gpu-host>:8901/v1
```

임계값을 바꾸려면 `AUDYSSEY_STEM_AGENT_CONFIG`에 JSON 경로를 줍니다(예: `{"purity": {"pass_at": 0.36}}`). 적지 않은 값은 기본값을 씁니다.

## 검증된 성능과 한계

- **스템 단위 (사람 라벨 625개, Qwen3-Omni-30B-A3B, 2026-11-21 측정):** ACCEPT 98개, 정밀도 0.837(사람이 S1·S2·S3 모두 O로 본 비율). 클립 단위 교차검증으로는 약 0.79–0.81입니다.
- **AUDYSSEY 루프 재생:** `evals/filtering/report.md`를 참고하세요. 모델 호출 없이 저장된 판정으로 비교했습니다.
- **한계**
  - 통과 수가 적습니다(625개 중 98개).
  - 순수성이 가장 약한 단계입니다.
  - 실제 SAM Audio 분리 결과에 대한 실행 측정은 아직 없습니다.
  - Qwen 판정 한 번에 트랙당 몇 초가 걸리므로, 소스가 많으면 분리 시간이 늘어납니다.
