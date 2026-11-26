# 작업 규칙과 CI/CD

## 규칙

**모듈과 계약**
- 담당 모듈 폴더만 고칩니다. `src/audyssey/tools/<모듈>/real.py`의 함수를 같은 시그니처([도구 함수](architecture.md#계약-함수-명령-api))로 구현합니다.
- 도구를 바꾸려면 `graph.py`, `api.py`, 화면까지 고쳐야 한다면 설계 문제일 수 있으니 팀에 먼저 공유합니다.
- `contracts.py`는 모든 모듈이 함께 쓰므로, 바꿀 때는 PR에서 먼저 팀 합의를 받습니다.
- `contracts.py`, `graph.py`, `api.py`, `settings.py`, 의존성, `compose.yaml`, `docker/`, `gpu/`는 핵심 파일입니다([`.github/CODEOWNERS`](../.github/CODEOWNERS)). 바꾸는 PR은 @gwpark0741 또는 @Zero-woo의 승인이 필요하고, `.github/`는 @gwpark0741만 승인합니다.
- 작업 상태는 명령으로만 바꿉니다(`handle_command`). 새 편집 기능은 새 명령으로 추가합니다.

**설정**
- 설정은 환경변수로 받습니다. 새 설정은 `settings.py` 필드, [설정 표](running.md#설정-표)의 한 줄, 테스트를 함께 추가합니다.
- 서버 경로, 키, 모델 경로를 코드에 직접 쓰지 않습니다.

**테스트와 검사**
- 테스트를 먼저 씁니다. 기능 테스트 → 구현 → 통과 순서입니다.
- CI에는 GPU가 없으므로 GPU 코드는 가짜 모듈로 검사합니다. 예: `tests/sam_audio_fakes.py`.
- 검사를 우회하지 않습니다. `# noqa`, `ty: ignore`, 테스트 skip, assert 완화 대신 코드를 고칩니다.

**의존성**
- 루트(`pyproject.toml`)에는 torch를 넣지 않습니다.
- GPU 의존성은 `gpu/pyproject.toml`에 넣고 `uv lock --project gpu`로 잠급니다. 다른 패키지가 정한 버전 제약을 덮어쓰지 않습니다.

**비밀값과 공용 서버**
- `.env`는 git에서 제외되어 있습니다. 커밋하거나 로그에 출력하지 않습니다. 가중치는 HF 캐시에만 둡니다.
- sv3-a100 같은 공용 서버에서는 다른 사람의 GPU, Docker 이미지, 캐시를 건드리지 않습니다. 내가 만든 이미지, 컨테이너, 볼륨만 지우고, 쓸 GPU 번호는 미리 알립니다.

## 모듈 담당

| 모듈 | 위치 | 담당 |
|---|---|---|
| 오케스트레이터·API | `graph.py`, `api.py`, `store.py` | 오케스트레이터 담당 |
| UI | `web/` (빌드 결과는 `src/audyssey/webui/`), `ui/` (`/legacy`), `devui/` (`/dev`) | UI 담당 |
| 플래닝 | `tools/planning/real.py` | 플래닝 담당 |
| 분리 | `tools/separation/real.py` | 분리 담당 |
| 분리 검증 | `tools/filtering/real.py` | 필터링 담당 |
| 그라운딩 | `tools/grounding/real.py` | 미정 |
| 생성·채점 | `tools/generation/real.py` | 미정 |
| 편집·합치기 | `tools/editing/render.py` | 미정 |
| 인프라·배포 | `docker/`, `compose.yaml`, `compose.tools.yaml`, `.github/workflows/` | 인프라 담당 |

모듈별 남은 과제는 [status.md](status.md)에 있습니다.

## 브랜치와 커밋

- 브랜치: `<type>/<짧은-설명>`. 예: `feat/sam3-grounding`, `fix/tools-image-ffmpeg`, `docs/e2e-results`
- 커밋: `<type>(<scope>): <소문자 명령형 요약>` (Conventional Commits). 예:
  - `feat(separation): support reranking with configurable ranker checkpoints`
  - `fix(grounding): track masks at a reduced frame rate`
  - `build(docker): run app, tools and vllm containers as non-root`
  - `docs(readme): add sam3 grounding guide`
- type: `feat`, `fix`, `docs`, `build`(Docker, CI, 의존성), `test`, `refactor`, `chore`
- scope: `planning`, `separation`, `filtering`, `grounding`, `graph`, `api`, `contracts`, `media`, `toolserver`, `docker`, `gpu`, `web`, `ui`, `ci`, `readme`, `spec` 등
- 커밋 하나에는 변경 하나만 담습니다. 테스트와 구현은 같은 커밋에 넣어도 됩니다.

## PR → merge → 배포

| 단계 | 자동으로 일어나는 일 | 내가 할 일 |
|---|---|---|
| 1. 브랜치 | 없음 | 최신 `main`에서 브랜치를 만듦 |
| 2. 커밋 | 없음 (로컬 훅 없음) | [로컬 검사](#로컬-검사)를 통과시킴 |
| 3. push | 없음. push만으로는 CI가 돌지 않음 | `git push -u origin <브랜치>` (팀원은 write 권한으로 직접 push) |
| 4. PR (대상 `main`) | `ci-lint`가 실행됨 ([아래](#ci가-확인하는-것)). 필수 검사는 `lint-and-format-check`, `numpy-1x`, `docker-build` | 설명에 요약과 확인 방법을 적음. 핵심 파일을 바꿨다면 팀 합의를 받음. 실패하면 고쳐서 다시 push |
| 5. merge | `main` 보호 규칙:<br>- 필수 검사 통과와 최신 `main` 반영 전에는 머지 불가 (관리자 포함)<br>- 승인 1명 필요. 핵심 파일은 위 승인자 필요. 새로 push하면 기존 승인은 다시 받아야 함<br>- 강제 push와 브랜치 삭제 금지 | 리뷰를 받고 머지. 관리자 본인 PR은 승인 없이 머지할 수 있지만 검사는 똑같이 통과해야 함. 머지 커밋 방식을 쓰고, 머지한 브랜치는 직접 지움 |
| 6. 배포 | `main`에 이미지에 들어가는 파일(`src/`, `web/`, `gpu/`, `docker/`, 의존성)이 반영되면 `publish-images`가 `audyssey-app`, `audyssey-tools`를 빌드해 GHCR에 `latest`와 커밋 SHA 태그로 올림 (수동 실행 가능, PR에서는 올리지 않음). 문서, 테스트, Compose만 바꾼 머지는 이미지를 올리지 않음 | [서버 갱신](#서버-갱신)대로 SHA 태그로 고정해 올림. RunPod은 Pod를 다시 만들 때 SHA 태그를 지정 |

이미지는 공개되어 있어 로그인 없이 받을 수 있습니다. tools 이미지는 약 23GB입니다.

## CI가 확인하는 것

`ci-lint`(`.github/workflows/ci-lint.yaml`)는 PR과 `main` push에서 job 4개를 실행합니다.

| job | 확인하는 것 | 필수 |
|---|---|---|
| `lint-and-format-check` | `src/`의 ruff lint·format, ty, `tests/` unittest. uv 다운로드 캐시를 `uv.lock` 기준으로 씀 | 예 |
| `numpy-1x` | Python 3.12 + numpy 1.26에서 unittest (GPU 환경과 같은 조건) | 예 |
| `docker-build` | 배포될 이미지가 실제로 실행되는지 확인. push와 캐시 쓰기는 없음 | 예 |
| `web` | Node 22에서 `npm ci`, `npm test`, `npm run build` | 아니오 (현재 보호 규칙에 없음) |

`docker-build`의 두 이미지 검사:
- **app**: 빌드한 이미지를 컨테이너로 띄워 uid가 10001인지, `GET /api/jobs`가 JSON을 돌려주는지, `GET /`이 빌드된 화면(`/assets` 참조)이고 그 asset이 내려오는지 봅니다.
- **tools**: 이미지가 크기 때문에 Docker에 올리지 않고 빌드 안의 `smoke` 단계(`docker/tools_smoke.py`)가 `import torch, audyssey`와 stub tool-server(`/health`의 도구 4개, 틀린 토큰은 401)를 검사합니다. GPU는 쓰지 않습니다. `docker/tools.*`, `gpu/`, `src/`, `pyproject.toml`, `uv.lock`, `ci-lint.yaml`이 바뀐 PR에서만 돕니다.

## 이미지 빌드 캐시

- Dockerfile은 바뀌는 빈도가 낮은 것부터 레이어를 쌓습니다. 의존성(`pyproject.toml`, `uv.lock`, `gpu/`)을 먼저 설치하고, `src/`와 웹 빌드 결과는 마지막에 `COPY --link`로 복사합니다. 그 뒤에는 실행 단계가 없습니다.
- 그래서 `src/`만 바꾼 `publish-images`는 캐시된 의존성 레이어(tools는 압축 약 7GB)를 내려받지 않고 바뀐 레이어만 올립니다. `web/`만 바꾸면 app 이미지의 Node 단계와 마지막 복사 레이어만 다시 만듭니다.
- 레지스트리 캐시는 `audyssey-app:buildcache`, `audyssey-tools:buildcache` 태그에 씁니다(실행 가능한 이미지가 아님). 캐시 레이어만 zstd로 압축하고, 배포되는 `latest`와 SHA 이미지는 gzip 레이어입니다.
- `docker-build`는 같은 캐시를 읽기만 합니다. 다만 tools의 `smoke` 단계는 이미지 안에서 실행되므로 의존성 레이어를 매번 내려받습니다. 그래서 PR 검사는 `src/`만 바꿔도 수 분이 걸립니다.
- 의존성이나 Dockerfile을 바꾼 PR은 push마다 `docker-build`가 전체 빌드(tools 약 10~12분)를 합니다(PR은 캐시를 쓰지 않음). 머지 뒤 `publish-images`의 첫 실행이 캐시를 새로 채웁니다.

## 서버 갱신

공용 GPU 서버는 `latest`가 아니라 확인한 커밋의 이미지로 고정합니다. `latest`는 머지할 때마다 바뀌므로, 그대로 받으면 확인하지 않은 이미지가 올라갈 수 있습니다.

1. `.env`의 `AUDYSSEY_IMAGE_TAG`에 머지 커밋의 전체 SHA를 넣습니다. 비우면 `latest`를 씁니다.
2. 이미지를 받고 띄웁니다. `compose.tools.yaml`로 도구만 띄웠다면 `-f compose.tools.yaml`을 붙입니다.
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
# web job과 같은 검사 (Node 20.19 이상)
(cd web && npm ci && npm test && npm run build)
```

비밀값 없이 Compose 파일만 검사하려면:

```bash
for f in compose.yaml compose.tools.yaml; do
  env -i PATH="$PATH" docker compose --env-file .env.example -f "$f" config --no-env-resolution --quiet
done
```
