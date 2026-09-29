from __future__ import annotations

import re
import secrets

from shared.bazaar_targets import (
    BazaarTarget,
    classify_target_resource,
    target_metadata,
)


class RegistryAggregator:
    def __init__(
        self,
        repository,
        adapters,
        *,
        page_size=100,
        max_pages=10,
        targeted_supply: tuple[BazaarTarget, ...] = (),
        progress_callback=None,
    ):
        self.repository,self.adapters=repository,adapters
        self.page_size,self.max_pages=page_size,max_pages
        self.targeted_supply=targeted_supply
        self.progress_callback=progress_callback

    def _report_progress(self):
        if self.progress_callback:
            self.progress_callback()

    def sync(self):
        results=[]
        for registry_id,adapter in self.adapters.items():
            results.append(self.sync_registry(registry_id))
        return results

    def sync_registry(self, registry_id, max_pages=None):
        adapter=self.adapters[registry_id]
        cursor=self.repository.get_registry_cursor(registry_id)
        if getattr(adapter,"pagination_style",None)=="cursor":
            return self._sync_cursor_registry(registry_id,adapter,cursor,max_pages)
        try: offset=int(cursor["cursor"] or 0)
        except (TypeError,ValueError): offset=0
        etag=cursor["etag"]
        count=0
        targeted_count=0
        target_errors=[]
        skipped_count=0
        item_errors=[]
        owner_token=secrets.token_urlsafe(24)
        if not self.repository.acquire_registry_lease(registry_id,owner_token):
            return {"registry_id":registry_id,"status":"busy","count":0,"next_offset":offset}
        if (
            registry_id == "cdp_bazaar"
            and self.targeted_supply
            and self._should_refresh_targets(offset)
        ):
            try:
                entries,target_errors=self._targeted_entries(adapter)
                targeted_count=len(entries)
                if entries and not self.repository.commit_registry_page(
                    registry_id,owner_token,entries,cursor=str(offset),etag=etag,status="running"
                ):
                    return self._busy(registry_id,offset,count)
                if entries:
                    self._report_progress()
            except Exception as exc:
                error=self._safe_error(exc)
                if not self.repository.commit_registry_page(
                    registry_id,owner_token,[],cursor=str(offset),etag=etag,status="partial",
                    last_error=error,release_lease=True,
                ):
                    return self._busy(registry_id,offset,count)
                return self._result(
                    registry_id,"partial",count,offset,targeted_count,
                    last_error=error,target_errors=target_errors,
                )
        for _ in range(self.max_pages if max_pages is None else max_pages):
            try:
                page=adapter.fetch_page(offset=offset,limit=self.page_size,etag=etag if offset==0 else None)
                if page.get("not_modified"):
                    if not self.repository.commit_registry_page(registry_id,owner_token,[],cursor="0",etag=page.get("etag") or etag,status="succeeded",release_lease=True): return self._busy(registry_id,offset,count)
                    self._report_progress()
                    return self._result(
                        registry_id,"succeeded",count,0,targeted_count,
                        target_errors=target_errors,skipped_count=skipped_count,
                        item_errors=item_errors,
                    )
                items=page.get("items",[])
                if not isinstance(items,list) or not all(key in page for key in ("offset","count","total")): raise ValueError("invalid inventory pagination")
                page_offset=int(page["offset"]);page_count=int(page["count"]);total=int(page["total"])
                if page_offset!=offset or page_count!=len(items) or page_offset<0 or total<page_offset+page_count: raise ValueError("invalid inventory pagination")
                entries,page_errors=self._normalize_entries(adapter,items)
                skipped_count+=len(page_errors)
                item_errors.extend(page_errors)
                if offset==0 and page.get("etag"): etag=page["etag"]
                next_offset=page_offset+page_count
                if next_offset>=total:
                    if not self.repository.commit_registry_page(registry_id,owner_token,entries,cursor="0",etag=etag,status="succeeded",release_lease=True): return self._busy(registry_id,offset,count)
                    self._report_progress()
                    count+=page_count
                    return self._result(
                        registry_id,"succeeded",count,0,targeted_count,
                        target_errors=target_errors,skipped_count=skipped_count,
                        item_errors=item_errors,
                    )
                if next_offset<=offset: raise ValueError("inventory pagination did not advance")
                if not self.repository.commit_registry_page(registry_id,owner_token,entries,cursor=str(next_offset),etag=etag,status="running"): return self._busy(registry_id,offset,count)
                self._report_progress()
                count+=page_count;offset=next_offset
            except Exception as exc:
                error=self._safe_error(exc)
                if not self.repository.commit_registry_page(registry_id,owner_token,[],cursor=str(offset),etag=etag,status="partial",last_error=error,release_lease=True): return self._busy(registry_id,offset,count)
                return self._result(
                    registry_id,"partial",count,offset,targeted_count,
                    last_error=error,target_errors=target_errors,
                    skipped_count=skipped_count,item_errors=item_errors,
                )
        if not self.repository.commit_registry_page(registry_id,owner_token,[],cursor=str(offset),etag=etag,status="running",last_error=None,release_lease=True): return self._busy(registry_id,offset,count)
        return self._result(
            registry_id,"in_progress",count,offset,targeted_count,
            target_errors=target_errors,skipped_count=skipped_count,
            item_errors=item_errors,
        )

    def _normalize_entries(self, adapter, resources):
        entries=[]
        errors=[]
        for index,resource in enumerate(resources):
            try:
                provider,offering=adapter.normalize_resource(resource)
                entries.append((provider,offering,offering.source_id))
            except Exception as exc:
                errors.append({"index":index,"error":self._safe_error(exc)})
        return entries,errors

    def _targeted_entries(self, adapter):
        if not hasattr(adapter,"search"):
            return [],[]
        entries={}
        errors=[]
        for target in self.targeted_supply:
            try:
                resources=adapter.search(
                    target.name,network=None,max_usd_price=None,limit=20
                )
                for resource in resources:
                    relationship=classify_target_resource(target,resource)
                    if relationship is None:
                        continue
                    provider,offering=adapter.normalize_resource(resource)
                    key=offering.offering_id
                    current=entries.get(key)
                    targets=[] if current is None else list(
                        current[1].metadata.get("bazaar_targets",[])
                    )
                    marker=target_metadata(target,relationship)
                    if marker not in targets:
                        targets.append(marker)
                    offering=offering.model_copy(update={
                        "metadata":{**offering.metadata,"bazaar_targets":targets}
                    })
                    entries[key]=(provider,offering,offering.source_id)
            except Exception as exc:
                errors.append({"name":target.name,"error":self._safe_error(exc)})
        return list(entries.values()),errors

    def _should_refresh_targets(self, offset):
        if offset == 0:
            return True
        coverage = self.repository.bazaar_target_coverage(self.targeted_supply)
        return any(item["status"] == "missing" for item in coverage)

    def _result(
        self,registry_id,status,count,next_offset,targeted_count,*,last_error=None,
        target_errors=None,skipped_count=0,item_errors=None,
    ):
        result={
            "registry_id":registry_id,"status":status,"count":count,
            "next_offset":next_offset,
        }
        if registry_id=="cdp_bazaar" and self.targeted_supply:
            result["targeted_count"]=targeted_count
        if last_error:
            result["last_error"]=last_error
        if target_errors:
            result["target_errors"]=target_errors
        if skipped_count:
            result["skipped_count"]=skipped_count
            result["item_errors"]=(item_errors or [])[:20]
        return result

    @staticmethod
    def _safe_error(exc):
        message=f"{type(exc).__name__}: {exc}"
        message=re.sub(r"(?i)(bearer\s+)[^\s,;]+",r"\1<redacted>",message)
        message=re.sub(
            r"(?i)((?:api[_ -]?key|secret|token)\s*[=:]\s*)[^\s,;]+",
            r"\1<redacted>",message,
        )
        return message[:500]

    def _sync_cursor_registry(self,registry_id,adapter,state,max_pages):
        cursor=None if state["cursor"] in {None,"0"} else state["cursor"]
        etag=state["etag"];count=0;owner_token=secrets.token_urlsafe(24)
        if not self.repository.acquire_registry_lease(registry_id,owner_token):
            return {"registry_id":registry_id,"status":"busy","count":0,"next_cursor":cursor}
        for _ in range(self.max_pages if max_pages is None else max_pages):
            try:
                page=adapter.fetch_page(cursor=cursor,limit=self.page_size,etag=etag if cursor is None else None)
                if page.get("not_modified"):
                    if not self.repository.commit_registry_page(registry_id,owner_token,[],cursor="0",etag=page.get("etag") or etag,status="succeeded",release_lease=True):return {"registry_id":registry_id,"status":"busy","count":count,"next_cursor":cursor}
                    self._report_progress()
                    return {"registry_id":registry_id,"status":"succeeded","count":count,"next_cursor":None}
                items=page.get("items")
                if not isinstance(items,list) or page.get("cursor")!=cursor:raise ValueError("invalid peer registry pagination")
                entries=[]
                for resource in items:
                    provider,offering=adapter.normalize_resource(resource)
                    source_id=str(resource.get("source_id") or offering.source_id)
                    entries.append((provider,offering,source_id))
                next_cursor=page.get("next_cursor")
                if next_cursor==cursor and next_cursor is not None:raise ValueError("peer registry cursor did not advance")
                if cursor is None and page.get("etag"):etag=page["etag"]
                done=next_cursor is None
                if not self.repository.commit_registry_page(registry_id,owner_token,entries,cursor="0" if done else str(next_cursor),etag=etag,status="succeeded" if done else "running",release_lease=done):
                    return {"registry_id":registry_id,"status":"busy","count":count,"next_cursor":cursor}
                self._report_progress()
                count+=len(items)
                if done:return {"registry_id":registry_id,"status":"succeeded","count":count,"next_cursor":None}
                cursor=str(next_cursor)
            except Exception:
                self.repository.commit_registry_page(registry_id,owner_token,[],cursor=cursor or "0",etag=etag,status="partial",last_error="inventory page failed",release_lease=True)
                return {"registry_id":registry_id,"status":"partial","count":count,"next_cursor":cursor}
        if not self.repository.commit_registry_page(registry_id,owner_token,[],cursor=cursor or "0",etag=etag,status="partial",last_error="inventory page limit reached",release_lease=True):
            return {"registry_id":registry_id,"status":"busy","count":count,"next_cursor":cursor}
        return {"registry_id":registry_id,"status":"partial","count":count,"next_cursor":cursor}

    @staticmethod
    def _busy(registry_id, offset, count):
        return {"registry_id":registry_id,"status":"busy","count":count,"next_offset":offset}
