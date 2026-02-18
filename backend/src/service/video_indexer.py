'''
Connector : Python ans Azure Video Indexer 
'''

import time
import logging
import requests
import yt_dlp
from azure.identity import DefaultAzureCredential
import os


logger = logging.getLogger("video-indexer")

class VideoIndexerService:
    def __init__(self):
        self.account_id = os.genenv("AZURE_VI_ACCOUNT_ID")
        self.location = os.genenv("AZURE_VI_LOCATION")
        self.subscription_id = os.genenv("AZURE_SUBSCRIPTION_ID")
        self.resource_group = os.genenv("AZURE_RESOURCE_GROUP")
        self.vi_name  = os.genenv("AZURE_VI_NAME","")
        self.credential  = DefaultAzureCredential()

    def get_access_token(self):
        '''
        Generates an ARM Access token
        '''
        try:
            token_object = self.credential.get_token("https://management.azure.com/.default")
            return token_object
        except Exception as e:
            logger.error(f"Failed to get Azure token : {e}")

    def get_account_token(self,arm_access_token):
        '''
        Exchange the ARM token for Video indexer account team
        '''

        url =(
            f"https://management.azure.com/subscriptions/{self.subscription_id}"
            f"/resourceGroups/{self.resource_group}"
            f"/providers/Microsoft.VideoIndexer/accounts/{self.vi_name}"
            f"/generateAccessToken?api-version=2024-01-01"
        )

        headers = {"Authorization" : f"Bearer {arm_access_token}"}
        payload = {"permissionType" : "Contributor" , "scope" : "Account"}
        reponse = requests.post(url,headers=headers , json=payload)
        if reponse. status_code != 200:
            raise Exception(f"Failed to ge VI Account token : {reponse.text}")
        
        return reponse.json().get("accessToken")
    
    def download_youtube_video(seld,url,output_path="temp_video.mp4"):
        '''
        downloads the youtube video to local file
        '''
        logger.info(f"Downloading Youtube video : {url}")
        
        ydl_opts = {
            "format" : 'best[ext=mp4]',
            'outtmpl' : output_path,
            'quiet' : True,
            'overwrites' : True
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            logger.info(f"Downloaded Completed")
            return output_path
        except Exception as e:
            raise Exception(f"Youtube Video Download Failed : {str(e)}")

    # Upload the video to Azure Video indexer
    def upload_vide(self, video_path, video_name) :
        arm_token = self.get_access_token()
        vi_token = self.get_account_token(arm_token)
        api_url = f"https://api.videoindexer.ai/{self.location}/Accounts/{self.account_id}/Videos"
        params = {
            "accessToken" : vi_token,
            "name" : video_name,
            "privacy" : "Private",
            "indexingPreset" : "Default"
        }

        logger.info(f"Uploading file {video_path} to Azure.......")

        # open the file in binary and stream it on azure
        with open(video_path, 'rb') as video_file:
            files = {'file' :video_file}
            response = requests.post(api_url, params=params, files=files)

        if response. status_code != 200:
            raise Exception(f"Azure Upload Failed : {response.text}")
        
    def wait_for_processing(self,video_id):
        logger.info(f"Waiting for the video {video_id} to process")
        while True:
            arm_token = self.get_account_token()
            vi_token = self.get_account_token(arm_token)

            url = f"https://api.videoindexer.ai/{self.location}/Accounts/{self.account_id}/Videos"
            params = {"accessToken":vi_token}
            response = requests.get(url,params=params)
            data = response.json()

            state = data.get("state")
            if state == "Processed":
                return data
            elif state == "Failed":
                raise Exception(f"Video Indexing Failed in Azure")
            elif state == "Quarantined":
                raise Exception(f"Video Quarantined (Copyright/ Content Policy Violation)")
            logger.info(f"Status {state} .........waiting 30s")
            time.sleep(30)

    def extract_data(self,vi_json) :
        '''parses teh JSON into our state format'''
        transcript_lines = []
        for v in vi_json.get("videos", []) :
            for insight in v.get("insights", {}).get("transcript", []):
                transcript_lines.append(insight.get("text"))

        ocr_lines = []
        for v in vi_json.get("videos", []):
            for insight in v.get("insights",{}).get("ocr",[]):
                ocr_lines.append(insight.get("text"))

        return {
            "transcipts" : " ".join(transcript_lines),
            "ocr_text" : ocr_lines,
            "video_metadata" : {
                "duration" : vi_json.get("summarizedInsights",{}).get("duration"),
                "platform" : "youtube"
            }
        }