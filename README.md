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
