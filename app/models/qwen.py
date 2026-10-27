from app.models.openai_compat import OpenAICompatibleAdapter
from app.config import settings

class QwenAdapter(OpenAICompatibleAdapter):
    def __init__(self):
        super().__init__(
            name="qwen",
            base_url=settings.qwen_base_url,
            api_key=settings.dashscope_api_key,
            default_model=settings.qwen_model,
        )
