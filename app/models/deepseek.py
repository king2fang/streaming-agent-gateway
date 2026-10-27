from app.models.openai_compat import OpenAICompatibleAdapter
from app.config import settings

class DeepSeekAdapter(OpenAICompatibleAdapter):
    def __init__(self):
        super().__init__(
            name="deepseek",
            base_url=settings.deepseek_base_url,
            api_key=settings.deepseek_api_key,
            default_model=settings.deepseek_model,
        )
