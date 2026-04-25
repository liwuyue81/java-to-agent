from pydantic_settings import BaseSettings
from pathlib import Path
import os


class Settings(BaseSettings):
    # ── LLM Provider 切换 ──
    # "ollama"    ：本地 Ollama，免费但受内存限制
    # "dashscope" ：阿里云百炼（OpenAI 兼容协议），qwen-plus/turbo/max 等
    llm_provider: str = "ollama"

    # ── 模型名（按 provider 含义不同）──
    # ollama    →  "qwen2.5:7b" / "qwen2.5:3b" 等本地模型标签
    # dashscope →  "qwen-plus" / "qwen-turbo" / "qwen-max" 等云端模型
    model_name: str = "qwen2.5:7b"

    # ── 云端 API 凭证（仅 dashscope/openai 类 provider 需要）──
    # 必须通过 .env 配置，禁止硬编码到代码里
    api_key: str = ""
    api_base_url: str = ""

    # ── 通用推理参数 ──
    temperature: float = 0
    timeout: int = 60
    max_iterations: int = 6

    # 日志文件路径
    log_file: Path = Path(__file__).parent / "logs" / "app.log"

    # ── LangSmith 可观测性（可选）──
    # 开启后所有 LangChain/LangGraph 调用自动 trace 到 https://smith.langchain.com/
    # 业务代码零侵入，只需环境变量。免费额度 5000 traces/月。
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "java-to-agent"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


# 全局单例，其他文件 from config import settings 直接用
settings = Settings()


def _apply_langsmith_env() -> None:
    """
    把 settings 的 langsmith 字段写回 os.environ。

    为什么需要这一步：
      LangChain/LangGraph 的 trace SDK 只识别进程环境变量，
      不会读 Settings 对象。而用户在 .env 里配置更方便，
      所以我们把 .env 读到 Settings，再主动写回 env，打通两边。

    关闭 tracing（默认）时完全不动 env，不影响现有功能。
    """
    if settings.langsmith_tracing and settings.langsmith_api_key:
        os.environ["LANGSMITH_TRACING"]  = "true"
        os.environ["LANGSMITH_API_KEY"]  = settings.langsmith_api_key
        os.environ["LANGSMITH_PROJECT"]  = settings.langsmith_project
        os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint


# 启动时立即应用（import config 就生效，在任何 LangChain 调用之前）
_apply_langsmith_env()


def get_llm(temperature: float | None = None, timeout: int | None = None):
    """
    LLM 工厂：根据 settings.llm_provider 返回对应的 LangChain chat 模型实例。

    这样业务代码不用关心 Ollama / DashScope 差异，切换 provider 只改 .env。
    类比 Spring 的 @ConditionalOnProperty + 多实现 Bean。
    """
    t = temperature if temperature is not None else settings.temperature
    to = timeout if timeout is not None else settings.timeout

    if settings.llm_provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(model=settings.model_name, temperature=t, timeout=to)

    if settings.llm_provider in ("dashscope", "openai"):
        # 阿里云百炼走 OpenAI 兼容协议，用 ChatOpenAI 指向自定义 base_url 即可
        if not settings.api_key:
            raise RuntimeError(
                f"llm_provider={settings.llm_provider} 需要在 .env 中配置 API_KEY"
            )
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=settings.model_name,
            api_key=settings.api_key,
            base_url=settings.api_base_url or None,
            temperature=t,
            timeout=to,
        )

    raise ValueError(f"未知的 llm_provider: {settings.llm_provider}")


def get_embeddings():
    """
    Embedding 工厂：根据 settings.llm_provider 返回对应的向量化模型。

    注意：ollama / dashscope 产出的向量维度不同（nomic-embed-text 768 维，
         text-embedding-v3 1024 维），切换 provider 后必须重建向量库：
         from rag.log_indexer import index_logs; index_logs(force=True)
    """
    if settings.llm_provider == "ollama":
        from langchain_ollama import OllamaEmbeddings
        return OllamaEmbeddings(model="nomic-embed-text")

    if settings.llm_provider in ("dashscope", "openai"):
        if not settings.api_key:
            raise RuntimeError(
                f"llm_provider={settings.llm_provider} 需要在 .env 中配置 API_KEY"
            )
        from langchain_openai import OpenAIEmbeddings
        # DashScope 的 embedding 模型：text-embedding-v3（1024 维，新版）
        # 若你的 provider=openai，改成 text-embedding-3-small 等即可
        embed_model = "text-embedding-v3" if settings.llm_provider == "dashscope" else "text-embedding-3-small"
        return OpenAIEmbeddings(
            model=embed_model,
            api_key=settings.api_key,
            base_url=settings.api_base_url or None,
            # DashScope 不接受 OpenAI SDK 默认的预 tokenize 格式，必须关掉
            check_embedding_ctx_length=False,
            # DashScope text-embedding-v3 限制 batch size <= 10
            chunk_size=10,
        )

    raise ValueError(f"未知的 llm_provider: {settings.llm_provider}")
