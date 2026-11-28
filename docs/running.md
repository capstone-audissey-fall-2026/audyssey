# 실행 방법

[README](../README.md)의 "어떻게 실행하나" 표에서 고른 방식별 절차입니다. 기능 수정과 실험은 1번(stub)으로 하고, GPU는 실제 모델 통합 테스트 때만 빌려 쓴 뒤 바로 반납합니다.

| 방식 | main(화면) | GPU 도구 | GPU |
|---|---|---|---|
| [1. GPU 없이 stub](#1-gpu-없이-stub) | 내 컴퓨터 | stub | 없음 |
| [2. 한 GPU 서버에서 전부](#2-한-gpu-서버에서-전부-composeyaml) | 서버 | 서버의 컨테이너 | 1장(80GB면 컨테이너 6개가 한 장에 들어감) |
| [3. 로컬 app + 원격 GPU tools](#3-로컬-app--원격-gpu-tools) | 내 컴퓨터 | RunPod Pod 또는 GPU 서버의 컨테이너 1개 | 48GB 이상 1장 |

## 1. GPU 없이 stub

```bash
uv sync --extra ui
(cd web && npm ci && npm run build)   # Node 20.19 이상 (22 권장). 건너뛰면 `/`에 이전 단일 파일 화면이 뜹니다
uv run audyssey serve                 # http://127.0.0.1:8600 에서 samples/sample.mp4를 열고 Separate 누르기
```

- 모든 도구가 stub입니다. 결과는 가짜이므로 품질 평가에는 쓰지 않습니다.
- 8600 포트가 사용 중이면 `--port 8601`처럼 바꿉니다. 끌 때는 Ctrl+C를 누르며, 작업 파일은 `work/jobs`에 남습니다.
- 화면 경로: `/`는 `web/`의 React 앱(`src/audyssey/webui/`가 있을 때), `/legacy`는 이전 단일 파일 화면, `/dev`는 개발용 화면입니다.
- 화면 개발: `cd web && npm run dev`(http://localhost:5173)는 `/api`를 `127.0.0.1:8600`으로 프록시하므로 `audyssey serve`를 먼저 띄웁니다. 웹 테스트는 `npm test`입니다.
- 무음 영상: `ffmpeg -i samples/sample.mp4 -an -c:v copy /tmp/silent.mp4`로 만들어 올리면 대사는 화면의 "Skipped by the plan check"에 소스 이름으로 나열되고 generation만 돕니다.
- 코드를 고친 뒤에는 [로컬 검사](contributing.md#로컬-검사)를 돌립니다. 단위 테스트도 GPU 없이 돕니다.

| 도구 | stub 동작 |
|---|---|
| 플래너 | 고정된 소스 4개(대사 2, 효과음 2)를 영상 길이 비율로 냄. 검증에서 하나를 지적받아 한 번 다시 계획 |
| 분리 | 계획 구간의 원본 오디오를 그대로 잘라 냄 |
| Judge | `character_a`를 한 번 불합격시켜 재분리 루프를 돌게 함 |
| 생성·채점 | 설명에서 정한 주파수의 사인파를 영상 가운데 최대 1초에 넣음. `sword_clash`만 기본 seed에서 진폭 0.1로 불합격하고 다음 seed는 0.2로 합격. 나머지는 바로 합격. 형제가 없으면 margin을 생략 |
| 그라운딩 | 시각 힌트를 켰을 때만 호출됨. 힌트 상자를 그대로 고정 마스크로 씀 (추적 없음) |

일부만 실제로 바꾸려면 바꿀 것만 환경변수로 지정하고 나머지는 stub으로 둡니다. 플래너만 실제로 쓰려면(GPU 불필요) [플래너 연결](#플래너-연결)의 설정에 `AUDYSSEY_PLANNER=real`을 더합니다. 내 GPU 도구만 실제로 쓰려면 [모듈 개발](#모듈-개발-내-도구만-gpu로)을 봅니다.

## 가중치 준비

2번과 3번을 하기 전에 사람마다, 캐시마다 한 번 합니다. 서버는 실행 중에 아무것도 내려받지 않고 `HF_HOME` 캐시를 오프라인(`HF_HUB_OFFLINE=1`)으로만 읽으므로 가중치를 미리 받아 둡니다. 가중치는 레포와 이미지에 들어 있지 않습니다.

1. **Hugging Face 계정**으로 `facebook/sam-audio-large-tv`, `facebook/sam-audio-judge`, `facebook/sam3.1` 페이지에서 접근 승인(SAM License)을 요청합니다. 하루 정도 걸릴 수 있습니다.
2. **팀 HF 조직 `sogang-audyssey`에 가입**합니다. 관리자에게 HF 아이디를 알리고 초대를 수락합니다. 생성 모델 가중치(`sogang-audyssey/internal-model`)는 비공개라 조직 멤버만 받을 수 있습니다.
3. HF 설정 → Access Tokens에서 **읽기(Read) 토큰**을 만듭니다. 가중치를 받을 때만 쓰고 레포, `.env`, 이미지, 채팅에 넣지 않습니다.
4. 받습니다. 모든 줄이 `ok`로 끝나야 하고, 403이면 1·2번이 아직 끝나지 않은 것입니다.
   ```bash
   uv tool install 'huggingface_hub[cli]<1.0'   # 또는 pip install 'huggingface_hub[cli]<1.0'
   huggingface-cli login                          # 3번의 읽기 토큰
   HF_HOME=<캐시 경로> bash scripts/download-weights.sh   # vLLM 플래너도 쓰면 앞에 WITH_VLLM=1
   ```

> sv3-a100에서는 1~4번을 건너뜁니다. 공용 캐시 `/home/common/huggingface`에 공식 모델과 미러가 모두 있으므로 복사하지 말고 `HF_CACHE`로 그대로 연결합니다.

받을 목록은 [`scripts/download-weights.sh`](../scripts/download-weights.sh) 하나에 있습니다.

| 모델 | 설정 | 캐시에 필요한 것 |
|---|---|---|
| 분리 | `AUDYSSEY_SAM_AUDIO_MODEL` | `facebook/sam-audio-large-tv`, `t5-base` |
| 필터링 | `AUDYSSEY_SAM_AUDIO_JUDGE_MODEL` | `facebook/sam-audio-judge`의 `sam_audio` revision 전체, `main` revision의 JSON(설정·토크나이저, 약 2MB) |
| 그라운딩 | `AUDYSSEY_SAM3_MODEL` | `facebook/sam3.1`의 `config.json`, `sam3.1_multiplex.pt` |
| 생성 | `AUDYSSEY_GEN_BASE_MODEL` / `AUDYSSEY_GEN_MODEL` | 공개 베이스 3개 + 내부 모델 2개, DFN5B CLIP·flan-t5·BigVGAN·CLAP·roberta-base |
| 후보 고르기 (선택) | 후보 2개 이상 | `lukewys/laion_clap`의 `630k-best.pt`, `roberta-base`, `bert-base-uncased`, `facebook/bart-base` |
| 플래너 (선택) | `AUDYSSEY_VLLM_MODEL` | `Qwen/Qwen2.5-VL-3B-Instruct` |

- 승인을 기다리는 동안에는 비공식 미러 `mrfakename/sam-audio-large-tv`, `mrfakename/sam-audio-judge`를 모델 ID로 쓸 수 있습니다. 미러도 사용 권한을 확인해야 하고, 미러 Judge는 `sam_audio` 브랜치의 `checkpoint.pt`가 캐시에 있어야 합니다.
- 생성 모델의 공개 베이스 코드는 라이선스 표시가 없어 레포에 복사하지 않고 고정 커밋 의존성으로 설치합니다. 가중치 라이선스는 CC-BY-NC-SA-4.0입니다.

## 2. 한 GPU 서버에서 전부 (compose.yaml)

main, separation, judge, grounding, generation, vllm 컨테이너 6개를 한 서버에서 띄웁니다. 필요한 것: Docker, [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html), 디스크 약 100GB(이미지 약 60GB + 가중치 약 45GB). 이미지는 공개라서 로그인 없이 받고, 직접 빌드하지 않습니다.

**설정 (처음 한 번)**
```bash
git clone https://github.com/capstone-audissey-fall-2026/audyssey.git && cd audyssey
cp .env.example .env && chmod 600 .env    # .env는 커밋하지 않음
```
`.env`에서 고칩니다.
- `AUDYSSEY_TOOL_TOKEN`: 긴 임의 값 (`openssl rand -hex 24`)
- `HF_CACHE`: 가중치 캐시 경로 (sv3는 `/home/common/huggingface` 그대로)
- `AUDYSSEY_{SEPARATION,JUDGE,GROUNDING,GENERATION,VLLM}_GPU`: 쓸 GPU 번호. 공용 서버에서는 `nvidia-smi`로 **아무 프로세스도 없는 GPU**를 골라 다섯 줄을 같은 번호로 둡니다. 다른 사람이 쓰는 GPU에 올리면 메모리가 부족해 서로의 작업이 죽을 수 있습니다. 번호가 같으면 그 GPU를 나눠 씁니다.
- Gemini 플래너를 쓰면 `GOOGLE_API_KEY=<키>`도 넣습니다.

**띄우기**
```bash
docker compose pull           # 새 이미지 받기 (main이 갱신될 때마다 바뀜)
docker compose up -d          # 컨테이너 6개를 백그라운드로 실행
docker compose logs -f vllm   # "Application startup complete"가 뜨면 준비 끝(약 1~2분). Ctrl+C는 로그 보기만 멈춤
```
Gemini 플래너를 쓰면 vLLM 없이 띄웁니다.
```bash
AUDYSSEY_PLANNER_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/ \
AUDYSSEY_PLANNER_MODEL=gemini-3.5-flash-lite \
docker compose up -d main separation judge grounding generation
```

**확인**
- 서버에서 http://localhost:8600, 원격 서버라면 노트북에서 `ssh -L 8600:localhost:8600 <서버>`를 연 뒤 같은 주소로 접속합니다.
- `samples/sample.mp4`를 열고 Separate를 눌러(무음 영상이면 Generate) 끝나는지 봅니다. 업로드만으로는 전처리까지만 돌고 Separate나 Generate를 눌러야 시작합니다. 끝나면 대사가 아닌 트랙에서 "Generate instead"를 눌러 봅니다. 첫 작업은 모델을 GPU에 올리느라 2~3분 걸립니다.
- 로그: `docker compose logs -f main separation judge generation`

**내리기 (끝나면 꼭)**
```bash
docker compose down   # 컨테이너를 지우고 GPU 메모리를 돌려줌
nvidia-smi            # 메모리가 비었는지 확인
```
`up -d`로 띄운 컨테이너는 Ctrl+C로 꺼지지 않습니다. 작업 결과(`jobs` 볼륨)와 이미지는 남습니다.

**참고**
- 호스트에는 main의 `127.0.0.1:8600`만 열립니다. main에는 인증이 없으므로 `127.0.0.1` 밖으로 열지 말고 원격에서는 SSH 터널을 씁니다. 꼭 열어야 하면 인증이 있는 리버스 프록시를 앞에 둡니다.
- `.env.example`은 GPU 0 한 장을 나눠 쓰는 설정이고 `AUDYSSEY_VLLM_GPU_UTIL=0.2`입니다(80GB A100 한 장에서 기본 설정 실측 46.1GB, 후보 4개면 56.6GB). vLLM에 GPU를 따로 주면 `0.85` 정도로 올립니다.
- 도구 컨테이너 4개는 같은 `audyssey-tools` 이미지를 실행 명령만 바꿔 씁니다. 컨테이너는 uid 10001로 실행되고, 가중치 캐시는 `/hf`에 읽기 전용으로 붙습니다.
- 플래너 기본값은 Compose 안의 vLLM(`Qwen/Qwen2.5-VL-3B-Instruct`)입니다. GPU 없이 main만 띄우려면 `AUDYSSEY_PLANNER=stub`과 도구 stub(또는 원격 주소)을 설정하고 `docker compose up main`을 실행합니다.
- 직접 빌드할 때는 `docker compose build`입니다. sv3-a100은 기본 빌드 엔진이 설정 문제로 실패하므로 `docker buildx --builder <docker-container 빌더>`를 씁니다.

## 3. 로컬 app + 원격 GPU tools

도구 서버 하나(컨테이너 1개)가 분리, Judge, 그라운딩, 생성 4개를 모두 처리하므로 연결할 주소도 하나입니다. 도구 서버는 RunPod Pod 또는 `compose.tools.yaml`을 쓰는 GPU 서버에서 띄우고, main은 내 컴퓨터에서 돌립니다. RunPod Pod 안에서는 Docker Compose를 쓸 수 없어서 이렇게 나눕니다.

### 3-1. 도구 서버 띄우기

**RunPod Pod**

처음 한 번, 가중치용 네트워크 볼륨을 만듭니다(팀에서 한 번만).
1. RunPod → Storage → New Network Volume. 60GB 이상(vLLM 플래너 가중치까지면 70GB), GPU를 빌릴 데이터센터와 같은 곳을 고릅니다.
2. 이 볼륨을 붙인 아무 저렴한 Pod(공식 PyTorch 템플릿 등)를 만들고 [가중치 준비](#가중치-준비)의 1~3번을 마친 뒤 웹 터미널에서 4번을 합니다. 볼륨은 `/workspace`에 붙습니다.
   ```bash
   pip install 'huggingface_hub[cli]<1.0' && huggingface-cli login
   git clone https://github.com/capstone-audissey-fall-2026/audyssey.git /tmp/audyssey
   HF_HOME=/workspace/huggingface bash /tmp/audyssey/scripts/download-weights.sh
   huggingface-cli logout        # 볼륨에 토큰을 남기지 않음
   ```
3. 받은 뒤 이 Pod는 지웁니다. 볼륨은 남습니다.

처음 한 번, Templates → New Template을 만듭니다([공식 안내](https://docs.runpod.io/pods/templates/manage-templates)).

| 항목 | 값 |
|---|---|
| Container image | `ghcr.io/capstone-audissey-fall-2026/audyssey-tools:latest` (공개, 로그인 불필요) |
| Container start command | 비워 둠 (이미지 기본 명령이 도구 4개를 함께 실행) |
| Expose HTTP ports | `8700` |
| 환경변수 | `HF_HOME=/workspace/huggingface`, `HF_HUB_OFFLINE=1`, `CUDA_VISIBLE_DEVICES=0` |
| 비밀값 | `AUDYSSEY_TOOL_TOKEN`은 공유 템플릿에 직접 쓰지 말고 RunPod Secrets에 만들어 `{{ RUNPOD_SECRET_이름 }}`으로 연결 |

쓸 때마다: 템플릿과 네트워크 볼륨으로 GPU Pod를 만듭니다(48GB 이상, 시각 힌트를 켜면 80GB, CUDA 12.8 이상 드라이버). Pod 로그에 `Uvicorn running on http://0.0.0.0:8700`이 뜨면 준비 끝입니다. 주소는 `https://<POD-ID>-8700.proxy.runpod.net`입니다. 끝나면 **Pod를 Stop/Terminate**합니다. 켜 둔 시간만큼 요금이 나가고 볼륨은 남습니다.

**GPU 서버 (`compose.tools.yaml`)**

서버에는 vLLM과 main 없이 도구 컨테이너 1개만 올라갑니다. `.env`는 2번과 같이 만들고(`AUDYSSEY_TOOL_TOKEN`, `HF_CACHE` 필요) 아래 값을 고릅니다.

| 변수 | 기본값 | 뜻 |
|---|---|---|
| `AUDYSSEY_TOOLS_GPU` | `0` | 쓸 GPU 번호. 공용 서버에서는 아무 프로세스도 없는 GPU |
| `AUDYSSEY_TOOLS_PORT` | `8700` | 호스트 포트 |
| `AUDYSSEY_TOOLS_BIND` | `127.0.0.1` | 바인드 주소. 기본은 이 서버만 |

```bash
docker compose -f compose.tools.yaml up -d
curl localhost:8700/health   # {"tools":["separation","filtering","grounding","generation"],"impl":"real"}
docker compose -f compose.tools.yaml down   # 끝나면
```

- 토큰(`AUDYSSEY_TOOL_TOKEN`)이 없으면 시작하지 않습니다.
- 토큰은 평문 HTTP로 오가므로 노트북에서 `ssh -L 8700:localhost:8700 <서버>` 터널을 여는 방식을 권합니다. 터널은 노트북의 127.0.0.1에서만 받으므로, main을 `uv run`으로 띄울 때만 주소 `http://localhost:8700`이 통합니다(3-2). Docker main의 `localhost`는 컨테이너 자신이라 연결되지 않습니다.
- `AUDYSSEY_TOOLS_BIND=0.0.0.0`으로 직접 공개할 수도 있지만, Docker가 공개한 포트는 `ufw` 같은 호스트 방화벽의 INPUT 규칙을 거치지 않아 막을 수 없습니다. 신뢰하는 사설 네트워크에서만 쓰고, 그 밖에서는 TLS 프록시를 앞에 둡니다.
- 2번의 전체 구성과 함께 올리면 같은 모델이 GPU에 두 번 올라가므로 하나만 띄웁니다.

### 3-2. 내 컴퓨터에서 app 띄우고 연결하기

1. 레포를 받고 `cp .env.example .env`를 한 뒤, 플래너를 `.env`에 설정합니다(Gemini 예). 플래너를 쓰지 않고 도구만 시험하려면 `AUDYSSEY_PLANNER=stub`을 둡니다.
   ```dotenv
   AUDYSSEY_PLANNER_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
   AUDYSSEY_PLANNER_MODEL=gemini-3.5-flash-lite
   GOOGLE_API_KEY=<키>
   ```
2. main만 띄웁니다. 이 컴퓨터에는 GPU가 필요 없습니다.
   ```bash
   docker compose up -d main    # http://localhost:8600
   ```
   Docker 없이 쓰려면 1번처럼 화면을 빌드한 뒤 아래처럼 띄웁니다(`uv run`은 `.env`를 자동으로 읽지 않으므로 `--env-file`이 필요하고, 플래너에는 `llm`이 필요함). SSH 터널로 연결할 때는 이 방법을 씁니다.
   ```bash
   uv run --extra ui --extra llm --env-file .env audyssey serve    # http://localhost:8600
   ```
   이 방법에서는 `.env`에 아래 모드도 있어야 합니다. 값이 없으면 stub이 기본이라 오류 없이 가짜 결과가 나옵니다. 화면의 **GPU tools**로 연결하면 모드는 자동으로 remote가 됩니다.
   ```dotenv
   AUDYSSEY_PLANNER=real
   AUDYSSEY_PLANNER_API_KEY=<GOOGLE_API_KEY와 같은 값>    # Compose만 GOOGLE_API_KEY를 변환해 줌
   AUDYSSEY_SEPARATOR=remote
   AUDYSSEY_FILTER=remote
   AUDYSSEY_GROUNDER=remote
   AUDYSSEY_GENERATOR=remote
   ```
3. 도구 서버에 연결합니다. 방법은 둘 중 하나입니다.

| 방법 | 어떻게 | 적용 |
|---|---|---|
| 화면 | 영상 열기(Open video) 창의 **GPU tools**에 `Tools server URL`과 `Token`을 넣고 Save | 재시작 없이, 새 작업과 이후의 편집 명령부터 |
| `.env` | 아래 값을 넣고 `docker compose up -d main`을 다시 실행 | 재시작 후 |

```dotenv
# 주소 4개는 같은 값이고 토큰은 도구 서버와 같은 값 (SSH 터널 + uv run main이면 http://localhost:8700)
AUDYSSEY_TOOL_TOKEN=<도구 서버와 같은 토큰>
AUDYSSEY_SEPARATOR_URL=https://<POD-ID>-8700.proxy.runpod.net
AUDYSSEY_FILTER_URL=https://<POD-ID>-8700.proxy.runpod.net
AUDYSSEY_GROUNDING_URL=https://<POD-ID>-8700.proxy.runpod.net
AUDYSSEY_GENERATOR_URL=https://<POD-ID>-8700.proxy.runpod.net
```

**화면 연결 동작** (`GET`·`POST /api/gpu-tools`)
- URL을 저장하면 분리·Judge·그라운딩·생성 4개가 모두 이 서버로 연결(remote)됩니다. 도구 모드가 `stub`이나 `real`이어도 바뀌며, 응답의 `remote`로 확인합니다.
- 토큰칸을 비워 두면 저장된 토큰을 씁니다. URL을 비우고 저장하면 연결이 해제되어 환경변수 설정으로 돌아갑니다.
- 값은 앱 프로세스 메모리에만 있습니다. 앱을 다시 띄우면 사라지고 환경변수로 돌아가며, 저장한 값이 있으면 `.env`보다 우선합니다.
- 토큰은 어떤 응답에도 나오지 않고(`token_set`만 반환) 브라우저에도 저장하지 않습니다.
- URL은 `http(s)`이고 사용자 이름·비밀번호가 없어야 합니다(아니면 422). 작업이 실행 중이면 저장할 수 없습니다(409).
- 연결 상태는 화면의 서버 상태 막대에서 'Tool server (<호스트>)' 한 줄(점이 초록이면 /health 응답)과 'Servers n/m up'으로 봅니다. `/health`는 인증이 없어서 토큰이 틀려도 정상으로 보이고, 작업을 돌릴 때 `tool server <주소>/separate failed: 401`로 실패합니다.

끝나면 `docker compose down`을 실행하고 도구 서버 쪽도 내립니다.

## 모듈 개발 (내 도구만 GPU로)

SAM Audio가 numpy 1.x를 요구해서 GPU 도구는 별도 uv 프로젝트 `gpu/`에서 돌립니다. 루트 환경과 CI에는 torch가 없습니다. 내 도구만 real로 띄우고 main은 루트 환경에서 돌리며, 나머지 도구는 stub으로 둡니다.

```bash
uv sync --project gpu --locked
# torchcodec(cu128)가 쓰는 NVIDIA NPP 라이브러리 경로 (Docker 이미지에는 이미 설정됨)
export LD_LIBRARY_PATH="$PWD/gpu/.venv/lib/python3.12/site-packages/nvidia/npp/lib:${LD_LIBRARY_PATH:-}"
export HF_HOME=<가중치 캐시> HF_HUB_OFFLINE=1 CUDA_VISIBLE_DEVICES=0
export AUDYSSEY_TOOL_TOKEN=<임의 토큰>

# --tool은 separation | filtering | grounding | generation, 반복 가능
uv run --project gpu --locked audyssey tool-server --tool separation --impl real --host 127.0.0.1 --port 8700

# 다른 터미널: main은 루트 환경에서, 같은 AUDYSSEY_TOOL_TOKEN으로
AUDYSSEY_SEPARATOR=remote AUDYSSEY_SEPARATOR_URL=http://127.0.0.1:8700 uv run audyssey serve
```

- GPU 없이 HTTP 연결만 확인하려면 루트 환경에서 `--impl stub`으로 띄웁니다. 예: `AUDYSSEY_TOOL_TOKEN=local-test uv run audyssey tool-server --tool generation --impl stub --port 8701` 뒤 main에 `AUDYSSEY_GENERATOR=remote AUDYSSEY_GENERATOR_URL=http://127.0.0.1:8701`을 줍니다.
- `127.0.0.1` 밖 주소로 띄우려면 토큰이 있어야 하고, TLS 프록시나 SSH 터널로 보호합니다.
- 분리와 Judge만 따로 확인하는 스크립트는 로딩·실행 시간, 최대 GPU 메모리, 판정, 결과 WAV 경로를 JSON으로 출력합니다.
  ```bash
  uv run --project gpu --locked python scripts/sam_audio_smoke.py samples/sample.mp4 --description "a person speaking" --out work/jobs/smoke-text
  uv run --project gpu --locked python scripts/sam_audio_smoke.py samples/sample.mp4 --description "a person speaking" --span 0 3 --out work/jobs/smoke-span
  ```
- 생성 모듈은 같은 `gpu/` 환경과 가중치 캐시를 씁니다. 기본값은 `large_44k`, bf16, Euler 25회, CFG 4.5이고 설명만 사용합니다. CLAP 채점은 자기 설명이 가장 가깝고 margin이 임계값 이상이면 합격하며, 형제가 없으면 margin 없이 합격합니다. real 생성·채점은 `HF_HUB_OFFLINE=1`이 필수이고 GPU 호출은 한 번에 하나씩 실행합니다. 시간·메모리 실측은 [현재 상태](status.md)에 있습니다.

## 플래너 연결

플래너 real(`planning/real.py`)은 영상 전체를 보고 소스 목록을 만들고, 검증기(`validate_plan`)는 소스마다 그 소스의 구간만 보고 `present: true/false`를 판정합니다. 입력은 두 가지입니다.

- `frames`(기본): `AUDYSSEY_PLANNER_FPS`로 JPEG를 뽑아 보냅니다(최대 `AUDYSSEY_PLANNER_MAX_FRAMES`장, 넘으면 실제 fps가 낮아짐). 오디오는 보내지 않습니다.
- `video`: 영상을 가로 512px로 다시 인코딩해 보내고 모델이 `AUDYSSEY_PLANNER_FPS`로 샘플링합니다. `AUDYSSEY_PLANNER_VIDEO_AUDIO=true`면 오디오 트랙도 보냅니다.

검증기 모델은 `AUDYSSEY_VALIDATOR_*`로 따로 고르고, 비워 둔 값은 플래너 값을 씁니다. 검증 정책과 평가는 [planning.md](planning.md), 공급자별 모델과 비용은 [플래너 모델 조사](planner-models.md)에 있습니다.

| 대상 | 설정 |
|---|---|
| Gemini 영상 (Google SDK) | `AUDYSSEY_PLANNER_API=gemini`, `AUDYSSEY_PLANNER_INPUT=video`, `AUDYSSEY_PLANNER_MODEL=gemini-3.5-flash-lite`, `AUDYSSEY_PLANNER_FPS=1`, `AUDYSSEY_PLANNER_VIDEO_AUDIO=true`. 키는 `AUDYSSEY_PLANNER_API_KEY` (Compose에서는 `GOOGLE_API_KEY`를 넣으면 대신 전달). 클립을 Files API로 올리고 주소와 fps를 보낸 뒤 지웁니다. 주소는 SDK가 정하므로 `BASE_URL`은 쓰지 않습니다 |
| OpenRouter (Gemini, GPT 등) | `AUDYSSEY_PLANNER_API=openrouter`, `AUDYSSEY_PLANNER_BASE_URL=https://openrouter.ai/api/v1`, `AUDYSSEY_PLANNER_MODEL=google/gemini-...`, 키는 `AUDYSSEY_PLANNER_API_KEY`. `video` 입력은 영상 입력을 받는 모델만 됩니다. Gemini로 실측하면 영상 속 소리는 전달되고 fps는 지정할 수 없어 1fps로 들어갑니다. GPT처럼 영상을 받지 않는 모델은 `frames` |
| Gemini 프레임 (OpenAI 호환) | `AUDYSSEY_PLANNER_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/`, `AUDYSSEY_PLANNER_MODEL=gemini-3.5-flash-lite`. 이 엔드포인트는 영상을 받지 않습니다 |
| OpenAI | `AUDYSSEY_PLANNER_BASE_URL=https://api.openai.com/v1`, `AUDYSSEY_PLANNER_MODEL=<모델 ID>`, 키는 `AUDYSSEY_PLANNER_API_KEY`. 영상을 받지 않으므로 `frames`만 씁니다 |
| 직접 띄운 vLLM | `AUDYSSEY_PLANNER_BASE_URL=http://<vllm>:8000/v1`, `AUDYSSEY_PLANNER_MODEL=<모델 ID>`. 인증 없는 서버면 키 생략. `video` 입력은 서버를 `--trust-request-mm-kwargs`로 띄워야 fps가 적용됩니다 |
| Compose 안의 vLLM | 기본값. `vllm/vllm-openai:v0.32.0` + `Qwen/Qwen2.5-VL-3B-Instruct` (캐시 필요). `video` 입력 가능. 오디오(`AUDYSSEY_PLANNER_VIDEO_AUDIO=true`)는 Qwen-Omni 모델만 |

`uv run audyssey serve`는 `.env`를 읽지 않습니다. 환경변수로 넘기거나 `uv run --env-file .env ...`를 씁니다.

검수기만 vLLM의 Qwen2.5-Omni로 두는 예입니다(Compose에 없으므로 따로 띄움).
```bash
docker run -d --name validator-vllm --gpus '"device=0"' --user 10001:10001 \
  -e HF_HUB_OFFLINE=1 -e HF_HOME=/hf -e HOME=/tmp/vllm -v "$HF_CACHE:/hf:ro" \
  --network audyssey_default vllm/vllm-openai:v0.32.0 \
  --model Qwen/Qwen2.5-Omni-3B --gpu-memory-utilization 0.35 --max-model-len 16384 \
  --trust-request-mm-kwargs
# .env: AUDYSSEY_VALIDATOR_BASE_URL=http://validator-vllm:8000/v1, AUDYSSEY_VALIDATOR_MODEL=Qwen/Qwen2.5-Omni-3B,
#       AUDYSSEY_VALIDATOR_API=openai, AUDYSSEY_VALIDATOR_API_KEY=unused, AUDYSSEY_VALIDATOR_INPUT=video, AUDYSSEY_VALIDATOR_VIDEO_AUDIO=true
```

## 실행 기록 보기 (LangSmith, Studio)

`.env` 또는 환경변수에 넣으면 그래프 실행, 도구 호출, 명령, LLM 토큰 사용량이 기록됩니다. 기본은 꺼져 있고, 끌 때는 `LANGSMITH_TRACING=false`입니다.

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=<개인 키>
LANGSMITH_PROJECT=audyssey
```

- [smith.langchain.com](https://smith.langchain.com) → Tracing의 `audyssey` 프로젝트에서 봅니다. 프로젝트는 첫 기록 때 생깁니다.
- 오디오·영상·프레임 데이터와 키·토큰은 올리지 않습니다. 파일 경로와 메타데이터만 남기고, 플래너 LLM 기록에는 모델명과 토큰 사용량만 남깁니다.

**Studio에서 그래프 보기.** `langgraph.json`의 `audyssey` 그래프(`src/audyssey/studio.py:graph`)는 앱의 `analyze()`와 같은 `build_graph()`를 씁니다. 처음 연결은 stub으로 확인합니다.

```bash
# .env: LANGSMITH_API_KEY와 AUDYSSEY_{PLANNER,SEPARATOR,FILTER,GROUNDER,GENERATOR}=stub, AUDYSSEY_VISUAL_PROMPT=false
uv run --locked --env-file .env --extra ui --extra llm audyssey serve    # 영상을 올리고 /api/jobs에서 작업 id 확인
# 다른 터미널 (CLI와 Agent Server는 uv 임시 환경에 설치됨)
uv run --locked --extra ui --extra llm --with "langgraph-cli[inmem]==0.4.43" --with "langgraph-api==0.18.1" langgraph dev
```

Studio 주소(Agent Server 기본 `http://127.0.0.1:2024`)에서 `audyssey`를 선택하고 `{"job_id": "<12자리 작업 id>", "method": "separate"}`를 입력합니다. `method`가 `null`이면 전처리, `"generate"`면 generation 경로입니다. API와 Studio의 `AUDYSSEY_WORK_DIR`를 같게 하고, 한 작업의 실행이 끝난 뒤 다음 실행이나 앱 편집을 시작합니다.

## 설정 표

설정은 `AUDYSSEY_*` 환경변수로만 읽습니다(`src/audyssey/settings.py`). 새 설정을 만들면 이 표에 한 줄을 추가합니다.

**도구 선택과 연결**

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `AUDYSSEY_PLANNER` | `stub` | `stub` 또는 `real` (Compose 기본 `real`) |
| `AUDYSSEY_SEPARATOR` / `AUDYSSEY_FILTER` / `AUDYSSEY_GROUNDER` | `stub` | `stub`, `real`, `remote` (Compose 기본 `remote`) |
| `AUDYSSEY_GENERATOR` | `stub` | 생성·채점 도구. `stub`, `real`, `remote` (Compose 기본 `remote`) |
| `AUDYSSEY_SEPARATOR_URL` / `AUDYSSEY_FILTER_URL` / `AUDYSSEY_GROUNDING_URL` / `AUDYSSEY_GENERATOR_URL` | 빈 값 | remote 도구 서버 주소. remote인데 비어 있으면 시작할 때 오류 (Compose 기본 `http://separation:8700` 등) |
| `AUDYSSEY_TOOL_TOKEN` | 빈 값 | 도구 서버 Bearer 토큰. main과 도구 서버에 같은 값 |
| `AUDYSSEY_REMOTE_TIMEOUT_S` | `600` | 원격 도구 호출 제한 시간(초) |
| `AUDYSSEY_VISUAL_PROMPT` | `false` | 시각 힌트 사용. 켜면 계획 검증에서 SAM3 `locate`, 분리 전 `mask_video`를 실행하고 마스크 영상을 분리에 넣음 |
| `AUDYSSEY_ROUTER` | `stub` | `stub`, `real` 또는 `hybrid`. 자연어 편집 요청을 명령으로 바꾸는 라우터 |

**플래너와 검수기**

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `AUDYSSEY_PLANNER_BASE_URL` / `_MODEL` / `_API_KEY` | 빈 값 | OpenAI 호환 플래너 주소, 모델, 키 |
| `AUDYSSEY_PLANNER_API` | `openai` | `openai`(Chat Completions: OpenAI, vLLM, Gemini OpenAI 호환), `gemini`(Google SDK, `video` 입력만) 또는 `openrouter`(OpenRouter Chat Completions, vLLM 전용 옵션 없이 보냄) |
| `AUDYSSEY_PLANNER_INPUT` | `frames` | `frames`(이미지 여러 장) 또는 `video`(영상 하나) |
| `AUDYSSEY_PLANNER_FPS` | `1` | `frames`면 프레임을 뽑는 fps, `video`면 모델이 샘플링하는 fps (0 초과~30) |
| `AUDYSSEY_PLANNER_MAX_FRAMES` | `32` | `frames` 입력에서 한 요청에 보내는 최대 프레임 수 (1~256, 검증기도 같은 값) |
| `AUDYSSEY_PLANNER_VIDEO_AUDIO` | `false` | `video` 입력에 오디오 트랙 포함 (Gemini, OpenRouter의 Gemini, vLLM Qwen-Omni) |
| `AUDYSSEY_VALIDATOR_API` / `_BASE_URL` / `_MODEL` / `_API_KEY` / `_INPUT` / `_FPS` / `_VIDEO_AUDIO` | 플래너 값 | 검증기 모델과 입력. 뜻은 같은 이름의 `AUDYSSEY_PLANNER_*`와 같고, 비우면 플래너 값을 씀 |
| `AUDYSSEY_VALIDATOR_AUDIO` | (비움) | 검증기가 오디오 입력을 받는지 선언. `true`면 오디오 검수, `false`면 시각 검수. 비우면 `INPUT=video`와 `VIDEO_AUDIO=true`일 때만 오디오 검수 |
| `AUDYSSEY_VALIDATOR_CONTEXT_S` | `0.5` | 검수 대상 앞뒤 문맥 길이(초, 0~5). 영상 경계로 제한하고 겹치는 클립은 병합. 실제 판정 대상 구간은 별도로 전달 |
| `AUDYSSEY_VALIDATOR_AUDIO_ONLY` | `true` | 분리 검수에서 영상 대신 원본 오디오의 PCM WAV 문맥 구간을 전달. 영상에 의한 소리 추측을 줄임. `false`는 영상+오디오 검수 비교용. 생성 검수는 계속 영상/프레임 사용 |

real 분리 검수는 오디오를 듣는 검수기(오디오를 지원하는 모델과 `INPUT=video`, `VIDEO_AUDIO=true`)면 오디오로, 오디오 입력이 없는 검수기(frames 입력 등)면 시각 검수로 합니다. 시각 검수에서는 시각 힌트가 있는 소스만 검수하고, 시각 힌트가 없는 music·ambience 소스는 `not_validated`로 표시합니다. 재시도 뒤에도 확인되지 않은 소스는 GPU 처리에서 제외합니다. `validation_unavailable`은 원본 오디오가 없는 작업에만 씁니다. 기본 vLLM과 Gemini frames 설정도 시각 검수로 동작합니다. generation은 장면 적합성을 확인하므로 이미지 검수도 가능합니다. 자세한 정책과 평가 명령은 [planning.md](planning.md)를 봅니다.

**라우터** (`AUDYSSEY_ROUTER`가 `real` 또는 `hybrid`일 때)

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `AUDYSSEY_ROUTER_API` / `_BASE_URL` / `_MODEL` / `_API_KEY` | 플래너 값 | 라우터 모델(hybrid에서는 값 채우기 단계). 뜻은 같은 이름의 `AUDYSSEY_PLANNER_*`와 같고, 비우면 플래너 값을 씀. API는 `openai` 또는 `openrouter`만 가능(`gemini`면 시작할 때 오류) |
| `AUDYSSEY_ROUTER_REASONING_EFFORT` | (비움) | `none`/`low`/`medium`/`high`. 비우면 보내지 않음. Gemini(OpenAI 호환)에서 `none`이면 thinking을 꺼 지연이 줄어듦 |
| `AUDYSSEY_ROUTER_FORMAT` | `tools` | `tools` 또는 `json_schema`. `tools`는 명령마다 함수 하나를 주고 모델이 하나를 호출(function calling), `json_schema`는 구조화 출력으로 JSON 하나를 받음. 비교용으로 남겨 둠 |
| `AUDYSSEY_ROUTER_DECISION_URL` | (비움) | `hybrid`일 때 필수. 결정 모델 서버 주소(`POST <url>/v1/systemone`). hybrid는 결정 모델이 명령 종류와 대상 소스를 고르고, 라우터 모델은 값(gain, 음높이, add_source 계획)이 필요한 명령에만 도구 하나로 호출함 |
| `AUDYSSEY_ROUTER_DECISION_MODEL` | `h2o-lightning-4b` | 실행 이름과 캐시 키에만 쓰는 결정 모델 이름. 서버로 보내지 않음 |
| `AUDYSSEY_ROUTER_HYBRID_ESCAPE` | `false` | 켜면 값 채우기 단계에 `clarify(missing_value)` 도구를 함께 줌. 캐시 키가 달라짐 |
| `AUDYSSEY_ROUTER_GUARD` | `false` | 켜면 작업이 실행할 수 없는 명령을 되묻기(clarify)로 바꿈 |

**흐름과 작업**

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `AUDYSSEY_MAX_PLAN_ROUNDS` | `2` | 플래닝 최대 횟수 |
| `AUDYSSEY_MAX_SEPARATION_RETRIES` | `2` | 소스마다 다시 분리하는 횟수 (총 시도 = 1 + 이 값) |
| `AUDYSSEY_JUDGE_PASS_THRESHOLD` | `3.0` | Judge overall 합격 기준(점수는 1~5). 실측으로 정한 값이며 [보정 기록](status.md#judge-합격-기준-보정-2026-11-27)에 있음. 앱이 판정 서버가 돌려준 점수로 판정하므로 **앱의 값**이 쓰임 |
| `AUDYSSEY_MAX_DURATION_S` | `30` | 업로드 영상 길이 상한(초) |
| `AUDYSSEY_MAX_UPLOAD_MB` | `200` | 업로드 파일 크기 상한. main과 도구 서버 모두 적용, 넘으면 413 |
| `AUDYSSEY_WORK_DIR` | `work/jobs` | 작업 폴더 |

**분리·Judge·그라운딩 모델**

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `AUDYSSEY_SAM_AUDIO_MODEL` | `facebook/sam-audio-large-tv` | 분리 모델 |
| `AUDYSSEY_SAM_AUDIO_JUDGE_MODEL` | `facebook/sam-audio-judge` | Judge 모델. 필터링과 후보 고르기에 씀 |
| `AUDYSSEY_SAM_AUDIO_DEVICE` | `cuda` | 분리와 Judge를 돌릴 장치 |
| `AUDYSSEY_SAM_AUDIO_RERANKING_CANDIDATES` | `1` | 분리 후보 수. 2 이상이면 그 수만큼 후보를 만들고 CLAP×5 + Judge×1 점수로 하나를 고름 |
| `AUDYSSEY_SAM_AUDIO_CLAP_CHECKPOINT` | 빈 값 | 후보 고르기용 CLAP 파일. 비우면 캐시의 `lukewys/laion_clap` 630k-best |
| `AUDYSSEY_SAM_AUDIO_IMAGEBIND_CHECKPOINT` | 빈 값 | 시각 힌트 소스의 후보 고르기용 ImageBind 파일. 비우면 쓰지 않음. Compose에서는 파일을 separation 컨테이너에 따로 마운트해야 함 |
| `AUDYSSEY_SAM_AUDIO_PREDICT_SPANS` | `false` | 구간이 없을 때 모델이 구간을 예측 (span predictor를 GPU에 추가로 올림) |
| `AUDYSSEY_SAM3_MODEL` / `AUDYSSEY_SAM3_DEVICE` | `facebook/sam3.1` / `cuda` | 그라운딩 모델과 장치 (CUDA 전용) |
| `AUDYSSEY_SAM3_TRACK_FPS` | `2` | 마스크 추적 fps. `0`이면 원본 fps (24GB GPU에서는 메모리 부족 위험) |

**생성 모델**

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `AUDYSSEY_GEN_SEED` | `42` | 첫 생성 seed. 다시 생성할 때 누적 attempts로 증가 |
| `AUDYSSEY_MAX_GENERATION_RETRIES` | `2` | 루프마다 최대 재시도 수(0 이상). 총 시도는 1 + 이 값 |
| `AUDYSSEY_GENERATION_MARGIN_THRESHOLD` | `0.0` | 텍스트 TargetSel 합격 임계값. 보정 전(stub은 진폭으로 판정). 앱이 생성 서버가 돌려준 점수로 판정하므로 **앱의 값**이 쓰임. 비교할 다른 소스가 없으면 적용하지 않음 |
| `AUDYSSEY_GEN_BASE_MODEL` | `jnwnlee/SelVA` | 공개 베이스 저장소 |
| `AUDYSSEY_GEN_MODEL` | `sogang-audyssey/internal-model` | 비공개 내부 모델 저장소 |
| `AUDYSSEY_GEN_GENERATOR_FILE` | `generator/S_O_s43/model_ema_step1000.pth` | 내부 모델 생성기 파일 |
| `AUDYSSEY_GEN_ENCODER_FILE` | `encoder/S_O/best.pt` | 내부 모델 인코더 파일 |
| `AUDYSSEY_GEN_DEVICE` | `cuda` | 생성 장치 |
| `AUDYSSEY_GEN_STEPS` / `AUDYSSEY_GEN_CFG` | `25` / `4.5` | Euler 생성 설정 |
| `AUDYSSEY_GEN_SINGLE_MAX_S` / `AUDYSSEY_GEN_WINDOW_S` | `15` / `8` | 단일 생성 최대 길이 / 긴 영상 창 길이(초) |

**Compose 전용 값** (`.env`. 앱 설정이 아님)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `AUDYSSEY_IMAGE_TAG` | `latest` | 이미지 태그. 공용 서버는 확인한 커밋 SHA로 고정 ([서버 갱신](contributing.md#서버-갱신)) |
| `HF_CACHE` | `~/.cache/huggingface` | 가중치 캐시 경로 |
| `AUDYSSEY_{SEPARATION,JUDGE,GROUNDING,GENERATION,VLLM}_GPU` | `0` | `compose.yaml` 서비스별 GPU 번호 |
| `AUDYSSEY_TOOLS_GPU` / `_PORT` / `_BIND` | `0` / `8700` / `127.0.0.1` | `compose.tools.yaml`의 GPU 번호, 호스트 포트, 바인드 주소 |
| `AUDYSSEY_VLLM_MODEL` / `AUDYSSEY_VLLM_GPU_UTIL` | `Qwen/Qwen2.5-VL-3B-Instruct` / `0.85` | vLLM 모델과 GPU 메모리 비율 (`.env.example`은 `0.2`) |
| `GOOGLE_API_KEY` | 빈 값 | Gemini 키. `AUDYSSEY_PLANNER_API_KEY`가 비면 대신 전달됨 |
| `LANGSMITH_*` | | [실행 기록 보기](#실행-기록-보기-langsmith-studio) |

## 문제 해결

| 증상 | 원인과 해결 |
|---|---|
| `/`에 이전 단일 파일 화면이 뜸 | 화면을 빌드하지 않았음. `cd web && npm ci && npm run build` 후 다시 띄움 (Docker 이미지에는 빌드되어 있음) |
| 가중치 받기에서 401/403 | 승인 대기 중이거나 조직 미가입. 승인 메일과 `sogang-audyssey` 초대를 확인 |
| 첫 작업에서 생성·분리 실패, 로그에 `LocalEntryNotFoundError` | 캐시에 가중치가 없음. `HF_CACHE`(또는 RunPod `HF_HOME`) 경로와 [가중치 준비](#가중치-준비) 실행 여부 확인 |
| `CUDA out of memory` | 다른 사람이 쓰는 GPU에 올렸거나 GPU가 작음. 빈 GPU로 바꾸거나 vLLM 대신 Gemini 사용 |
| 작업 중 `tool server ... failed: 401` (main 로그에도 401) | main과 도구 서버의 `AUDYSSEY_TOOL_TOKEN`이 다름. 화면에서 연결했다면 토큰을 다시 저장 |
| GPU tools 저장이 409 | 작업이 실행 중임. 끝난 뒤 다시 저장 |
| GPU tools 저장이 422 | URL이 `http(s)://호스트:포트` 형식이 아니거나 사용자 이름·비밀번호를 포함함 |
| 업로드가 400 | 영상이 30초를 넘거나 비디오 스트림이 없음 |
| 작업 폴더 쓰기 권한 오류 | 예전 root 이미지로 만든 볼륨. `docker compose down && docker volume rm audyssey_jobs` 후 다시 띄움 |
| `AUDYSSEY_PLANNER_API=openrouter`로 바꾼 뒤 main이 안 뜸 | `c0ee48e` 이전 이미지는 `openrouter` 값을 모름. 새 이미지를 받거나 `AUDYSSEY_IMAGE_TAG`를 그 뒤 커밋으로 |
| 플래너는 되는데 검수기만 실패, 로그에 `API key not valid` | vLLM용 `AUDYSSEY_VALIDATOR_API_KEY=unused`가 남음. 키를 같이 바꾸거나 지워서 플래너 키를 쓰게 함 |
| 화면 서버 상태에서 OpenRouter가 응답 없음 | 키가 틀렸거나 만료됨(`/key` 조회 실패). LLM 서버가 응답 없음이면 `BASE_URL`과 키 확인 |
