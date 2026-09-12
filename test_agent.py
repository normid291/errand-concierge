import os

from dotenv import load_dotenv
from strands import Agent
from strands.models.openai import OpenAIModel

load_dotenv()

BEDROCK_API_KEY = os.environ["BEDROCK_API_KEY"]

model = OpenAIModel(
    client_args={
        "base_url": "https://bedrock-mantle.us-east-1.api.aws/v1",
        "api_key": BEDROCK_API_KEY,
    },
    model_id="openai.gpt-oss-120b",
)

agent = Agent(model=model)

response = agent("Hello! In one sentence, what can you help me with?")
print(response)
