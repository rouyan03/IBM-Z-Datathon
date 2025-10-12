import streamlit as st
import re
from openai import OpenAI
from main import RAGSystem

# Set OpenAI API key from Streamlit secrets
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

# Set a default model
if "openai_model" not in st.session_state:
    st.session_state["openai_model"] = "gpt-3.5-turbo"

def format_llm_output(text: str) -> str:
    # --- Extract sections using DOTALL (re.S) to handle multiline content ---
    think_match = re.search(r"<think>(.*?)</think>", text, re.S)
    answer_match = re.search(r"<answer>(.*?)</answer>", text, re.S)
    sources_match = re.search(r"<sources>(.*?)</sources>", text, re.S)

    # --- Extract individual sources if present ---
    sources = re.findall(r"<source>(.*?)</source>", text, re.S)

    # --- Clean up text ---
    think = think_match.group(1).strip() if think_match else ""
    answer = answer_match.group(1).strip() if answer_match else ""
    sources_block = sources_match.group(1).strip() if sources_match else ""

    # --- Remove the sources block from inside the answer (if nested) ---
    if sources_block:
        answer = re.sub(r"<sources>.*?</sources>", "", answer, flags=re.S).strip()

    # --- Build styled HTML sections ---
    think_html = f'<div class="think"><h2>Thinking...</h2><p>{think}</p></div>' if think else ""
    answer_html = f'<div class="answer">{answer}</div>' if answer else ""
    sources_html = (
        "<div class='sources'><strong>Sources:</strong><br>"
        + "<br>".join(sources)
        + "</div>"
        if sources
        else ""
    )

    # --- Combine with CSS styling ---
    styled_html = f"""
    <style>
    .think {{
        background-color: #f7f7f7;
        color: #555;
        font-style: italic;
        padding: 0.5rem;
        border-left: 4px solid #ddd;
        white-space: pre-wrap;
        margin-bottom: 1rem;
    }}
    .answer {{
        font-weight: 500;
        white-space: pre-wrap;
        margin-bottom: 1rem;
    }}
    .sources {{
        font-size: 0.9rem;
        color: #aaaaaa;
        white-space: pre-wrap;
    }}
    </style>
    {think_html}{answer_html}{sources_html}
    """
    return styled_html

def login_screen():
    st.header("this app is private. you may only log in as a pre-approved user.")
    st.subheader("please log in")
    st.button("Google Login", on_click=st.login)


if "messages" not in st.session_state:
    st.session_state.messages = []

system_prompt = {
    "role": "system",
    "content": """
You are a helpful AI assistant that answers questions by reasoning step-by-step internally, 
Provide your final answer in the following XML-like format:

<think>
[your reasoning for the answer]
</think>
<answer>
[your comprehensive answer citing the evidence you found or "I don't know" if you didn't get enough information]

<sources>
<source>doc_id_1</source>
<source>doc_id_2</source>
</sources>
</answer>

Only include one <think> section and one <answer> section per reply. 
Do not include any other text outside these tags.
    """
}

if not st.user.is_logged_in:
    login_screen()
else:
    rag = RAGSystem(max_turns=5, xml_file="./normalized_enhanced.xml") if "rag" not in st.session_state else st.session_state["rag"]
    st.session_state["rag"] = rag
    st.header(f"Welcome, {st.user.name}")
    st.button("Log Out", on_click=st.logout)

    # Display chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.html(message["content"])

    if prompt := st.chat_input("Ask me anything"):
        # Add user message to history
        with st.chat_message("user"):
            st.markdown(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})

        # Prepare chat history for RAG (exclude formatting, just raw content)
        chat_history_for_rag = [
            {"role": msg["role"], "content": msg["content"]}
            for msg in st.session_state.messages[:-1]  # Exclude the current message
        ]

        with st.chat_message("assistant"):
            # Pass chat history to RAG system
            response = st.session_state["rag"].query(
                user_query=prompt,
                chat_history=chat_history_for_rag
            )
            st.html(format_llm_output(response))

        st.session_state.messages.append({"role": "assistant", "content": response})
    

   
    
    