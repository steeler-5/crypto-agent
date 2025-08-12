from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
CMC_API_KEY = "ce5750f3-89e7-4d9f-80b1-98434e75e1d3"
