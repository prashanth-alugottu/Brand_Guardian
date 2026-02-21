import json
import os
import logging
import re
from typing import Dict, Any, List

from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
from langchain_community.vectorstores import AzureSearch
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage

# import state Schema
from backend.src.graph.state import VideoAuditState,ComplianceIssue

#import service
from backend.src.service.video_indexer import VideoIndexerService

# Configure the logger
logger = logging.getLogger("brand-gardian")
logging.basicConfig(level=logging.INFO)


# NODE 1 : Indexer
# Function resposible for convert video to text
def index_video_node(state : VideoAuditState) -> Dict[str,Any]:
    '''
        Download the youtube video from the url
        Upload to the Azure Video Indexer
        extract the insights
    '''
    video_url = state.get("video_url")
    video_id_input = state.get("video_id")

    logger.info(f"------[Node:Indexr] Processing : {video_url}")
    local_filename = "temp_audit_video.mp4"

    try:
        vi_service = VideoIndexerService()
        #download
        if "youtube.com" in video_url or "youtube.be" in video_url or "youtu.be" in video_url:
            local_path=vi_service.download_youtube_video(video_url,output_path=local_filename)
        else:
            raise Exception("Please provide a valid youtube URL for this test.")

        #upload
        azure_video_id = vi_service.upload_video(local_path, video_name=video_id_input)
        logger.info(f"Upload success. Azure ID : {azure_video_id}")

        # cleanup
        if os.path.exists(local_path):
            os.remove(local_path) 

        # wait
        raw_insights = vi_service.wait_for_processing(azure_video_id)

        # extract
        clean_data = vi_service.extract_data(raw_insights)
        logger.info(f"------[NODE: Indexer] Extraction completed ---------")
        return clean_data
    except Exception as e:
        logger.error(f"Video Indexer Failed : {e}")
        return {
            "errors" : [str(e)],
            "final_status": "FAIL",
            "transcript":"",
            "ocr_text":[]
        }

# NODE 2 : Compliance Auditor
def audit_content_node(state:VideoAuditState) -> Dict[str,Any]:
    '''
    Perform Retrival Augumented Generation to audit the content - brand video
    '''
    logger.info(f"-----[Node: Auditor] quering the knowledge base & LLM")
    transcript = state.get("transcript","")
    logger.info(f"=======>>>> Here is the transcripts :{repr(transcript)}")
    if not transcript:
        logger.warning(f"No transcript available. Skipping audit....")
        return {
            "final_state" : "FAIL",
            "final_report" : "Audit Skipped because video proccessing failed (No transcript.)"
        }

    # initialise the azure services
    llm = AzureChatOpenAI(
        azure_deployment = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT"),
        openai_api_version = os.getenv("AZURE_OPENAI_API_VERSION"),
        temperature = 0.0
    )

    embeddings = AzureOpenAIEmbeddings(
        azure_deployment = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT"),
        openai_api_version = os.getenv("AZURE_OPENAI_API_VERSION"),
    )

    vector_store = AzureSearch(
        azure_search_endpoint = os.getenv("AZURE_SEARCH_ENDPOINT"),
        azure_search_key = os.getenv("AZURE_SEARCH_API_KEY"),
        index_name = os.getenv("AZURE_SEARCH_INDEX_NAME"),
        embedding_function = embeddings.embed_query
    )

    # RAG Retrival 
    ocr_text = state.get("ocr_text",[])
    query_text = f"{transcript} {''.join(ocr_text)}"
    docs = vector_store.similarity_search(query_text,k=3)
    retrieved_rules = "\n\n".join([doc.page_content for doc in docs])
    
    # System prompt
    system_prompt = f"""
    You are a Senior Brand Compliance Auditor.
    
    OFFICIAL REGULATORY RULES:
    {retrieved_rules}
    
    INSTRUCTIONS:
    1. Analyze the Transcript and OCR text below.
    2. Identify ANY violations of the rules.
    3. Return strictly JSON in the following format:
    
    {{
        "compliance_results": [
            {{
                "category": "Claim Validation",
                "severity": "CRITICAL",
                "description": "Explanation of the violation..."
            }}
        ],
        "status": "FAIL", 
        "final_report": "Summary of findings..."
    }}

    If no violations are found, set "status" to "PASS" and "compliance_results" to [].
    """

    user_message = f"""
                    VIDEO_METADATA : {state.get('video_metadata',{})}
                    TRANSCRIPT : {transcript}
                    ON-SCREEN TEXT (OCR) : {ocr_text}
                    """
    
    try:
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message)
        ])
        content =  response.content
        logger.info(f"========>>> content : {content}")
        if "```" in content:
            content = re.search(r"```(?:json)?(.?)```",content,re.DOTALL).group(1)

        audit_data = json.loads(content.strip())
        return {
            "compliance_result" : audit_data.get("compliance_results",[]),
            "final_status" : audit_data.get("status","FAIL"),
            "final_report" : audit_data.get("final_report","No report generated")
        }
    except Exception as e:
        logger.error(f"System Error in Auditor Node : {str(e)}")
        # logging the raw response 
        logger.error(f"Raw LLM response : {response.content if 'response' in locals() else None}")
        return {
            "errors" : [str(e)],
            "final_status" : "FAIL"
        }