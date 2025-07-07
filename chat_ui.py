import streamlit as st
from langchain.agents import initialize_agent, AgentType
from langchain.memory import ConversationBufferMemory
from langchain.tools import Tool
from langchain_openai import ChatOpenAI
import os
from dotenv import load_dotenv

# Load environment variables (like your OpenAI key)
load_dotenv()

# Set up LangChain agent
llm = ChatOpenAI(temperature=0.7, model="gpt-3.5-turbo")  # or "gpt-4" if you have access
tools = []  # Add tools here later if needed
memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)

agent = initialize_agent(
    tools=tools,
    llm=llm,
    memory=memory,
    agent=AgentType.CONVERSATIONAL_REACT_DESCRIPTION,
    verbose=False,
)

# Streamlit UI
st.set_page_config(page_title="Crypto Chat Agent")
st.title("💬 Crypto Chat Agent")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

user_input = st.chat_input("Ask me about crypto, altcoins, or anything risky...")

if user_input:
    with st.spinner("Thinking..."):
        response = agent.run(user_input)
        st.session_state.chat_history.append(("You", user_input))
        st.session_state.chat_history.append(("Bot", response))

# Display chat history
for speaker, msg in st.session_state.chat_history:
    st.markdown(f"**{speaker}:** {msg}")
