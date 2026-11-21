from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


Api = Literal["openai", "gemini", "openrouter"]
Input = Literal["frames", "video"]


class LLMEndpoint(BaseModel):
    """One model the planner or validator calls, resolved from settings."""

    api: Api
    base_url: str
    model: str
    api_key: str = Field(repr=False)
    input: Input
    fps: float
    max_frames: int
    video_audio: bool


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUDYSSEY_")

    planner: Literal["stub", "real"] = "stub"
    router: Literal["stub", "real", "hybrid"] = "stub"
    separator: Literal["stub", "real", "remote"] = "stub"
    filter: Literal["stub", "real", "remote"] = "stub"
    grounder: Literal["stub", "real", "remote"] = "stub"
    grounding_url: str = ""
    generator: Literal["stub", "real", "remote"] = "stub"
    generator_url: str = ""
    gen_base_model: str = "jnwnlee/SelVA"
    gen_model: str = "sogang-audyssey/internal-model"
    gen_generator_file: str = "generator/S_O_s43/model_ema_step1000.pth"
    gen_encoder_file: str = "encoder/S_O/best.pt"
    gen_device: str = "cuda"
    gen_steps: int = 25
    gen_cfg: float = 4.5
    gen_seed: int = 42
    gen_single_max_s: float = 15
    gen_window_s: float = 8
    max_generation_retries: int = Field(default=2, ge=0)
    generation_margin_threshold: float = 0.0
    # Visual prompting (SAM3 locate + masked video for SAM Audio) is off by default:
    # with a text description the mask barely changed separation in our tests.
    visual_prompt: bool = False
    sam3_model: str = "facebook/sam3.1"
    sam3_device: str = "cuda"
    # SAM3 keeps per-frame tracking state on the GPU; 1080p60 at 4 fps already needs >24 GB.
    # 0 tracks at the source frame rate.
    sam3_track_fps: float = Field(default=2, ge=0)
    separator_url: str = ""
    filter_url: str = ""
    tool_token: str = Field(default="", repr=False)
    remote_timeout_s: float = Field(default=600, gt=0)
    planner_base_url: str = ""
    planner_model: str = ""
    planner_api_key: str = Field(default="", repr=False)
    # openai: Chat Completions (OpenAI, vLLM, Gemini's OpenAI endpoint).
    # gemini: native generateContent, the only Gemini path that accepts video.
    planner_api: Api = "openai"
    # frames: JPEGs sampled at planner_fps. video: one downscaled clip the model
    # samples at planner_fps (vLLM video_url or Gemini inline video; the OpenAI
    # API takes frames only).
    planner_input: Input = "frames"
    planner_fps: float = Field(default=1, gt=0, le=30)
    # Frames input: cap per request, so long spans lower the effective fps.
    planner_max_frames: int = Field(default=32, ge=1, le=256)
    # Video input only: keep the clip's audio (Gemini, or vLLM Omni use_audio_in_video).
    planner_video_audio: bool = False
    # Validator model; each unset value falls back to the planner's.
    validator_api: Api | None = None
    validator_base_url: str | None = None
    validator_model: str | None = None
    validator_api_key: str | None = Field(default=None, repr=False)
    validator_input: Input | None = None
    validator_fps: float | None = Field(default=None, gt=0, le=30)
    validator_video_audio: bool | None = None
    # Declares that the validator accepts audio input; unset: the video+audio rule.
    validator_audio: bool | None = None
    # Extra context around each validation target; overlapping clips are merged.
    validator_context_s: float = Field(default=0.5, ge=0, le=5)
    # Separation validates PCM audio without visual cues; generation still uses video.
    validator_audio_only: bool = True
    # Router model; each unset value falls back to the planner's.
    router_api: Api | None = None
    router_base_url: str | None = None
    router_model: str | None = None
    router_api_key: str | None = Field(default=None, repr=False)
    # Unlike the fields above there is no planner fallback: None sends nothing.
    router_reasoning_effort: Literal["none", "low", "medium", "high"] | None = None
    # tools: one function call per decision type; json_schema: structured output.
    router_format: Literal["tools", "json_schema"] = "tools"
    # Replace router commands the job cannot run with a clarify answer.
    router_guard: bool = False
    # hybrid: a decision server picks the command and source; the router model fills values.
    router_decision_url: str = ""
    router_decision_model: str = "h2o-lightning-4b"  # names the run; never sent
    # Offer a clarify(missing_value) tool to the value filler.
    router_hybrid_escape: bool = False
    max_plan_rounds: int = Field(default=2, ge=1)
    max_separation_retries: int = Field(default=2, ge=0)
    max_duration_s: float = Field(default=30, gt=0)
    # Per uploaded file, on the app and the tool server; checked while streaming.
    max_upload_mb: float = Field(default=200, gt=0)
    work_dir: Path = Path("work/jobs")
    sam_audio_model: str = "facebook/sam-audio-large-tv"
    sam_audio_judge_model: str = "facebook/sam-audio-judge"
    sam_audio_device: str = "cuda"
    sam_audio_reranking_candidates: int = Field(default=1, ge=1)
    sam_audio_predict_spans: bool = False
    # Reranking (candidates > 1) only: CLAP and ImageBind checkpoint files. Empty CLAP
    # uses the cached lukewys/laion_clap 630k-best.pt; empty ImageBind disables the
    # visual ranker, so masked videos fall back to the text rankers (CLAP + Judge).
    sam_audio_clap_checkpoint: str = ""
    sam_audio_imagebind_checkpoint: str = ""
    judge_pass_threshold: float = 0.5

    def planner_endpoint(self) -> LLMEndpoint:
        return LLMEndpoint(
            api=self.planner_api,
            base_url=self.planner_base_url,
            model=self.planner_model,
            api_key=self.planner_api_key,
            input=self.planner_input,
            fps=self.planner_fps,
            max_frames=self.planner_max_frames,
            video_audio=self.planner_video_audio,
        )

    def validator_endpoint(self) -> LLMEndpoint:
        planner = self.planner_endpoint()
        overrides = {
            "api": self.validator_api,
            "base_url": self.validator_base_url,
            "model": self.validator_model,
            "api_key": self.validator_api_key,
            "input": self.validator_input,
            "fps": self.validator_fps,
            "video_audio": self.validator_video_audio,
        }
        return planner.model_copy(
            update={k: v for k, v in overrides.items() if v is not None}
        )

    def router_endpoint(self) -> LLMEndpoint:
        overrides = {
            "api": self.router_api,
            "base_url": self.router_base_url,
            "model": self.router_model,
            "api_key": self.router_api_key,
        }
        return self.planner_endpoint().model_copy(
            update={k: v for k, v in overrides.items() if v is not None}
        )

    @model_validator(mode="after")
    def _router_api_is_chat_completions(self) -> Self:
        if self.router != "stub" and self.router_endpoint().api == "gemini":
            raise ValueError("AUDYSSEY_ROUTER_API must be openai or openrouter")
        return self

    @model_validator(mode="after")
    def _hybrid_needs_decision_url(self) -> Self:
        if self.router == "hybrid" and not self.router_decision_url:
            raise ValueError("AUDYSSEY_ROUTER_DECISION_URL is required for hybrid")
        return self

    @model_validator(mode="after")
    def _gemini_takes_video(self) -> Self:
        for name, endpoint in [
            ("PLANNER", self.planner_endpoint()),
            ("VALIDATOR", self.validator_endpoint()),
        ]:
            if endpoint.api == "gemini" and endpoint.input != "video":
                raise ValueError(
                    f"AUDYSSEY_{name}_API=gemini requires AUDYSSEY_{name}_INPUT=video"
                )
        return self
