from __future__ import annotations
import httpx
from shared.models import Provider,ServiceOffering

class ClinkPeerAdapter:
    pagination_style="cursor"
    def __init__(self,url,*,client=None):self.url=url.rstrip("/");self.client=client or httpx.Client(timeout=15)
    def fetch_page(self,*,cursor=None,limit=100,etag=None):
        headers={"If-None-Match":etag} if etag else {};params={"limit":limit}
        if cursor:params["cursor"]=cursor
        response=self.client.get(f"{self.url}/registry/export",params=params,headers=headers)
        if response.status_code==304:return {"items":[],"cursor":cursor,"next_cursor":None,"etag":etag,"not_modified":True}
        response.raise_for_status();payload=response.json();items=payload.get("offerings",[])
        if not isinstance(items,list):raise ValueError("peer registry offerings must be a list")
        return {"items":items,"cursor":cursor,"next_cursor":payload.get("next_cursor"),"etag":response.headers.get("etag")}
    @staticmethod
    def normalize_resource(row):
        return Provider.model_validate(row["provider"]),ServiceOffering.model_validate(row["offering"])
