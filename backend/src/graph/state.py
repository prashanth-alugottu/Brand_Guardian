import operator
from typing import List, Dict, Annotated, Optional, Any, TypedDict


# defining the schema for single compliance result
# Error Report

class ComplianceIssue(TypedDict):
    category : str
    description : str # Specific details of violation
    severity : str # CRITICAL | WARNING
    timestamp : Optional[str]

# defina the global graph state
# This defines the state that gets passed around in the agentic flow
class VideoAuditState(TypedDict):
    '''
    Define the data schema for langgraph execution content
    Main container : holds all the information about the audit
    right from the initial URL to the final report
    '''

    # input params:
    video_url : str
    video_id : str

    #ingestion and extraction data
    local_file_path : Optional[str]
    video_metadata : Dict[str,Any] # {'duration':10, 'resolution':'1080p'}
    transcript : Optional[str]  # Full extracted speech-to-text
    ocr_text : List[str]

    # analysis the output
    # store the list of all violations found by AI
    compliance_results : Annotated[List[ComplianceIssue], operator.add]

    # final deliverables
    final_status : str # PASS | FAIL
    final_report : str # mark down format

    # system observability 
    # error : API timeout, system level errors
    # list of system level crashes
    errors : Annotated[List[str], operator.add]
        
