# Audyssey

Audyssey는 짧은 영상(최대 30초)의 오디오를 소리를 내는 대상별 트랙(stem)으로 나누고, 필요한 소리를 생성해 다시 합치는 오디오 편집 도구입니다. 원본 오디오가 있으면 separation으로 나누고, 만족스럽지 않은 소리나 원본에 없는 소리는 사용자가 요청할 때 generation으로 만듭니다. 오디오가 없는 영상은 대사를 제외한 소리를 generation으로 만듭니다. 트랙별로 켜고 끄거나 음량과 피치를 바꾼 뒤 합쳐, 편집된 영상과 트랙별 오디오를 내보냅니다.

처리 흐름과 서버 구성은 [docs/architecture.md](docs/architecture.md)에 있습니다.

## 어떻게 실행하나

| 방식 | GPU | 필요한 것 | 안내 |
|---|---|---|---|
| 1. GPU 없이 stub | 없음 | Python, uv, ffmpeg | [아래 빠른 실행](#빠른-실행-gpu-없이) |
| 2. 한 GPU 서버에서 전부 | 서버의 GPU 1장 | Docker, NVIDIA Container Toolkit, HF 가중치 | [running.md 2](docs/running.md#2-한-gpu-서버에서-전부-composeyaml) |
| 3. 로컬 app + 원격 GPU tools | 원격 Pod 또는 GPU 서버 | 로컬 Docker, 도구 서버 주소와 토큰 | [running.md 3](docs/running.md#3-로컬-app--원격-gpu-tools) |

기능 수정과 실험은 1번으로 합니다. GPU는 실제 모델 통합 테스트 때만 쓰고 바로 반납합니다.

## 빠른 실행 (GPU 없이)

```bash
git clone https://github.com/capstone-audissey-fall-2026/audyssey.git && cd audyssey
uv sync --extra ui
(cd web && npm ci && npm run build)   # 화면 빌드. Node 20.19 이상 필요, 건너뛰면 이전 단일 파일 화면이 뜹니다
uv run audyssey serve
```

브라우저에서 http://127.0.0.1:8600 을 열고 `samples/sample.mp4`를 연 뒤 Separate를 누릅니다(업로드만으로는 전처리까지만 돌며, 무음 영상은 Generate를 누릅니다). 모든 모델 자리에 가짜 구현(stub)이 들어 있어 GPU, API 키, 모델 가중치가 필요 없습니다. Python 3.11 이상, [uv](https://docs.astral.sh/uv/), ffmpeg가 필요합니다.

### Hydrogen AV · SAM Audio 배치 · TF32

Hydrogen은 오디오가 포함된 영상을 받아 분리할 소스를 계획합니다. SAM Audio는 검수를 통과한 소스마다 전체 모노 음원, `description`, 원래 타임스팬 앵커를 받습니다.

#### 설정 및 실행

Docker Compose와 NVIDIA GPU가 있는 서버에서 [모델 가중치 준비](docs/running.md#실제-모델로-실행하기-팀원용)를 마친 뒤, [.env.example](.env.example)을 참고해 `.env`의 `HF_CACHE`와 `AUDYSSEY_TOOL_TOKEN`을 설정합니다. 유효한 OpenRouter 키를 `AUDYSSEY_PLANNER_API_KEY`에 넣고 다음 값을 적용합니다.

```dotenv
AUDYSSEY_PLANNER=real
AUDYSSEY_PLANNER_API=openrouter
AUDYSSEY_PLANNER_BASE_URL=https://openrouter.ai/api/v1
AUDYSSEY_PLANNER_MODEL=google/gemini-4-hydrogen
AUDYSSEY_PLANNER_INPUT=video
AUDYSSEY_PLANNER_VIDEO_AUDIO=true
AUDYSSEY_SAM_AUDIO_BATCH_SIZE=32
AUDYSSEY_SAM_AUDIO_ALLOW_TF32=true
```

이 브랜치에서 도구 서버를 먼저 빌드해 시작하고 앱을 올립니다.

```bash
docker compose up -d --build separation judge
docker compose up -d --build main
```

브라우저에서 `http://127.0.0.1:8600`을 열고 `samples/sample.mp4` 또는 오디오가 있는 짧은 영상을 업로드한 뒤 **분리 시작**을 누릅니다. 작업이 끝나면 타임라인에서 소스별 음원을 재생할 수 있습니다.

외부 GPU 도구 서버를 쓰는 경우 앱과 분리 서버에 같은 배치 크기를 설정하고, 분리 서버에 TF32 설정을 적용합니다. 기존 Router가 플래너 설정을 상속하고 있었다면 기존 Router 값은 `AUDYSSEY_ROUTER_*`로 지정합니다.

#### 코드 위치와 동작

| 위치 | 동작 |
|---|---|
| [Planner 설정 예시](.env.example) | OpenRouter Hydrogen에 오디오 트랙을 포함한 영상을 전달합니다. 기존 프롬프트와 검수 규칙을 사용합니다. 검수기 모델을 따로 지정하지 않으면 Hydrogen을 상속하며, 분리 검수 입력은 기본적으로 오디오입니다. |
| [분리 그래프](src/audyssey/graph.py) · [도구 서버](src/audyssey/toolserver.py) | 검수를 통과한 소스의 첫 분리 요청을 묶습니다. Judge, 소스 재시도, 시각 마스크 입력은 소스별로 처리합니다. |
| [SAM Audio](src/audyssey/tools/separation/real.py) | 설정한 수만큼 소스를 배치로 처리합니다. CUDA OOM이 나면 크기를 절반으로 줄여 같은 요청의 남은 소스에 적용합니다. TF32를 켜면 SAM Audio 추론의 CUDA FP32 행렬곱에서 이를 허용합니다. |

설정을 지정하지 않을 때 배치 크기는 `1`, TF32 옵션은 `false`입니다.

#### 검증 결과

- RunPod A40에서 `jjangu.mp4`의 Hydrogen AV 플래닝부터 검수, SAM Audio, Judge까지 실행했습니다. 소스 4개를 배치 요청 한 번으로 분리했고, 각 48 kHz WAV가 원본 모노 음원과 같은 469,229샘플인 것을 확인했습니다.
- 배치 32에서 시작해 CUDA OOM으로 크기를 줄이는 동작은 모의 테스트로 확인했습니다. 실제 A40 실행에서는 소스 4개를 배치했습니다.
- 로컬 테스트 445개, Ruff, ty, Compose 설정 검사가 통과했습니다. A40 검증은 앱과 원격 도구 서버를 직접 실행했습니다.

## 작업 규칙
## 폴더

| 위치 | 내용 |
|---|---|
| `src/audyssey/` | 앱. `graph.py` 처리 흐름, `api.py` API, `tools/<모듈>/` 모듈별 `stub.py` · `real.py` · `remote.py` |
| `web/` | 화면(React). 빌드 결과는 `src/audyssey/webui/` |
| `gpu/` | GPU 도구 전용 uv 프로젝트 |
| `docker/`, `compose.yaml`, `compose.tools.yaml` | 이미지와 Compose. `compose.tools.yaml`은 GPU 도구만 띄움 |
| `scripts/` | 가중치 다운로드, SAM Audio 확인 스크립트 |
| `tests/`, `evals/`, `samples/` | 단위 테스트, 평가, 샘플 영상 |

## 문서

| 문서 | 내용 |
|---|---|
| [docs/running.md](docs/running.md) | 실행 방식별 절차, 가중치 준비, 플래너 연결, 설정 표, 문제 해결 |
| [docs/contributing.md](docs/contributing.md) | 작업 규칙, 브랜치와 커밋, PR부터 배포까지, CI 검사 |
| [docs/architecture.md](docs/architecture.md) | 처리 흐름, 서버 구성, 용어, 계약·명령·API, 코드 위치 |
| [docs/status.md](docs/status.md) | 모듈별 남은 과제, 실측 기록 |
| [docs/planning.md](docs/planning.md) | 플래닝과 검수 정책, 평가 |
| [설계 문서](docs/superpowers/specs/) | 단계별 설계와 결정 기록 |
