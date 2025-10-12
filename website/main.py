import json
import re
import sys
from typing import Optional
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch

# Import the three tool functions
from semantic_search import FAISSSemanticSearch
from KeywordSearch import keyword_search
from ReadDocumentPart import read_document_part

class RAGSystem:
    def __init__(self, max_turns: int = 5, xml_file: str = "./normalized_enhanced.xml"):
        self.max_turns = max_turns
        self.xml_file = xml_file
        self.state = ""  # Accumulated context from tool outputs
        self.tool_outputs = []
        
        # Initialize tools
        try:
            self.semantic_search_engine = FAISSSemanticSearch()
        except Exception as e:
            print(f"[WARNING] Could not initialize semantic search: {e}")
            self.semantic_search_engine = None
        
        # Initialize Qwen2.5-14B-Instruct
        print("Loading Qwen2.5-14B-Instruct...")
        model_name = "Qwen/Qwen2.5-14B-Instruct"
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            dtype=torch.bfloat16,
            device_map="auto",
            attn_implementation="eager"
        )
        print("✓ Model loaded successfully")
    
    def semantic_search(self, query: str, n: int = 3) -> str:
        """Semantic search using FAISS + embeddings"""
        if not self.semantic_search_engine:
            return '{"error": "Semantic search not initialized"}'
        try:
            result = self.semantic_search_engine.search(query, n=n)
            return result
        except Exception as e:
            return json.dumps({"error": str(e)})
    
    def keyword_search_tool(self, query: str, n: int = 3) -> str:
        """Keyword search using BM25"""
        try:
            result = keyword_search(self.xml_file, query, n=n)
            return result
        except Exception as e:
            return json.dumps({"error": str(e)})
    
    def read_document_part_tool(self, part_id: str, wrap: bool = True, stream: bool = False) -> str:
        """Read a specific document part by ID"""
        try:
            result = read_document_part(self.xml_file, part_id, wrap=wrap, stream=stream)
            return result
        except Exception as e:
            return json.dumps({"error": str(e)})
    
    def execute_tool(self, tool_name: str, args: dict) -> str:
        """Execute the specified tool and return result"""
        if tool_name == "semantic_search":
            return self.semantic_search(args.get("query", ""), args.get("n", 3))
        elif tool_name == "keyword_search":
            return self.keyword_search_tool(args.get("query", ""), args.get("n", 3))
        elif tool_name == "read_document_part":
            return self.read_document_part_tool(
                args.get("part_id", ""),
                args.get("wrap", True),
                args.get("stream", False)
            )
        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
    
    def parse_tool_call(self, response: str) -> Optional[dict]:
        """Extract tool call from model response"""
        tool_pattern = r'<tool>\s*({.*?})\s*</tool>'
        match = re.search(tool_pattern, response, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                return None
        return None
    
    def format_system_prompt(self) -> str:
        return f"""You are a helpful RAG assistant specializing in legal document analysis. You have access to three tools:

1. **semantic_search**: Find documents semantically similar to a query
   - args: {{"query": "search query", "n": number_of_results}}
   
2. **keyword_search**: BM25 keyword search across documents
   - args: {{"query": "keywords", "n": number_of_results}}
   
3. **read_document_part**: Retrieve a specific document section by ID
   - args: {{"part_id": "doc_id.section.subsection"}}

You may call one tool per turn, for up to {self.max_turns} turns, before giving your final answer.

In each turn, analyze what information you need and respond with EITHER a tool call OR your final answer.

For tool calls, use this format:
<think>
[your reasoning for what to search for and why]
</think>
<tool>
{{"name": "tool_name", "args": {{"query": "search query"}}}}
</tool>

When you have enough information to answer the user's question, give your final answer in this format:

<think>
[your reasoning for the answer based on gathered information]
</think>
<answer>
[your comprehensive answer citing the evidence you found or "I don't know" if you didn't get enough information]

<sources>
<source>doc_id_1</source>
<source>doc_id_2</source>
</sources>
</answer>

Context from previous tool calls:
{self.state if self.state else "No prior context."}
"""
    
    def query(self, user_query: str, chat_history: list = None) -> str:
        """Process a user query through the RAG system with optional chat history context
        
        Args:
            user_query: The current user question
            chat_history: List of previous messages in format [{"role": "user"/"assistant", "content": "..."}, ...]
        """
        self.state = ""
        self.tool_outputs = []
        turn = 0
        messages = []
        
        system_prompt = self.format_system_prompt()
        
        # Build initial message context with chat history
        initial_messages = [{"role": "system", "content": system_prompt}]
        
        # Add chat history if provided
        if chat_history:
            for msg in chat_history:
                initial_messages.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", "")
                })
        
        # Add current user query
        initial_messages.append({"role": "user", "content": user_query})
        
        while turn < self.max_turns:
            turn += 1
            print(f"\n{'='*60}")
            print(f"Turn {turn}/{self.max_turns}")
            print(f"{'='*60}")
            
            # Build messages for this turn (starting fresh with history)
            messages = initial_messages.copy()
            
            # Add prior tool results if any
            if self.tool_outputs:
                for tool_output in self.tool_outputs:
                    messages.append({
                        "role": "assistant",
                        "content": tool_output["full_response"]
                    })
                    messages.append({
                        "role": "user",
                        "content": f"Tool '{tool_output['tool']['name']}' returned:\n{tool_output['result']}\n\nContinue with analysis or provide final answer if you have enough information."
                    })
            
            # Generate response
            input_ids = self.tokenizer.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_tensors="pt"
            ).to(self.model.device)
            
            with torch.no_grad():
                output = self.model.generate(
                    input_ids,
                    max_new_tokens=1024,
                    temperature=0.7,
                    top_p=0.9,
                    eos_token_id=self.tokenizer.eos_token_id
                )
            
            response = self.tokenizer.decode(output[0], skip_special_tokens=True)
            
            # Extract just the assistant's response part
            if "assistant" in response:
                response = response.split("assistant")[-1].strip()
            
            print(f"\nModel Output:\n{response}")
            
            # Check for tool call
            tool_call = self.parse_tool_call(response)
            
            if tool_call:
                print(f"\n[TOOL CALL] {tool_call['name']}")
                print(f"Arguments: {json.dumps(tool_call.get('args', {}), indent=2)}")
                
                tool_result = self.execute_tool(tool_call["name"], tool_call.get("args", {}))
                print(f"\n[TOOL RESULT]\n{tool_result[:500]}{'...' if len(tool_result) > 500 else ''}")
                
                # Append to state for context
                self.state += f"\n\n--- Tool: {tool_call['name']} ---\nQuery/Args: {json.dumps(tool_call.get('args', {}))}\nResult: {tool_result[:1000]}"
                
                # Store for next turn
                self.tool_outputs.append({
                    "full_response": response,
                    "tool": tool_call,
                    "result": tool_result
                })
            else:
                # Check if this is a final answer
                if "<answer>" in response:
                    print(f"\n{'='*60}")
                    print("FINAL ANSWER REACHED")
                    print(f"{'='*60}")
                    return response
                else:
                    print("\n[INFO] No tool call detected and no final answer. Continuing...")
        
        # Max turns reached - request final answer
        print(f"\n{'='*60}")
        print("MAX TURNS REACHED - GENERATING FINAL ANSWER")
        print(f"{'='*60}")
        
        messages.append({
            "role": "assistant",
            "content": "I have used my available tool turns. Let me provide my final answer based on the information gathered."
        })
        
        input_ids = self.tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt"
        ).to(self.model.device)
        
        with torch.no_grad():
            output = self.model.generate(
                input_ids,
                max_new_tokens=1024,
                temperature=0.7,
                top_p=0.9,
                eos_token_id=self.tokenizer.eos_token_id
            )
        
        response = self.tokenizer.decode(output[0], skip_special_tokens=True)
        if "assistant" in response:
            response = response.split("assistant")[-1].strip()
        
        print(f"\nFinal Response:\n{response}")
        return response



# Main execution
if __name__ == "__main__":
    # Initialize RAG system
    rag = RAGSystem(max_turns=5, xml_file="./normalized_enhanced.xml")
    
    # Example query
    user_query = "What are the key facts in the Marbury v Madison case?"
    
    print(f"\n{'='*60}")
    print(f"USER QUERY: {user_query}")
    print(f"{'='*60}")
    
    final_response = rag.query(user_query)
    
    print(f"\n{'='*60}")
    print("COMPLETE RESPONSE")
    print(f"{'='*60}")
    print(final_response)