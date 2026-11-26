# 작업 규칙과 CI/CD

[README](../README.md)의 "작업 규칙" 요약을 자세히 적은 문서입니다.

## 코드 규칙

**모듈과 계약**
- 담당 모듈 폴더만 고칩니다. `src/audyssey/tools/<모듈>/real.py`의 함수를 같은 시그니처([도구 함수](architecture.md#계약-함수-명령-api))로 구현합니다.
- 도구를 바꿀 때 `graph.py`, `api.py`, UI를 고쳐야 한다면 설계 문제일 수 있으니 팀에 먼저 공유합니다.
- `contracts.py`는 모든 모듈이 함께 쓰는 파일입니다. 바꿀 때는 PR에서 팀 합의를 받고 머지합니다.
- `contracts.py`, `graph.py`, `api.py`, `settings.py`, 의존성, Docker·Compose, CI 설정은 핵심 파일입니다([`.github/CODEOWNERS`](../.github/CODEOWNERS)). 바꾸는 PR은 @gwpark0741 또는 @Zero-woo의 승인이 있어야 머지됩니다. CI·CODEOWNERS 같은 `.github/` 설정은 @gwpark0741만 승인합니다.
- 작업 상태는 명령으로만 바꿉니다(`handle_command`). 새 편집 기능은 새 명령으로 추가합니다.

**설정**
- 설정은 환경변수로 받습니다. 새 설정을 만들면 `settings.py` 필드, [설정 표](running.md#설정-환경변수)의 한 줄, 테스트를 함께 추가합니다.
- 서버 경로, 키, 모델 경로를 코드에 직접 쓰지 않습니다.

**테스트와 검사**
- 테스트를 먼저 씁니다. 기능 테스트 → 구현 → 통과 순서입니다.
- CI에는 GPU가 없으므로 GPU 코드는 가짜 모듈로 검사합니다. 예: `tests/sam_audio_fakes.py`.
- 검사를 우회하지 않습니다. `# noqa`, `ty: ignore`, 테스트 skip, assert 완화로 통과시키지 말고 코드를 고칩니다.

**의존성**
- 루트(`pyproject.toml`)에는 torch를 넣지 않습니다.
- GPU 의존성은 `gpu/pyproject.toml`에 넣고 `uv lock --project gpu`로 잠급니다. 다른 패키지가 정한 버전 제약을 덮어쓰지 않습니다.

**비밀값과 공용 서버**
- `.env`는 git에서 제외되어 있습니다. 커밋하거나 로그에 출력하지 않습니다.
- 가중치는 HF 캐시에만 둡니다.
- sv3-a100 같은 공용 서버에서는 다른 사람의 GPU, Docker 이미지, 캐시를 건드리지 않습니다. 지울 때는 내가 만든 이미지와 볼륨만 지우고, 쓸 GPU 번호는 미리 알립니다.

## 브랜치와 커밋

- 브랜치: `<type>/<짧은-설명>`. 예: `feat/sam3-grounding`, `fix/tools-image-ffmpeg`, `docs/e2e-results`
- 커밋: `<type>(<scope>): <소문자 명령형 요약>` (Conventional Commits). 예:
  - `feat(separation): support reranking with configurable ranker checkpoints`
  - `fix(grounding): track masks at a reduced frame rate`
  - `build(docker): run app, tools and vllm containers as non-root`
  - `docs(readme): add sam3 grounding guide`
- type: `feat`, `fix`, `docs`, `build`(Docker, 의존성), `test`, `refactor`, `chore`
- scope: `planning`, `separation`, `filtering`, `grounding`, `graph`, `api`, `contracts`, `media`, `toolserver`, `docker`, `gpu`, `readme`, `spec` 등
- 커밋 하나에는 변경 하나만 담습니다. 테스트와 구현은 같은 커밋에 넣어도 됩니다.

## commit → push → PR → merge → 배포

| 단계 | 자동으로 일어나는 일 | 내가 할 일 |
|---|---|---|
| 1. 브랜치 | 없음 | 최신 `main`에서 브랜치를 만듦 |
| 2. 커밋 | 없음 (로컬 훅 없음) | 커밋 전에 [로컬 검사](#로컬-검사)를 통과시킴 |
| 3. push | 없음. push만으로는 CI가 돌지 않음 | `git push -u origin <브랜치>` (팀원은 write 권한으로 레포에 직접 push) |
| 4. PR (대상 `main`) | `ci-lint`가 job 3개를 실행하며 모두 필수:<br>- `lint-and-format-check`: ruff lint·format, ty, unittest<br>- `numpy-1x`: Python 3.12 + numpy 1.26 unittest<br>- `docker-build`: app 이미지 빌드(push 안 함). tools 이미지는 `docker/tools.Dockerfile`, `gpu/`, 도구 코드, 의존성이 바뀐 PR에서만 빌드 | 설명에 요약과 확인 방법을 적음. 핵심 파일을 바꿨다면 팀 합의를 받음. 실패하면 고쳐서 다시 push |
| 5. merge | `main` 보호 규칙 적용:<br>- 필수 검사 통과와 최신 `main` 반영 전에는 머지 불가 (관리자 포함)<br>- 승인 1명 필요. 핵심 파일은 @gwpark0741 또는 @Zero-woo 승인 필요 (`.github/`는 @gwpark0741만). 새로 push하면 기존 승인은 다시 받아야 함<br>- 강제 push와 브랜치 삭제 금지 | 리뷰를 받고 머지. 관리자 본인 PR은 승인 없이 머지할 수 있지만 검사는 똑같이 통과해야 함. 머지 커밋 방식을 쓰고, 머지한 브랜치는 직접 지움 |
| 6. 배포 | `main`에 이미지에 들어가는 파일(`src/`, 의존성, `gpu/`, `docker/`)이 반영되면 `publish-images`가 `audyssey-app`, `audyssey-tools`를 빌드해 GHCR에 `latest`와 커밋 SHA 태그로 올림 (수동 실행 가능, PR에서는 올리지 않음) | 아래 [서버 갱신](#서버-갱신)대로 SHA 태그로 고정해 올림. RunPod은 Pod를 다시 만들 때 SHA 태그를 지정 |

이미지는 공개되어 있어 로그인 없이 받을 수 있습니다. tools 이미지는 약 23GB라 빌드와 다운로드에 시간이 걸립니다.

### 이미지 빌드 캐시

- Dockerfile은 바뀌는 빈도가 낮은 것부터 레이어를 쌓습니다. 의존성(`pyproject.toml`, `uv.lock`, `gpu/`)을 먼저 설치하고 그다음 `src/`, 웹 빌드 결과를 복사하므로, 코드만 바꾸면 의존성 레이어(tools는 torch 포함 약 20GB)를 다시 만들지 않습니다. 웹(`web/`)만 바꾸면 app 이미지의 Node 단계와 마지막 복사 레이어만 다시 만듭니다.
- `publish-images`는 이미지마다 레지스트리 캐시를 씁니다. 캐시는 `ghcr.io/capstone-audissey-fall-2026/audyssey-app:buildcache`, `audyssey-tools:buildcache` 태그에 저장되고(실행 가능한 이미지가 아님), 바뀐 레이어만 새로 빌드합니다. 이미지와 캐시 레이어는 zstd로 압축하므로 Docker 23 이상이 필요합니다. `ci-lint`의 `docker-build`는 같은 캐시를 읽기만 합니다.
- 서버에서 직접 빌드할 때는 `uv` 다운로드 캐시가 BuildKit 캐시 마운트에 남아 재시도와 재빌드가 빨라집니다.

## 서버 갱신

공용 GPU 서버는 `latest`가 아니라 확인한 커밋의 이미지로 고정합니다. `latest`는 머지할 때마다 바뀌므로, 그대로 받으면 확인하지 않은 이미지가 올라갈 수 있습니다.

1. `.env`의 `AUDYSSEY_IMAGE_TAG`에 머지 커밋의 전체 SHA를 넣습니다. 비우면 `latest`를 씁니다.
2. 이미지를 받고 띄웁니다.
   ```bash
   docker compose pull && docker compose up -d
   ```
3. 실제 영상으로 분리와 생성을 한 번씩 돌려 확인합니다. 모델을 올리는 첫 실행은 느립니다.
4. 문제가 있으면 `AUDYSSEY_IMAGE_TAG`를 이전 SHA로 되돌리고 2번을 다시 합니다.

## 로컬 검사

CI와 같은 검사입니다. ffmpeg/ffprobe가 PATH에 있어야 테스트가 돕니다.

```bash
uv sync --dev --locked --extra ui --extra llm
uv run ruff check src/
uv run ruff format --check src/
uv run ty check --error-on-warning src/
uv run python -m unittest discover tests
# numpy-1x job과 같은 검사
uv run --isolated --no-project --python 3.12 --with-editable '.[ui,llm]' --with 'numpy==1.26.4' python -m unittest discover tests
```

비밀값 없이 Compose 파일만 검사하려면:

```bash
env -i PATH="$PATH" docker compose --env-file .env.example config --no-env-resolution --quiet
```
