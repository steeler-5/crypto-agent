import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain.agents import initialize_agent, Tool
from langchain.agents.agent_types import AgentType
from langchain.memory import ConversationBufferMemory

# Load environment variables
load_dotenv()

# Initialize the GPT model
llm = ChatOpenAI(temperature=0.7, model="gpt-3.5-turbo")  # or "gpt-4"
memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)

# Optional tools for the agent (start simple, we’ll add more later)
tools = []

# Initialize the agent
agent = initialize_agent(
    tools=tools,
    llm=llm,
    agent=AgentType.CHAT_CONVERSATIONAL_REACT_DESCRIPTION,
    verbose=True,
    memory=memory,
    agent_kwargs={
        "system_message": "You are a bold, creative AI crypto researcher who speaks clearly and helps your user find smart, aggressive new memecoins to trade."
    }
)

# Simple chat loop
print("🔮 Crypto Agent Ready. Type 'exit' to quit.")
while True:
    user_input = input("You: ")
    if user_input.lower() in ["exit", "quit"]:
        break
    response = agent.invoke(user_input)
    print("Agent:", response)
